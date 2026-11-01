# Compact-memory representation verification

Scope: simplify current shopping/API state and user-memory presentation while preserving
canonical validation, audit evidence and historical formats. No semantic retrieval, model
calls, external learner, procedural activation or scoring-rule change.

This branch is stacked on open PR #19 (`57f6a3b`), not merged into main. Existing evaluation
defaults remain legacy. Normal UI/CLI defaults are compact; longitudinal opt-in is explicit.

## Actual checks

```text
.venv/bin/python -m unittest discover -s tests -q
Ran 531 tests in 11.789s
OK (skipped=1, expected failures=2)

.venv/bin/ruff check src tests
All checks passed

.venv/bin/ruff format --check src tests
92 files already formatted

git diff --check
No whitespace errors
```

528 ordinary passes, one existing missing-tokenizer skip, two existing watch/wristwatch
expected failures. Eighteen new tests cover view/schema contracts, ranges/exclusions/alternatives,
field/reference resolution, captured revisions, correction/search invalidation, memory
formation/recall/correction, current-point injection audit, snapshots/replay, card evidence,
verified soft-match paths, old profiles, escaped markup and unchanged files on profile read.
New mocked-HTTP UI and CLI tests exercise the actual compact defaults. Historical fixture
tests explicitly choose legacy rather than silently changing their prescribed provider format.
No existing correctness assertion was removed; the Markdown assertion was updated for prose.

An in-memory comparison loaded context.py from `57f6a3b` and compared actual legacy messages
for empty and range/user-memory fixtures. Both were byte-identical (7,910 and 11,204 content
characters). No old file was rewritten. Exact old DeepSeek payloads remain reproducible when
the legacy format and equivalent values are selected.

## Measured size, not live performance

The same two synthetic cases used actual serialized messages and the real six-field legacy
user-memory projection, with no products/dialogue. Empty prompt: 7,910 → 6,715 characters;
range/preferences plus one memory: 11,204 → 9,495. That fixture's state: 650 → 246; memory:
165 → 81. These are character counts, not billed DeepSeek tokens. Live recommendation quality,
token costs and transfer benefit were not measured. Product IDs/order, matching and eligibility
remain enforced; soft-match evidence is retained through current preference paths.

A one-record Markdown fixture grows 533 → 647 characters. Readability is the goal; audit
metadata is still retained in the same atomic file. Superseded records are not visible in the
active prose or selected API memories. Prose is derived and checked against exact metadata,
not an independently editable second truth. No LLM summary is generated.

## Preservation

All 170 pre-existing files anywhere under `data/` were inventoried before implementation.
After tests, the same paths and every SHA-256 matched. Inventory hash before/after:

```text
2af306ac726feaa7030529c1f93676e399adca99fa8d86235a0053403c73b198
```

This includes original catalogue/index, benchmark drafts/frozen versions, procedural pilot
database, evaluation outputs, smoke sessions and UI histories. New test files use temporary
roots. No credentials, profile data, session files or generated indexes are committed.

## Boundaries and limitations

The backend retains its tested requirement model and full event log; this is a representation
change, not wholesale removal of metadata. State/search revisions are server-side. Current
field-index and memory references cannot address another session/user or invisible record.
Profile validation and raw-catalogue gates are unchanged. Compact mode shortens policy
instructions, so mocked compatibility does not establish identical live decision behaviour.

Library and existing evaluations default legacy; compact experiments must select/record it
equally in both arms. There is no bulk migration of existing artifacts; profile reads support
v1/v2, and accepted profile writes use v2. Current caches rebuild from authoritative events.
The exhaustive inspect CLI remains an audit tool. No vector index or embedding dependency is
introduced. Follow-up semantic retrieval requires a separate controlled design/evaluation.
