"""Chat backend: the web channel adapter and the single public entry point.

Per turn: ask the orchestrator for the intent, then stream the chosen
specialist's answer back to the browser as SSE. The orchestrator only
classifies (ADR-0006), so this service does the routing.

Both agent calls use this app's managed identity plus `x-ms-user-identity`
(the member id) so the platform sees a delegated end user; see ADR-0007.
The same app serves the built React UI from ./static.

SSE events: {"type":"text_delta","text":...}, {"type":"done","intent",...},
{"type":"error","error":...}.
"""
import asyncio
import datetime
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import admin
import telemetry
from guardrails import BLOCKED_MESSAGE, ContentSafety

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
DEMO_SHARED_SECRET = os.environ.get("DEMO_SHARED_SECRET", "")
MAX_HISTORY = 20
# Prompts and answers are attached to traces only when enabled (demo data is synthetic).
CAPTURE_CONTENT = os.environ.get("CAPTURE_CONTENT", "").lower() in ("1", "true", "yes")
MEMBER_RE = re.compile(r"^MBR-[A-Za-z0-9-]{3,40}$")
SPECIALISTS = {
    "claims": "claims-specialist",
    "appointments": "appointments-specialist",
    "pharmacy": "pharmacy-specialist",
}
ERROR_MESSAGE = "Sorry - something went wrong on our side. Please send your message again."

# Cold agent sessions cost ~8s, so reuse one session per (agent, member). The platform
# returns the id in x-agent-session-id; sending it back as agent_session_id reuses it.
_sessions: dict[tuple[str, str], str] = {}

telemetry.setup()
app = FastAPI()
app.include_router(admin.router)
_credential = DefaultAzureCredential()
_http = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
_account = urlparse(PROJECT_ENDPOINT).hostname.split(".")[0]
_safety = ContentSafety(
    os.environ.get("CONTENT_SAFETY_ENDPOINT", f"https://{_account}.cognitiveservices.azure.com"), _credential, _http
)


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    member_id: str
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{8,64}$")
    messages: list[Turn] = Field(min_length=1, max_length=MAX_HISTORY)


def _capture(rec: dict, answer: str) -> None:
    if CAPTURE_CONTENT:
        rec["answer"] = answer[:4000]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _agent_url(agent: str) -> str:
    return f"{PROJECT_ENDPOINT}/agents/{agent}/endpoint/protocols/openai/responses?api-version=v1"


async def _headers(member_id: str) -> dict:
    token = await _credential.get_token("https://ai.azure.com/.default")
    headers = {"authorization": f"Bearer {token.token}", "x-ms-user-identity": member_id}
    tp = telemetry.traceparent()
    if tp:
        headers["traceparent"] = tp
    return headers


def _payload(agent: str, member_id: str, messages, stream: bool) -> dict:
    # Models do not know the date; specialists compare record dates (refill eligibility,
    # appointments) with the present, so every request carries it.
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    if agent in SPECIALISTS.values():
        messages = [{"role": "system", "content": f"Today's date is {today} (UTC)."}, *messages]
    body = {"input": messages, "stream": stream, "metadata": {"member_id": member_id}}
    sid = _sessions.get((agent, member_id))
    if sid:
        body["agent_session_id"] = sid
    return body


def _remember(agent: str, member_id: str, resp: httpx.Response) -> None:
    sid = resp.headers.get("x-agent-session-id")
    if sid:
        _sessions[(agent, member_id)] = sid


async def _post(agent: str, member_id: str, messages) -> httpx.Response:
    """Non-streaming call; drops a stale cached session and retries once on a 4xx."""
    for attempt in range(2):
        resp = await _http.post(
            _agent_url(agent),
            json=_payload(agent, member_id, messages, False),
            headers=await _headers(member_id),
        )
        if resp.status_code < 400 or attempt == 1:
            break
        _sessions.pop((agent, member_id), None)
    resp.raise_for_status()
    _remember(agent, member_id, resp)
    return resp


