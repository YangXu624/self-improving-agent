# Context and durable-event compaction

31 October 2026. Scope: the user requested smaller state and event representations after
the live boots/women trace consumed 24,959 reported input tokens. No new framework, model
summary, dependency, retrieval strategy, memory layer or larger budget is introduced.

## Implemented representations

**Model context (`shopping-baseline-v3-compact`):**

- Active requirements contain stable ID, field, operator, value and hard/soft strength.
  State version, goal epoch and conflicts remain visible. Creation quotes, source-event
  references and retired requirements stay in durable storage, rather than each prompt.
- Dialogue contains user text, assistant action/text, clarification attribute or error, and
  ordered prior recommendation evidence. Transport IDs/budgets and full product-card objects
  are omitted. Only the current user event is excluded by identity; earlier identical short
  answers are retained. The limit remains twelve prior messages, trimmed oldest first.
- Every current candidate ID and its order are retained. Title, categories, known facts,
  fact sources, distinct snippet text and soft-match references remain visible. Missing facts
  explicitly mean unknown. Image URLs, full precision scores, repeated verdicts, duplicate
  fact values and title/category prefixes in snippets are omitted. Hard-filter IDs refer to
  active state; all returned candidates passed those gates. Historical recommendations are
  not a current result that can be referenced for RECOMMEND.
- The schema is generated from the same Decision model, with generated titles removed and
  compact JSON separators. Constraints, discriminator, defaults and example remain. Essential
  state/results still fail before an API request if over the existing character cap. The
  executor continues to validate IDs, current versions and full catalogue eligibility.

**Durable storage:**

- JSONL remains append-only. New encoded records carry `storage_version: 2` where necessary.
  Identity, timestamps, event IDs, sequence/turn/state versions remain in event envelopes.
- State commits store changed/appended requirement entries, including status changes, quotes
  and source provenance. Previous state versions are reconstructable. Unusual reordered or
  shortened external ledgers fall back to a compact full state rather than losing data.
- Accepted decisions reference their exact recorded model response; accepted commit edits
  reference that validated decision. Recommended products reference the actual search result
  with an ordered ID list. Completed turns reference their assistant response. These avoid
  copying the same data into several adjacent records.
- Identical prompt messages reference earlier messages in the same log. Other long prompt
  strings use stdlib zlib/base64 when smaller. This is lossless storage compression: the
  exact prompt strings and their existing context hashes are preserved, not summarized or
  regenerated using whatever prompt code happens to be installed later.
- `state.json` uses compact JSON with default/null fields omitted. The existing state model
  restores defaults; correction and withdrawal history is retained. Ordinary conversation
  and tool evidence remain readable JSON; inspect commands/UI expand compressed/reference
  payloads to canonical events.

`sessions.py` applies the codec at its disk boundary. Agent, UI service and CLI receive the
same canonical event/state/response structures. Full product facts, evidence and images are
retained for rendering and eligibility checks even though the model gets a smaller view.

## Preservation and failure behavior

Existing logs are not rewritten, migrated, truncated or deleted. New records can append to
a legacy prefix; the mixed format is supported. Older versions of the application cannot
read version-2 records, so use the current reader when inspecting/resuming new logs.

References are backward-only, session-local, type-checked and turn-checked where required.
Invalid/future/wrong-type references, unseen product references, duplicate state-delta rows,
invalid state versions, bad compressed streams and oversized expansions fail closed without
rewriting the log. Canonical event size is checked before encoding and after decoding;
compressed prompt output is separately bounded. Session ownership, locks, snapshot recovery
and request-ID replay remain enforced. This is not an authenticated or tamper-proof log.

## Measurements actually executed

All measurements below are offline. The supplied DeepSeek tokenizer asset and audit-only
`tokenizers==0.23.3` from the earlier investigation were reused under `/tmp`; application
dependencies are unchanged. No credentials or live provider requests were used.

The exact saved prompts from “hiking boots for the winter” → “do you have something for
women” were rebuilt with the new context projection using their recorded state/results and
history. This holds the observed decision/search sequence fixed; it does not simulate how
a real model might change its decisions under a shorter prompt.

| Second-turn decision | Original message-content tokens | Compact message-content tokens |
| --- | ---: | ---: |
| First call | 8,070 | 4,194 |
| Second call | 8,220 | 4,001 |
| Third call | 8,588 | 4,336 |
| **Total** | **24,878** | **12,531** |

Reduction: **49.6%**. The original API reported 24,959 input tokens: 81 additional tokens,
27 per request, whose provider-side details are not exposed. New provider totals/caching
and dollar savings have not been measured. The first turn's content shrank from 8,125 to
5,068 tokens (37.6%); the reduction is workload dependent.

Separately, the original canonical events were losslessly re-encoded in memory using the
new disk codec. Every recovered event was compared to the original, including exact prompt
strings, decisions, facts, timestamps and usage. Source files were verified unchanged.
These storage numbers retain the **original large prompts**, so are separate from context
projection savings and must not be added to the token percentages.

| Existing trace | Events | Original log bytes | Re-encoded bytes | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Boots/women | 37 | 202,058 | 82,639 | 59.1% |
| Watch failure | 43 | 117,106 | 56,144 | 52.1% |
| Earlier live smoke | 37 | 213,035 | 88,650 | 58.4% |

The boots trace's complete state payload also shrank from 885 to 621 serialized bytes
(29.8%), with all defaults/restored values and history equal. This compares equivalent state
payloads, not the whole snapshot envelope or a provider prompt.

## Tests and reproduction

Added six context tests for stable correction IDs, exact schema constraints, unknown facts,
fact provenance, all visible candidate IDs/order, distinct snippet evidence, previous
recommendation order and repeated short-answer handling. Ten storage tests cover exact
prompt hashes and event equality, ordered product cards, completed-request replay with
network denied, legacy-prefix appends, correction/retraction/new-goal state versions,
snapshot recovery, corrupt references, invalid/truncated/oversized compressed data, Unicode,
fallback state encoding and canonical event-size enforcement.

```sh
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check src tests docs/reviews/measure_compaction.py streamlit_app.py
.venv/bin/python -m pip check
```

Results: **92 executed: 89 passed, three existing expected failures, zero skipped and zero
unexpected failures**. Ruff lint/format and dependency checks passed. Existing Streamlit
bare-mode context warnings were emitted. The expected failures remain the two watch-type
matching cases and exhausted-search closure; this compaction does not repair those defects.
No broad shopping-quality, live decision-validity, latency, memory-transfer or cost benchmark
was executed. Restart/resume, correction and recommendation safeguards are verified offline.

Read-only reproduction of log roundtrips and context character counts:

```sh
.venv/bin/python docs/reviews/measure_compaction.py /path/to/events.jsonl
```

For tokenizer counts, supply the same published V4 tokenizer documented in the
[watch audit](watch-decision-budget-audit.md#input-token-accounting):

```sh
PYTHONPATH=/tmp/astra-watch-audit/tokenizer-runtime .venv/bin/python \
  docs/reviews/measure_compaction.py \
  data/ui-sessions/deepseek/825cae45bccd4053aef7a0f6bf5eed3e/events.jsonl \
  --tokenizer /tmp/astra-watch-audit/tokenizer-assets/deepseek_v4_tokenizer/tokenizer.json
```

The script emits counts only, does not construct a provider or write source sessions, and
does not require tokenizer packages for the byte/character comparison. Legacy-v2 prompts
are rebuilt under the current projection; already compact-v3 prompts are retained as saved.
Raw sessions, data, tokenizer assets and generated measurements remain ignored/uncommitted.
