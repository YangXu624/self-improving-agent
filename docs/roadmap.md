# ASTRA research and development roadmap

Status reviewed: **31 October 2026**. This roadmap organises the agreed direction; it does
not authorise starting every future phase. Complete and review one phase before approving
the next. This roadmap is a plan; implementation evidence is recorded at the corresponding
checkpoints.

## Objective

Establish a credible conversational shopping baseline, then test whether confirmed experience
improves future decisions on new tasks. Measure personalization separately from procedural
improvement. Persistent storage, more sophisticated retrieval and a plausible lesson are not
by themselves evidence that the agent has learned something useful.

## Where we are

| Phase | Status | Remaining gate |
| --- | --- | --- |
| 1. Frozen catalogue | Complete for the initial 50k scope | Future category expansion is a separate decision |
| 2. Session-only conversational baseline | Implemented; small live smoke passed | Broader acceptance pending; earlier fixes merged, watch taxonomy remains limited |
| 3. Minimal UI | Streamlit UI connected to DeepSeek; runtime script removed | User review pending; five-request smoke is not a benchmark |
| 4. Evaluation and baseline measurement | Simulated-shopper harness implemented and offline-tested ([details](simulated-shopper-evaluation.md)); two real memory-OFF target learning sessions recorded | Validate Llama 3.1 reliability locally, approve protocol and budget, record the baseline |
| 5. Retrieval/ranking improvements | BM25 baseline exists; alternatives not implemented | Compare alternatives under Phase 4's protocol |
| 6. Persistent user memory | Not started | Approve lifecycle and repeated-user evaluation |
| 7. Agent experience learning | MVP vertical slice implemented and verified offline ([details](reviews/experiential-memory-mvp.md)) | Review focused trigger/audit/provenance fixes, then explicitly approve the single-lesson development pilot |
| 8. Retrieval-code experimentation | Deferred, optional research extension | Demonstrate a need beyond permitted configuration choices |

