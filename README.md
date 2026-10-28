# Foundry Call Center

A healthcare call-center agent system on **Microsoft Foundry**: an orchestrator
routes member requests to Claims, Appointments and Pharmacy specialists, each
grounded in a knowledge base and backed by simulated enterprise-system tools.

The system is built in phases; see the roadmap for what is done and what is next.
All data is synthetic; there is no real member or PHI data.

## Status

Phases 1-9 done, plus an admin dashboard at `/#/admin` (scaffold; Foundry project + model; Cosmos + Functions tool
backends; Claims, Appointments and Pharmacy specialists with Foundry IQ grounding;
classifier-only orchestrator, since agent-to-agent relay is blocked, see ADR-0006;
chat backend + React UI on Container Apps, ADR-0007;
guardrails + eval gate, ADR-0008; Application Insights tracing + dashboard workbook, ADR-0009, ADR-0010) - see [docs/roadmap.md](docs/roadmap.md).

## Relay blocker re-test

Agent-to-agent relay is blocked by the platform (ADR-0006). `python scripts/relay_probe.py` re-tests it against the deployed agents: exit 0 means fixed, 1 means still blocked, 2 means inconclusive. Last run (2026-10-27): still blocked on agent-framework 1.23.0, foundry-hosting 1.0.0b261022, azd agents extension beta.22.

## Tool backends

```
scripts/deploy_tools.sh rg-foundry-call-center-dev <agent-principal-id>...   # Cosmos + Function App (Entra auth) + code
python seed-data/load_knowledge_base.py https://<search>.search.windows.net   # Foundry IQ knowledge bases (infra/search.bicep)
COSMOS_ENDPOINT=<endpoint> python seed-data/load_seed_data.py
cd tools && python -m pytest                              # unit tests, no Azure needed
```


## Chat app

```
scripts/deploy_chat.sh rg-foundry-call-center-dev <foundry-account> foundry-call-center   # ACR + Container App + roles
cd frontend && npm install && npm run dev   # local UI; run the API with uvicorn in src/chat-backend
```

## Deploy

```
azd env set AZURE_SUBSCRIPTION_ID <id>
azd env set AZURE_LOCATION eastus2
azd env set TOOLS_API_URL <function-app>/api/tools
azd env set TOOLS_API_AUDIENCE api://<fcc-tools-api app id>
azd env set SEARCH_ENDPOINT https://<search>.search.windows.net
azd provision
azd deploy        # if it 404s right after provision, wait a minute and retry
```

Each specialist reads the member from the request's `metadata.member_id`. After the
first deploy of an agent, grant its instance identity (`azd ai agent show <name>`)
access to the tools API and Search (see ADR-0004/0005). Example call:
`POST .../agents/claims-specialist/endpoint/protocols/openai/responses` with
`{"input": "...", "metadata": {"member_id": "MBR-DEMO-000101"}}`.

## Layout

```
agents/          orchestrator + specialist prompts, skills and tool schemas (ported as-is)
eval/            eval_set.yaml (ported; cloud-neutral)
seed-data/       synthetic members/claims/appointments/prescriptions/providers + KB source docs
docs/decisions/  ADRs
docs/roadmap.md  phased plan
```

## Evals

```
python eval/run_eval.py --url https://<chat-app> --workers 3 --threshold 0.9
```

Replays `eval/eval_set.yaml` (single turns and multi-turn conversations) against the
deployed chat API and exits non-zero below the threshold. Needs `httpx` and `pyyaml`.
Results go to `eval/results/` (gitignored). Keep workers low: the model deployment
has 100K TPM and parallel load causes transient platform `server_error`s.

## Admin dashboard

`<chat-url>/#/admin` (sign in with the admin secret) has three tabs: **System Health** (turns, error rate,
latency percentiles, tokens and estimated cost, intent mix, tool use, failures), **Traces** (filterable
turn list; each trace shows the prompt and reply, plus a span waterfall) and **Agent Quality** (eval run
history and per-case results). Get the secret with
`az containerapp secret show -g <rg> -n <chat-app> --secret-name admin-secret --query value -o tsv`.
Eval runs appear after `COSMOS_ENDPOINT=<cosmos-endpoint> python eval/run_eval.py --url <chat-url>`.
Prompt and reply capture is on for this demo (`CAPTURE_CONTENT`); turn it off for real member data.
