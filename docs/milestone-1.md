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
State-commit events contain complete post-state versions and edit provenance. A process/thread
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
