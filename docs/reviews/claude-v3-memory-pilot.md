# Claude V3 longitudinal memory pilot: partial run, no paired result

Date: 1 November 2026 (Asia/Singapore). Frozen implementation: `34b33db` from PR #26.
**The approved experiment was launched once and stopped automatically after its third OFF
session. Memory ON never started. There are zero completed OFF/ON pairs, so this run cannot
establish whether persistent user memory improves recommendation quality or efficiency.**

## Configuration and execution validity

The exact approved command from the readiness report ran with `--live` added. Four frozen
customers × three visits × OFF/ON = 24 planned sessions. The selected subset's SHA-256 is
`3dfc1344fb38483f595c151c192ac16bcce4a7a406ebbefae5b9e0af40ac30d4`.
Models: Claude `claude-sonnet-5-5` (between-tools thinking, low effort, output cap 512, no sampling
parameters); ASTRA `deepseek-flash`. Compact session/user-memory views, original 50k catalogue,
unchanged index/BM25/prompt/auditor/scoring, K=5, six shopper turns and 18 ASTRA calls/session.
Global caps: 432 DeepSeek calls, 285 remaining Claude attempts (three previous preflights
counted under 288 total), US$10 shared accounting ceiling with US$0.055158 carried forward.
All OFF timelines precede ON; session memory remains on, procedural experience is off.

The runner used new `live-24` output and fresh isolated condition stores. No runtime code,
criteria, scenario, product, evidence hash or prompt changed. No experiment restart occurred.
Shared configuration hash: `8aa6b6fe98171939f609f8b4417639b7588180e3f9d5f9a1a7759f3a33aa50a9`.

Observed stop: `session_error:simulator_failure`. The existing one-retry consistency allowance
was used for a single response; both attempts were rejected, then `--stop-on-error` halted the
whole run. The source counter named `consistency_retries` is 2 because it counts rejected
attempts, including the final rejection; **one actual retry call** occurred. There was no
automatic retry of a session or the experiment, no spending denial and no unknown-usage event
in the pilot. The failure was evaluated under the existing rules and remains invalid.

| Customer | OFF started / valid / planned | ON started / planned |
| --- | --- | --- |
| Capsule Wardrobe | 3 / 2 / 3 | 0 / 3 |
| Activewear | 0 / 0 / 3 | 0 / 3 |
| Footwear | 0 / 0 / 3 | 0 / 3 |
| Simple Jewelry | 0 / 0 / 3 | 0 / 3 |
| **Total** | **3 / 2 / 12** | **0 / 12** |

There are **21 unstarted sessions**. `summary.json` contains no within-timeline blocked visits
because the stop happened on the last Capsule visit; that empty list does not imply the other
21 planned sessions ran. They are identified by comparing the frozen plan with actual rows.

## OFF versus ON: available observations only

| Metric | OFF observations | ON observations |
| --- | --- | --- |
| Valid sessions | 2 (both unsuccessful) | Not run |
| Invalid sessions | 1/3 started | Not run |
| Success@5 | 0/2 valid; 0/3 all-started success outcomes | Not measured |
| nDCG@5 | No valid recommendation list; inherited aggregate imputes 0 | Not measured |
| Verified soft-preference satisfaction | No valid recommendation list | Not measured |
| Formal CLARIFY actions | 0 across all 3 started visits | Not measured |
| Retrieval calls | 18 total; 6 per started visit | Not measured |
| ASTRA conversation turns | 10 total: 3, 3, 4 | Not measured |
| DeepSeek calls | 28: 9, 9, 10 | None |
| Persistent memory writes / retrieval / injection | Disabled as designed, zero events | Not exercised |
| Confirmed disclosed hard compliance | 5/5 presented cards pass, all in invalid Visit 3 | Not measured |