Historical **Milestone 1** covers the session/retrieval/CLI baseline in Phase 2, using the
Phase 1 catalogue. These roadmap phase numbers do not rename previous commits or milestones.
The initial implementation and coding-guidance PRs were merged ([PR 1](https://github.com/YangXu624/self-improving-agent/pull/1),
[PR 2](https://github.com/YangXu624/self-improving-agent/pull/2)). Future merges require approval.

The Phase 2 checkpoint had 45 passing automated tests. The current suite has 70 passing
cases after UI/live integration; see [UI evidence](phase-3-ui.md).
Prior full-catalogue smoke evidence is in [milestone notes](milestone-1.md).
Those smoke decisions were test fixtures. No shopping-success benchmark or benefit from learning has been established. A small live
integration check succeeded; it does not establish broad interpretation quality.

## Phase 1 — Freeze and audit the catalogue

**Purpose:** keep experiments comparable before expanding the product domain.

- Retain the frozen TechJam catalogue: 50,000 records and 50,000 unique parent-product IDs.
- Retain image URL references only: 49,944 mapped products; 56 without an image entry.
- Keep source hashes/provenance and generated indexes separate from session memory.
- Record coverage limits: 49,990 category roots are `Clothing, Shoes & Jewelry`, and 10 are
  `Shoe, Jewelry & Watch Accessories`; this is not broad multi-domain coverage.
- Under the current exact-positive-price parser, 39,591 products have unknown price and
  10,409 have usable price. Missing/from/range/zero values do not satisfy a budget filter.
- Treat explicit attributes as catalogue evidence. Parent records do not establish child
  variant availability or current price. Remote image reachability remains unverified.

**Exit evidence:** frozen source manifest, counts/hashes and documented metadata limitations.
This initial scope is complete. A larger 100k catalogue is deferred until broader coverage
answers a specific research question. A legacy ASTRA comparison additionally requires the
same tasks, scoring and budgets; sharing a catalogue alone is insufficient.

## Phase 2 — Establish and validate the conversational baseline

**Implemented:** unique owner-associated sessions; full JSONL conversation/action history;
JSON snapshots; structured hard/soft requirements, exclusions, corrections and version history;
CLARIFY/SEARCH/RECOMMEND/RESPOND; deterministic FTS5/BM25; bounded decisions; tracing; CLI.

The LLM chooses questions, queries, all/any matching and eligible recommendation order.
Trusted Python applies every stored active hard constraint and verifies recommendation IDs.
The model does not write SQL or own the retrieval implementation. Full history is retained,
but prompts use active state and bounded recent dialogue; perfect recall of every incidental
fact in a long session is not established. Requirement extraction still depends on the model.

**Remaining work, subject to approval:**

1. Agree a live provider/model and conservative request/spend cap. Keep credentials local.
2. Exercise explicit hard/soft requests, clarification answers, budget correction, exclusion
   withdrawal, goal changes, unknown attributes, zero matches, and resumed/isolated sessions.
3. Inspect state and traces against the user's actual words; record failures and actual usage.
4. Test long-session state retention and explicitly decide whether incidental-history recall
   needs to improve beyond the current bounded prompt. Do not equate storage with recall.
5. Fix confirmed defects with regression tests and preserve the baseline checkpoint.

**Exit gate:** live acceptance report identifies completed checks, defects and remaining
limitations; the user reviews the baseline before the next phase. Mocked tests alone do not
satisfy this live-validation gate. The user subsequently authorised live integration and a
small check passed; the broader gate remains pending; the two deferred defects are fixed on `fix/state-evidence-and-conflicts` (pending merge).

## Phase 3 — Add a minimal visual interface

**Current implementation:** the initial mock-first UI was authorised before the pending
Phase 2 fixes. The user then supplied a key and authorised removing scripted application
decisions. Streamlit now uses DeepSeek for live decisions, retaining the same chat, product,
session/state and trace views. Seventy offline tests and a five-request live smoke passed;
see [Phase 3 evidence](phase-3-ui.md). Historical mock sessions remain separate. The two
reviewed backend defects were later fixed on a branch pending merge; this is not a complete live-quality evaluation.

**Purpose:** make conversation and decisions inspectable while preserving the existing core.

Show chat, session selection/resumption, product cards/image URLs, active requirements and
corrections. Include a collapsible trace for actions, search counts, failures and resource use.
Provide a visible session ID and make a new session distinct from resuming an old one.

Reuse the decision loop and tools; do not reimplement business logic in UI callbacks.
Streamlit was chosen as an optional dependency to retain the Python architecture. Do not add
memory learning, embeddings or hosted multi-user authentication as incidental UI features. A hosted service needs a separate design.

**Exit gate:** reviewed end-to-end UI demo and relevant regression tests, including session
isolation and corrections. A failed image URL must not prevent viewing product facts.

## Phase 4 — Build evaluation and measure the baseline

**Purpose:** establish what success means before tuning retrieval or adding persistent memory.
Both preference-based and target-item evaluation modes are implemented and tested offline (see
[simulated-shopper-evaluation.md](simulated-shopper-evaluation.md)). Live baseline measurement remains to be run.

Separate hidden task truth, shopper dialogue generation and independent scoring. Include
exact-item discovery and needs-based tasks with potentially multiple acceptable products.
A local model served through Ollama may generate shopper dialogue; its model, configuration,
goal consistency and leakage behaviour must be checked before relying on its scores.

Measure success within a turn budget, hard-constraint violations, turns to verified success,
correction recovery and resource use. Track impossible tasks, catalogue-unknown cases and
agent/tool/provider failures separately. Keep a small manually reviewed conversation set.
Version tasks, catalogue, prompts, model settings, budgets and scorer. Create learning,
development and final held-out groups before memory/code experiments begin.

**Exit gate:** reproducible baseline report includes failures, denominators and simulator
limitations. The final test set stays unavailable for iterative tuning.

## Phase 5 — Improve retrieval and ranking under measurement

**Purpose:** establish a stronger baseline and expose which failures experience might address.

Compare existing BM25 against candidate dense/bi-encoder and hybrid strategies, adding a
reranker only if needed. Measure candidate retrieval separately from final conversational
recommendation quality, including latency, indexing/storage and embedding cost.

Preserve the original baseline. Evaluate changes on development tasks; freeze the chosen
retrieval implementation before the memory comparison. Do not credit a retrieval upgrade to
memory. Hard-constraint gates remain outside the model for every permitted strategy.

The agent may later choose a strategy, reformulate queries or select bounded configuration
values. Deterministic tools continue executing retrieval; unrestricted generated search code
is not needed for this phase. Strategies must have observable identifiers and versions.

**Exit gate:** measured comparisons and a documented decision, including null/negative results.
No alternative is adopted merely because it is more sophisticated.

## Phase 6 — Add persistent user memory

**Purpose:** retain useful user-specific information across sessions, with user control.

Distinguish episodic interactions from durable preference/fact summaries. Define when to
write nothing, add, correct, supersede, withdraw and delete. Preserve provenance, scope and
correction history; use bounded relevant retrieval. Current explicit needs take precedence
over old preferences. Do not infer a permanent preference from every task-specific request.

Use repeated-user sessions to test usefulness, corrections and cross-user isolation. Storage
choice (including SQLite) and deletion/retention semantics require design review. Withdrawing
an active preference is distinct from erasing retained personal history. No implementation
has been selected by this roadmap alone.

**Exit gate:** lifecycle/isolation tests and a controlled user-memory comparison. This measures
personalization, not proof of transferable agent experience.

## Phase 7 — Learn and apply agent experience

**Purpose:** improve clarification, query formulation, retrieval selection, ranking or recovery
from confirmed experience, conditional on task/query characteristics and catalogue evidence.
Avoid assuming a demographic persona determines the best retrieval algorithm.

Proceed in reviewable steps:

1. **Outcome evidence:** link an observed success/failure to independent checks and trace IDs.
2. **Candidate lessons:** record conditions, proposed procedure, evidence, uncertainty and
   scope. One successful source interaction does not prove causality or generalisation.
3. **Verification and lifecycle:** define promotion criteria, counterevidence, conflicts,
   correction, expiry/withdrawal and privacy rules for sharing across users.
4. **Controlled retrieval/application:** include only applicable bounded guidance; trace what
   was retrieved, actually included, and which observable decisions changed.
5. **Transfer study:** compare frozen memory conditions on new held-out tasks; never update
   memory from evaluation feedback. Report negative transfer and cost as well as gains.

Compare session-only, user-memory-only, experience-only and both. Hold model, tools, tasks
and budgets equivalent within each comparison. Repeated runs and paired task results are
needed to distinguish an apparent gain from stochastic variation. Additional raw-history or
human-authored-guidance controls can help explain the source of a benefit.

**Exit gate:** a reproducible outcome → lesson → retrieval → decision → independent result
trace and an honest transfer report. A null result is valid; do not promise monotonic gains.

## Phase 8 — Optional guarded retrieval-code experimentation

Start only after permitted strategies/configurations prove insufficient. Run candidate code
in an isolated workspace with bounded resources, restricted data access and rollback. Protect
hard gates, scoring, hidden tasks, ground truth and reference code from candidate edits.
Promote changes only after independent validation on development/validation tasks. Final
held-out feedback must not become an optimisation signal. Log candidate versions, failed
attempts and validation costs. User review is required before promotion to the main system.

**Exit gate:** reproducible evidence for improvement without weakened constraints, evaluator
gaming or test contamination. This is deferred research, not a current implementation goal.

## Immediate next checkpoint

The live DeepSeek UI is implemented for review and running locally. Review its behaviour;
then broaden acceptance/evaluation. The blank-evidence, false-conflict and exhausted-search
defects are fixed on `fix/state-evidence-and-conflicts` (pending review/merge). The
small smoke is not the Phase 4 benchmark, and neither memory nor retrieval upgrades are part
of this integration. Each submitted turn now makes paid API requests; display/inspection does not.

The [watch failure audit](reviews/watch-decision-budget-audit.md) now identifies an additional
product-type representation limitation and exhausted-search recovery issue. Its independent
replays, token accounting and synthetic regressions are complete. Prompt and lossless event
compaction are implemented in a separate [checkpoint](reviews/context-and-storage-compaction.md);
exhausted-turn recovery is implemented; retrieval/type semantics remain a proposal for review.
Resolve bounded completion and catalogue-grounded type semantics before
assuming that a larger budget or semantic search is needed. Two regression cases (watch
type vocabulary) remain explicit expected failures; the exhausted-search case now passes.

Experiment A (BM25 card count/format only) is implemented and offline-validated on branch
`feat/experiment-a-cards`: card profiles, runner, budget, replay and report. No live run has
been made; it needs an approved budget and an independently verified frozen-v3
([provenance](reviews/experiment-a-benchmark-provenance.md)). No dense/hybrid/rerank work
has started.

Retrieval improvement is now under [design review](reviews/multistage-retrieval-proposal.md):
larger local eligible candidate pools, five compact evidence cards, optional dense/RRF and
reranking, then one bounded DETAILS batch if supported by evidence. The immediate proposed
checkpoint is serving-version verification and a fixed, independently judged query benchmark.
The application remains BM25; full retrieval implementation awaits review. Known correctness
defects and decision-decoder versioning must remain separate from ranking-quality attribution.

### Current attribute-state checkpoint

Asked/disclosed current-goal ledgers and redundant-clarification validation are implemented
on `feat/asked-disclosed-state`, pending independent review and PR approval. This is working
memory only. Target-item evaluation is a separate approved component; persistent user and
procedural experience memories remain unimplemented. No paid calls are used for this work.

## Immediate checkpoint: experience integrity

The focused fix branch implements goal-scoped opening cues, truthful injection/application
audits, reviewed-lesson overwrite protection, and separately labelled hidden-profile versus
disclosed compliance. [Pilot commands and artifact evidence](experience-pilot.md) await explicit
activation/live approval after PR review. Lesson 1 stays candidate; Lesson 2 stays rejected.
No new memory feature, simulator tuning or retrieval optimisation belongs to this checkpoint.
Older "immediate" checkpoints above are historical and do not supersede this next action.

## Current Stage 1: persistent user memory

The approved architecture-alignment stage adds opt-in per-user Markdown profiles, evidence-backed
formation, bounded context recall, corrections/withdrawals, audit history and normal UI/CLI
controls. Session persistence, retrieval, procedural memory and existing evaluator behaviour
are retained. See [implementation, data flow and limits](user-memory.md).

Stage 1 stops for PR review. Returning-customer timelines, a longitudinal evaluator, a four-arm
evaluation CLI, external LLM lesson extraction and source-code optimisation are not implemented.
Existing procedural Lesson 1 activation and live paired trials remain separately approval-gated.
User-profile persistence tests are integration evidence, not measured shopping improvement.

## Current Stage 2: returning-customer development evaluator

PR #18 (Stage 1) is merged. Stage 2 adds a thin timeline layer around existing session
evaluation, three four-visit development customers, isolated user-memory OFF/ON conditions,
catalogue validation and per-session/customer metrics. See [Stage 2](longitudinal-evaluation.md).
One live four-customer pilot stopped after five OFF sessions; ON never started. The simulator
integrity fix and [fresh restart plan](reviews/shopper-disclosure-integrity.md) are under review.
No new held-out benchmark, paid restart or procedural activation has run.
An opt-in expansion now contains the original three plus eight new development customers
(36 visits), with offline catalogue evidence validation. See the
[curation report](reviews/expanded-development-customers.md). Stop for customer-data review
before any live expanded experiment; memory benefit remains unmeasured.

## Current representation simplification

Normal chat uses compact current-state and selected text-memory views, readable Markdown
profiles and schema-2 current snapshots. Canonical events/validation and all frozen inputs
are retained. Evaluations remain legacy by default; longitudinal compact mode is explicit
and recorded. See [memory representations](memory-representations.md). Semantic/embedding
retrieval will be evaluated separately; no new retrieval or live experiment belongs here.

## Shopper V3 prototype checkpoint

Opt-in Ollama/Claude provider interface, autonomous openings/replies, conservative independent
disclosure evidence, returning-visit history and budgeted longitudinal entry point are implemented.
V2 and frozen scoring/fixtures remain available. Deterministic/mock verification precedes PR
review. Real provider compatibility, realism, disclosure reliability and memory effectiveness
remain unverified; paid tests require a separately approved budget. [Protocol](../experiments/longitudinal/shopper-v3-comparison.md).

Sonnet 5.5 transport compatibility is fixed with deterministic regressions and a successful
two-reply Claude-only smoke. Shared financial reservations prepare a capped 24-session run;
full DeepSeek execution and merge remain approval-gated. [Readiness report](reviews/claude-sonnet55-readiness.md).

## Reliability gate before further paid experiments

Session offer history, category inflection, empty-search guards, conditional color validation,
redundant retractions and failure-scope isolation are implemented with full lifecycle regressions.
The [readiness decision](reviews/conversation-reliability.md) is GO for deterministic review,
NO-GO for an unattended paid rerun or a memory-effectiveness claim. Human review and a separately
authorized controlled canary precede any fresh full pilot.
