# ADR-0001: Build on Foundry in phases

## Decision

Build the full call-center feature set incrementally. Reuse
cloud-neutral assets (seed data, KB documents, prompts, tool schemas,
eval set) and implement the platform layer on Azure.

## Rationale

Plans can break against real
platform behavior. Phasing lets each Azure assumption be verified before the
next layer depends on it, and keeps the eval set as the constant across both
implementations.

## Consequences

- Prompts and tool schemas may need light edits for the Azure platform; record such changes in later ADRs.
- Source ADRs (guardrail placement, trace context, latency at the edge) are
  re-evaluated for Azure, not copied.
