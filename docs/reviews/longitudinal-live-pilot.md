# Four-customer longitudinal user-memory pilot

## Frozen protocol (before live execution)

Exploratory development pilot using four unchanged customers from PR #21's expanded fixture:

| Customer | Rationale | Visits |
| --- | --- | ---: |
| dev-office-basics | Stable Cool Grey shirt preference, same-category recall, belt non-transfer | 3 |
| dev-commuter-bags | Stable Black bag preference across daypack, folio and tote | 3 |
| dev-gift-shopper | Silver/Gold gift recipient isolation followed by own wallet | 3 |
| dev-bag-style-change | Black bag recall then explicit Cream correction | 3 |

All 12 OFF sessions precede all 12 ON sessions, with customers in the table order and visits
chronological within each timeline. ON starts empty and learns only from conversations.
Session memory is enabled; procedural experience is disabled. Stores are isolated by
condition and user. No previous run's profiles are used.

- Policy: locally configured `deepseek-flash`, temperature 0, thinking disabled, output cap 2,000.
- Shopper: `llama3.1:latest`, temperature 0, seed 7, context 4,096, output cap 220,
  timeout 120 seconds, window 8, existing malformed/consistency retry limits unchanged.
- Compact memory `shopping-baseline-v7-compact-memory` in both arms.
- Full-feature OFF/ON comparison: ON adds memory instructions/schema; user explicitly approved
  this difference. No claim of byte-identical prompts or pure retrieval-only causality.
- Existing BM25, frozen catalogue, price budgets, hidden profiles and preference scoring.
- Primary K=5, six user turns/visit, three decisions/two searches per turn, 18 calls/session.
- At most 216 DeepSeek calls/phase; 432 for 24 sessions. No full 11-customer run.
- Stop complete run on significant infrastructure/simulator/invalid-session errors, preserve
  partial results; do not change conditions or silently resume. Agent-quality failures remain
  scored outcomes. No production agent, memory, retrieval or scoring changes.

Artifacts will remain local under `data/eval/longitudinal/pilot-20261101-off-then-on/`:
selected frozen input, protocol/plan, preflight/balance checks, request/response journals,
per-session transcripts and traces, profiles, standard reports and analysis.
No credentials or raw session logs are committed.

## Pre-live verification

DeepSeek credential present and account balance available, without a paid completion.
Existing Ollama structured budget probe passed; model present locally (3.214 seconds).
Runner changes are restricted to evaluation ordering and opt-in stop behavior.
Full pre-live suite: 545 tests run, 542 ordinary passes, one existing tokenizer skip and two
existing watch/wristwatch expected failures. No production/scoring changes.

## Results

The run **stopped**, as configured, after 5/12 OFF sessions (4 valid, 1 simulator-invalid).
ON started 0/12 sessions. No memory-effectiveness comparison exists, and no profiles were
learned or injected. The failed run remains at the path above. It must not be resumed with
new simulator behavior or pooled with a fresh version.

| OFF visit | Outcome | First nDCG@5 | Turns | Searches | Clarifications | DeepSeek calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| office-basics-01 | failure | 0 | 6 | 7 | 0 | 14 |
| office-basics-02 | success | 0 | 6 | 2 | 1 | 8 |
| office-basics-03 | success | 0.16958 | 6 | 2 | 1 | 8 |
| commuter-bags-01 | failure | no recommendation | 6 | 12 | 0 | 18 |
| commuter-bags-02 | simulator-invalid | not scored | 1 | 2 | 0 | 3 |

OFF Success@5: 2/4 valid sessions; 2/5 all started. Mean first nDCG@5 over valid sessions,
with no recommendation assigned 0 for this diagnostic: 0.042395. These are partial descriptive
results, not representative pilot estimates. First visits: 0/2 successes; returning visits:
2/2 valid successes plus 1 invalid. This is within OFF alone, not a memory gain. Success
requires any hard-compatible item; it does not establish color preference satisfaction.
All 58 recommendation occurrences checked against disclosed hard-state requirements passed;
hidden budget/profile mismatch remains a separate issue. No ON preference storage/retrieval/
application/correction was observed. Gift and preference-change customers never started.

The namespace failure: on commuter-bags-02, valid fact keys were `type`, `budget`, and
`preferred_color`. Raw Ollama responses 21 and 22 were identical:

> I'm looking for a folio bag for work, not just briefcases.

Both declared `reveals=["type","current_goal"]`. `current_goal` is private roleplay metadata,
not a requirement key. The second request carried `reveals_unknown_key: current_goal` feedback;
both attempts failed. The runner terminated `simulator_failure`, then its opt-in global
`stop_on_error` ended the run. Fourteen `claimed_reveal_missing` warnings had already occurred.
They were logged without invalidating sessions under the old protocol; no rejected output
was used for the failed fifth session.

Separate agent limitations observed: singular hard categories `daypack` and `briefcase`
failed literal category matching; repeated searches found no eligible products. Color-query
terms can be absent from indexed structured detail fields. The shopper repeatedly asked
whether items were within budget after stating it; this prolonged sessions. These remain
separate findings, not memory failures, and neither retrieval nor scoring is changed here.

Actual recorded usage: **51 DeepSeek attempts**, 159,901 input tokens, 4,468 output tokens,
including 94,464 cache-hit and 65,437 cache-miss input tokens; **22 Ollama attempts**. Token-rated
cost is approximately **US$0.012780** at the checked off-peak Flash prices (cache-hit .003,
cache-miss .15, output .60 per million). This is derived from actual usage, not a verified
invoice: before/after balance snapshots both report the same rounded CNY balance (delta 0.00),
so settled billing is unconfirmed. No new balance query or paid completion is required.
Prices: https://api-docs.deepseek.com/quick_start/pricing/ (checked 2026-11-01).

Raw DeepSeek/Ollama request/response journals, transcripts, traces, selected input, protocol,
model metadata and balances are local audit artifacts. No raw session log or credential is
committed. The next simulator-fix checkpoint will preserve their hashes and document a fresh
restart protocol; no additional paid run is authorized by that checkpoint.
