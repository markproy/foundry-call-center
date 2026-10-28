"""Admin API behind the /admin UI (ADR-0010): health, traces and eval history.

Health and traces are KQL over the Application Insights spans written by telemetry.py
(queried with the app's managed identity through the App Insights REST API). Eval runs
are documents in the Cosmos `evalruns` container, uploaded by eval/run_eval.py.
Every route requires the x-admin-secret header; with no ADMIN_SECRET configured the
admin API is disabled.
"""

import asyncio
import hmac
import os
import re

import httpx
from azure.identity.aio import DefaultAzureCredential
from fastapi import APIRouter, HTTPException, Request

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
APPI_APP_ID = os.environ.get("APPINSIGHTS_APP_ID", "")
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "")
# gpt-4.1-mini list prices, USD per 1M tokens; keep in step with infra/workbook.json.
PRICE_IN, PRICE_OUT = 0.40, 1.60

_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_credential = DefaultAzureCredential()
_http = httpx.AsyncClient(timeout=30)
_cosmos = None


async def _guard(request: Request) -> None:
    supplied = request.headers.get("x-admin-secret", "")
    if not ADMIN_SECRET or not hmac.compare_digest(supplied.encode(), ADMIN_SECRET.encode()):
        raise HTTPException(status_code=403, detail="forbidden")


router = APIRouter(prefix="/api/admin")


@router.get("/ping")
async def ping(request: Request):
    await _guard(request)
    return {"ok": True}


async def _kql(query: str, hours: int) -> list[dict]:
    if not APPI_APP_ID:
        raise HTTPException(status_code=503, detail="APPINSIGHTS_APP_ID not configured")
    token = await _credential.get_token("https://api.applicationinsights.io/.default")
    resp = await _http.post(
        f"https://api.applicationinsights.io/v1/apps/{APPI_APP_ID}/query",
        json={"query": query, "timespan": f"PT{hours}H"},
        headers={"authorization": f"Bearer {token.token}"},
    )
    if resp.status_code >= 400:
        print(f"app insights query failed {resp.status_code}: {resp.text[:300]}", flush=True)
        raise HTTPException(status_code=502, detail="telemetry query failed")
    table = resp.json()["tables"][0]
    names = [c["name"] for c in table["columns"]]
    return [dict(zip(names, row)) for row in table["rows"]]


def _hours(value: int) -> int:
    return max(1, min(value, 24 * 30))


def _num(v):
    return None if v is None else round(v, 1)


_TURN = """
dependencies | where name == 'chat_turn'
| extend member = tostring(customDimensions.member_id), session = tostring(customDimensions.session_id),
    intent = tostring(customDimensions.intent), agent = tostring(customDimensions.agent),
    tools = tostring(customDimensions.tools), guard = tostring(customDimensions.guardrail),
    total = todouble(customDimensions.total_ms), ttft = todouble(customDimensions.ttft_ms),
    classify = todouble(customDimensions.classify_ms),
    inTok = coalesce(todouble(customDimensions.orchestrator_input_tokens), 0.0) + coalesce(todouble(customDimensions.specialist_input_tokens), 0.0),
    outTok = coalesce(todouble(customDimensions.orchestrator_output_tokens), 0.0) + coalesce(todouble(customDimensions.specialist_output_tokens), 0.0)
"""


def _cost(in_tokens, out_tokens) -> float:
    return round((in_tokens or 0) * PRICE_IN / 1e6 + (out_tokens or 0) * PRICE_OUT / 1e6, 4)


@router.get("/health")
async def health(request: Request, hours: int = 24):
    await _guard(request)
    hours = _hours(hours)
    bin_ = "1h" if hours <= 48 else "1d"
    totals_q = _TURN + """| summarize turns = count(), errors = countif(success == false), guardrail_blocks = countif(guard != ''),
        members = dcount(member), total_p50 = percentile(total, 50), total_p95 = percentile(total, 95),
        ttft_p50 = percentile(ttft, 50), ttft_p95 = percentile(ttft, 95),
        classify_p50 = percentile(classify, 50), classify_p95 = percentile(classify, 95),
        input_tokens = sum(inTok), output_tokens = sum(outTok)"""
    intent_q = _TURN + """| summarize turns = count(), errors = countif(success == false), total_p95 = percentile(total, 95),
        input_tokens = sum(inTok), output_tokens = sum(outTok) by intent, agent | order by turns desc"""
    series_q = _TURN + f"""| summarize turns = count(), errors = countif(success == false), total_p95 = percentile(total, 95) by t = bin(timestamp, {bin_}) | order by t asc"""
    tools_q = """dependencies | where name == 'specialist' | extend tool = split(tostring(customDimensions.tools), ',') | mv-expand tool to typeof(string)
        | where isnotempty(tool) | summarize calls = count() by agent = tostring(customDimensions.agent), tool | order by calls desc"""
    fails_q = """dependencies | where name in ('classify', 'specialist') and success == false
        | summarize failures = count(), last_seen = max(timestamp) by stage = name, agent = tostring(customDimensions.agent), error_type = tostring(customDimensions.error_type)
        | order by failures desc"""
    totals, intents, series, tools, fails = await asyncio.gather(
        *(_kql(q, hours) for q in (totals_q, intent_q, series_q, tools_q, fails_q))
    )
    t = totals[0] if totals else {}
    for row in intents:
        row["cost_usd"] = _cost(row["input_tokens"], row["output_tokens"])
    return {
        "hours": hours,
        "totals": {
            **{k: (_num(v) if isinstance(v, float) else v) for k, v in t.items()},
            "cost_usd": _cost(t.get("input_tokens"), t.get("output_tokens")),
        },
        "by_intent": intents,
        "series": series,
        "tools": tools,
        "failures": fails,
    }


