# Experiment A pilot protocol

Approved scope: baseline verification, fixed pilot and BM25 card count/formatting only.
No embeddings, hybrid retrieval, reranker, DETAILS action or memory learning is included.
`tasks.json` is a fixed 36-task pilot: 12 development/24 held out, six strata. Families stay
within one split. It contains declared intent and fixed state predicates, not product IDs.

## Baseline and known-defect isolation

The original `src/shopping_agent/retrieval.py` must remain byte-identical. Every trial uses
the exact same frozen BM25 top-ten result for its task. State extraction and query generation
are deliberately fixed; canonical category values isolate the known type-vocabulary defect.
Quotes are nonblank exact request excerpts; predicates avoid false same-field conflicts.
The controlled recommendation decision rejects state updates and new searches. Existing
blank-quote/conflict/watch/final-search defects remain visible in their separate reproduction
scripts/tests; this experiment does not fix or claim retrieval gains from them.

The application was restarted on localhost:8501. An isolated UI request completed with two
calls/one search, 4,893 reported input/198 output tokens. Both trace metadata and body are
`shopping-baseline-v3-compact`. This verifies serving/integration, not shopping quality.
The local preflight trace and screenshot stay outside Git.

## Source judgments and freeze

Prepare candidates and initial source-evidence seeds without a provider:

```sh
.venv/bin/python -m experiments.experiment_a.prepare \
  --output data/benchmarks/experiment-a/draft
```

Use physical JSONL lines: Unicode line separators inside strings are valid source text.
The seed rules are not semantic ground truth. A reviewer independently checks every pooled
candidate against raw title, taxonomy, features and requested metadata, with source support,
without importing the app matcher/oracle or seeing ranks/scores. Resolve semantic taxonomy
false negatives and source ambiguities before freezing. Do not edit labels after seeing
model outcomes. This pilot uses source-backed independent QA review, not human preference
ratings. No general comfort/style or real-world stock judgment is claimed.

Finalize into a fresh directory with the reviewed labels/witnesses:

```sh
.venv/bin/python -m experiments.experiment_a.finalize \
  data/benchmarks/experiment-a/draft reviewed_labels.json \
  data/benchmarks/experiment-a/frozen
```

The independently verified frozen-v2 pilot contains 215 task/product pairs (202 unique
products), 213 hard-pass judgments and two requested-field metadata ambiguities marked
unknown. All 215 have source-backed category/function relevance: this is a strong relevance
ceiling and limits the pilot. Twenty-four tasks have independently verified positive
witnesses. Twelve have no certified match under the declared evidence contract; this does
not prove universal semantic absence or real-world impossibility.

Verification is a separate `verification.json`, bound to all frozen hashes. The live runner
must require that certificate. The source catalogue hash is
`da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`;
frozen-v2 manifest hash is `3a6d66eb8157392590491a9ddca241c40ddae29ebdd32c92c3020c9572a82051`.
All catalogue rows, qrels, witnesses, certificates, baseline snapshots and live artifacts
remain under ignored `data/`; none is imported by the shopping application.

## Prespecified Experiment A comparisons

Four profiles, using one raw BM25 result per task:

| Profile | Visible cards | Representation |
| --- | ---: | --- |
| v3_k10 | at most 10 | Existing compact-v3 cards; baseline |
| v3_k5 | at most 5 | Identical fields/evidence; count-only change |
| shared_k10 | at most 10 | Same semantic content; repeated full category/source maps shared in headers |
| shared_k5 | at most 5 | Count plus shared-header representation |

Select prefix K before sharing metadata. Decoding a shared card must exactly recover its
v3 counterpart: IDs, titles, full category paths, facts, sources, snippets and soft matches.
No new source span, evidence selection, clipping, ranking, hard gate or action-schema change.
All shared headers count towards product-token overhead. Default v3 remains available.

Run all 36 tasks locally; then 24 held-out tasks × four interleaved profiles × one live
decision = 96 proposed requests. No prompt/formatter/scorer tuning from held-out outcomes.
Use a seed-fixed schedule, identical system instructions, state, query, raw result, provider
settings and history treatment. Inference remains stochastic despite temperature zero.
Only terminal RECOMMEND/CLARIFY/RESPOND actions are allowed; updates/search/schema errors and
unseen/stale IDs count as failures, with no hidden repairs. Actual recommendations must be
validated by the same executor guard and rehydrated from full raw catalogue cards.

This measures **conditional one-turn recommendation success** given correct fixed state and
retrieval; it is not a multi-turn shopping, extraction, clarification or memory benchmark.
The live UI preflight exercises the normal loop separately. Do not rename conditional
success as general end-to-end shopping success.

## Frozen metrics and limitations