The inherited aggregate gives no-recommendation/invalid sessions zero nDCG contribution, but
raw per-session nDCG is null for Visits 1–2 and absent for invalid Visit 3. Do not interpret the
aggregate's zero as a measured ranking of a valid list. Likewise, no recommendation is not
proof of constraint compliance. The five checked cards below are descriptive evidence from
the invalid visit, not a restored score or counted success.

### First versus returning visits

Visit 1: one OFF session, failed, 3 ASTRA turns, 6 searches, 9 DeepSeek and 4 Claude calls.
Visits 2–3: two OFF sessions, one failed and one invalid, 7 ASTRA turns, 12 searches,
19 DeepSeek and 10 Claude calls. No returning ON visit exists. The only valid returning
observation is Visit 2's failure, so no returning-customer memory effect can be estimated.

### Every planned visit

| Customer / visit | Category | OFF result | ON result |
| --- | --- | --- | --- |
| Capsule 1 | Active Shirts & Tees | Failure; shopper gave up, no recommendations | Unstarted |
| Capsule 2 | Active Hoodies | Failure; shopper gave up, no recommendations | Unstarted |
| Capsule 3 | Pants | Invalid; auditor rejected reference to a prior recommendation | Unstarted |
| Activewear 1 | Tanks Tops | Unstarted | Unstarted |
| Activewear 2 | Active Shirts & Tees | Unstarted | Unstarted |
| Activewear 3 | Pants | Unstarted | Unstarted |
| Footwear 1 | Cycling | Unstarted | Unstarted |
| Footwear 2 | Equestrian Sport Boots | Unstarted | Unstarted |
| Footwear 3 | Industrial & Construction Boots | Unstarted | Unstarted |
| Simple Jewelry 1 | Anklets | Unstarted | Unstarted |
| Simple Jewelry 2 | Necklaces | Unstarted | Unstarted |
| Simple Jewelry 3 | Bangle | Unstarted | Unstarted |

All three started visits have zero formal CLARIFY actions. Two clarification-like offer
questions appear inside RESPOND text; these are not CLARIFY actions under the existing metric.
No action labels or scoring definitions were changed to combine them.

## Actual dialogue and catalogue evidence

### Visit 1: category representation and repeated ineffective search

Shopper: “an everyday casual top, something like an active shirt or tee. Keeping it under $45.”
ASTRA stored `product_type in ["active shirt", "tee"]` and searched `active shirt tee`.
The first search found 123 lexical matches, all failed known constraints; zero verified
candidates were shown. Across the visit it made six searches, repeatedly using the same
queries with and without Black. The shopper asked to retain the budget and relax color,
then gave up after the third ASTRA response.

A frozen, independently verified compatible witness, `B08L5CNVZ6`, costs US$7.98, has Color
Black, and category `Active Shirts & Tees`. Running the **unchanged gate** on that real row with
ASTRA's captured filters rejects **only the product-type requirement**. The gate uses exact
category token containment: singular `shirt`/`tee` do not match plural `shirts`/`tees`.
This demonstrates a specific category-normalization problem. It does not prove that changing
that gate alone would retrieve the witness within the same BM25 candidate window.

When ASTRA said it could not search “right now,” it had actually run two searches earlier in
that turn and then used its terminal response. This wording is misleading across new turns;
the traces show fresh searches did execute. It is not evidence that retrieval was offline.

### Visit 2: category mismatch plus invalid correction reference

The shopper requested an active-style hoodie under US$110, Black if available. ASTRA stored
`product_type eq "hoodie"`. Six searches returned no verified candidates. The real compatible
witness `B09SS262CG`, US$103.99 and Black, belongs to `Active Hoodies`; the captured gate again
rejects only the singular category predicate. Broader lexical queries alone did not fix it.

After the shopper said Black was just a preference, ASTRA correctly retracted its soft color
record, but later tried to retract `preferences.color.0` again when that path no longer existed.
The validator rejected this with `invalid_current_state_reference`, exhausting that turn's
three-decision allowance. This is an ASTRA decision/edit failure, separate from the later
simulator audit failure. The shopper eventually gave up; this remains a valid failed session.

