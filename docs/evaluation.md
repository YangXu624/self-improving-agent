# Evaluation plan — proposed, not implemented

Reviewed 31 October 2026. There is no shopper simulator, evaluation runner, measured shopping
baseline or memory-transfer result in this project yet. The 45 original baseline tests verify
mechanics with fixtures/mocked policies; additional UI cases are recorded in [Phase 3](phase-3-ui.md).
These checks are not an end-to-end model-quality benchmark.
Prior real-catalogue smoke runs used test-only decisions; Phase 3 UI browser checks use an
explicitly scripted mock policy. Neither is evidence of live interpretation, shopping success
or learning. A later two-turn live DeepSeek smoke succeeded in five requests; this confirms
integration only, not comparative shopping quality or transfer. The two Phase 2 defects remain
deferred, and offline UI tests use mocked HTTP rather than the local key.
See [roadmap Phase 4](roadmap.md#phase-4--build-evaluation-and-measure-the-baseline).

## Task truth, dialogue and scoring

Keep three independent responsibilities:

1. Structured hidden task truth: hard needs, exclusions, soft preferences, available answers,
   acceptable-product criteria and whether the task is catalogue-verifiable/feasible.
2. Shopper rendering: a pinned local model served through Ollama may express that truth and
   answer questions. It must not invent new constraints or leak IDs/titles from target records.
3. Scoring: trusted checks compare recommendations to hidden requirements and source evidence.
   A shopper's declaration of satisfaction is feedback, not the sole success score.

Include exact-item discovery tasks and needs-based tasks with multiple valid products. Keep
target details hidden from the shop agent except deliberately revealed clues. Avoid turning
all shopping into guessing one title. Validate simulator consistency/leakage on manually
reviewed conversations, including corrections, refusal to answer and ambiguous requests.
LLM simulator leakage and target bias are documented risks:
[simulator reliability study](https://arxiv.org/abs/2403.16416) and
[target-free evaluation research](https://aclanthology.org/2025.findings-emnlp.1067/).

## Proposed core measures

| Measure | Definition to finalise before a benchmark run |
| --- | --- |
| Success@K within B turns | Fraction of eligible tasks with at least one independently verified acceptable item in a top-K recommendation by turn B |
| Hard-constraint violations | Share of recommended items violating a hidden hard requirement; report unknown/unverifiable required evidence separately |
| Turns to first verified success | Turn count including a predeclared treatment of failures/timeouts; also report success rate and successful-task distribution |
| Correction recovery | Whether subsequent state/recommendations honour a changed or withdrawn need |
| Resource use | Model/search calls, reported input/output tokens, latency and available cost evidence |

Do not count an unknown attribute as a valid match. Preclassify feasible, impossible and
catalogue-unverifiable tasks using independent evidence; report results by group. Do not
silently remove failed runs or change denominators. Include provider/tool errors, abstentions
and exhausted budgets. Handle impossible tasks with an explicit abstention/recovery measure.
MTTC and hit rate need precise definitions before inclusion; avoid duplicate metric names
for the same success event. Decide K, B, denominators, failure treatment, thresholds and
minimum meaningful improvement before claiming gains. Numeric values are not fixed here.

## Comparisons and separation

- First measure the session-only baseline. Evaluate retrieval upgrades separately from memory.
- Candidate retrieval can be measured against independently acceptable products, separately
  from final recommendation quality. Relevance/soft utility need explicit definitions.
- Later compare session-only, user-memory-only, experience-only and both under equivalent
  models, tools and budgets. User-memory tests need prior-user sessions; experience transfer
  tests need genuinely new tasks and appropriately held-out users/intents/product families.
- Separate experience-generating tasks, development/validation tasks and a final held-out set.
  Freeze memory before evaluation; evaluation outcomes cannot update lessons, user profiles,
  ranking parameters, prompts or code. In user-memory tests, new corrections may affect current
  session state while cross-session stores remain frozen unless a separate protocol allows it.
- Preserve the available catalogue across conditions; task/product-family separation need not
  remove products from retrieval. It prevents learning from the held-out interactions/answers.
- Pair conditions on the same tasks, with independent condition-specific shopper histories.
  Pin seeds where supported, repeat stochastic runs and report paired differences/uncertainty.
  A seed alone does not guarantee reproducible hosted-model responses.
- Compare legacy ASTRA only after aligning task definitions/scoring/budgets and disclosing
  model/tool differences. The original implementation remains read-only reference material.

## Reproducibility and anti-gaming

Version catalogue/index hashes, task/split IDs, task-generation method, hidden truth version,
scorer, code commit, prompt/schema version, model identifier/settings, simulator configuration,
budgets, seeds, memory snapshot IDs and per-run outcome/usage records. Preserve failed runs
and selection criteria. Do not commit private tasks, traces, datasets or credentials.

The shopper may read its hidden task; the shop agent and candidate code must not read ground
truth, protected scoring code or final test feedback. Development feedback can guide changes;
final held-out feedback cannot become an iterative optimisation signal. Test-family/title
leakage and memorised answers require explicit checks. Raw histories and learned lessons must
not carry held-out targets into later runs. Use evidence checks wherever determinable and
record manual/subjective judgement separately.

Outstanding approval decisions: exact local simulator/model, task counts and splits, success
utility criteria, metrics/thresholds, budgets, repetition/statistical plan and privacy/retention.
No simulator, new dependency or evaluation infrastructure is selected by this document alone.

## Watch incident diagnostic evidence

The [31 October watch audit](reviews/watch-decision-budget-audit.md) reproduces one live
failure with recorded decisions and synthetic fixtures. All four real searches reproduce;
the type filter, rather than lack of catalogue watches, explains the empty results. A final
terminal-response counterfactual completes within the same budget. This is diagnosis, not a
benchmark or proof of a live-policy improvement. At the time of that audit the test suite added three passing controls
and three explicitly expected failures; one has since been fixed (see the roadmap). No held-out tasks, scoring
rules or learning stores were introduced or modified.

The [compaction checkpoint](reviews/context-and-storage-compaction.md) measures serialized
prompt tokens and lossless log size on existing local traces. The saved second boots turn's
message content shrank 49.6%; no live quality, latency or billed-token improvement is claimed.
Exact event roundtrips, replay, product order, correction history, ownership and failure
handling are checked independently of the model through automated tests. This adds no
shopper simulator, scoring infrastructure or learning/evaluation tasks.

## Proposed retrieval comparison

The [multi-stage retrieval investigation](reviews/multistage-retrieval-proposal.md) proposes
36 fixed, source-judged tasks (12 development/24 held out), separate retrieval/card-format/
DETAILS/strategy-selection ablations, and a small optional grounded recommendation study.
No query manifest, verified qrels or comparative relevance scores exist yet. Historical
BM25 replay timings and product-token counts in that report are diagnostic measurements,
not retrieval-quality results. Confirm the serving prompt version, preserve the original
BM25 path and freeze gate/presentation/model conditions before making comparisons. No
embedding model, reranker, evaluation runner or additional dependency has been implemented.