- Shortlist Hit@K and relevant/displayed precision use reviewed verified matches. Report
  shared-format quality invariance at fixed K, and top-ten→top-five retention separately.
  Do not claim exhaustive Recall/global nDCG from pooled labels.
- Feasible-task strict recommendation success: one to three recommendations, **every** item
  relevant and hard-pass, no invalid action. Also report any-verified-hit and selected count.
- No-witness tasks: report safe product-free abstention separately, not shopping success.
  CLARIFY/RESPOND text accuracy and physical availability are not independently established.
- Report runtime hard-gate violations, independently known hard failures and independently
  unknown/ambiguous required evidence separately. Unknown never receives verified credit.
  If no items are recommended, item violation rate is N/A. False feasible abstentions remain
  failures. Prespecify a structured-facts-only sensitivity analysis for the two metadata
  ambiguities; it supplements the strict primary labels and never replaces them.
- Count product payload including shared headers, complete context, official input/output
  usage, calls, latency, failures and missing usage. Report feasible and no-witness strata
  separately so empty-result tasks do not manufacture token/quality gains.
- Measure BM25 latency separately from formatting and API latency. Candidate count does not
  avoid the original exhaustive lexical scan. Report paired differences, raw counts and
  ranges; 36 tasks/one live repeat and ceiling effects do not establish superiority.

Initial live cap, including the two preflight requests: 100 requests, 600k input and 200k
output tokens. Reserve bounded allowance before calls; preserve every request/failure and
stop on budget exhaustion. No automatic retry/resume of an interrupted paid trial. No live
request is made by prepare/finalize or automated tests. Experiment B/C require user approval.

## Running the controlled comparison (offline first)

Install the optional experiment extra and the pinned tokenizer asset, build the BM25
index, then use a **verified** frozen directory:

```sh
.venv/bin/python -m pip install -r requirements-experiment-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m shopping_agent index
```

**Tokenizer.** Token counts use DeepSeek's published V4 tokenizer
(`https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip`, linked from its
[token-usage documentation](https://api-docs.deepseek.com/quick_start/token_usage/)).
The zip downloaded on 31 October 2026 had SHA-256
`e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`. Extract only
`deepseek_v4_tokenizer/tokenizer.json` (data; do not run the bundled `.py`) to
`data/tokenizers/deepseek_v4/tokenizer.json`. `run.py` accepts only a file whose SHA-256 is
`89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614` and refuses anything
else. The Python package is `tokenizers==0.23.3` (extra `experiment`). The tokenizer
approximates provider token counts: encoded content was consistently 27 tokens per call
below API-reported input in the earlier audit, so API usage remains authoritative.

```sh
.venv/bin/python -m experiments.experiment_a.run offline \
  --frozen data/benchmarks/experiment-a/frozen-v3 --output data/benchmarks/experiment-a/runs/offline-1 \
  --tokenizer data/tokenizers/deepseek_v4/tokenizer.json
.venv/bin/python -m experiments.experiment_a.report \
  --frozen data/benchmarks/experiment-a/frozen-v3 \
  --offline data/benchmarks/experiment-a/runs/offline-1/offline.json \
  --output data/benchmarks/experiment-a/reports/offline-1
```

`offline` replays frozen BM25 for all 36 tasks (exact IDs, order, counts and evidence;
BM25 floats within a 1e-9 relative tolerance for SQLite rounding), formats the four
profiles, binds the visible set with a receipt, and measures tokens and formatting time.
`live` (paid; **needs explicit budget approval**) additionally needs a clean Git tree, a
fresh output directory and the verified certificate. `replay` re-validates a saved run and
re-scores it with no provider. `report` summarises either or both: per profile, split by
feasible vs no-witness tasks and by intent stratum, with exact denominators, paired
differences (exact McNemar for discordant pairs, seeded bootstrap interval for the mean
difference) and an exploratory caveat. Output is deterministic and never overwrites.

## Status (31 October 2026)

Implemented and offline-tested: card profiles and receipts, the executor guard, the
runner (offline/live/replay, usage budget, schedule), metrics and the report. **Not
run:** no live provider request has been made; no live result exists. On the real data the
offline run covered 36 tasks × 4 profiles with a scratch certificate only (see
[benchmark provenance](../../docs/reviews/experiment-a-benchmark-provenance.md)); the
frozen-v3 independent certificate is still required before live use. Observations: all
profiles show Hit@K 16/16 on held-out feasible tasks (a ceiling effect, so shortlist
quality cannot separate them); the shared encoding is identical to v3 evidence in 36/36
tasks; median context content tokens fall from 3,010 (v3_k10) to 2,464 (v3_k5), 2,769
(shared_k10) and 2,369 (shared_k5). These are cost measurements, not recommendation quality.

