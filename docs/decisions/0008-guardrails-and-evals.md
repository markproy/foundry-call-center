# ADR-0008: Guardrails and eval gate

Status: accepted

## Context
We need guardrails (content filters, prompt-attack detection, topic denial, PII
rules) on input and output, plus a repeatable eval gate.

## Decision
Guardrails live in the chat backend (`src/chat-backend/guardrails.py`), the only
public entry point:

| Original policy | Here |
|---|---|
| Content filters (hate, sexual, violence, misconduct) | Azure AI Content Safety `text:analyze`, block at severity >= 4 (`GUARDRAIL_MIN_SEVERITY`) on input (last 6 turns) and on the output |
| PROMPT_ATTACK | Content Safety Prompt Shields on the latest user message; the model's built-in filter is a second layer (the orchestrator maps a content-filter rejection to `out_of_scope`) |
| Denied topics (medical, legal, financial, off-topic) | The orchestrator's `out_of_scope` intent; not duplicated |
| PII: block SSN/card | Local regex + Luhn on input and output (Content Safety has no text PII detector) |
| PII: anonymize phone/email | Dropped: members' own contact data is legitimate output |

- Input check runs in parallel with classification, so it adds no latency. A block returns the standard redirect with `intent: "blocked"`.
- Output is checked after streaming, so a flagged answer is replaced in the UI via a `replace` event (same accepted trade-off as before).
- Content Safety calls fail open and log; the local PII check still runs.
- The chat app identity needs "Cognitive Services User" on the account (added to `deploy_chat.sh`).
- The `done` event now carries `tools` (function calls the specialist made) and `guardrail`.

`eval/run_eval.py` replays the ported eval set through `/api/chat`, scores intent, contains/excludes and
knowledge-base use, writes JSON to `eval/results/` and exits non-zero under the threshold.

## Findings
- The backend retries a specialist once on transient platform `server_error`s (seen under parallel load). Run evals with 3 workers or fewer.
- Cached agent sessions stay on the code version they started on; restart the chat app after redeploying an agent.
- First full run: 96/97 (99%). The one failure, eval-046, had two causes. (1) The fixture's next-eligible date was absolute and had passed on the real clock, which made the case time-bombed: `load_seed_data.py` now re-dates that record to today + 5 days at load. (2) The assertion matched only a few phrasings of "not eligible yet", so it is broader now. The agents also had no notion of today's date, so the chat backend now prepends a system message with the current UTC date to every specialist request (no agent redeploy needed). Result: 97/97.

## Consequences
Output moderation is not pre-emptive; a harmful answer is visible briefly. Foundry-native evaluators and
trace-based quality metrics are left to Phase 9.

## Date-relative seed data

Fixtures hold absolute dates, which go stale. `seed-data/load_seed_data.py` re-dates appointments, appeal deadlines and refill-eligibility dates to fixed offsets from today at load time, and the eval set uses `{{today+N}}` tokens with the same offsets. Re-run the loader periodically (dates drift as time passes) and after any eval-set change that adds date-dependent cases.