### Visit 3: over-hardening, recovery, then a false-positive invalidation

Opening: “comfortable casual pants, under $60. Black if you have it.” ASTRA made Black a
**hard** condition despite that conditional wording. `casual pants black` returned 340 lexical
matches, all with at least one unknown required attribute; zero eligible candidates. After
retracting the color condition at the shopper's request, `pants casual` yielded **73 eligible
products**, returning ten candidates. A stale `preferences.color.0` retraction again caused
one rejected decision and a `decision_budget_exhausted` turn. A subsequent turn successfully
presented five catalogue-grounded products.

| Presented product ID | Catalogue price | Frozen hard type/budget | Verified Black preference |
| --- | ---: | --- | --- |
| B0BBTK1FY5 | US$20.89 | Pass | Unknown |
| B0B1HFC9X7 | US$29.99 | Pass | Unknown |
| B0B3V4FWD2 | US$19.99 | Pass | Unknown |
| B09GVXYCCS | US$38.99 | Pass | Unknown |
| B0BDDXMB8G | US$27.99 | Pass | Unknown |

The independent raw oracle gives these products hard pass and soft-color unknown (grade 1
under the unchanged rubric). Success@5 ordinarily accepts any positive grade, so it does not
require verified Black satisfaction. **No session score was recomputed or promoted:** this
session's official result stays invalid. This table is a catalogue audit of actually shown
items, not a modified relevance rubric.

The shopper asked whether the last, US$27.99 quick-dry elastic-waist pants came in Black.
ASTRA correctly replied that color/variant availability was unverified, in a text-only RESPOND.
The shopper then said it would accept those pants and check color options itself.

The audit rejected both that reply and its bounded retry with:

- `price_not_in_profile: 27.99`
- `accepted_without_recommendation`

