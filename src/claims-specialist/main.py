"""Claims specialist hosted agent.

The member the call is about is bound per request by `bind_member` from the
Responses `metadata.member_id` field and handed to tools through
a request-scoped ContextVar. Tool schemas shown to the model contain no member
parameter, so the model can neither choose nor change whose data is read.
"""
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated

import httpx
from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import Field

load_dotenv()

HERE = Path(__file__).parent
TOOLS_URL = os.environ.get("TOOLS_API_URL", "").rstrip("/")
TOOLS_AUDIENCE = os.environ.get("TOOLS_API_AUDIENCE", "")
SEARCH_ENDPOINT = os.environ.get("SEARCH_ENDPOINT", "").rstrip("/")
KNOWLEDGE_BASE = os.environ.get("KNOWLEDGE_BASE_NAME", "kb-claims")

_credential = DefaultAzureCredential()
_http = httpx.AsyncClient(timeout=20)
_member: ContextVar[str | None] = ContextVar("member_id", default=None)
_token = {"value": "", "exp": 0.0}
_search_token = {"value": "", "exp": 0.0}


def _bearer() -> str:
    if time.time() > _token["exp"] - 120:
        t = _credential.get_token(f"{TOOLS_AUDIENCE}/.default")
        _token.update(value=t.token, exp=float(t.expires_on))
    return _token["value"]


def _search_bearer() -> str:
    if time.time() > _search_token["exp"] - 120:
        t = _credential.get_token("https://search.azure.com/.default")
        _search_token.update(value=t.token, exp=float(t.expires_on))
    return _search_token["value"]


async def _call(action: str, params: dict) -> str:
    member_id = _member.get()
    if not member_id:
        return json.dumps({"error": "No authenticated member on this call."})
    resp = await _http.post(
        f"{TOOLS_URL}/{action}",
        json={"auth": {"member_id": member_id}, "params": params},
        headers={"authorization": f"Bearer {_bearer()}"},
    )
    return resp.text


@tool(approval_mode="never_require")
async def get_claim_status(
    claim_id: Annotated[str, Field(description="The claim ID, e.g. CLM-DEMO-10045")],
) -> str:
    """Look up a single claim by its claim ID and return its current status, amounts, and (if denied) the denial reason code. Only claims belonging to the member on this call can be read."""
    return await _call("get_claim_status", {"claim_id": claim_id})


@tool(approval_mode="never_require")
async def search_claims_by_member() -> str:
    """List all claims on file for the member on this call, most recent first. Takes no arguments - the member is bound from the authenticated session, not passed in."""
    return await _call("search_claims_by_member", {})


@tool(approval_mode="never_require")
async def get_appeal_info(
    claim_id: Annotated[str, Field(description="The claim ID, e.g. CLM-DEMO-10045")],
) -> str:
    """For a denied claim, return whether it is eligible for appeal, the appeal deadline, and current appeal status. Only claims belonging to the member on this call can be read."""
    return await _call("get_appeal_info", {"claim_id": claim_id})


@tool(approval_mode="never_require")
async def check_eligibility() -> str:
    """Check the current enrollment status and plan of the member on this call, to confirm they are eligible for the claim being discussed. Takes no arguments - the member is bound from the authenticated session, not passed in."""
    return await _call("check_eligibility", {})


@tool(approval_mode="never_require")
async def search_knowledge_base(
    query: Annotated[str, Field(description="What to search for")],
) -> dict:
    """Search the claims policy knowledge base (denial reason codes, appeals FAQ, coverage policy) for grounding context."""
    if not SEARCH_ENDPOINT:
        return {"passages": []}
    resp = await _http.post(
        f"{SEARCH_ENDPOINT}/knowledgebases/{KNOWLEDGE_BASE}/retrieve?api-version=2026-04-01",
        json={"intents": [{"type": "semantic", "search": query}]},
        headers={"authorization": f"Bearer {_search_bearer()}"},
    )
    resp.raise_for_status()
    body = resp.json()
    scores = {r["id"]: r.get("rerankerScore") for r in body.get("references", [])}
    passages = []
    for part in body.get("response", []):
        for c in part.get("content", []):
            for p in json.loads(c["text"]):
                passages.append({
                    "title": p.get("title"),
                    "content": p.get("content"),
                    "score": scores.get(str(p.get("ref_id"))),
                })
    return {"passages": passages}


def bind_member(request, options):
    """Per-request hook: take the member from request metadata; fail closed if absent."""
    member_id = (request.request.get("metadata") or {}).get("member_id")
    _member.set(member_id or None)
    return options


def build_instructions() -> str:
    prompt = (HERE / "prompts" / "system_prompt.md").read_text()
    skills = json.loads((HERE / "skills.json").read_text())
    return f"{prompt}\n\nYour declared skills:\n{json.dumps(skills, indent=2)}"


def main():
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=_credential,
    )
    agent = Agent(
        client=client,
        instructions=build_instructions(),
        tools=[get_claim_status, search_claims_by_member, get_appeal_info, check_eligibility, search_knowledge_base],
        default_options={"store": False},
    )
    ResponsesHostServer(agent, prepare_options=bind_member).run()


if __name__ == "__main__":
    main()
