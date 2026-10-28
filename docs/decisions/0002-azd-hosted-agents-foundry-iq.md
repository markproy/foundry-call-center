# ADR-0002: azd + Foundry hosted agents, Foundry IQ for retrieval

## Decision

- **Tooling:** `azd` with the `azure.ai.agents` extension. `azure.yaml` declares
  an `ai-project` service (Foundry project + model deployments) and one
  `host: azure.ai.agent` service per agent.
- **Agents:** Foundry *hosted* agents (code deploy, Python 3.13, Microsoft Agent
  Framework, Responses protocol), one per agent (orchestrator + 3 specialists).
- **Retrieval:** Foundry IQ knowledge bases (built on Azure AI Search), starting
  at `minimal` retrieval reasoning effort to avoid LLM query-planning latency.
  Fallback: query the same Search index directly.
- **Model:** `gpt-4.1-mini`, GlobalStandard, `eastus2`.

## Findings

- `infra.provider: microsoft.foundry` provisions the resource group, Foundry
  resource, project and model deployment **without any local Bicep**. Bicep is
  not required for the Foundry baseline. Cosmos DB (tool data) and any Search
  resources beyond what Foundry IQ creates will need custom Bicep, added in the
  phase that first needs them; how that coexists with the `microsoft.foundry`
  provider must be verified then.
- The first `azd deploy` right after `azd provision` returned 404 "Project not
  found"; retrying after ~1 minute succeeded (propagation delay).
- A hosted-agent cold invoke took ~15s (8s first byte). Relevant to the latency
  work in phase 10.
