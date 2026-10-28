# ADR-0005: Foundry IQ knowledge bases for grounding

Status: accepted

## Decisions
- **Azure AI Search (Basic, `infra/search.bicep`)** hosts one index per domain (`kb-claims`, `kb-appointments`, `kb-pharmacy`), each exposed as a **search-index knowledge source** and a **knowledge base** (GA API `2026-04-01`). `seed-data/load_knowledge_base.py` creates and loads them (one chunk per `##` section; idempotent).
- **No LLM attached to the knowledge base** (GA behaviour): retrieval is semantic search with the semantic ranker (free tier), called with `intents`. Cheaper and faster than query-planning modes; revisit in Phase 10 if recall is a problem. Documents are small, so no vectors or embedding model yet.
- **Auth is Entra only** (`disableLocalAuth`). The agent's instance identity has *Search Index Data Reader*; the deployer has Service/Index Data Contributor.
- The agent's `search_knowledge_base(query)` tool keeps the original name and `{"passages": [...]}` result shape so evals asserting trajectories and citations carry over.
- **Region:** Search is in `eastus`, because `eastus2` had no capacity at deploy time. Other resources stay in `eastus2`.

## Verified
A denied claim (CO-197) question calls `get_claim_status`, `get_appeal_info` and `search_knowledge_base` and answers with the KB's guidance.
