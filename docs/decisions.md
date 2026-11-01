# Architectural and research decisions

Reviewed 31 October 2026. This records adopted baseline choices and proposed sequencing;
it does not approve implementation of future phases. See [open questions](open-decisions.md).

| Decision | Status and rationale | Consequence / trade-off |
| --- | --- | --- |
| Keep the frozen TechJam 50k catalogue | Adopted; data-only reuse authorised, avoiding a changing comparison corpus | Mostly clothing/shoes/jewellery; broader domain transfer remains untested |
| Import product records and image URLs only | Adopted; original implementation/configuration/sessions remain outside this project | No legacy history, embeddings or model assets are silently reused |
| Direct bounded orchestration | Implemented; the baseline does not require a framework | Explicit policy/context/tool/storage contracts must remain maintainable |
| JSONL authority and JSON snapshots | Implemented for trusted local CLI use; history and corrections are inspectable | Single-writer POSIX design, not authenticated hosting or a transactional database |
| DeepSeek as first adapter | User-selected; live UI connected and a five-request smoke passed | Broad quality and dollar cost remain unmeasured; later adapters use the policy interface |
| FTS5/BM25 first | Implemented; deterministic lexical retrieval provides a measurable starting point | Limited semantic recall; explicit attributes are sparse and category matching is literal |
| Enforce stored hard needs outside the LLM | Implemented; generated proposals do not define product truth | Incorrect/missing requirement extraction is still possible and needs evaluation |
| Keep session, user and experience memory distinct | Session layer implemented; remaining layers deferred | Personalization and transferable procedural improvement must be measured separately |
| Evaluate before retrieval tuning and persistent memory | Recommended roadmap sequence | Requires independently defined truth, validated simulation and preserved baseline versions |
| Require evidence before promoting experience | Future design principle | A plausible summary or successful source episode alone does not establish a transferable lesson |
| Prefer permitted strategy/configuration choices before code edits | Future roadmap direction | Trusted execution/gates remain even when policy choice expands; code experiments require isolation |
| Complete Milestone 1 with mocked provider tests | Historical validation boundary; user later authorised live integration | Live use is explicit; no runtime script or fallback remains |

