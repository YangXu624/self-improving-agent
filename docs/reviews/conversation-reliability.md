# Conversation reliability hardening

This pass addresses workflow failures across boundaries, not just isolated unit behavior.
No API calls, paid pilot restart, scorer changes, frozen data edits or automatic merge occurred.
Historical runs keep their original invalid/failure labels. Source baseline is PR #27 (`c1a9b42`).

## Failure taxonomy and root causes

| Layer / failure | Root cause | Fix / observable behavior | Regression evidence |
| --- | --- | --- | --- |
| V3 false invalidation after follow-up | Acceptance and price checks saw only the latest assistant cards | Accepted RECOMMEND offers from the current session/goal remain eligible evidence after text-only messages; audit records scoped offer IDs | `test_pr27_accept_previous_offer_after_text_only_followup`; full compact search/recommend/follow-up/accept lifecycle |
| Phantom, foreign or old-goal offer | Conversation history is not equivalent to a current presented offer | Search-only results and prior visits/conditions/customers are excluded; bound memory cannot be swapped; unseen prices/IDs and explicit unsupported item references fail | Offer history tests for each boundary, including invented same-price product reference |
| Singular category rejected | Exact tokens reject `hoodie` against `Hoodies`, `shirt` against `Shirts` | Bounded English number-inflection matching applies only to category predicates and category-conflict validation | Actual local taxonomy inventory test; synthetic positive/negative category cases; watch regression now passes |
| Repeated empty tool work | No semantic request deduplication across decision calls/turns | Logical request fingerprint includes catalogue/strategy, query token set/mode, goal and active predicates; identical empty search is not re-executed | Permuted query returns one actual search, terminal safe closure; changed budget permits a fresh successful search |
| Conditional preference hardened | Model chooses hard strength despite quoted availability condition | Deterministic state validation rejects hard color updates for conditional wording; explicit hard language remains hard | Hard proposal rejected, soft repair accepted within the compact loop; quote-shortening test checks current utterance context |
| Stale state path aborts valid terminal action | Model retracts an attribute already removed from the visible state | Narrow, evidence-backed no-op for an absent index-zero field with a current-goal retracted tombstone; original reply and ignored retraction stay traced | Compact preference/correction/search/stale retraction/recommend lifecycle; unknown/live/old-goal/REPLACE references remain guarded |
| One bad dialogue cancels independent timelines | `stop_on_error` treated all invalidity as global infrastructure failure | Isolated invalid session blocks its dependent timeline; independent customer/condition timelines continue; systematic failures/resources still stop globally | Two-customer OFF-then-ON test; repeated-fault threshold; immediate accounting stop |
| Test count without lifecycle coverage | Components passed separately while cross-turn context/paths diverged | Real session files, compact contexts, BM25, V3 policy/audit and longitudinal memory runner exercised together with scripted model outputs | 22-test integration suite, live network access explicitly blocked |

## Implementation boundaries

### Offer verification

`AutonomousShopper` binds a session to its actual `ShopperMemory` object. The runner records
ASTRA's real goal epoch with each assistant transcript entry. Only accepted RECOMMEND cards
in that epoch, plus the trusted current presented view, supply offer evidence. Owner/condition
history remains available for roleplay but never authorizes acceptance in a fresh session.
After a text-only follow-up, the model also receives at most five sanitized previously shown
options from that scope; the model and verifier use the same offer-history helper. This avoids
making acceptance depend on the model reconstructing cards from its own earlier prose.
Prompt-context version is `autonomous-shopper-prompt-2-offer-context`; offer-audit version is
`session-offers-2`. The roleplay system instructions and independent scoring are unchanged.
Prices still must be present in authentic cards/profile; invented identifiers remain rejected.
Explicit acceptance descriptions without any meaningful overlap with a shown title are rejected;
generic “the first option” remains possible. This is a bounded lexical reference check, not a
general proof of free-form identity. Synonyms may still need review.

