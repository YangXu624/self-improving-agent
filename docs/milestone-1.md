# Milestone 1 implementation checkpoints

Scope: session-only shopping baseline. No persistent user profiles, experience retrieval,
learning, simulated shoppers, evaluator or code optimisation is implemented in this milestone.

## Contracts and session persistence

Strict Pydantic models reject extra/executable fields, incompatible requirement operators,
nonfinite values and duplicate recommendation IDs. State edits cite the current user message
and target active requirement IDs. Replacements/retractions preserve history; explicit new
goals retire prior active requirements. Duplicate additions are no-ops. Simple numeric/text
contradictions are recorded and block search/recommendation until resolved.

Sessions use opaque UUIDs, owner checks, append-only JSONL records and a rebuildable snapshot.
Decoded state-commit events contain complete post-state versions and edit provenance. New
disk records store only changed requirement entries and reference accepted edits; legacy
full-state events remain readable. See the [compaction checkpoint](reviews/context-and-storage-compaction.md).
A process/thread
lock allows one writer per session; snapshots use flushed temporary files and atomic replacement.
Malformed/truncated logs fail closed and are preserved for manual repair; they are not silently
rewritten. The event log overrides a stale or corrupt snapshot. Valid state changes can survive
an interrupted turn; this is not a multi-file transactional database or tamper-proof audit store.
File locking currently targets macOS/Linux, not Windows. Real authentication and hosted
multi-worker deployment are outside this local CLI milestone.

Schema/provenance checks cannot prove semantic entailment of every natural-language edit.
Both deterministic fixtures and later real-model smoke checks are needed. Tests use generated
local fixtures, not TechJam sessions. Initial checkpoint: nine passing contract/session tests.

## Deterministic catalogue retrieval

The index stores a versioned, source-hashed projection of the catalogue and original image
URLs. Build uses a temporary database and atomic replacement; existing indexes require an
explicit rebuild. Queries become quoted lexical tokens, never SQL or raw FTS expressions.
BM25 weights title/taxonomy/features/description; ties use product ID. All matching rows are
checked before the final limit, so unknown-price rows cannot crowd out eligible products.
Soft matches are evidence annotations, not hard filters or a hidden reranking rule.

Only explicit detail fields support brand/color/material/size/department filters. Store name
is not treated as brand. Product type uses literal category tokens; it is not semantic type
inference. Keyword checks use catalogue text. Missing required attributes, even for exclusions,
are unknown and exclude the product. Numeric prices must be exact positive values; ranges,
`from` strings, zero and missing prices are unknown. Price is historical source currency (USD),
not current availability or a guaranteed variant price. Parent-product facts do not prove a
particular size/color variant is purchasable. These conservative rules can yield zero matches.

Checkpoint: 17 tests passed (9 session/contracts, 8 retrieval). On the local Python 3.14.3 /
SQLite 3.51.2 environment the actual 50,000-product index built in 2.24 seconds (172,797,952
bytes). Unconstrained lexical smoke queries returned 341 `hiking boots`, 6,263 `dress` and 468
`backpack` matches in approximately 3–43 ms. These are functionality/timing observations,
not relevance or shopping-success evaluation. Raw asset checksums remained unchanged.

## Bounded decisions and traces

The policy returns JSON proposals; orchestration validates state edits, commits accepted edits,
executes trusted search, then invokes the policy again with actual tool results. Default budget
is three model calls (including malformed-output repairs) and two searches per user turn.
No search runs on the last call because a further decision must inspect its result. Provider
HTTP/auth/network failures stop the turn without hidden retries or offline fallback. A failed
turn retains already accepted state changes. Completed request IDs replay the recorded answer
without another model call; incomplete IDs fail closed for explicit inspection/new-request recovery.