@router.get("/traces")
async def traces(request: Request, hours: int = 24, member: str = "", intent: str = "",
                 errors_only: bool = False, limit: int = 50):
    await _guard(request)
    hours = _hours(hours)
    filters = []
    for column, value in (("member", member), ("intent", intent)):
        if value:
            if not _ID_RE.match(value):
                raise HTTPException(status_code=400, detail=f"invalid {column}")
            filters.append(f"| where {column} == '{value}'")
    if errors_only:
        filters.append("| where success == false")
    q = _TURN + "\n".join(filters) + f"""
| extend user_message = tostring(customDimensions.user_message)
| order by timestamp desc | take {max(1, min(limit, 200))}
| project timestamp, operation_Id, member, session, intent, agent, tools, guard, total, ttft, ok = success,
    cost_in = inTok, cost_out = outTok, user_message"""
    rows = await _kql(q, hours)
    for r in rows:
        r["cost_usd"] = _cost(r.pop("cost_in"), r.pop("cost_out"))
    return {"traces": rows}


@router.get("/traces/{operation_id}")
async def trace_detail(request: Request, operation_id: str):
    await _guard(request)
    if not re.match(r"^[0-9a-f]{32}$", operation_id):
        raise HTTPException(status_code=400, detail="invalid trace id")
    q = f"""let t0 = toscalar(union dependencies, requests | where operation_Id == '{operation_id}' | summarize min(timestamp));
union withsource=src dependencies, requests | where operation_Id == '{operation_id}'
| project start_ms = datetime_diff('millisecond', timestamp, t0), id, parent = operation_ParentId, name, duration_ms = duration,
    ok = tostring(success) =~ 'true', source = src, target, dims = tostring(customDimensions)
| order by start_ms asc"""
    rows = await _kql(q, 24 * 30)
    if not rows:
        raise HTTPException(status_code=404, detail="trace not found")
    by_id = {r["id"]: r for r in rows}

    def depth(r) -> int:
        d, seen = 0, set()
        while r.get("parent") in by_id and r["parent"] not in seen:
            seen.add(r["parent"])
            r, d = by_id[r["parent"]], d + 1
        return d

    for r in rows:
        r["depth"] = depth(r)
        r["duration_ms"] = _num(r["duration_ms"])
    turn = next((r for r in rows if r["name"] == "chat_turn"), None)
    return {"operation_id": operation_id, "turn": turn, "spans": rows}


async def _evals():
    global _cosmos
    if not COSMOS_ENDPOINT:
        raise HTTPException(status_code=503, detail="COSMOS_ENDPOINT not configured")
    if _cosmos is None:
        from azure.cosmos.aio import CosmosClient

        _cosmos = CosmosClient(COSMOS_ENDPOINT, credential=_credential)
    return _cosmos.get_database_client("callcenter").get_container_client("evalruns")


@router.get("/evals")
async def eval_runs(request: Request, limit: int = 30):
    await _guard(request)
    container = await _evals()
    query = ("SELECT c.id, c.timestamp, c.pass_rate, c.threshold, c.total, c.passed, c.chat_url "
             f"FROM c ORDER BY c.timestamp DESC OFFSET 0 LIMIT {max(1, min(limit, 100))}")
    return {"runs": [r async for r in container.query_items(query)]}


@router.get("/evals/{run_id}")
async def eval_run(request: Request, run_id: str):
    await _guard(request)
    if not _ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    container = await _evals()
    try:
        doc = await container.read_item(run_id, partition_key=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {k: v for k, v in doc.items() if not k.startswith("_")}
