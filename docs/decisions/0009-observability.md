# ADR-0009: Observability with Application Insights

Status: accepted

## Context
Phases 7-8 gave us a working chat path with no visibility into latency, routing, tool use, failures or cost. 

## Decision
- **Application Insights** (workspace-based, in `infra/chat.bicep`) receives OpenTelemetry from the chat backend via `azure-monitor-opentelemetry`; `src/chat-backend/telemetry.py` is a no-op when no connection string is set.
- Each message produces one `chat_turn` span with child `classify` and `specialist` spans. Attributes: `member_id`, `intent`, `agent`, `tools`, `guardrail`, `classify_ms`, `ttft_ms`, `total_ms`, input/output tokens per stage. Spans appear in the `dependencies` table; failures set `success == false`. **Message content is never recorded.**
- Token usage is read from the Responses `usage` (orchestrator body, specialist `response.completed`). Cost in the dashboard is an estimate using gpt-4.1-mini list prices embedded in the KQL.
- The backend forwards a W3C `traceparent` header on agent calls. Whether the hosted agent runtime joins it is unverified; if not, the backend spans still give the full per-stage picture.
- **Dashboard**: a shared Workbook (`infra/workbook.json`, deployed by the same template) with health, intent mix, p50/p95 latency by stage, tool use, tokens/cost, failures by stage and the slowest turns (with `operation_Id` for drill-down).

## Consequences
- Quality is covered by guardrail-block and failure rates here, and by `eval/run_eval.py` as a gate. Foundry-native evaluations over traces are a follow-up.
- Pre-existing gotcha, now twice: every new backend module must be added to the `COPY` line in the chat Dockerfile.