The PR #27 failure pattern uses the actual US$27.99 wording with synthetic IDs in portable
fixtures. It passes both a direct scoped audit and the complete compact conversation. Original
saved transcripts, product IDs and official invalid scores were not rewritten.

### Category and search behavior

New `category_matching.py` implements limited number morphology, not semantic search or a
category synonym framework. FTS5/BM25 and the frozen index remain unchanged. The search trace
records `category_match_version: number-inflection-v2`; query/eligibility behavior changes are
therefore distinguishable from old results. Color/brand/keyword/price predicates retain their
literal semantics. Category conflict checks use the same number matching, while the independent
scoring oracle is deliberately unchanged.

A read-only replay of the original captured filters against the three genuine witnesses gave:

| Original task | Old gate eligibility | New gate eligibility |
| --- | --- | --- |
| Capsule Wardrobe 1 | false | true |
| Capsule Wardrobe 2 | false | true |
| Capsule Wardrobe 3 | true | true |

This verifies the category mismatch repair only. It does not establish BM25 recall, ranking,
recovery of these products in live candidate windows or an improvement in recommendation scores.
No production logic contains benchmark witness IDs.

Empty-search deduplication preserves another attempt when predicates, query/mode, goal or
catalogue strategy change. New quotes/UUIDs/versions alone do not make an identical logical
request useful. The model can change its query, clarify or respond. If it insists on the same
empty search through its bounded decision allowance, the turn closes safely without products;
the evaluator records `search_stalled` rather than spending more shopper turns on that loop.
No cached candidates authorize a recommendation after a state change.

### State validation and correction

The color guard reads the relevant current-utterance clauses, including when a model quotes
only “Black.” Conditional words such as “if you have it,” “ideally” and “preference” cannot
silently become a hard color requirement. Explicit “must/required/only” language remains hard.
The model receives the validation error and must propose a valid soft correction. It is not
silently rewritten, and ignoring feedback can still exhaust the bounded decision budget.

A redundant RETRACT is ignored only when: its field is already absent; a retracted record is
from the current goal; the current user message supports the quote; and it is an index-zero
compact field reference. It never rebinds to another live record or repairs REPLACE, unknown
attributes, old-goal records or unsupported evidence. `redundant_retraction_ignored` explains
the no-op in the authoritative session log. Accepted state version need not change. The original
model response is retained, so proposal normalization remains inspectable.

## End-to-end integration suite

