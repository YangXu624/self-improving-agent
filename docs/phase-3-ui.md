# Phase 3 — Minimal mock chat UI

The user authorised proceeding with a minimal UI on 31 October 2026, explicitly deferring
the two Phase 2 review findings and using a mock provider until a later DeepSeek setup.
This changes the earlier phase sequence: UI work is approved while live baseline validation
and the documented defects remain pending. No fix to those defects is included implicitly.

## Checkpoint 1: backend adapter

Implemented `MockShoppingPolicy` and `ChatService`, with optional Streamlit UI dependencies.
The policy is a visibly scripted demo, not a general natural-language model or an automatic
fallback. It handles known product types, simple USD upper budgets, colours/materials,
`no leather`, `leather is okay` and explicit `new goal: ...` requests. Unknown text receives
limited-demo guidance. It may not interpret compound or unsupported requirements correctly.
This is a UI demonstration, not a shopping-quality or learning benchmark.

The existing agent performs validation, state commits, actual FTS5 search and current-result
recommendation checks. No product IDs/answers are canned. The service reads messages/state/
events from SessionStore, lists only the selected local owner's chats, and opens/closes the
SQLite connection per request. Mock UI sessions default to their own ignored directory;
CLI sessions and original reference data are not changed.

Validation: 54 tests passed (45 baseline plus 9 new adapter/service cases), with Ruff passing.
New cases exercise clarification, real fixture retrieval, budget replacement, soft/hard
separation, withdrawal, new goals, unknown-price filtering, empty results, owned listing/resume,
request replay and thread-local SQLite use. DeepSeek transport was patched to fail if called
in the offline flow. Streamlit 1.66.1 was installed in the project venv as an optional extra;
the visual renderer and AppTest acceptance checks are the next checkpoint.
