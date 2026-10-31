# Self-Improving Conversational Search Agent

A research project asking whether confirmed shopping experience can improve an agent's
future decisions. The intended research cycle is: complete a task, independently confirm
its outcome, distil applicable experience, and compare future behaviour with/without it.
Memory is not assumed to improve performance; negative transfer is an outcome to measure.

## Current status: live DeepSeek shopping UI

Implemented: session-only memory, lexical product retrieval, a bounded DeepSeek decision
loop, local tracing, CLI and automated acceptance tests. The Streamlit chat UI now uses
DeepSeek for decisions and real catalogue retrieval. The scripted application policy has
been removed; mocked responses remain confined to automated tests. **No long-term
user memory, agent experience learning, evaluator or code self-optimisation is implemented.**

This is a new implementation inspired by
[ASTRA](https://devpost.com/software/reimagining-the-digital-experience). ASTRA and the earlier
AutoML project remain separate. No reference code, weights, configuration, sessions or
historical evaluation cases were copied. Only the user-approved frozen 50k catalogue and
image-URL references were reused as local, ignored data.

The [roadmap](docs/roadmap.md) records phase goals, exit gates and current status. The user
subsequently supplied a local key and authorised live DeepSeek integration. A bounded two-turn
live check succeeded with five API requests, including a budget correction and fresh verified
recommendations. This is integration evidence, not a quality benchmark. The two deferred
[review findings](docs/reviews/phase-2-subagent-review.md) remain unchanged. See
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

## Live chat UI

From this repository, install the optional UI dependencies and launch the local app:

```bash
.venv/bin/python -m pip install -r requirements-ui-lock.txt
.venv/bin/python -m pip install --no-deps -e .
# Configure DEEPSEEK_API_KEY in this project's ignored .env; see .env.example.
.venv/bin/python -m streamlit run streamlit_app.py
```

Open [the local chat UI](http://127.0.0.1:8501). The user-provided key remains server-side;
no key should be entered into chat or committed. If the index is absent, first run
`.venv/bin/python -m shopping_agent index`. The UI binds to loopback by default and assumes
a trusted local operator; shopper labels are not authentication.

The UI reads only the project's explicit `.env` file (or `ASTRA_ENV_FILE`), accepts
`DEEPSEEK_API_KEY` and `DEEPSEEK_MODEL`, and gives process variables precedence. File values
are not copied into os.environ, so later reruns can pick up a changed file key. Restart the
server after upgrading code to ensure the final module versions are loaded. A missing or
invalid key disables chat. HTTP/auth/network failures surface as safe errors; **there is no
scripted fallback**. No live request runs just from startup, refresh or session inspection.

Sending a prompt or using a suggested prompt makes paid DeepSeek requests. Defaults remain
three API attempts (including repairs) and two searches per turn, with a 2,000-output-token
cap per request. There is no lifetime spend cap. Each answer shows API attempts/searches and
reported input/output usage; incomplete usage is labelled. Dollar cost is not estimated.

Try a shopping request and a follow-up correction, such as `boots under 100 USD` then
`actually under 30 USD`. The model chooses what to clarify, which queries to run, and which
returned candidates to recommend; the Python gates still enforce stored hard constraints
and valid/current product IDs. Prompt `shopping-baseline-v2` includes a schema and an example
JSON shape, following [DeepSeek JSON-output guidance](https://api-docs.deepseek.com/guides/json_mode/).

Use the sidebar to start/select/resume a chat, inspect active needs/preferences and history,
or switch the local shopper label. **View activity** shows real state edits, search counts
and recommendation events. Product text remains available when images are missing.
New live chats default to ignored `data/ui-sessions/deepseek/`. Earlier mock histories remain
untouched in `data/ui-sessions/mock/` and are not migrated or listed in the default live UI.
Refresh creates a fresh UI session; select/resume a saved UUID to recover history.

Process variables `ASTRA_CATALOGUE`, `ASTRA_INDEX`, `ASTRA_UI_SESSIONS` and `ASTRA_ENV_FILE`
can override UI paths; these are not additional accepted keys in the `.env` file. Keep custom
live storage separate from historical mock fixtures. The UI lock records the tested UI/dev
environment; the core lock remains separate. `ChatService` now requires explicit policy
injection; tests supply a fixture or mock HTTP, while production supplies DeepSeekPolicy.

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
The default model is `deepseek-flash`; `DEEPSEEK_MODEL` overrides it. The adapter is covered
by mocked HTTP tests and a successful five-request live integration smoke. Broad interpretation
quality, reliability across tasks/model versions and actual dollar cost remain unmeasured.
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
usage and durations. New records use lossless references for repeated data, state deltas and
bounded stdlib compression for long prompt strings. The inspect commands and UI expand these
into complete events; raw JSONL is a storage format, not the model context. Snapshots omit
default/empty fields while retaining correction history and provenance. Old logs remain
readable and are never rewritten; new turns append compact records. Use the current reader
for new logs, as older application versions cannot decode storage version 2. See the
[compaction evidence and reproduction instructions](docs/reviews/context-and-storage-compaction.md).
The log excludes authorization headers and provider reasoning fields. Logs
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
| `event_codec.py` | Lossless event references, state deltas and bounded prompt-string compression |
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
- Full history is stored; compact prompts use active requirement IDs/predicates, current
  candidate facts/provenance and up to twelve prior dialogue messages. Product images, ranking
  floats and repeated title/category text stay outside the prompt. Omitted facts mean unknown;
  no candidate IDs are dropped. Old dialogue is trimmed first under 40,000 characters. Essential
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

The suite uses generated catalogue fixtures, scripted **test-only** policies and mocked
DeepSeek HTTP responses; no application module supplies scripted decisions. UI acceptance
tests exercise the real provider adapter with offline responses, never the local key. UI tests are explicitly skipped without the optional
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
