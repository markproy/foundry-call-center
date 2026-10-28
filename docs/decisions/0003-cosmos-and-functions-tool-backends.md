# ADR-0003: Tool backends on Cosmos DB + Azure Functions

## Decision

- **Store:** Cosmos DB for NoSQL, serverless, Entra-only (`disableLocalAuth`).
  Five containers; `claims`, `appointments`, `prescriptions` and `members` are
  partitioned by `/member_id`, `providers` by `/provider_id`.
- **Compute:** one Function App (Flex Consumption, Python 3.11) exposing
  `POST /api/tools/{action}` for all twelve actions, instead of five services.
  The logic lives in `tools/callcenter_tools` and is independent of Azure.
- **Contract:** the tool contract is: `{"auth": {"member_id"},
  "params": {...}}`. Identity comes only from `auth`.
- **IaC:** `infra/tools.bicep`, deployed with `scripts/deploy_tools.sh` into the
  azd-created resource group. It is not wired into `azd` (ADR-0002 open
  question), so `azd provision` does not touch it.

## Rationale

- Checking ownership after each read is easy to get wrong. With member_id as the partition key, a record lookup is a point
  read inside the caller's own partition, so another member's record is
  unreachable and indistinguishable from a missing one. The checks are
  structural, and `tests/test_logic.py` still asserts the behaviour.
- One Function App serves all actions; a per-service split would be a deployment artifact, not a domain boundary.
- Serverless Cosmos and Flex Consumption keep an idle demo near zero cost.
- No keys: Cosmos and the Function App's storage use managed identity.

## Open items

- The endpoint is protected by a Function key only. Before the Foundry agents
  call it, move to Entra auth (Easy Auth with the project/agent identity) or an
  MCP tool exposure; decide in phase 4.
- `reschedule_appointment` writes to Cosmos.

## Verified

Unit tests (11, in-memory repo with the same partition semantics) and a live
smoke test: owner reads a claim, another member gets "not found", no `auth`
gives 401, no function key gives 401.
