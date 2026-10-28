# ADR-0010: Admin dashboard

Status: accepted

## Context
An in-app dashboard (System Health, Traces with a span waterfall, Agent Quality) was a goal from the start. The Phase 9 Workbook covers the portal view, but operators want it inside the product.

## Decision
- The chat backend exposes `/api/admin/*` (`src/chat-backend/admin.py`), guarded by an `x-admin-secret` header (constant-time compare; disabled when no secret is configured). The React app serves it at `#/admin` with three tabs.
- **Health and traces** are KQL over the ADR-0009 spans, queried through the App Insights REST API with the app's managed identity (Monitoring Reader on the component). A trace's waterfall is every span sharing its `operation_Id`.
- **Evals**: `eval/run_eval.py` uploads each run to the Cosmos `evalruns` container (partition `/id`) when `COSMOS_ENDPOINT` is set; the app identity has Cosmos data access. Local `eval/results/` files are still written.
- **Content**: prompts and replies are attached to the `chat_turn` span only when `CAPTURE_CONTENT` is true (on for this synthetic-data demo). The chat UI sends a `session_id` per conversation; it is recorded on spans.
- `scripts/deploy_chat.sh` generates the admin secret on first deploy (reusing the app's existing one afterwards), creates the container, and grants the roles.

## Consequences
- A shared secret is demo-grade; real use should put Entra roles in front of `/api/admin`.
- The orchestrator's Responses `usage` reports 0 tokens, so cost excludes routing (small: the classifier prompt is short).
- Eval cases carry no trace link because the runner sends no `session_id`; adding one would allow eval-to-trace drill-down.
- KQL gotcha: a union source column cannot be named `kind`; and `success` unions as a string, hence the `tostring(...) =~ 'true'`.
