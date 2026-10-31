# Self-Improving Conversational Search Agent

A research project asking whether confirmed shopping experience can improve an agent's
future decisions. The intended research cycle is: complete a task, independently confirm
its outcome, distil applicable experience, and compare future behaviour with/without it.
Memory is not assumed to improve performance; negative transfer is an outcome to measure.

## Current status: baseline and mock chat UI

Implemented: session-only memory, lexical product retrieval, a bounded DeepSeek decision
loop, local tracing, CLI and automated acceptance tests. Phase 3 adds a minimal Streamlit
chat UI using explicitly scripted mock decisions with real catalogue retrieval. **No long-term
user memory, agent experience learning, evaluator or code self-optimisation is implemented.**

This is a new implementation inspired by
[ASTRA](https://devpost.com/software/reimagining-the-digital-experience). ASTRA and the earlier
AutoML project remain separate. No reference code, weights, configuration, sessions or
historical evaluation cases were copied. Only the user-approved frozen 50k catalogue and
image-URL references were reused as local, ignored data.

The [roadmap](docs/roadmap.md) records phase goals, exit gates and current status. The user
approved mock-first UI work while deferring live Phase 2 validation and the two documented
[review findings](docs/reviews/phase-2-subagent-review.md). Those defects remain unchanged.
UI tests/demo do not establish live interpretation or shopping quality. See the
[Phase 3 evidence and limitations](docs/phase-3-ui.md).
See [current architecture](docs/architecture.md), [proposed evaluation](docs/evaluation.md)
and [decision record](docs/decisions.md).

## Setup

Use macOS/Linux and Python 3.11+ with SQLite FTS5. Tested locally on Python 3.14.3 /
SQLite 3.51.2; other Python versions and Windows are unverified.

```bash
cd /Users/yangxu/code/self-improving-agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
```

Pydantic is the only direct core runtime dependency; Ruff is a development tool. The lock file
records exact tested versions; the editable build also uses isolated setuptools. No agent
framework, model SDK or embedding service is needed. Streamlit is an optional UI dependency.

The ignored `data/catalogue/` directory must already contain the imported `catalog.jsonl`
and `product_images.json`; a GitHub clone alone does not contain these assets. The catalogue
has 50,000 unique parent products. The URL map covers 49,944 products; 56 have no image entry.
No image binaries were imported into the dataset. Browser checks loaded some images;
bulk remote URL reachability remains unverified.
`manifest.json` records local import provenance and checksums.

Build the index (no API key needed):

```bash
.venv/bin/python -m shopping_agent index
# To replace an existing index explicitly:
.venv/bin/python -m shopping_agent index --rebuild
```

The index is generated at `data/index/catalogue.sqlite`; it is not session memory. Source
hashes and index version are recorded. Chat checks the source hash and refuses a stale index.
The measured local index size is about 173 MB, in addition to about 61 MB of raw catalogue.

## Mock chat UI (no API key)

From this repository, install the optional UI dependencies and launch the local app:

```bash
.venv/bin/python -m pip install -r requirements-ui-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m streamlit run streamlit_app.py
```

Open [the local chat UI](http://127.0.0.1:8501). If the catalogue index is not built yet,
run `.venv/bin/python -m shopping_agent index` first. The UI is bound to loopback by default;
it is for a trusted local operator, with no hosted authentication.

Try `hello`, `boots under $100`, `actually under $30`, `prefer red`, `no leather`,
`leather is okay`, or `new goal: backpack`. The mock recognises a limited vocabulary and
simple phrase patterns; compound/unrecognised requirements may not be interpreted correctly.
The interface clearly labels mock mode. Recommendations come from the actual catalogue,
with deterministic hard gates; no product IDs or search results are canned.

Use the sidebar to start/select/resume a chat, inspect active needs/preferences and previous
requirements, or switch the local shopper label. Each response has a **View activity**
expander showing actual state edits, searches, candidate counts and recommendation actions.
Product cards keep text/facts available when images are missing; remote image reachability
is not guaranteed. The default UI sessions live separately in ignored `data/ui-sessions/mock/`.
Refresh creates a fresh UI session; select a saved chat or resume its UUID to recover history.
The browser does not maintain a second authoritative transcript.

The UI does not load `.env`, read keys or call DeepSeek. Adding a key does **not** silently
switch modes. `ChatService(policy=...)` can receive the existing `DeepSeekPolicy` when live UI
integration is explicitly enabled later. The existing live CLI below remains available.
For local tests/custom paths, process variables `ASTRA_CATALOGUE`, `ASTRA_INDEX` and
`ASTRA_UI_SESSIONS` override UI paths; they are not additional `.env` loader settings.
The UI lock records the complete tested UI/dev environment; the core lock remains separate.

## Chat with DeepSeek

```bash
cp .env.example .env
# Edit this project's .env and set DEEPSEEK_API_KEY locally.
.venv/bin/python -m shopping_agent chat --user yangxu
```

The CLI prints a new session UUID. Try a conversation such as:

1. `I need hiking boots.`
2. Answer a clarification, or volunteer: `My budget is under 100 USD.`
3. `Actually, keep the budget under 60 USD.`
4. `Prefer red, but that is optional.`

The live model chooses its own questions/actions; this sequence is illustrative, not a
scripted production path. It may ask more questions or find no verified matches. Enter
`/state` to see active and superseded requirements, or `/quit` to exit. Resume the same chat:

```bash
.venv/bin/python -m shopping_agent chat --user yangxu --session SESSION_UUID
```

Only `DEEPSEEK_API_KEY` and `DEEPSEEK_MODEL` are accepted in `.env` (simple KEY=value, optional
quotes, whole-line comments; no shell expansion). Existing process variables take precedence.
The default model is `deepseek-flash`. This adapter has been tested with mocked HTTP responses;
**no live DeepSeek request was run during this milestone, at the user's request.** Model
availability, live interpretation quality, latency and actual API cost remain unverified.
Each user turn allows at most three requests (repairs included), each capped at 2,000 output
tokens, and two searches. HTTP/network errors stop without automatic retries. Total spend
still grows with turns. Credentials are not placed in prompts or persisted in session logs.

For a single JSON response and an explicit retry key:

```bash
.venv/bin/python -m shopping_agent chat --user yangxu --session SESSION_UUID \
  --message 'Actually, under 60 USD' --request-id budget-correction-1 --json
```

Repeating a **completed** request ID with the same message returns its recorded response.
Using a different message with that ID fails. An incomplete request fails closed; inspect
its log and state before deliberately starting a new request. Accepted edits survive failed
or interrupted turns. Request IDs prevent local replay; they cannot guarantee exactly-once
billing if the process dies after a provider request.

## Inspect session memory and traces

```bash
.venv/bin/python -m shopping_agent inspect --user yangxu --session SESSION_UUID
.venv/bin/python -m shopping_agent inspect --user yangxu --session SESSION_UUID --events
```

These commands do not call a model. Each session has:

```text
data/sessions/<session UUID>/
  events.jsonl   # authoritative, append-only conversation/action/state-version history
  state.json    # rebuildable latest snapshot, including requirement correction history
  .lock         # local single-writer lock
```

The log records full user/assistant messages, actual bounded model prompts, JSON decisions,
validation failures, state transitions, tool calls/results, recommendations, reported token
usage and durations. It excludes authorization headers and provider reasoning fields. Logs
contain private conversation data and remain ignored by Git. Owner checks isolate sessions
but are not authentication: the CLI assumes a trusted local operator. Do not host it as a
multi-user service without adding authentication and a suitable storage/security design.

## How the baseline works

```text
User turn → owned session/event log → bounded context → LLM JSON decision
  → validate quoted state edits → commit a versioned requirement ledger
  → CLARIFY / RESPOND: terminal message
  → SEARCH: deterministic tool → trace actual results → another LLM decision
  → RECOMMEND: current inspected IDs + constraint recheck → deterministic product cards
```

| Module | Responsibility |
| --- | --- |
| `contracts.py`, `state.py` | Closed action schemas; evidence-linked ADD/REPLACE/RETRACT/NEW_GOAL edits; simple conflict detection |
| `sessions.py` | Owner checks, JSONL replay, atomic snapshot replacement, process/thread locks |
| `retrieval.py` | Source-hashed SQLite FTS5 index, literal queries, BM25, hard gates and soft-match evidence |
| `context.py` | Active state/current results/recent dialogue under a context cap; separate from execution |
| `provider.py` | DeepSeek JSON-mode transport; sanitized failures; no hidden fallback |
| `agent.py` | Decision validation, bounded execution, current-result checks, trace and retry handling |
| `cli.py` | Index build, interactive/single-turn chat, inspection |

The model chooses clarification attributes/questions, query tokens and all/any matching,
when to search, and which eligible candidates to recommend in which order. It cannot supply
SQL, change search code, silently remove filters at tool invocation, or invent recommendation
IDs. All **stored active hard constraints** are applied by the tool; soft preferences are
annotated for the model, not automatically reranked. Deterministic validation cannot prove
that the model extracted every need or understood a correction correctly. Inspect `/state`.

A replacement names an active same-field requirement ID, cites the current message, retires
the previous entry and appends a new one. Retraction removes an exclusion without inventing
a positive preference. An explicit new goal retires the old active requirements. A state or
retrieval-strategy change invalidates previous search results. Recommendations must use the
result provided to their decision and pass a current hard-constraint recheck.

Policy, context builder, retrieval tool and storage are separate interfaces. Future scoped
experience can be added to context construction without replacing the executor. There is
no future-memory placeholder implementation or persistent cross-session preference reuse.

## Conservative catalogue semantics and limitations

- Missing price/required attributes are **unknown**, including when checking exclusions.
  Such products cannot pass the relevant hard requirement. Unknown soft attributes are not
  failures. Exact positive prices are accepted; zero, missing, `from` and ranges are unknown.
- Brand/color/material/size/department come from explicit detail fields. Store is not brand.
  Product type checks literal category tokens; keyword checks catalogue text. This is lexical
  evidence, not semantic understanding, verified safety claims or an inferred product ontology.
- Exact equality and token containment differ. For example, material `not_contains: leather`
  rejects `Leather and cotton`; `neq: leather` only excludes the exact normalized value.
- Parent-product metadata and historical USD prices do not establish child-variant stock,
  current price or purchasable size/color combinations. Availability is unverified.
- BM25 is a retrieval baseline; it does not establish recommendation quality. Sparse fields
  can produce few or zero verified candidates. No live crawling or attribute imputation occurs.
- Full history is stored; prompts use active requirements, current results and up to twelve
  recent dialogue messages. Old dialogue is trimmed first under 40,000 characters. Essential
  context is never silently truncated; oversized essential context fails before a paid call.
- Schema/quote checks do not prove semantic entailment. RESPOND/CLARIFY natural-language
  factual accuracy and resistance to prompt injection remain unverified. Recommendation
  cards, IDs and stored-constraint checks have deterministic gates.
- Session files are a local single-writer design, not a transactional database or tamper-proof
  audit system. Malformed/truncated/inconsistent logs are preserved and rejected for manual
  repair. An intact event log rebuilds a corrupt or stale snapshot.

## Verification

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check src tests streamlit_app.py
.venv/bin/python -m pip check
```

The baseline test suite uses generated catalogue fixtures, scripted **test-only** policies
and mocked HTTP transport. The UI has its own explicitly labelled scripted demo policy and
Streamlit AppTest acceptance tests. UI tests are explicitly skipped without the optional
`[ui]` extra; install the UI lock to run them. Coverage includes corrections, retractions,
unknown data, real SQLite search/filtering,
owner/session isolation, restart recovery, a second-process writer lock, bounded repairs,
unseen/stale IDs, failed eligibility rechecks, request replay and CLI execution. These tests
are acceptance checks, not the future simulated-shopper evaluation framework.

The actual 50k index was also exercised with a test-only policy through clarification → search
→ recommendation → budget correction → fresh search/recommendation. The 341 lexical `hiking
boots` matches yielded 13 verified matches below USD100, and 8 below USD60 with the stored
literal `boots` category filter. These overlapping failure/unknown counters are not relevance
or shopping-success measurements. No API tokens were used and no learning benefit is claimed.

See [milestone notes](docs/milestone-1.md) for checkpoint evidence and trade-offs,
[project context](docs/project-context.md), [research questions](docs/research-questions.md),
[open decisions](docs/open-decisions.md) and [coding guidance](AGENTS.md).