Milestone implementation was merged in [PR 1](https://github.com/YangXu624/self-improving-agent/pull/1);
user-supplied coding guidance was merged in [PR 2](https://github.com/YangXu624/self-improving-agent/pull/2).
On 31 October 2026 the user authorised Phase 3 with a mock policy and deferred the two
reviewed Phase 2 defects and live validation. Streamlit is the optional UI dependency: it
reuses the Python application and supports headless UI testing without a separate frontend
stack. Core CLI dependencies remain separate; UI dependency versions have their own lock file.
This does not authorise live provider calls, memory layers, evaluation or merging the UI PR.
No embedding model, user-memory schema, simulator model or code sandbox has been selected.

## Compact context (31 October 2026)

The user authorised shrinking state and events after inspection of the boots/women trace.
Prompt v3 projects active requirements to stable ID, field, operator, value and strength.
Full quotes/correction provenance remain in session storage. All search candidate IDs and
their order are retained; facts, fact sources and distinct supporting text stay visible,
with missing facts explicitly unknown. Prior recommendation order and evidence remain in
history, but transport metadata and duplicated product fields are omitted. The generated
Decision schema keeps its constraints and examples while omitting generated titles. This
is deterministic projection, not LLM summarisation or a change to retrieval semantics.

Offline reconstruction of the recorded second boots turn reduced encoded message-content
tokens from 24,878 to 12,531 (49.6%). The recorded API input was 24,959, with 81 additional
tokens across three calls. No new live call was made; changed-policy quality and actual
provider billing remain unverified. Six projection tests plus the existing suite passed
(82 executed, three existing expected failures).

## Compact durable events (31 October 2026)

New JSONL records use optional storage version 2. State commits encode changed requirement
entries; accepted decisions/updates, recommendation products, completed responses and repeated
prompt messages refer only to earlier events in the same session. Long prompt strings use
bounded stdlib zlib/base64 encoding. Exact prompt strings, facts, source quotes, timestamps,
usage, rejection reasons, state versions and product order remain recoverable. In-memory
events and CLI/UI inspection retain their canonical interfaces. Snapshots omit default/null
fields and restore them through the existing strict state model.

No legacy log is migrated or truncated. A session may contain both formats; current readers
expand records before ownership/sequence/state checks and reject invalid references or
oversized compressed streams. Older application readers cannot consume version-2 records.
This format is not tamper-proof storage, a database or long-term memory. Detailed measurements,
limits and reproduction commands are in the [compaction report](reviews/context-and-storage-compaction.md).

## Fresh DeepSeek configuration (31 October 2026)

The user supplied a local key and authorised replacing the scripted UI policy. Configuration
parsing is shared between CLI and provider composition. `DeepSeekPolicy.from_env_file` reads
only the explicit project file, with process settings taking precedence, without copying file
secrets into the process environment. This allows a later UI rerun to pick up a changed file
key. The CLI's `load_env` interface remains compatible. Explicit blank credentials fail closed.
The next checkpoint connects the UI and removes the scripted application policy; its results
are recorded below. Test fixtures remain offline and never require the local key.


## Live UI policy (31 October 2026)

The UI now requires the configured DeepSeek policy; the application mock module is deleted.
Historical mock sessions are retained but not reused in the new default live directory.
Fixtures remain exclusively in tests and simulate HTTP, including auth failures and token
usage. There is no fallback policy after API failure. The request shape follows
[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) and
[JSON Output](https://api-docs.deepseek.com/guides/json_mode/); the prompt version advances to
v2 for its explicit JSON-shape example. The live smoke used five requests, within a cap of six,
and confirmed budget correction and checked recommendations. This is not a quality study.

## Correctness fixes (31 October 2026)

The user prioritised three confirmed defects before retrieval work. All are enforced in the
trusted executor, not the prompt, and adds only the optional `closure` response key and `turn_closed_safely` event; no existing field, contract or `retrieval.py` changes.

- **Blank evidence:** `apply_updates` rejects a quote whose normalised text is empty. The
  check is in `state.py`, not the pydantic contract, so old logs still replay and the
  prompt schema is unchanged.
- **Conflicts:** detection reuses the gate's semantics instead of a separate scalar-set
  model. Trade-off: `product_type eq boots` plus `eq shoes` is no longer a conflict because
  one category path can contain both tokens. The alias table is copied to `state.py` and
  pinned by a test to avoid editing the frozen BM25 baseline.
- **Exhausted search:** a final unexecutable SEARCH closes the turn with a fixed RESPOND
  rather than `decision_budget_exhausted`. This deliberately changes the prior
  `test_repeated_search_cannot_loop_or_exceed_budget` status from `error` to `ok`; budgets are
  unchanged. The message is deterministic so it cannot assert catalogue facts.

## Experiment A completion decisions (31 October 2026)

- **Recovered Codex work** was cherry-picked onto a new branch from `main` (after the
  correctness-fix PR); the recovery and original Experiment A branches are untouched.
- **BM25 stays frozen.** `retrieval.py` is unchanged and the runner refuses to run if its
  hash differs from the manifest. Replay compares counts, IDs, order and evidence exactly;
  only BM25 floats get a 1e-9 relative tolerance because another SQLite build changed the
  last digit of 27 scores. Trade-off: a build changing tie order would still fail loudly.
- **Benchmark versioning, not regeneration.** Verified frozen-v2 leaks task IDs through
  requirement IDs, so the runner needs the opaque-ID v3. v2 is preserved; v3 requires an
  independent certificate before live use ([provenance](reviews/experiment-a-benchmark-provenance.md)).
- **Pinned tokenizer.** `tokenizers==0.23.3` is an optional `experiment` extra with its own
  lock file, and the runner accepts only the tokenizer.json with the documented SHA-256.
  Token counts approximate provider usage; API-reported usage remains authoritative.
- **Report is descriptive.** Paired exact McNemar and a seeded bootstrap are reported with
  explicit denominators and an exploratory caveat; no significance threshold is promoted.
- **Interface hardening.** `ShoppingAgent` now binds each decision to the serialized visible
  set (`BuiltContext` and a receipt). A legacy or custom `context_builder` that returns plain
  messages still works, but a turn now fails with `invalid_context_visibility` if its last
  message is not JSON naming the current search or if its evidence differs from the raw
  result; previously such a builder was accepted. The default profile is unchanged.
- **Dependency surface.** `tokenizers` pulls in `huggingface_hub` and HTTP libraries that are
  never used: only `Tokenizer.from_file` on a local, hash-pinned file is called. Streamlit's
  `watchdog==6.0.0` is installed but not in any lock file (pre-existing).
- **Cumulative budget.** The live cap is shared across runs via `--prior-run`; the budget is
  persisted before each paid call. Primary comparison, a null replicate arm and a cache-aware
  latency policy remain open for the owner (experiment README).
- **Authenticated visibility.** For a named card profile, `bind_context` now requires the
  model-visible `latest_search` to equal the profile's projection of the raw result exactly,
  so extra keys, rewritten counts, reordered/dropped cards and unreferenced shared entries
  are rejected. `custom` (legacy) builders keep the evidence-only check.
- **Replay integrity** checks the seeded schedule, duplicates, completeness and error trials;
  consistent record fabrication and forged certificates remain undetectable by code.

## Simulated-shopper evaluation (31 October 2026)

The user approved building the evaluation harness without waiting for a proposal review, with
Ollama (`llama3.1:latest`) running only on the user's Mac.

- **Separate package, one-way dependency.** `astra_eval` depends on `shopping_agent`, never the
  reverse; ground truth is a separate hash-checked file loaded only by the scorer and audit.
- **Independent oracle.** The scorer re-judges raw catalogue rows with its own small rule set
  instead of the agent's retrieval gate, so a gate bug cannot grade itself; a test cross-checks
  the two. Trade-off: a little duplicated matching logic.
- **Scenario truth is verifiable, not guessed.** Acceptable sets come from explicit catalogue
  fields; unknown is never acceptable; no-valid-product tasks are verified empty variations.
- **Shopper memory is consistency-only.** Immutable profile, token-budgeted window and a
  code-built ledger; no vectors, no persistence, no model summaries (so nothing generated can
  override the profile). Trade-off: lexical question-to-fact matching is brittle by design.
- **Lexical consistency checks and invalid sessions.** Simulator faults invalidate a session and
  are excluded from agent denominators but reported; agent failures and exhausted budgets are
  failures that stay in every denominator.
- **No scripted application policy.** Offline end-to-end tests use test-only decision policies;
  the CLI can only use DeepSeek, and only with `--live --max-model-calls`.
- **Memory comparison seam only.** `Condition`/`ExperienceSnapshot`/agent factory and one hashed
  shared config; memory ON raises `NotImplementedError` until a factory exists.


## Attribute ledgers: derived session projection, not a second requirement store

Asked/disclosed ledgers are rebuilt from canonical events and active requirements and cached
as a separate snapshot field. This avoids changing historical ShoppingState/codec payloads,
keeps requirement IDs/statuses authoritative, and avoids invalidating retrieval when merely
asking a question. Narrow evidence patterns handle explicit response dispositions, currency
and width. Ambiguous or unsupported language stays unresolved; deterministic validation does
not claim complete semantic understanding. Related question facets have separate names.
The new working-context prompt version distinguishes this intentionally changed agent policy
from older evaluation baselines. Watch regression fixtures now use product_subtype for their
legitimate type-narrowing question; their two taxonomy expected failures stay visible.

## Target-item evaluation: exact discovery and grounded abstention (Part B)

Target-item evaluation is implemented as an explicit mode (`--evaluation-mode target_item`), strictly separate from the preference-based benchmark.
- **Catalogue grounding:** Sampling derives only from documented explicit fields, category tokens, and next strictly greater $10 USD boundaries. Target IDs and titles are stored strictly in `TargetGroundTruth` and never enter shopping agent or shopper contexts.
- **Early termination:** Halts immediately once ASTRA presents the target product within primary $K$ ($K \le 5$, default 5). No additional simulated-shopper or shopping-agent calls are made after a hit.
- **Conservative disclosure evidence:** Evaluates disclosures literally with NFKC unicode normalization, negation awareness, color canonicalization, and budget operator contradiction checks. Over-reveal (>2 new facts) triggers a retry error.
- **Audit and metrics:** Preserves independent constraint checking and explicit failure reasons. Tracks Hit@K, MRR@K, MTTC, cumulative success by turn, search and clarification efficiency, and separate grounded abstention on verified empty tasks. Invalid sessions are recorded safely without crashing the batch.

## Experiential memory: procedural self-improvement without evaluation contamination

The user approved implementing the vertical slice of experiential self-improvement with explicit refinements:
- **Separation of candidate vs confirmed lessons:** Raw LLM-extracted lessons remain in `candidate` status and cannot be retrieved until human review explicitly confirms them. This prevents hallucinated or spurious failure explanations from automatically corrupting agent behavior.
- **Explicit lesson structure:** Every lesson maintains separate fields for observed outcome, hypothesized failure cause, bounded procedural directive, expected action, deterministic action signature, and evidence references.
- **Cross-category behavioral triggers:** Retrieval matches decision triggers (`initial_query`, `empty_search_recovery`, `recommend_cutoff`, `attribute_clarification`) and decision context cues rather than narrow product families, ensuring transfer between disjoint learning and evaluation splits.
- **Anti-contamination enforcement:** Sourcing is restricted strictly to the `learning` split. Lexical and structural guards reject ASINs (`B0...`), product IDs, evaluator target product titles, and prompt injection patterns. Snapshots for held-out evaluation are frozen and content-hashed; evaluation runs never update memory.
- **Provenance, superseding and retraction:** Lessons are versioned in SQLite. Superseding links new versions to the replaced lesson ID while updating the superseded lesson. Retracted or rejected lessons are excluded from retrieval without destroying historical provenance.
- **Distinct metrics for retrieval, injection, application, and improvement:** The agent explicitly logs retrieved lessons, injected lessons, and applied lessons (verified deterministically via `verify_decision_application` against action signatures). Measuring improvement requires comparing outcome metrics between identical frozen scenarios under `memory_on` versus `memory_off`.


## Focused pilot-integrity fixes

First decision means first policy request for a category-identified current goal, including
repaired decisions and validated goal transitions. Conservative category-only parsing suppresses
unrecognized extra words; false negatives are preferable to applying a clarification directive
to a specified request. Read-only vocabulary projection leaves BM25 and the tool interface
unchanged. Cue provenance records provisional scope separately from committed state.

Retrieval, actual serialized prompt inclusion, accepted action conformance, and empirical
outcome improvement are distinct. Candidate upserts cannot alter reviewed content; duplicate
extraction is idempotent. Revisions require a new unused ID, and explicit lifecycle transitions
retain approval notes. Disclosed compliance uses per-recommendation committed hard state;
hidden target requirements and exact target hits keep their existing independent definitions.
The extractor chooses predefined templates; its causal explanations remain hypotheses. No
simulator/profile/benchmark tuning or lesson activation is part of this checkpoint.

## Stage 1: separate opt-in user profiles

Reuse session owner IDs, JSONL replay/state validation, BM25 and procedural SQLite memory.
Add one authoritative per-user Markdown profile with four sections, instead of coordinating
four independently replaced files. JSON-escaped bullets are readable and reversible; there
is no companion user database or copied conversation history. Atomic replacement, user locks,
revision checks and source-event idempotency protect updates across concurrent sessions.

Use an enabled-only policy schema so the OFF path retains baseline prompts/contracts. Current
user evidence must support model proposals, persistence, personal ownership, polarity and scope.
General facts also require explicit persistence/frequency cues; broad 'I am' is insufficient.
The conservative rules intentionally sacrifice paraphrase coverage. Existing requirements
override advisory memory. Purchase records require explicit confirmation, not recommendations.
Rejected memory writes are visible without discarding valid shopping actions. Default OFF is
explicit opt-in and leaves existing evaluation conditions unchanged. Future learner/timeline
interfaces are documentation only; no new evaluator, paid calls or source-code editing.

## Stage 2: thin returning-customer orchestration

Reuse Scenario/ShopperProfile, DialogueRunner, OllamaShopper, CatalogueOracle and both existing
scorers. Add customer/visit contracts and explicit current-boundary projection rather than a
parallel dialogue loop. Optional stable-owner/private-context parameters preserve single-session
defaults. Isolate complete OFF/ON timelines by condition storage; rotate whole customer arms,
not visit order. User memory starts empty and forms only through normal message evidence.
Procedural memory remains OFF. Invalid earlier sessions block later visits in that arm.

Curated development witnesses use explicit catalogue facts and frozen evidence hashes. Targets
may be ambiguous; exact ID discovery and graded suitability stay separate. Memory exposure and
product associations are diagnostics, not causal application or disclosed-constraint violations.
Reported usage and missing-coverage flags preserve the inherited failed-shopper accounting limit.
These fixtures/tests establish infrastructure only; no live run or held-out expansion is approved.

## Memory representation simplification

Retain canonical state/event validation and separate a compact attribute-based shopping view.
Model edits use current field/index paths; the executor resolves IDs and binds the captured
revision. Actual product/search identities stay visible and verified; soft-match UUIDs become
preference paths without losing evidence. Current snapshots can omit historical/provenance
fields because authoritative events retain them. No new state engine or retrieval algorithm.

User Markdown displays only active prose, with exact canonical records/history in a collapsed
audit section in the same atomic file. Rendering is deterministic and consistency-validated,
so prose and metadata are not independently editable sources of truth. Old profiles load
without migration; accepted writes use the new format. Readability can increase file bytes.
Normal app defaults to compact v7; library/experiment defaults remain legacy, with an explicit
longitudinal format option. Protect historical conditions and measure API characters separately
from billed tokens. Semantic retrieval, LLM summarization and live trials remain separate.

## Autonomous shopper V3, opt-in

Give the shopper typed current needs and actual history rather than canned sentences or
model-generated disclosure labels. Keep transport, roleplay context and text evidence separate.
Derive bounded evidence from accepted language, leaving unknown paraphrases unverified and
recognized contradictions rejected. Preserve V2, independent catalogue validation and existing
scoring. This trades exact conversational repeatability for autonomy; request replay, isolated
condition histories, provider budgets and explicit audit limitations keep the change inspectable.
No new framework/dependency or production memory layer is introduced. [Details](simulator-v3.md).

Claude shopper settings may share `.env` with DeepSeek using separately named
`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` fields. Reuse the literal, allowlisted parser so the
application still loads its DeepSeek settings when Claude fields are present. An explicit
shopper file remains supported; model precedence is CLI, process, file. No implicit provider
switch or model request occurs when configuration is read.

## Sonnet 5.5 transport and capped evaluation

Omit Claude sampling parameters rather than advertise ineffective temperature control.
Use Sonnet between-tools/low-effort settings to bound a text-only shopper and test an explicit
512-token cap. Preserve prompts/auditor/scoring. Record envelope usage before rejecting refusals
or truncations. A shared evaluation-only Decimal ledger reserves conservative costs before
either provider call; missing usage retains the reserve and stops. This is client accounting
with explicit billing-bound limitations, not a provider invoice or guarantee of run completion.
