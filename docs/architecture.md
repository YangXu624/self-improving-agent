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
gates. Its memory-OFF context is `shopping-baseline-v5-experience`: active requirement IDs and
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

A live watch conversation exposed a product-type vocabulary mismatch and a final SEARCH
after search slots were exhausted; see the
[trace diagnosis](reviews/watch-decision-budget-audit.md). The exhausted-search case is
now closed: when the last permitted decision is a SEARCH that cannot execute
(`search_budget_exhausted` or `search_requires_a_remaining_decision_call`) the executor
appends `turn_closed_safely` and returns `status=ok`, `action=RESPOND`, no products, a fixed
message and a `closure` code. No extra call or search is made; other failures (schema
errors, conflicts, provider errors) still end as `turn_failed`. If calls remain, the model
may still repair its decision. Product-type vocabulary matching remains unfixed, with two
expected-failure regressions. The earlier successful smoke does not establish reliability.

Evidence edits require a nonblank quote contained in the current message (`state.py`).
`state.conflicts` now uses the gate's semantics: department aliases are normalised, and
product-type requirements conflict only when category token containment cannot be
satisfied (`state.type_conflict`). Detection stays conservative; oversized cases are not
flagged. The alias table is duplicated in `state.py` so the frozen `retrieval.py` baseline is
unchanged; a test pins both tables together.

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
| `src/shopping_agent/event_codec.py` | Lossless compact disk records; expands to canonical events before replay/presentation |
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
hard gates. Procedural experience now uses these seams; persistent user memory remains deferred.

## Card profiles and visibility receipts (Experiment A)

`cards.py` defines reversible presentation profiles over the unchanged BM25 result:
`baseline` (default; all IDs, byte-identical prompt to before), `v3_k10`, `v3_k5`,
`shared_k10`, `shared_k5`. K is a prefix of the same ranked list; "shared" interns repeated
category/source maps into headers and decodes exactly to the v3 cards. `context.py` binds
each decision to the serialized, model-visible set through a `VisibilityReceipt` (search,
state and catalogue versions, visible IDs, projection and semantic hashes);
`agent.verified_products` recommends only receipt-visible, current, eligible IDs. The
receipt and profile name are recorded on `model_request` events. Custom `context_builder`s
that return plain messages still work. `retrieval.py` and ranking are unchanged; profiles
are selected by `--cards-profile` / `ASTRA_CARDS_PROFILE` (default `baseline`). The provider
trace now also records the returned model name and prompt-cache token counts.
`experiments/experiment_a/` holds the offline/live/replay runner and the report; it is not
imported by the application.

## Data boundaries

- Catalogue: ignored `data/catalogue/catalog.jsonl`, image URL map and import manifest.
- Generated retrieval index: ignored `data/index/catalogue.sqlite`, separate from memory.
- CLI session data: ignored `data/sessions/<UUID>/events.jsonl` plus rebuildable `state.json`.
- UI session data: ignored `data/ui-sessions/deepseek/<UUID>/`; old mock histories are separate.
  Owner association does not automatically transfer facts into another session.
- Credentials: ignored local environment; never in prompts or authorization-header traces.
- Persistent user profiles remain deferred. Procedural lessons use a separate local SQLite
  experience store and content-hashed snapshot files. The simulated-shopper evaluation lives
  in a separate package, `astra_eval` (see [its documentation](simulated-shopper-evaluation.md));
  the application never imports it and it never feeds the agent anything but the shopper's messages.

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

### Asked and disclosed attribute working memory

`shopping_agent.attributes` projects executed CLARIFY responses, user-message evidence and
active requirements into current-goal asked/disclosed ledgers. Values, exclusions and
corrections retain authoritative requirement IDs; the model never maintains another value
store. Narrow deterministic response patterns record declined/no-preference/uncertain
answers, explicit currencies and direct width answers. Bare `$` does not establish currency.
This is not a general natural-language verifier: other confirmed values still require validated
requirement extraction by the decision policy.

The snapshot caches `attribute_ledger` separately from `ShoppingState`; full canonical events
rebuild it on reopen. Existing state schema 1 and storage codec versions remain readable.
Question-only changes do not increment requirement versions or invalidate search results.
NEW_GOAL scopes both ledgers to the current goal, including its initiating user message.
Compact working context references active requirements instead of repeating their values.
The prompt is `shopping-baseline-v4-attributes`; old prompts/events are retained unchanged.