async def _classify(messages: list[dict], member_id: str) -> dict:
    resp = await _post("orchestrator", member_id, messages)
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:300])
    text = "".join(
        c.get("text", "")
        for o in body.get("output", [])
        if o.get("type") == "message"
        for c in o.get("content", [])
    )
    decision = json.loads(text)
    decision["_usage"] = body.get("usage") or {}
    return decision


async def _traced_classify(messages: list[dict], member_id: str) -> dict:
    span = telemetry.child("classify")
    try:
        decision = await _classify(messages, member_id)
    except Exception as exc:
        telemetry.finish(span, error=True, error_type=type(exc).__name__)
        raise
    usage = decision.get("_usage", {})
    telemetry.finish(span, intent=decision.get("intent"), input_tokens=usage.get("input_tokens", 0),
                     output_tokens=usage.get("output_tokens", 0))
    return decision


async def _stream_specialist(agent: str, messages: list[dict], member_id: str):
    async with _http.stream(
        "POST",
        _agent_url(agent),
        json=_payload(agent, member_id, messages, True),
        headers=await _headers(member_id),
    ) as resp:
        if resp.status_code != 200:
            await resp.aread()
            _sessions.pop((agent, member_id), None)
            raise RuntimeError(f"{agent} returned {resp.status_code}: {resp.text[:300]}")
        _remember(agent, member_id, resp)
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            event = json.loads(data)
            etype = event.get("type")
            if etype == "response.output_text.delta":
                yield "text", event["delta"]
            elif etype == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                yield "tool", event["item"].get("name", "")
            elif etype == "response.completed":
                yield "usage", event.get("response", {}).get("usage") or {}
            elif etype in ("response.failed", "error"):
                raise RuntimeError(f"{agent} failed: {data[:300]}")


def _unauthorized(request: Request):
    if DEMO_SHARED_SECRET and request.headers.get("x-demo-secret") != DEMO_SHARED_SECRET:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return None


@app.get("/api/health")
async def health():
    return {"ok": True}


class WarmupRequest(BaseModel):
    member_id: str