Recommendations must reference the result supplied in that decision context, at the current
state/catalogue versions, contain only returned IDs, and pass a fresh hard-constraint recheck.
Product cards use tool facts, not model-written descriptions. The model selects questions,
queries, all/any matching, eligible product order and when to recommend. Soft matches are
available for its ranking decisions. Ordinary RESPOND/CLARIFY text is model-generated and
cannot be proved factually correct by schema validation; the prompt restricts those channels,
but semantic adherence, correct requirement extraction and prompt-injection resistance need
real-model evaluation. Deterministic gates protect stored constraints, not unextracted needs.

Policy, context construction, tool and session interfaces are separate. The context builder
can later supply scoped guidance without altering the executor; no persistent experience or
user-memory implementation has been added. Full dialogue/events are durable; the prompt uses
active state, current message, current search and up to twelve recent conversation messages.
Old dialogue is trimmed first under a 40,000-character cap. Essential context is never silently
truncated: an oversized essential context fails before a paid call. Long sessions may need a
new session. Deterministic prompt projections and lossless event compaction were added in
the later checkpoint above. No LLM summarizer is used.

The DeepSeek adapter uses stdlib HTTP, JSON mode, disabled thinking, a 2,000-output-token cap
and 25-second socket timeout; no automatic retries. Model/usage/duration and full actual prompt,
structured output, validation failures, tool results and recommendations are traced locally.
Authorization headers and provider reasoning fields are excluded. Logs contain private user
and product content and must remain local. Socket timeout is not a global wall-clock deadline.

Checkpoint: all 32 automated tests passed, including 12 orchestration acceptance cases and
three mocked HTTP-adapter cases. No live requests were executed: the new project had no local
key. Real-model usefulness/constraint extraction and cost are not established by these tests.

## CLI and final integration

Added `index`, `chat` and `inspect` commands via `python -m shopping_agent` and the installed
`shopping-agent` entry point. Interactive chat prints a session UUID; `/state` inspects the
ledger and `/quit` exits. Single-message JSON mode supports explicit request IDs. Session
inspection and index construction need no API key. Chat refuses a missing key or stale source
index before creating a session. The explicit project `.env` loader accepts two settings
without executing shell syntax; process environment values take precedence. `.env.example`
contains no key. No neighbouring project credentials were read or copied.

Review tightened key-format validation to prevent header errors exposing malformed credentials,
closed HTTP error resources, checked replayed state-version consistency and invalidated cached
results after a retrieval-strategy version change. Added corresponding tests, mixed-material
exclusion coverage, CLI coverage and a real second-interpreter writer-lock check.

Final local acceptance: **45 tests passed** (11 session/contracts, 9 retrieval, 15 orchestration,
4 provider-transport, 6 CLI). Ruff lint/format and package dependency checks passed. Installed
entry point and module help were exercised. An editable reinstall initially failed with
`--no-build-isolation` because setuptools was not installed in the runtime venv; rerunning
with normal isolated build succeeded. No application dependency change was needed.

The actual imported index also completed a three-turn integration smoke with test-only
scripted decisions: ask budget, recommend below USD100, replace budget with below USD60,
then search/recommend again. State advanced v1→v2→v3, preserving the superseded price. Of
341 literal `hiking boots` matches, 13 and 8 passed the respective stored price/category
requirements. There were 39 local trace events and five mocked policy calls; **zero paid
API calls**. Counts of unknown/failed products overlap and are not additive. This confirms
mechanics with the real catalogue, not live model quality or measured learning.

The user explicitly chose mocked-provider tests for completion. Unverified: live DeepSeek
compatibility/decision quality, cost, real shopping success, semantic constraint extraction,
prompt-injection resistance, other Python/OS environments and remote image reachability.
Sparse metadata/lexical category matching can prevent useful recommendations. Source hashes
and reference ZIP are checked for preservation; raw assets and generated traces/index remain
ignored. There is no experience-learning demonstration yet because Levels 2/3 and evaluation
were explicitly excluded; the README documents a reproducible session-memory demonstration.
