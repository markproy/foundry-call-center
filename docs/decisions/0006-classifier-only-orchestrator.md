# ADR-0006: Classifier-only orchestrator (agent-to-agent relay blocked)

Status: accepted, **to be revisited**

## Context
The original design had the orchestrator classify intent and then relay to a specialist.
We built that on Foundry: the orchestrator hosted agent classified, then
streamed the specialist's Responses endpoint.

## The problem
Classification worked. The relay always failed with a `response.failed` from the
specialist: `Foundry hosted requests require a trusted user ID and call ID.`

- That check lives in `agent_framework_foundry_hosting/_scope.py`. It needs the
  platform headers `x-agent-user-id` and `x-agent-foundry-call-id`.
- The platform injects those headers only for callers presenting a **user**
  token. The orchestrator calls with its **managed identity** (`idtyp=app`), so
  the specialist never receives them. Our own user token works.
- Docs ("Isolate hosted agent sessions per user", "Hosted agent permissions")
  describe a middle tier passing `x-ms-user-identity` once it holds the custom
  data action `Microsoft.CognitiveServices/accounts/AIServices/agents/endpoints/UserIdentityImpersonation/action`.
  We created that role ([infra/roles/user-identity-delegate.json](../../infra/roles/user-identity-delegate.json)),
  assigned it to the orchestrator identity at resource-group and account scope,
  and waited for propagation. The specialist still got no user/call id.
  Removing the role changed nothing, so the header appears to be ignored for
  app-identity callers (the 403 for a user without the role proves it is checked
  for user tokens).
- Also tried: forwarding the call id, `isolation_key_source: Header` (rejected for
  protocol 2.0.0 agents, which direct you to `x-ms-user-identity`).

## Decision
The orchestrator only classifies. It replies with JSON
`{"intent": "claims|appointments|pharmacy|out_of_scope|error", "reason": "...", "message"?: "..."}`.
`message` carries the fixed redirect (out_of_scope) or error text. The Phase 7
chat backend calls the orchestrator, then calls the chosen specialist with the
authenticated user's identity and sets `metadata.member_id`. The orchestrator
is stateless: the caller sends the whole conversation as an input list each turn.

## Consequences
- Routing logic and the specialist call move to the backend (Phase 7).
- The backend identity may also need the delegate role if it calls with a
  service identity rather than a user token. Delegated calls from a service
  principal are the thing to re-test first.
- The delegate role definition is kept in `infra/roles/` but is unassigned.

## Revisit
Update (ADR-0007): a Container App managed identity holding the same delegate role
*can* call agents with `x-ms-user-identity`, so the limitation seems specific to
calls made from inside a hosted agent. Re-test that first.

Also try: an OBO token for the
user, A2A or Toolbox-based agent calling, or in-process sub-agents in one
hosted agent.

## Re-test log

Run `python scripts/relay_probe.py` (needs `httpx`, an `az` login, and the orchestrator deployed with its `__relay_probe__` mode). It makes a control call (user to specialist) and a relay call (orchestrator managed identity to specialist). Exit 0: relay works, the blocker is gone. Exit 1: still blocked. Exit 2: inconclusive.

- **Latest run: still blocked.** The control call succeeds. The relay returns `Foundry hosted requests require a trusted user ID and call ID.` Pinned `agent-framework-foundry-hosting` is 1.0.0b261022.
- **Release notes checked:** agent-framework python 1.20.0 to 1.23.0 and azd agents extension beta.11 to beta.22. Neither mentions this check, `x-ms-user-identity` for agent callers, or agent-to-agent identity propagation. The hosting changes are unrelated: a redesign (1.20), sandbox and header hardening, and the MCP 2.x foundation (1.23).
