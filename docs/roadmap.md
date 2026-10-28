# Roadmap

## Phases

1. **Scaffold** (done): repo, ported assets, roadmap, ADR-0001.
2. **Infrastructure baseline** (done, see ADR-0002): azd, Foundry project, gpt-4.1-mini, baseline hosted agent deployed and invoked. Cosmos and Search move to the phases that need them.
3. **Tool backends** (done, see ADR-0003): 12 actions on one Function App, Cosmos DB, seed loader, 11 unit tests, live smoke test.
4. **First specialist (Claims)** (tools done, see ADR-0004): hosted agent with 4 member-bound tools behind Entra auth, deployed and verified. **4b done (ADR-0005): Foundry IQ KB grounding** (`search_knowledge_base`).
5. **Appointments and Pharmacy specialists** (done): same pattern as Claims, generated from each agent's `tool_schemas.json`; per-domain knowledge bases; each agent identity is granted the tools API and Search Index Data Reader. Model capacity raised to 100K TPM after a rate-limit failure with two agents active.
6. **Orchestrator** (done as classifier-only, see ADR-0006): returns `{intent, reason, message?}`; routing to the specialist moves to the Phase 7 backend because agent-to-agent calls are blocked by the platform. Revisit.
7. **Chat backend and frontend** (done, see ADR-0007; demo-grade auth, Entra sign-in still to do): streaming API that calls the orchestrator for intent, then the chosen specialist with the user's token (sets `metadata.member_id` from the authenticated user), React chat UI, single public entry point.
8. **Safety and evals** (done, see ADR-0008): Content Safety + Prompt Shields on input, harm + SSN/card checks on output, `eval/run_eval.py` replay gate. Foundry-native evaluations are still to do.
9. **Observability** (done, see ADR-0009): Application Insights, one `chat_turn` trace per message with `classify` and `specialist` child spans, token usage, and an "operations" Workbook (health, routing, latency, tools, cost, failures). An **admin dashboard** in the UI (ADR-0010) covers health, trace exploration and eval history. Agent-side spans joining the trace and Foundry-native evaluations are still to do.
10. **Optimization backlog**: latency work and accuracy gaps carried over from the source repo.

Open items for phase 10:
- Re-test agent-to-agent routing with `scripts/relay_probe.py` after platform or library releases (ADR-0006).
- Entra sign-in to replace the shared admin secret and the demo `member_id`.
- Cold-start latency: the first message takes 15-30s.
- Browser-test the guardrail redirect and out-of-scope flows.
- Agent-side trace joining and Foundry-native evaluations.
- Link eval runs to traces by sending a `session_id` from the eval runner.
