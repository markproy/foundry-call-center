# ADR-0007: Chat backend and UI on Container Apps

Status: accepted

## Context
Phase 7 needs a public entry point that routes each turn: orchestrator for
intent (ADR-0006), then the chosen specialist, streamed to a browser.

## Decisions
- **One service** (`src/chat-backend`, FastAPI) serves `/api/chat`, `/api/warmup`
  and the built React UI (`frontend/`, Vite + TS), so there is a single origin and
  no CORS. Streaming is SSE: `text_delta`, `done`, `error`.
- **Azure Container Apps + ACR** (`infra/chat.bicep`, `scripts/deploy_chat.sh`).
  App Service quota was 0 for F1 and B1 in this subscription; Container Apps needs
  no VM quota. The script deploys the app on a placeholder image, grants roles,
  builds with `az acr build`, then re-deploys with the real image.
- **Calls to agents use the app's managed identity plus `x-ms-user-identity: <member_id>`.**
  The identity holds "Foundry User" and the custom "Foundry Agent User Identity
  Delegate" role on the Foundry account (`infra/roles/`). **This works** from a
  Container App, so delegated calls from a service identity are viable. The
  orchestrator-to-specialist case in ADR-0006 still failed with the same kind of
  identity (hosted agent MI); the difference is worth investigating when revisiting.
- **Stateless chat:** the browser sends the full message list each turn (max 20),
  matching the stateless orchestrator.
- **Session reuse:** a cold hosted-agent session costs ~8-10s. The backend caches
  `x-agent-session-id` per (agent, member) and sends it back as `agent_session_id`;
  `/api/warmup` (called by the UI on member selection) starts all four sessions.
  The cache is in-process, so it is lost on restart and not shared across replicas
  (a miss only costs a cold start).

## Trust boundary (important)
`member_id` is taken from the request body. The backend only validates its format.
This is demo-grade: anyone who can reach the URL can chat as any demo member.
Mitigation now: optional `DEMO_SHARED_SECRET` (header `x-demo-secret`). Before any
real data: put Entra sign-in (Container Apps auth) in front and derive `member_id`
from the signed-in user's claims, never from the client.

## Measured (warm sessions)
Classification ~4s, first token ~5s, total 6-13s. Sources: hosted-agent overhead
on the classifier call plus the specialist's tool call + model call. Phase 10 item.

## Verified live
Appointments, claims and pharmacy routing; out-of-scope redirect; a multi-turn
follow-up; a different member cannot see claim `CLM-DEMO-10005` ("not found");
malformed member id -> 400.