Run without any live provider:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_conversation_reliability.py' -v
```

The suite has **22 distinct tests** (no inherited duplicate test collection). Both urllib and
ASTRA's imported DeepSeek network entry point are patched to fail immediately if called.
Synthetic catalogue/model fixtures drive real deterministic tools and persistence.

Covered complete lifecycles:

1. Compact search → catalogue-grounded recommend → text-only follow-up → accept prior item.
2. Clarification → user supplies budget → validated state → search/recommend/accept.
3. Hard conditional color proposal rejected → soft repair → recommendation → color withdrawn
   → new search → redundant retraction ignored → accepted current recommendation.
4. Repeated empty searches → one actual tool execution → bounded graceful termination.
5. Empty search → revised budget → fresh search allowed → successful recommendation.
6. Invalid shopper utterance → one bounded retry → corrected opening → real recommendation.
7. Returning-customer compact timeline → quoted preference stored → new session → records
   retrieved/injected → scripted policy ranks matching real candidates → independent target check.
8. Separate users/conditions start empty, session UUIDs remain distinct, ASTRA does not receive
   persona/future-change fields. Earlier V3 private-view tests continue checking future/target
   fields and condition labels. No private evaluator target ID is used by the ranking policy.
9. Isolated invalid timeline blocks later dependent visits without cancelling the independent
   customer's complete OFF/ON timeline. Repeated failures and infrastructure faults still stop.

The memory integration demonstrates the mechanism's complete data flow under a scripted
policy. It is **not** measured evidence that DeepSeek applies memory reliably or that memory
improves real recommendations. Those remain live empirical questions.

## Revised stopping contract

All started sessions retain existing scoring/validity labels and full trace. No invalid session
is converted to success. New result field `failure_scope` and plan version
`isolated-timeline-global-infrastructure-v2` explain orchestration decisions.

| Failure class | Scope and consequence |
| --- | --- |
| One malformed/inconsistent shopper or refused/incomplete response with reliable accounting | Invalid session; block later visits in that customer/condition timeline because causal history is incomplete; continue independent timelines |
| Consecutive simulator-invalid timelines | Global stop at configured `max_consecutive_simulator_failures` (default 3); a non-simulator-invalid result resets the counter |
| Provider connectivity/authentication/API failure | Immediate global stop |
| Unknown/unreliable billing, cost/attempt/global call cap | Immediate global stop; retain uncertain reservations |
| Harness integrity, bound-session mismatch, unexpected agent exception | Immediate global stop |
| Recommendation failure, bad search strategy, per-turn decision exhaustion | Preserve agent-quality failure; do not relabel as simulator success or cancel unrelated customers |

The legacy `--stop-on-error` flag remains accepted for command compatibility; it no longer
means “cancel every independent customer after any invalid dialogue.” Infrastructure always
stops, even without the flag. The explicit threshold can be configured, including 1 for an
intentionally strict run. OFF-then-ON order and chronological visits are preserved. Independent
ON timelines may run when a customer's OFF timeline is invalid, but cannot become a valid paired
comparison merely because both have output files; reports must retain invalid/incomplete pairs.

## Verification actually executed

- Conversation reliability suite: **22 passed**, including the installed 50k catalogue taxonomy
  check. This test skips explicitly if the catalogue is absent on another machine.
- Full suite: **630 run: 628 ordinary passes, 1 missing-tokenizer skip, 1 remaining expected
  compound-wristwatch vocabulary failure**. The singular-watch expected failure was removed
  only after its assertion passed under the new matching behavior.
- `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `git diff --check`:
  passed. The final run includes all acceptance-boundary and lifecycle regressions.
- Offline replay of historical captured gate predicates: first two valid witnesses change
  from rejected to eligible; original scores and logs untouched.
- **329 protected data/experiment files** match before/after hashes. Canonical inventory SHA-256:
  `84f6920c447f6cd5b5dd606bcbd87107a68f96f7b1e759f0ef76fbf8676b20bf`.
- No paid/live request, dataset or ground-truth modification, secret inspection, dependency
  installation, score rewrite, lesson approval or memory-learning experiment occurred.

## Readiness decision

**GO for deterministic local workflow validation and code review. NO-GO for an unattended full
paid pilot or any claim of demonstrated memory improvement.**

The known historical failures now have regressions at the boundary where they occurred, and
independent timelines no longer vanish after an isolated bad dialogue. This meaningfully
improves the test evidence over merely adding isolated schema checks. It still does not prove
a live LLM will choose productive queries, repair a rejected edit, use memory, or avoid new
language the bounded auditor cannot recognize.

Remaining limits: compound taxonomy terms (the explicit wristwatch expected failure), English
morphology ambiguity, lexical offer-reference/attribute-audit false positives and false negatives,
conditional-language ambiguity, only narrowly justified redundant edits normalized, and unknown
live simulator/ASTRA error rates. The scorer's existing Success@K admits a hard-compatible
item even without verified soft preference satisfaction; keep soft outcomes separately visible.
No change to that metric is included.

Recommended next gate after human review: a separately approved small live canary across
independent categories, exercising recommendation/follow-up/accept and returning-memory use,
with the same scoring, complete traces, frozen settings and explicit money/call caps. Assess
invalidity and stop scopes before considering a fresh 24-session run. Preserve all earlier
pilots; do not resume them silently. No paid canary is authorized or started by this pass.

Verification logs and protected before/after manifests are preserved locally under
`data/eval/reliability-hardening-20261101/` (ignored by Git). They include the actual full-suite
and integration outputs and the read-only taxonomy replay. No simulated live run or replacement
score report was generated.
