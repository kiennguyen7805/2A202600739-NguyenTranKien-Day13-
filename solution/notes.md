# Diagnosis notes

## Baseline defects corrected

- Unstable sampling: `temperature=1.6`.
- Injected tool errors: `tool_error_rate=0.18`, retry disabled.
- Loop risk: no loop guard, 12 allowed steps.
- Cost/latency risk: premium tier, verbose system, 2000 output tokens, no cache.
- Data corruption: Unicode normalization off and a false catalog override.
- Privacy/drift risk: PII redaction off, session drift enabled, no context reset.
- Prompt defects: no grounding, exact arithmetic, tool economy, privacy, refusal, or injection rules.

## Telemetry emitted by the wrapper

Each `AGENT_CALL` event records latency, usage, estimated cost, tools, nested trace
errors, repeated actions, PII redactions, retry count, session/turn, and whether an
untrusted note was removed. Cache hits emit `AGENT_CACHE_HIT`.

## Before final scoring

Run practice traffic and replace baseline evidence in `findings.json` with measured
values and correlation IDs from `logs/*.log`. The current workspace has no `bin/`
directory, Python executable, or configured LLM endpoint, so runtime measurements
cannot be produced here yet.
