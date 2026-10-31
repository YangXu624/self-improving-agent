# Live watch failure: diagnosis before implementation

Reviewed 31 October 2026 against `aa62f66155ae671821b44ef5ad3dc27dc698a9ba`
(merged live-DeepSeek implementation; runtime source identical to `239b406`).
**No production fix, budget increase, retrieval change or new live model request was made.**
This checkpoint adds diagnostics and synthetic regression tests only. Proposed fixes below
require review; three correctness regressions remain explicitly expected failures.

## Evidence and conclusion

Authorized local session:
`data/ui-sessions/deepseek/2419651698a1407390cec082dee0efc7/events.jsonl`.
It contains 43 events. Event sequence numbers equal one-based JSONL line numbers. Its
SHA-256 is `25230b24d21a9f9ca738efe8dba99ea7af9a010020cdf67d69557754ea5dd029`;
the original log was verified byte-for-byte unchanged. Neither reviewer opened the original
through SessionStore. Raw traces, catalogue rows, indexes and credentials are not committed.

**Primary retrieval failure:** natural-language product type is treated as literal category
tokens. `watch` misses `Watches` and admits `Watch Accessories`; `wristwatch` misses the
two-token category `Wrist Watches`. Broadening the query cannot overcome that unchanged
hard eligibility predicate. See [retrieval.py:202](../../src/shopping_agent/retrieval.py#L202),
[retrieval.py:222](../../src/shopping_agent/retrieval.py#L222) and
[retrieval.py:233](../../src/shopping_agent/retrieval.py#L233).

**Immediate turn failure:** the final model decision repeats SEARCH with zero searches
remaining. The executor correctly rejects it as `search_budget_exhausted`; no calls remain
to repair the decision, so the outer error becomes `decision_budget_exhausted`.
See [agent.py:78](../../src/shopping_agent/agent.py#L78),
[agent.py:160](../../src/shopping_agent/agent.py#L160) and
[agent.py:277](../../src/shopping_agent/agent.py#L277).

All six responses passed the Decision schema and state validation. All finished with
`finish_reason=stop`. There were no schema rejections, transport errors, hidden repair
retries, state conflicts, unknown-price failures or recommendations in this session.
These were three distinct decision calls per turn, rather than three retries of one request.
The accepted correction persisted correctly, with the original type superseded and the
soft recipient `dad` retained. The UI is reporting the underlying executor outcome.

## Every decision and executed search

Queries below are literal strings. `all` means AND, `any` means OR. Each SEARCH requested
limit 10. Counts include all scanned lexical rows, not only the candidates shown to the model.
Model reasons are summarized here; the exact recorded JSON remains in the cited local log.

| Turn/call | Decision, state changes and stated reason | Actual result | Log lines |
| --- | --- | --- | --- |
| 1/1 | SEARCH `watch`, all. ADD hard `product_type eq watch`; ADD soft `recipient eq dad`. Reason: type appears clear; recipient is contextual. | 1,738 lexical; 1,199 fail hard filter; 539 eligible; 10 visible accessories. | request 4, response 5, commit 7, result 9 |
| 1/2 | SEARCH `watch men wristwatch`, all, no updates. Reason: prior results were accessories; refine toward actual watches. | 72 lexical; 71 fail; 1 eligible/visible, a display case. | request 11, response 12, result 15 |
| 1/3 | CLARIFY product_type, no updates. Reason: visible result is not wearable. | Asks: “Just to confirm — are you looking for an actual wristwatch to wear, or a watch accessory like a display case or storage box?” Completes. | request 17, response 18, assistant 20 |
| 2/1 | SEARCH `wristwatch`, all. REPLACE hard type `watch` with `wristwatch`. Reason: user confirmed wearable product. | 113 lexical; all 113 fail type filter; zero eligible/candidates. State version becomes 2. | request 24, response 25, commit 27, result 29 |
| 2/2 | SEARCH `watch wristwatch`, any, no updates. Reason: broaden related tokens while preserving confirmed hard type. | 1,741 lexical; all 1,741 fail type filter; zero eligible/candidates. | request 31, response 32, result 35 |
| 2/3 | SEARCH `watch wristwatch`, any, no updates. Reason: search with confirmed hard type. This duplicates call 2/2. | **Not executed.** Prompt already says `model_calls=1, searches=0`. Rejected as `search_budget_exhausted`, then failed as `decision_budget_exhausted`. | request 37, response 38, rejection 40, failure 41, assistant 42 |

The only rejected action is turn 2/call 3. `decision_validated` records schema/state validity
before executor action checks; it does not mean a tool action executed. The last proposed
SEARCH therefore has a validated-decision event but no tool call/result.
See [agent.py:126](../../src/shopping_agent/agent.py#L126).

### Every candidate actually returned to the model

First search ID `bb433a0536814ca5a5de67f9293b9330`:

| Rank | Product ID | Title abbreviated for readability | Catalogue subtype |
| --- | --- | --- | --- |
| 1 | B08QCNXZ95 | Watch Box Organizer, 12 Compartments | Cabinets & Cases |
| 2 | B01M16LHXS | Dowswin Watch Back replacement tool kit | Repair Tools & Kits |
| 3 | B07333TX5X | Watch Repair Tools Kit Professional Spring Bar Tool Set | Repair Tools & Kits |
| 4 | B09PDDZJG9 | 12-Slot Watch Box, Portable Zip Watch Storage | Cabinets & Cases |
| 5 | B08FXQDLBD | Watch Hand Pusher, Multi Sizes Set | Repair Tools & Kits |
| 6 | B07L9YXT9Q | Replacement 12mm Silicone Rubber Watch Strap for Swatch | Watch Bands |
| 7 | B07T87P421 | Kalawen Automatic Double Watch Winder Box | Watch Winders |
| 8 | B09TVGYB5Y | Pack of 2 Zipper Travel Watch Cases | Cabinets & Cases |
| 9 | B07B9SKX9N | WOCCI 20mm Suede Leather Watch Strap | Watch Bands |
| 10 | B00F0FT5G0 | Danibos Watch Repair Tool Set | Repair Tools & Kits |

Second search ID `3a96158b7c56439fa0b5528a3b565d44`: its sole candidate is
`B075J257N5`, “LANSCOERY Watch Box Single Slot PU Leather Wristwatch Display Case Bracelet
Jewelry Holder Storage Organizer with Cushion for Men Women (Black)”, categorized under
Watch Accessories / Cabinets & Cases.

Third search ID `47371349d06f4e769bc79d0260f32de5` and fourth search ID
`95aca89b551f429ea004349763d1fee0` both return empty candidate lists. The failed duplicate
has no search ID. No accessory was recommended: the model rejected the first turn's poor
candidates and the executor kept second-turn failed candidates out of the context.

## Catalogue and BM25 verification

QA recomputed all four recorded searches against the existing **read-only** index with
their recorded committed states. Counts **and candidate IDs** matched every original result.
Catalogue hash: `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`.

- **1,034** records have the category node `Wrist Watches`.
- Category ancestry contains exact token `watch` in 539 records, `watches` in 1,186,
  and `wristwatch` in **zero**.
- With no hard type filter, BM25 query `watch` places an actual wristwatch **first**;
  `wristwatch` places actual wristwatches **first through third**. Of the latter's 113
  lexical matches, 105 have the `Wrist Watches` category node.
- A synthetic catalogue independently demonstrates: type `watch` permits box and band;
  `watches` permits wearable and band; `wristwatch` permits nothing; `wrist watches`
  permits the wearable only.

Thus absence of watches, candidate limit 10, BM25 rank order and missing prices do not explain
this incident. Product-type semantics remove correctly ranked products. Adding embeddings
would not repair an unchanged hard gate. Blindly replacing `watch` with `watches` also does
not solve accessory exclusion because bands inherit a `Watches` ancestor. Source categories
establish retrieval evidence, not stock, authenticity or current variant availability.

FTS population is at [retrieval.py:169](../../src/shopping_agent/retrieval.py#L169),
query tokenization/ranking at [retrieval.py:313](../../src/shopping_agent/retrieval.py#L313),
and hard filtering before the candidate limit at
[retrieval.py:336](../../src/shopping_agent/retrieval.py#L336).

## Input-token accounting

API totals exactly reproduce the UI: first turn **11,100 input / 348 output**;
second turn **8,600 input / 298 output**. No new model request was needed to obtain these.

The saved exact message strings were encoded offline using DeepSeek's published
[V4 tokenizer](https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip), linked from its
[token-usage documentation](https://api-docs.deepseek.com/quick_start/token_usage/).
`tokenizer.json` SHA-256:
`89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614`.
Audit-only `tokenizers==0.23.3` was installed under `/tmp`; application dependencies were
unchanged. No remote tokenizer code or transformers model was executed.

Component attribution uses each token's first character offset in the actual serialized
system/user strings. Separators and cross-component boundary tokens follow that convention.
Encoded message content is consistently **27 tokens below the API input count per call**;
this residual is reported separately. It may include server framing or other provider
processing; the trace does not expose its internals. Local component counts are reproducible
measurements under this tokenizer/convention, not provider-supplied per-field billing data.
The API totals remain authoritative, including any provider cache accounting not stored here.

| Input component | Turn 1 | Turn 2 |
| --- | ---: | ---: |
| System instructions | 1,905 | 1,905 |
| Decision JSON schema, example and system separators | 3,813 | 3,813 |
| Structured state, current message and recent dialogue | 611 | 1,338 |
| Latest search result, including candidates/filter metadata | 4,485 | 1,259 |
| Budgets, feedback, flags, prompt version and JSON field envelope | 205 | 204 |
| Unattributed API difference, 27 per call | 81 | 81 |
| **API-reported total** | **11,100** | **8,600** |

| Turn/call | Instructions | Schema/example | Session | Search | Other | Residual | API input / output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1/1 | 635 | 1,271 | 59 | 1 | 69 | 27 | 2,062 / 193 |
| 1/2 | 635 | 1,271 | 276 | 3,798 | 68 | 27 | 6,075 / 65 |
| 1/3 | 635 | 1,271 | 276 | 686 | 68 | 27 | 2,963 / 90 |
| 2/1 | 635 | 1,271 | 434 | 686 | 68 | 27 | 3,121 / 155 |
| 2/2 | 635 | 1,271 | 452 | 287 | 68 | 27 | 2,740 / 80 |
| 2/3 | 635 | 1,271 | 452 | 286 | 68 | 27 | 2,739 / 63 |

The schema alone contributes 1,193 tokens per call; instructions contribute 635 and the
example/separators 78. Total system content is 1,906 per call, **51.5%** of first-turn and
**66.5%** of second-turn input. The ten-candidate search is the first turn's largest variable
payload. History is **not** the dominant cost in this short incident: dialogue contributes
60 tokens across turn 1 calls and 534 across turn 2 calls. The second turn initially receives
the previous turn's one-item search because it is still state-current before the correction.

The builder does duplicate the current user message, and stores complete assistant response
objects in dialogue, which can duplicate product cards in longer conversations. That larger
card-history problem is visible in code, but this trace contains only a prior clarification,
so it does not demonstrate that particular cost. See
[context.py:82](../../src/shopping_agent/context.py#L82) and
[context.py:94](../../src/shopping_agent/context.py#L94).

Reproduce token counts locally with the same downloaded tokenizer and a temporary
installation of `tokenizers==0.23.3` (not required to run application tests):

```sh
PYTHONPATH=/tmp/astra-watch-audit/tokenizer-runtime .venv/bin/python \
  docs/reviews/measure_prompt_components.py \
  data/ui-sessions/deepseek/2419651698a1407390cec082dee0efc7/events.jsonl \
  /tmp/astra-watch-audit/tokenizer-assets/deepseek_v4_tokenizer/tokenizer.json
```

The reader prints counts only and performs no API, session or index writes. Paths above
refer to the local audit assets; they are deliberately not committed.

## Recommended fixes, not yet implemented

1. **Make bounded completion explicit.** Supply allowed actions and a terminal-decision flag;
   SEARCH is unavailable when searches are zero or the current call is the last. Clarify
   that a SEARCH must leave a subsequent decision call for inspection. Keep executor guards.
   If a valid but disallowed final SEARCH still occurs, produce a deterministic product-free
   limitation with a distinct bounded-abstention outcome, preserving its rejection and usage.
   Do not count this as shopping success, auto-recommend accessories, grant repair calls,
   or turn malformed/provider/constraint failures into successful recommendations. Current
   prompt wording at [context.py:46](../../src/shopping_agent/context.py#L46) is ambiguous.
2. **Repair the product-type contract separately.** Preserve raw stated type, quote and
   correction provenance; resolve it against a deterministic, catalogue-grounded category
   vocabulary with explicit resolved/ambiguous/unsupported outcomes. Wearable versus accessory
   scope needs positive and negative fixtures; universal stemming or title-word matching is
   insufficient. Do not silently remove a hard type or rewrite persisted history. Version
   changed matching semantics so old search results cannot be reused as current. This is the
   principal retrieval fix; terminal messaging alone will not recover the missing watches.
3. **Avoid unproductive repeated searches.** Trace the effective request identity:
   state/catalogue/strategy versions, normalized tokens, mode and limit. Reuse or reject an
   exact per-turn duplicate without spending another tool search; do not hide its paid model
   call. Show concise attempted-query history and whether zero results came from lexical
   matching, known filters or unknown facts. The observed searches before the final duplicate
   are different, so deduplication alone does not fix this incident. Never relax constraints
   automatically to improve counts.
4. **Reduce prompt duplication, then measure decision quality.** Keep the durable trace
   intact, project conversational text plus ordered recommendation references into history,
   and omit the duplicate current event by identity. Retain information needed for “the
   second one” and corrections. Mechanically compact the existing schema (such as redundant
   generated titles/whitespace) rather than maintain a second hand-written contract or remove
   safety rules. Project search candidates without image URLs, overly precise ranking floats
   or repeated fact values where they add no decision evidence; preserve IDs, category scope,
   facts/unknowns, supporting text, provenance and hard/soft match evidence. If a projection
   removes candidates, validation must use the **exact visible set**, not a larger hidden
   search result. See [agent.py:194](../../src/shopping_agent/agent.py#L194). Do not blindly
   lower candidate count: reduced recall could cost more searches and worse recommendations.

Implement completion first as a small reliability checkpoint, category resolution as a
separately reviewed semantics checkpoint, and deduplication/compaction with focused tests.
Then verify the same live scenario and a diverse small development set under unchanged
budgets. No live quality improvement, token savings from proposed prompts, latency benefit
or cost reduction has yet been measured. No embedding stack, framework, persistent memory
or evaluation framework is required for these bounded fixes.

## Independent review and executed checks

`qa_tester` independently inspected the trace, ran the 70-test baseline suite, recomputed
all four real searches and replayed the three exact second-turn decisions against a copy
of the completed first-turn prefix. It reproduced the same failure at state version 2,
3 model calls / 2 searches. A synthetic catalogue reproduced it too. Changing only the
last decision to RESPOND completed within the **same** budget with no products; this proves
bounded completion is possible, not that a changed live policy will reliably choose it.

`architecture_reviewer` independently traced responsibilities and reviewed the remedies.
It endorsed explicit terminal action availability with authoritative executor checks,
separate category-resolution semantics/provenance/versioning, and preserving the exact
visible-candidate boundary during compaction. It warned that deduplication alone does not
repair this incident and that a smaller schema must still preserve the decision contract.

Added [test_watch_regressions.py](../../tests/test_watch_regressions.py):

- Three passing controls: unfiltered retrieval finds synthetic wearables; catalogue wording
  plus price constraints rejects accessories and unknown prices; the corrected two-turn flow
  can finish with a product-free response at current bounds while preserving state history.
- Three **expected failures**, not correctness passes: singular `watch` loses wearables;
  compound `wristwatch` yields no wearable candidates; final repeated SEARCH yields generic
  exhaustion rather than the proposed safe terminal closure. Remove these markers when the
  reviewed fixes are implemented; unexpected success will then fail the suite until reviewed.

QA independently checked these tests and ran their undecorated methods: the failures are
the intended assertions, not fixture/schema exceptions. A network-denied run made zero
network attempts. No raw trace, real product IDs or credentials are used in tests.

Executed in the project environment:

```sh
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check src tests docs/reviews/measure_prompt_components.py streamlit_app.py
.venv/bin/python -m pip check
```

Results: **76 executed: 73 passed, 3 expected failures, zero skipped and zero unexpected
failures**. Ruff lint and formatting checks passed; pip reported no broken requirements.
Streamlit's existing bare-mode ScriptRunContext warnings were emitted. The prompt-count
reader was also executed against all six saved requests and reproduced the tables above.
No production change or new live sampling is included. The original known Phase 2 review
defects remain separate and unfixed.
