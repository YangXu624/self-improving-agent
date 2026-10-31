# Current baseline architecture

Status: session-only CLI baseline plus mock Streamlit UI, reviewed 31 October 2026. Live provider
behaviour remains unverified. Future phases are in the [roadmap](roadmap.md).

## Phase 3 mock UI boundary

The user authorised a mock-first UI before the pending live Phase 2 acceptance/fixes.
`ui_service.py` now adapts the existing ShoppingAgent and SessionStore for a visual client;
`mock_policy.py` is an explicitly scripted DecisionPolicy, never a fallback for DeepSeek.
It selects IDs from actual search results, not canned products, and supports a limited set
of product types, USD upper budgets, colour/material preferences and explicit new goals.
No core validator, executor, retrieval or storage implementation was changed. SQLite opens
per request so a UI rerun thread never reuses another thread's connection. Persisted logs
are the conversation source of truth. `ui.py`/`streamlit_app.py` render those persisted
messages, product facts, active requirements/history and per-turn activity. No Streamlit
import enters the agent/tool/storage modules. The UI never loads credentials or selects a
live provider; policy injection keeps a later explicit provider swap local to composition.
Mock sessions default to `data/ui-sessions/mock/`, separate from CLI sessions. Local shopper
labels are organisational identity, not authentication. UI selection is distinct from transient
widget state so browser reruns cannot silently replace the active conversation UUID.

## Execution and responsibilities

```text
CLI or Streamlit UI message + user/session/request IDs
  → SessionStore: owner check, writer lock, event replay
  → context builder: active state + recent dialogue + current search + budgets/feedback
  → decision policy: DeepSeek JSON proposal (CLI) or scripted mock (UI)
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
| `src/shopping_agent/ui_service.py`, `mock_policy.py` | UI session boundary and explicit scripted demo decisions; real agent/tool execution |
| `src/shopping_agent/ui.py`, `streamlit_app.py` | Optional Streamlit chat, product cards, session controls, state and activity views |

Policy, context construction, retrieval and storage are separate. Future guidance can enter
through context construction; future search implementations must keep tool contracts and
hard gates. These extension points do not constitute implemented experience/user memory.

## Data boundaries

- Catalogue: ignored `data/catalogue/catalog.jsonl`, image URL map and import manifest.
- Generated retrieval index: ignored `data/index/catalogue.sqlite`, separate from memory.
- Session data: ignored `data/sessions/<UUID>/events.jsonl` plus rebuildable `state.json`.
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