CLARIFY uses separate `size`, `width`, `price`, `currency`, `product_type` and
`product_subtype` attributes. Resolved exact attributes are rejected after current edits;
unanswered, conflicting, incomplete or explicitly uncertain/reopened attributes remain
available. Repeated rejected questions end in a bounded product-free RESPOND closure.
The original watch-taxonomy failures remain; subtype clarification does not repair retrieval.
Confirmed non-USD budgets are recorded but never converted implicitly: SEARCH/RECOMMEND
with an active hard price limit require a USD budget, otherwise validation rejects the action
and a bounded product-free closure explains the limitation.

## Experiential-memory self-improvement subsystem

`shopping_agent.experience` provides the first vertical slice of experiential self-improvement:
1. **Lesson Lifecycle and Storage:** Managed in SQLite (`ExperienceStore`), distinguishing:
   - Observed outcome (what occurred in the trace)
   - Hypothesized failure cause (why it occurred)
   - Proposed procedural directive (concise, actionable advice bounded to $\le 400$ characters)
   - Verifiable action signature (observable structural criteria such as `token_mode`, `query_contains`, `attribute_in`, `min_products`)
   - Supporting evidence (source session, turn, and split)
   - Lifecycle status: `candidate` (raw extractions; never retrieved), `confirmed` / `active` (human-confirmed), `superseded` (versioned replacement), `rejected`, and `retracted` (historical record preserved without retrieval).
2. **Contamination Guard:** `validate_lesson` enforces that lessons only originate from the `learning` split. It systematically rejects ASIN patterns (`B0...`), product IDs, target product titles from evaluation ground truth, and prompt injection patterns.
3. **Retrieval and Context Injection:** Lessons are retrieved primarily by generalizable behavioral decision triggers (`initial_query`, `empty_search_recovery`, `recommend_cutoff`, `attribute_clarification`) rather than exact product-family matches. Context cues (`searches`, `calls`, `has_search`, `candidate_count`) match trigger conditions. Guidance is injected bounded into `procedural_guidance` in the decision context.
4. **Observable Application and Audit:** `ShoppingAgent` logs:
   - Retrieved lesson IDs (`retrieved_experience`)
   - Injected lesson IDs (`injected_experience`)
   - Applied lesson IDs (`applied_experience`), verified by `verify_decision_application` against the emitted decision's concrete action and signature.
   The session event log records `experience_audit` events and exposes experience tracking on `AgentTurn`, `SessionRecord`, and `results.jsonl`.
5. **Frozen Snapshots and Evaluation:** Active lessons can be frozen into an immutable, content-hashed `ExperienceSnapshot`. The evaluation harness executes paired conditions (`memory_off` vs `memory_on`) under identical task budgets and models via `experiential_agent_factory` and `--experience-snapshot`.

## Focused experience integrity

See [the checkpoint and pilot protocol](experience-pilot.md). Category-only opening cues use
read-only documented category metadata and the current goal's canonical event timeline; an
explicit reset can provisionally scope guidance but cannot retire committed requirements.
No extra model call classifies the opening. Actual policy payloads establish injection; only
accepted, signature-matching actions establish application. Reviewed lesson records cannot
be changed by candidate insertion. New recommendation events snapshot active hard state so
independent per-presentation compliance is separate from hidden-target-profile mismatches.
Historical snapshots missing this evidence are unknown; extraction completeness is not proved.

## Persistent user profiles (Stage 1)

`user_memory.py` adds a separate per-user Markdown store with evidence-linked proposals,
atomic updates, explicit corrections/withdrawals and bounded relevance selection. See
[user-memory.md](user-memory.md) for storage authority, validation limits and checkpoint status.
It reuses existing user/session identities and does not replace session or procedural memory.
The normal CLI/UI can opt in; the evaluator remains OFF. Enabled context uses
`shopping-baseline-v6-user-memory` and an enabled-only `MemoryDecision` contract. Memory
selection, actual prompt inclusion and profile writes/rejections are traced independently.
Current hard state remains authoritative; recalled profile records are advisory, not filters.
The external LLM learner and returning-customer evaluator remain future work.
