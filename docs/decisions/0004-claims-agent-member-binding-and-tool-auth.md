# ADR-0004: Claims agent — member binding and tool-API authentication

Status: accepted

## Context
The agent closes `member_id` over its tools per turn, and the model never saw a member parameter. Tools need authenticated access. On Foundry hosted agents we use Entra auth.

## Decisions
1. **Member binding.** The hosting `prepare_options` hook reads `metadata.member_id` from the Responses request and stores it in a request-scoped `ContextVar`. Tools read it from there; they have no member parameter, and a missing member fails closed. Hook-returned options cannot carry tool kwargs (they are forwarded to the model call as chat options — verified, it errors), hence the ContextVar.
2. **Trust boundary.** `metadata.member_id` is caller-supplied. It is only trustworthy when the caller is the (future, Phase 7) chat backend, which derives it from the authenticated user. Callers with access to the agent endpoint can set any member; restrict agent endpoint access accordingly.
3. **Tool API auth.** The Function App uses App Service authentication (Entra) with an app registration (`fcc-tools-api`, assignment required). The hosted agent's instance identity is granted access and obtains tokens via `DefaultAzureCredential`. No shared secret; function keys are no longer used (`AuthLevel.ANONYMOUS` behind Easy Auth).
4. **Packaging.** Prompt and `skills.json` are copied into `src/claims-specialist/` because the deploy package contains only that folder. Dependencies pinned to `agent-framework-core>=1.23`, hosting `>=1.0.0b261022` (older versions lack `prepare_options`).

## Verified (deployed)
Owner reads own claim; another member gets "not found"; no member → refusal; anonymous call to tools API → 401.

## Deferred
Knowledge-base retrieval (Foundry IQ) is Phase 4b; the agent has no `search_knowledge_base` tool yet. Per-version agent identity should be re-checked if the grant stops working after redeploys (it was stable across versions 1→N).
