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
