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

Not yet executed at this protocol checkpoint. Final results will replace this section without
changing the frozen input, model settings, budgets or scoring rules.