Both flags arise because [the V3 audit](../../src/astra_eval/shopper_v3.py#L263) uses only the
**current** assistant view's cards/prices. The immediately previous RESPOND had no cards;
the authentic earlier recommendation was ignored. The prior US$27.99 card is preserved in
the transcript and Claude's actual input/history. Re-running the unchanged price checker with
those actual previously shown prices removes the price error for both rejected messages.
The acceptance guard independently rejects because `view.products` is empty.

This is a reproduced **session-offer context defect in the audit/guard**, not a Claude API
failure or invented price/product. All 14 Claude calls returned complete JSON with `end_turn`.
The shopper's two earlier give-ups were allowed lifecycle decisions after repeated failures,
not malformed replies. No general conclusion about Claude's simulator reliability follows.

## Memory lifecycle: what was and was not tested

Accepted shopper dialogue disclosed Black in each started visit. For example, Visit 1 said
“ideally in black,” Visit 2 opened “Black if you have it,” and Visit 3 did the same. These
statements establish a current-session preference. They do **not** explicitly say a durable
cross-visit habit such as “I usually prefer Black clothing”; that distinction matters for
future learning-opportunity analysis. V3 is free to choose such wording rather than being
forced to emit a persistent-preference template.

| Returning task(s) | Disclosed current preference | Persisted / retrieved / injected | Search / recommendation |
| --- | --- | --- | --- |
| Capsule 2 OFF | Yes, conditional Black preference | Disabled by condition | 6 searches; no recommendation |
| Capsule 3 OFF | Yes, conditional Black preference | Disabled by condition | 6 searches; 5 cards; session invalid |
| Capsule 2–3 ON | Unobserved | Unobserved | Unstarted |
| Other customers' Visits 2–3, both arms | Unobserved | Unobserved | Unstarted |

There are no profile files, memory-selection/injection/update events or observed memory
application. OFF's absence of writes is expected, **not a persistence bug**. ON did not get a
learning opportunity because it never ran; we cannot infer whether it would have stored these
preferences or needed clarification about their scope/stability. No example of memory helping,
being ignored or being incorrectly applied exists in this run. The pants recovery reflects a
session-state correction, not persistent memory or experiential learning.

Actual input inspection found no condition labels, target/witness IDs, scoring fields or future
visits in any of the 14 Claude model payloads. Prior-visit history lengths were 0 for Visit 1,
1 for Visit 2 and 2 for Visit 3, consistent with the isolated same-customer OFF timeline. All
28 hydrated ASTRA request contexts lack the private persona/verified-needs/ground-truth fields
checked. Cross-condition history isolation has no live ON observation in this partial run.

## Tokens, latency and costs

| Provider | Actual calls | Input tokens | Output tokens | Cache input | Frozen-rate estimate |
| --- | ---: | ---: | ---: | --- | ---: |
| Claude | 14 | 27,041 | 805 | 0 read / 0 creation | US$0.062132 |
| DeepSeek | 28 | 65,588 | 2,693 | 43,904 hit / 21,684 miss | US$0.010000224 |
| **Pilot total** | **42** | **92,629** | **3,498** | — | **US$0.072132224** |

The immutable shared ledger ends at **US$0.127290224 accounted**: this pilot plus prior known
US$0.005158 smoke expense and the prior failed-request **US$0.05 unresolved allowance**. Known
usage-derived estimates across successful calls total US$0.077290224. The US$10 ceiling was
not approached. No pilot usage was missing; all 42 reservations settled, with no cost denial
or cost-bound breach. Generic historical failure-accounting warnings remain in the saved result;
the new provider/cost journals supply the actual complete attempt/usage record for this run.

These are estimates from actual reported tokens at the **unchanged conservative ledger rates**,
not provider invoices. DeepSeek rates use the peak-price upper estimate even where actual
billing qualifies for a lower rate; taxes/account activity are not observed. The failed earlier
preflight's actual billed cost remains unknown and is not assumed zero.

Per-session total DeepSeek+Claude input/output: Visit 1 **22,012 / 1,015**, Visit 2
**24,365 / 1,077**, Visit 3 **46,252 / 1,406**. Provider latency totals: Claude **30.495s**;
DeepSeek model time **34.671s**; ASTRA wall time including local work **35.453s**. No successful
recommendation efficiency or ON/OFF cost difference can be measured from these partial data.

## Preserved results and next steps

Complete live outputs remain under:

`data/eval/longitudinal/claude-sonnet55-readiness-20261101/live-24/`

Sibling journals: `live-24.shopper-v3.jsonl`, `live-24.api-cost.jsonl`. The run directory contains
frozen inputs/config, raw event histories/state snapshots, transcripts, per-session traces and
scores, summary and the existing report. Read-only diagnostics, lifecycle observations and
protected before/after manifests are in sibling `pilot-analysis/`. The original failed pilot,
PR #25 preflight and PR #26 smoke remain intact. No secrets or raw data are committed.

Recommended priority before any new paid attempt:

1. **Fix and independently test session-level offer grounding in the shopper audit.** Accepting
   or discussing a previously presented product after a text-only follow-up must use its
   authentic prior card/price. Keep rejection of never-presented products and isolate session,
   goal and customer boundaries. This is the immediate blocker to a valid memory experiment.
2. Verify ordinary singular/plural category handling against catalogue labels, without
   hardcoding these witness IDs or assuming embeddings are required. Separately test that
   “if you have it” stays soft and that already-removed state paths are not edited again.
3. Only after deterministic checks and explicit approval, launch a **new** controlled run
   using unchanged scoring/ground truth and both arms. Preserve this failure and carry forward
   spending/attempts. Do not silently resume or rerun the stopped experiment.

No implementation fix, score rewrite, paid restart or automatic merge was performed. The
scientifically defensible conclusion is **insufficient paired evidence**, with specific
baseline and harness defects diagnosed for a focused next checkpoint.

Integrity check: all **294** pre-existing protected artifact hashes match before/after.
Canonical inventory SHA-256: `c40a874de3ed1d81a0e61c76365e734badc1788281b2b4276974cfd3e5ae9798`.
