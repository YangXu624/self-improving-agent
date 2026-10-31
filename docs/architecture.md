# Current baseline architecture

Status: session-only CLI and Streamlit UI use live DeepSeek decisions, reviewed 31 October
2026. A bounded two-turn integration smoke passed; broad quality remains unmeasured.

## Live UI boundary

The user supplied a local key and authorised replacing the mock application policy. The
runtime scripted module was removed. `ui.py` constructs DeepSeekPolicy from the explicit
project env file, then passes it to ChatService. The service requires a policy; there is no
implicit default/fallback. Only tests contain deterministic decision/HTTP fixtures.

`configuration.py` parses the two supported settings without shell evaluation or value
logging. Process settings take precedence. File secrets are not cached into os.environ.
The CLI retains its compatible `load_env` interface; UI/provider composition uses fresh file
resolution. Missing configuration disables the chat; provider errors stop a turn safely.
The adapter retains JSON mode, disabled thinking, output/timeout bounds and no hidden retries.

The existing ShoppingAgent owns validation, state commits, trusted search and recommendation
gates. Its default context is `shopping-baseline-v3-compact`: active requirement IDs and
predicates, concise dialogue, and all current candidates with facts, provenance and distinct
supporting text. Generated schema titles, presentation fields and repeated fact values are
omitted; omitted facts mean unknown. Candidate IDs/order and deterministic gates are retained.
SQLite opens per service request to avoid cross-thread connections.

The renderer reads persisted messages, product facts, state/history and real activity.
It shows API attempts and reported token usage, with missing usage explicit. Inspection and
widget reruns make no model request. New live chats use `data/ui-sessions/deepseek/`; historical
mock chats remain separate and untouched. Local shopper names are organisational labels,
not hosted authentication. Session UUID selection remains separate from transient widgets.

## Execution and responsibilities

A subsequent live watch conversation exposed a product-type vocabulary mismatch and a
final SEARCH request after search slots were exhausted. The executor stayed within its
bounds, but the user received `decision_budget_exhausted`. See the
[trace diagnosis and proposed remedies](reviews/watch-decision-budget-audit.md). Prompt
compaction is implemented separately; matching and exhausted-turn recovery remain unfixed,
with explicit expected-failure regressions. The earlier successful smoke does not establish
general reliability.

```text
CLI or Streamlit UI message + user/session/request IDs
  → SessionStore: owner check, writer lock, event replay
  → context builder: active state + recent dialogue + current search + budgets/feedback
  → decision policy: DeepSeek JSON proposal
  → trusted executor: schema/evidence/version checks, accepted state commit
      CLARIFY / RESPOND → assistant message → completed turn
      SEARCH → FTS5/BM25 + hard gates → actual result in next decision context
      RECOMMEND → inspected/current IDs + eligibility recheck → product cards
  → JSONL event history + rebuilt/updated snapshot
```

| Code | Responsibility |
| --- | --- |
| `src/shopping_agent/contracts.py` | Closed state/edit/action schemas |
| `src/shopping_agent/state.py` | ADD/REPLACE/RETRACT/NEW_GOAL, quoted evidence, history and simple conflicts |
| `src/shopping_agent/sessions.py` | User/session ownership, JSONL replay, snapshots and thread/process locks |
| `src/shopping_agent/retrieval.py` | ProductSearch interface, versioned index, literal queries, BM25 and constraint assessment |
| `src/shopping_agent/context.py` | Bounded prompt construction and current-search selection |
| `src/shopping_agent/provider.py` | DeepSeek transport, token limit, safe errors; no automatic retries |
| `src/shopping_agent/agent.py` | DecisionPolicy interface, bounded turn execution, validation, recommendations and tracing |
| `src/shopping_agent/cli.py` | CLI index/chat/inspect composition and explicit local environment loading |
| `src/shopping_agent/ui_service.py` | UI session boundary with mandatory policy injection and real agent/tool execution |
| `src/shopping_agent/configuration.py` | Shared explicit environment-file parsing; values never logged |
| `src/shopping_agent/ui.py`, `streamlit_app.py` | Optional Streamlit chat, product cards, session controls, state and activity views |

Policy, context construction, retrieval and storage are separate. Future guidance can enter
through context construction; future search implementations must keep tool contracts and
hard gates. These extension points do not constitute implemented experience/user memory.

## Data boundaries

- Catalogue: ignored `data/catalogue/catalog.jsonl`, image URL map and import manifest.
- Generated retrieval index: ignored `data/index/catalogue.sqlite`, separate from memory.
- CLI session data: ignored `data/sessions/<UUID>/events.jsonl` plus rebuildable `state.json`.
- UI session data: ignored `data/ui-sessions/deepseek/<UUID>/`; old mock histories are separate.
  Owner association does not automatically transfer facts into another session.
- Credentials: ignored local environment; never in prompts or authorization-header traces.
- No persistent user profile, agent-experience store, shopper simulator or scoring service.

The event log retains full conversation/action history and state-commit versions. The prompt
uses active requirements and at most twelve recent dialogue messages, with a 40,000-character
cap; older dialogue is trimmed first. Oversized essential context fails before a paid call.
Storage of old messages does not establish perfect conversational recall.

## Decision authority and limits

The model chooses clarification attributes/questions, lexical query terms, all/any matching,
result limit and eligible recommendation selection/order. Default turn bounds are three
model calls (including repairs) and two searches. Retrieval implementation and BM25 weights
are currently fixed. The model cannot execute SQL or edit code through an action.

Python enforces stored hard requirements, treats missing required fields as unknown, checks
correction IDs and state versions, and invalidates stale search evidence. Soft matches are
annotations available to the model; there is no separate automatic soft-preference reranker.
Recommendations use catalogue-backed cards and returned IDs. Schema/quote checks cannot
prove correct extraction of every user requirement; ordinary response text remains generated.

## Reliability boundaries

JSONL is authoritative; stale/corrupt snapshots are rebuilt. Malformed/truncated/inconsistent
logs fail closed and are preserved. Local POSIX locks allow one writer per session. Accepted
state changes can survive a failed/interrupted turn. Completed request IDs replay a stored
answer; incomplete IDs require inspection and a deliberate new request. Exactly-once remote
billing, hosted authentication and tamper-proof/transactional storage are not provided.

Metadata is sparse and historical. Exact prices, literal categories and explicit detail
fields cannot establish current availability or child-variant stock. Product content is
untrusted; model-level resistance to malicious instructions has not been established.
See [milestone evidence](milestone-1.md) and [decisions](decisions.md).
