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

## Checkpoint 2: visual interface and acceptance

Implemented the Streamlit entry point and renderer: chat bubbles, catalogue-backed product
cards/images, new/select/resume chat controls, local shopper labels, active requirements and
correction history, and per-response activity with raw turn events available on demand.
Text from users/products is rendered as text, not inserted into raw HTML. Missing/malformed
image references fall back to text; unreachable remote images may show browser alt text.
The default configuration binds to loopback and disables Streamlit usage telemetry.

The UI reads persisted events/state instead of maintaining a second conversation log. Its
session UUID is separate from transient selector state. A real-browser test exposed selector
reset after a first-message title changed; stable labels and independent selected-session state
resolved it. A headless regression explicitly resets the picker and verifies the same chat
continues. This is a new UI fix; the two existing Phase 2 findings were not modified.

Executed verification: **63 tests passed**, comprising 45 existing baseline tests, 9 service/
mock cases and 9 Streamlit AppTest cases, with no skipped tests in the installed UI environment.
Ruff lint/format and dependency checks passed. AppTest exercises corrections, persistent resume,
new/selected chats, owner changes, no-result replies, missing/malformed images, text rendering,
mock-only transport, busy-send errors and picker-reset recovery. Without the optional UI extra,
the nine UI cases are explicitly skipped. AppTest emits its documented bare-mode context
warning; its testing-only module temporary directory is explicitly cleaned up by test teardown
so strict ResourceWarning checks do not emit a finalizer error. No vendor source was edited.

Real browser checks against the actual 50k index exercised a suggested product search,
product cards with some successfully loaded Amazon image URLs, resuming a saved chat and a
USD100 → USD30 correction. The recorded turn showed state replacement, a new `boots` search,
3,140 lexical matches, 17 verified eligible products and three recommendations below USD30.
These are demo observations, not relevance/quality metrics. The browser's narrow default
viewport stacked cards; broader device/browser coverage has not been established.

The ordinary shell sandbox initially blocked the listening socket; the local-only server
started successfully with the permitted execution context. Browser control could not locate
an expander through a button-role selector; clicking the observed accessibility element
verified the actual activity view. Neither issue changed the agent/tool implementation.

## Reproduce and limits

Follow README's mock UI setup and run `streamlit run streamlit_app.py` through the venv Python.
The UI does not load `.env` or expose a live-provider selector. Later live UI integration can
inject the existing DeepSeekPolicy into ChatService without changing rendering or orchestration;
a key's presence alone never enables calls. Session files default to ignored
`data/ui-sessions/mock/`; catalogue/index paths and source files remain separate.

Live DeepSeek behaviour, general intent parsing, shopping success, persistent memories,
learning and evaluation remain unverified or unimplemented. Mock parsing is a limited demo
and may misinterpret unsupported/compound requirements. Known whitespace-evidence and
false-conflict backend defects remain deferred at the user's explicit instruction. The UI
has no authentication or production hosting guarantees; do not expose it publicly as a
multi-user service. No live shopping-provider API calls, new dataset downloads, image-binary
imports, AGENTS.md changes or original ASTRA/AutoML modifications are part of this phase.

## Checkpoint 3: live DeepSeek policy — current behaviour

The user supplied a local key and explicitly authorised replacing scripted decisions. The
prior mock-only descriptions above are historical checkpoints. Current UI startup reads the
explicit project env file and instantiates DeepSeekPolicy; ChatService requires an explicit
policy. `src/shopping_agent/mock_policy.py` has been deleted. Deterministic fixtures now live
only in tests and simulate HTTP responses, not a selectable runtime fallback.

The shared parser preserves CLI compatibility and process-variable precedence. UI/provider
resolution does not copy file secrets into os.environ, so later reruns can see a changed file
key. Missing/invalid credentials disable chat. Provider failures return safe errors and never
switch to a canned answer. API attempts/search counts and reported token usage replace mock
labels. New live sessions default to `data/ui-sessions/deepseek/`; earlier mock histories are
preserved unchanged in their old directory. Startup/resume/widget reruns do not call the model.

Prompt `shopping-baseline-v2` adds a current-version JSON example alongside the closed schema,
following the official provider guidance. Existing action choices, hard gates, BM25, budgets,
session lifecycle and deferred Phase 2 validator defects remain unchanged. No SDK, new model
framework, memory layer or retrieval strategy was introduced.

**Executed offline verification:** 70 tests passed: the original 45 baseline checks, 9 service
cases now exercising the real provider with mocked HTTP, 12 AppTest cases and 4 configuration
cases. New checks cover fresh key-file resolution, environment precedence, missing-key gating,
HTTP401 without fallback/key leakage, usage display and no requests during widget reruns.
A temporary test-only NameError from a removed redundant assertion was caught and corrected
in a follow-up commit; the full suite, lint and formatting then passed. No secret file is read
by the test fixtures; ASTRA_ENV_FILE points them to temporary test paths. Strict ResourceWarning
checks remain clean apart from Streamlit's expected bare-mode context log warning.

**Executed live smoke:** two generated shopping turns used the real 50k catalogue and the
actual configured API, capped at six requests. Five requests were used. Both turns completed
with RECOMMEND, with no decision-validation rejections. The first stored a USD100 upper budget
and used two calls/one search (9.65 seconds); the second replaced it with USD30 and used three
calls/two searches (5.46 seconds). The old budget remained superseded. Every final recommended
price was below USD30. The API reported 35,507 input and 664 output tokens in total. Actual
dollar cost and model quality across tasks are not measured by this smoke. No further paid
requests were made for browser inspection: the saved conversation was resumed and its usage,
state and activity were verified in the running UI. The actual credential was checked absent
from the stored smoke log without printing or persisting it.

The key remains local/ignored. Use README's live UI setup; do not paste it into chat. Missing
configuration, unavailable service, incomplete usage, wider language/constraint behaviour and
prompt-injection resistance still need broader testing. The two previously deferred defects
remain pending; this integration does not implement or claim the formal evaluation baseline.
