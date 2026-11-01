# Current evaluation status

Memory representation is now explicitly controlled: normal chat defaults to compact v7,
while existing evaluation modes default to legacy. Longitudinal `--memory-format compact`
records the format and prompt versions for both arms; keep the same format across comparisons.
Character-size checks in [memory-representations.md](memory-representations.md) do not establish
live recommendation quality, token savings or memory benefit. Frozen artifacts are unchanged.

Stage 1 profiles are opt-in in the application. Existing single-session evaluators remain
user-memory OFF and their scenarios/scoring are unchanged. Stage 2 adds a separate thin
[returning-customer orchestration](longitudinal-evaluation.md) with development-only customers,
user memory OFF/ON, procedural memory OFF, existing scorers and per-customer reports. A first live pilot stopped after five OFF sessions because of a shopper fault; ON never
started, so no user-memory effectiveness result exists. The four-arm comparison and external
learner remain future work. See [simulator diagnosis and recovery](reviews/shopper-disclosure-integrity.md).

The separate [expanded customer fixture](reviews/expanded-development-customers.md) is
human-directed development data: 11 customers / 36 visits, preserving the original three.
Its eight new customers and 24 preference-scored visits have been checked offline against
the catalogue; no live comparison or effectiveness result is implied.

Preference and target-item evaluation are implemented. Two real memory-OFF learning sessions
produced candidate procedural templates; a real memory-ON/OFF transfer result is not yet
established. See [the focused integrity checkpoint and exact proposed pilot](experience-pilot.md).
Hidden-target-profile mismatches retain historical scores, but are labelled separately from
new per-presentation compliance with confirmed disclosed hard state. Missing historical
compliance evidence is unknown. These checks do not verify complete natural-language extraction.

The original plans below are historical; their old implementation/status claims are superseded
by this paragraph and the focused checkpoint. No historical run or frozen benchmark is rewritten.

# Evaluation plan

**Update (1 November 2026):** the simulated-shopper harness described in
[simulated-shopper-evaluation.md](simulated-shopper-evaluation.md) is implemented and tested
offline with scripted and mocked components (preference-based evaluation and target-item evaluation
modes, scenario/target generators, catalogue audit, Ollama/scripted shopper with session memory,
dialogue runner with early cutoff, independent scorer, experiment runner, report). It has **not**
been run against a real Ollama model or DeepSeek, so no baseline or quality result exists, and
experience memory is still not implemented. The plan below remains the methodology; where it says
"proposed", the harness now supplies the mechanics but the protocol values (K, B, budgets,
thresholds) still need the project owner's approval before a reported baseline.

# Original evaluation plan (proposed)

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

## Experiment A baseline checkpoint

Experiment A is approved incrementally. Its [fixed pilot protocol](../experiments/experiment_a/README.md)
and 36 public task specifications are now implemented; source-backed pooled judgments,
witnesses and raw BM25 snapshots remain local/ignored. Independent QA reviewed 215 pairs
and 24 feasibility witnesses; two requested-field source ambiguities are unknown. Labels
are pooled and source-grounded, not human ratings or exhaustive semantic relevance. The
pilot has a strong category/function relevance ceiling. The serving UI has been restarted
and an actual two-call trace confirms compact v3. Card profiles/live comparisons are the
approved next checkpoint. They are now implemented with offline tests: a runner (offline,
live, replay), a usage budget and a deterministic paired report; see the
[experiment README](../experiments/experiment_a/README.md). The offline run on the real
catalogue gave Hit@K 16/16 for every profile on held-out feasible tasks (a ceiling effect)
and lower context tokens for K5/shared profiles; no live request has been made and no
recommendation-quality result exists. Frozen-v2 is verified but unusable by the runner
(task IDs in requirement IDs); frozen-v3 awaits independent verification, see the
[provenance note](reviews/experiment-a-benchmark-provenance.md). Known defects remain isolated.

### Attribute-state baseline revision

The asked/disclosed working-memory change uses prompt `shopping-baseline-v4-attributes`.
It is an intentional agent-baseline change: compare future memory conditions against this
same version, not against v3 runs with a different policy. Old v1 scenarios and saved runs
are not rewritten. Offline regressions cover question evidence, dispositions, correction,
goal scope, history truncation, bounded rejections and legacy replay. This change supplies
no target IDs, simulator state or experience-learning capability to the shopping agent.

## Opt-in autonomous shopper prototype

[V3](simulator-v3.md) changes the conversation generator, not the protected fixtures or
preference/target scorers. Generated openings and free paraphrasing mean results must not be
pooled with V2. Python-derived disclosures are conservative evidence, not proof of complete
semantic consistency. The [Ollama/Claude protocol](../experiments/longitudinal/shopper-v3-comparison.md)
requires separate reliability/naturalness review before a new effectiveness study. No V3
live comparison has run. Claude costs and missing failure usage need separate billing reconciliation.

The authorized four-customer Claude V3 run stopped at its live preflight: one Claude request
returned HTTP 400 for an unsupported `temperature` parameter; zero shopping sessions or
DeepSeek calls started. There is no OFF/ON result. See the [preserved preflight report](reviews/claude-v3-four-customer-preflight.md)
for the exact error, unknown billing usage, unchanged artifacts and required transport/cost checks.

The [Sonnet compatibility/readiness checkpoint](reviews/claude-sonnet55-readiness.md) fixes
the rejected sampling parameter. Two actual Claude-only replies succeeded (US$0.005158 token-based
estimate); no DeepSeek request or longitudinal session was run. Shared evaluation cost reservations
are tested. Correct natural paraphrases can remain unverified by the unchanged disclosure auditor;
review dialogue and accepted memory evidence during the proposed pilot. Full execution awaits approval.

The approved Claude V3 pilot was launched once and [stopped after three OFF visits](reviews/claude-v3-memory-pilot.md):
two valid failures and one audit-invalid visit. ON never started, so there is no memory-effectiveness
comparison. The stop exposed a prior-recommendation context gap in the shopper audit; the live
traces also show category-token and stale-state-edit failures in ASTRA. Runtime/scoring remained
unchanged. The pilot's conservative token-cost estimate is US$0.072132224; prior uncertainty is retained.
