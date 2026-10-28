"""Guardrail checks for the chat backend (ADR-0008).

Input and output guardrails:
- harm categories (hate, sexual, violence, self-harm) and Prompt Shields come
  from Azure AI Content Safety on the Foundry account;
- the topic policy (medical/legal/financial/off-topic) is the orchestrator's
  `out_of_scope` intent, so it is not duplicated here;
- SSN and payment-card numbers are blocked locally (Content Safety has no PII
  detector for text).

Every Content Safety call fails open and is logged: a miss on the input side
still meets the output check before anything is final.
"""
import os
import re

import httpx

# FourSeverityLevels returns 0, 2, 4 or 6; 4 (medium) and above blocks.
# 4 (medium) and above blocks.
MIN_SEVERITY = int(os.environ.get("GUARDRAIL_MIN_SEVERITY", "4"))
# The last few turns are checked together so a harmful turn cannot be split up.
CONTEXT_MESSAGES = 6

BLOCKED_MESSAGE = (
    "I can help with claims, appointments, and pharmacy questions for your "
    "account. For medical, legal, or financial advice, please contact your "
    "provider or a licensed professional directly."
)

_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def contains_blocked_pii(text: str) -> bool:
    if _SSN.search(text):
        return True
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


class ContentSafety:
    def __init__(self, endpoint: str, credential, http: httpx.AsyncClient):
        self._base = endpoint.rstrip("/") + "/contentsafety"
        self._credential = credential
        self._http = http

    async def _post(self, path: str, body: dict) -> dict:
        token = await self._credential.get_token("https://cognitiveservices.azure.com/.default")
        resp = await self._http.post(
            f"{self._base}/{path}?{API}", json=body, headers={"authorization": f"Bearer {token.token}"}
        )
        resp.raise_for_status()
        return resp.json()

    async def _harmful(self, text: str) -> bool:
        data = await self._post("text:analyze", {"text": text[:10000], "outputType": "FourSeverityLevels"})
        return any(c.get("severity", 0) >= MIN_SEVERITY for c in data.get("categoriesAnalysis", []))

    async def blocks_input(self, messages: list[dict]) -> bool:
        """True if the latest user message is a prompt attack or, with recent
        turns, harmful content."""
        last = messages[-1]["content"]
        recent = "\n".join(m["content"] for m in messages[-CONTEXT_MESSAGES:])
        try:
            shield = await self._post("text:shieldPrompt", {"userPrompt": last[:10000], "documents": []})
            if shield.get("userPromptAnalysis", {}).get("attackDetected"):
                return True
            return contains_blocked_pii(last) or await self._harmful(recent)
        except Exception as exc:  # noqa: BLE001
            print(f"input guardrail failed open: {exc!r}", flush=True)
            return contains_blocked_pii(last)

    async def blocks_output(self, text: str) -> bool:
        if not text:
            return False
        if contains_blocked_pii(text):
            return True
        try:
            return await self._harmful(text)
        except Exception as exc:  # noqa: BLE001
            print(f"output guardrail failed open: {exc!r}", flush=True)
            return False
