"""Orchestrator hosted agent: classify the member's intent and return it.

Each turn makes one structured-output classification call over the whole
conversation and replies with a JSON object:
  {"intent": "claims|appointments|pharmacy|out_of_scope", "reason": "...", "message": "..."}
`message` is only set for out_of_scope (the fixed redirect) and for classifier
failure (intent "error"). The caller (the Phase 7 chat backend) routes to the
specialist itself; see ADR-0006 for why the orchestrator does not relay.
"""
import json
import os
from pathlib import Path
from typing import Literal

from agent_framework import (
    Agent,
    AgentResponse,
    AgentResponseUpdate,
    BaseAgent,
    Content,
    Message,
    ResponseStream,
)
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

HERE = Path(__file__).parent
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")

CLASSIFIER_ERROR_MESSAGE = (
    "Sorry - something went wrong on our side routing your message. "
    "Please send it again."
)
REDIRECT_MESSAGE = (
    "I can help with claims, appointments, and pharmacy questions for your "
    "account. For medical, legal, or financial advice, please contact your "
    "provider or a licensed professional directly."
)

_credential = DefaultAzureCredential()


RELAY_PROBE_PREFIX = "__relay_probe__"


async def relay_probe(agent: str, member_id: str) -> dict:
    """Diagnostic for ADR-0006: calls a specialist from inside this hosted agent with its
    managed identity, exactly as a relaying orchestrator would. scripts/relay_probe.py
    drives it. Returns what the specialist answered so a platform fix is easy to detect."""
    token = _credential.get_token("https://ai.azure.com/.default").token
    url = f"{PROJECT_ENDPOINT}/agents/{agent}/endpoint/protocols/openai/responses?api-version=v1"
    body = {"input": "hello", "stream": False, "metadata": {"member_id": member_id}}
    headers = {"authorization": f"Bearer {token}", "x-ms-user-identity": member_id}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
        resp = await client.post(url, json=body, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    error = data.get("error") or (resp.text[:400] if resp.status_code >= 400 else None)
    text = "".join(
        c.get("text", "")
        for o in data.get("output", [])
        if o.get("type") == "message"
        for c in o.get("content", [])
    )
    ok = resp.status_code == 200 and not error and data.get("status") != "failed" and bool(text)
    return {"probe": "relay", "agent": agent, "http_status": resp.status_code, "ok": ok,
            "error": str(error)[:400] if error else None, "answer": text[:200]}


class IntentDecision(BaseModel):
    intent: Literal["claims", "appointments", "pharmacy", "out_of_scope"]
    reason: str


class Orchestrator(BaseAgent):
    def __init__(self, classifier: Agent):
        super().__init__(name="orchestrator", description="Routes member messages to specialists")
        self._classifier = classifier

    async def _classify(self, messages) -> IntentDecision:
        last: Exception | None = None
        for _ in range(2):  # one retry: realistic failures are transient throttles
            try:
                resp = await self._classifier.run(
                    messages, options={"response_format": IntentDecision, "store": False}
                )
                if resp.value is None:
                    raise ValueError("classifier returned no structured value")
                return resp.value
            except Exception as exc:  # noqa: BLE001
                last = exc
                print(f"classification failed: {exc!r}", flush=True)
                if "contentfilter" in repr(exc).lower().replace("_", ""):
                    # The model's built-in safety filter rejected the prompt: treat as adversarial.
                    return IntentDecision(intent="out_of_scope", reason="blocked by model content filter")
        raise last  # type: ignore[misc]

    async def _updates(self, messages):
        def reply(payload: dict):
            return AgentResponseUpdate(
                contents=[Content.from_text(json.dumps(payload))], role="assistant"
            )

        last = (list(messages or []) or [None])[-1]
        last_text = str(getattr(last, "text", "") or "")
        if last_text.startswith(RELAY_PROBE_PREFIX):
            parts = last_text.split()
            try:
                yield reply(await relay_probe(parts[1], parts[2]))
            except Exception as exc:  # noqa: BLE001
                yield reply({"probe": "relay", "ok": False, "error": repr(exc)[:400]})
            return
        try:
            decision = await self._classify(list(messages or []))
        except Exception:  # noqa: BLE001
            yield reply({"intent": "error", "reason": "classifier failed", "message": CLASSIFIER_ERROR_MESSAGE})
            return
        print(f"routing intent={decision.intent} reason={decision.reason!r}", flush=True)
        payload = {"intent": decision.intent, "reason": decision.reason}
        if decision.intent == "out_of_scope":
            payload["message"] = REDIRECT_MESSAGE
        yield reply(payload)

    def run(self, messages=None, *, stream=False, session=None, **kwargs):
        if isinstance(messages, (str, Message)):
            messages = [messages if isinstance(messages, Message) else Message("user", [messages])]

        def finalize(updates):
            return AgentResponse.from_updates(updates)

        response_stream = ResponseStream(self._updates(messages), finalizer=finalize)
        if stream:
            return response_stream

        async def collect():
            return await response_stream.get_final_response()

        return collect()


def main():
    client = FoundryChatClient(
        project_endpoint=PROJECT_ENDPOINT,
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=_credential,
    )
    prompt = (HERE / "prompts" / "system_prompt.md").read_text()
    classifier = Agent(client=client, instructions=prompt, default_options={"store": False})
    # The caller sends the whole conversation each turn; this agent keeps no history.
    ResponsesHostServer(Orchestrator(classifier), history_source="agent").run()


if __name__ == "__main__":
    main()