@app.post("/api/warmup")
async def warmup(req: WarmupRequest, request: Request):
    """Starts this member's session on every agent so the first real message is fast."""
    denied = _unauthorized(request)
    if denied:
        return denied
    if not MEMBER_RE.match(req.member_id):
        return JSONResponse(status_code=400, content={"error": "invalid member_id"})
    hello = [{"role": "user", "content": "hello"}]

    async def one(agent: str):
        try:
            await _post(agent, req.member_id, hello)
        except Exception as exc:  # noqa: BLE001
            print(f"warmup {agent} failed: {exc!r}", flush=True)

    await asyncio.gather(*(one(a) for a in ["orchestrator", *SPECIALISTS.values()]))
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    denied = _unauthorized(request)
    if denied:
        return denied
    if not MEMBER_RE.match(req.member_id):
        return JSONResponse(status_code=400, content={"error": "invalid member_id"})
    if req.messages[-1].role != "user":
        return JSONResponse(status_code=400, content={"error": "last message must be from the user"})
    messages = [t.model_dump() for t in req.messages]
    member_id = req.member_id

    async def events():
        turn = telemetry.start_turn(member_id)
        rec: dict = {"session_id": req.session_id}
        if CAPTURE_CONTENT:
            rec["user_message"] = messages[-1]["content"][:2000]
        try:
            async for chunk in _turn(rec):
                yield chunk
        except BaseException:
            rec["error"] = True
            raise
        finally:
            telemetry.finish(turn, error=bool(rec.pop("error", False)), **rec)

    async def _turn(rec: dict):
        start = time.perf_counter()
        ms = lambda: round((time.perf_counter() - start) * 1000)  # noqa: E731
        # The input guardrail runs alongside classification so it adds no latency.
        blocked, classified = await asyncio.gather(
            _safety.blocks_input(messages), _traced_classify(messages, member_id), return_exceptions=True
        )
        if blocked is True:
            rec.update(intent="blocked", guardrail="input", total_ms=ms())
            _capture(rec, BLOCKED_MESSAGE)
            yield _sse({"type": "text_delta", "text": BLOCKED_MESSAGE})
            yield _sse({"type": "done", "intent": "blocked", "guardrail": "input", "total_ms": ms()})
            return
        if isinstance(classified, Exception):
            print(f"classification failed: {classified!r}", flush=True)
            rec.update(error=True, outcome="classification_failed", total_ms=ms())
            yield _sse({"type": "error", "error": ERROR_MESSAGE})
            return
        usage = classified.pop("_usage", {})
        decision, intent = classified, classified.get("intent")
        classify_ms = ms()
        rec.update(intent=intent, classify_ms=classify_ms, orchestrator_input_tokens=usage.get("input_tokens", 0),
                   orchestrator_output_tokens=usage.get("output_tokens", 0))
        specialist = SPECIALISTS.get(intent)
        if not specialist:
            text = decision.get("message") or ERROR_MESSAGE
            rec["total_ms"] = ms()
            _capture(rec, text)
            yield _sse({"type": "text_delta", "text": text})
            yield _sse({"type": "done", "intent": intent, "reason": decision.get("reason"),
                        "classify_ms": classify_ms, "total_ms": ms()})
            return
        yield _sse({"type": "status", "text": f"Asking the {intent} agent…"})
        sent, first, answer, tools, gap = False, None, [], [], False
        spec_usage: dict = {}
        spec = telemetry.child("specialist", agent=specialist)
        rec["agent"] = specialist
        # Platform "server_error"s are transient under load; retry once if nothing has streamed.
        for attempt in (1, 2):
            try:
                async for kind, value in _stream_specialist(specialist, messages, member_id):
                    if kind == "usage":
                        spec_usage = value
                        continue
                    if kind == "tool":
                        tools.append(value)
                        gap = sent  # text after a tool call starts a new paragraph
                        label = "Searching our guides…" if value == "search_knowledge_base" else "Looking up your records…"
                        yield _sse({"type": "status", "text": label})
                        continue
                    if gap:
                        value, gap = "\n\n" + value, False
                    if first is None:
                        first = ms()
                    sent = True
                    answer.append(value)
                    yield _sse({"type": "text_delta", "text": value})
                break
            except Exception as exc:  # noqa: BLE001
                print(f"specialist call failed (attempt {attempt}): {exc!r}", flush=True)
                if sent or attempt == 2:
                    if not sent:
                        telemetry.finish(spec, error=True, error_type=type(exc).__name__)
                        rec.update(error=True, outcome="specialist_failed", total_ms=ms(), tools=tools)
                        yield _sse({"type": "error", "error": ERROR_MESSAGE})
                        return
                    break
                tools.clear()
                await asyncio.sleep(2)
        guardrail = None
        telemetry.finish(spec, tools=tools, ttft_ms=first,
                         input_tokens=spec_usage.get("input_tokens", 0),
                         output_tokens=spec_usage.get("output_tokens", 0))
        # The answer has already streamed; if it fails the check the UI replaces it.
        if await _safety.blocks_output("".join(answer)):
            guardrail = "output"
            yield _sse({"type": "replace", "text": BLOCKED_MESSAGE})
        _capture(rec, BLOCKED_MESSAGE if guardrail else "".join(answer))
        rec.update(tools=tools, guardrail=guardrail, ttft_ms=first, total_ms=ms(),
                   specialist_input_tokens=spec_usage.get("input_tokens", 0),
                   specialist_output_tokens=spec_usage.get("output_tokens", 0))
        yield _sse({"type": "done", "intent": intent, "reason": decision.get("reason"), "agent": specialist,
                    "tools": tools, "guardrail": guardrail,
                    "classify_ms": classify_ms, "ttft_ms": first, "total_ms": ms()})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


STATIC = Path(__file__).parent / "static"
if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="ui")
