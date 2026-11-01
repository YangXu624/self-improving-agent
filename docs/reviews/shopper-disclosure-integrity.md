# Ollama shopper disclosure integrity and pilot recovery

This checkpoint changes evaluation simulation and validation only. Production ASTRA,
retrieval, user/procedural memory, customer ground truth, oracle and scoring formulas are
unchanged. No new DeepSeek request or paid evaluation was made. The failed pilot is retained.
The prerequisite phased-runner/failed-pilot report is PR #22; this fix is a separate PR.

## Diagnosis from the actual run

Run: `data/eval/longitudinal/pilot-20261101-off-then-on/`, code `e4846ef`.
Five OFF sessions ran: four valid, one simulator-invalid. ON never started. There is no
paired memory-effectiveness result. See [partial results and actual usage](longitudinal-live-pilot.md).

On `commuter-bags-02`, the hidden facts were:

| Allowed key | Existing fact |
| --- | --- |
| type | I need Briefcases. |
| budget | My budget is under 70 USD. |
| preferred_color | I generally prefer Black bags. |

`ollama.requests.jsonl` records 21 and 22 contained the correct current-visit profile and
private context: goal “Buy a folio bag for work”, Black bags preference, recipient self,
recall-probe behavior, and a ledger with only `type` already disclosed. They contained no
future visits, target/witness ID, suitability score or memory-condition label.

Both `ollama.responses.jsonl` records 21 and 22 returned exactly:

```json
{"message":"I'm looking for a folio bag for work, not just briefcases.","reveals":["type","current_goal"],"action":"reply"}
```

`current_goal` was a real private-context field, but not a disclosure identifier. The old
Ollama schema constrained `reveals.items` only to string, while the prose said profile keys
only. The independent validator correctly emitted `reveals_unknown_key: current_goal`.
The second request's user JSON included that exact feedback, but no explicit valid-key list
or rejected-response example. It received the identical invalid output. The logs establish
this repetition, not why the model failed to follow the feedback. The seed/temperature and
context were unchanged. No rejected reply reached ASTRA or updated the shopper ledger.

After the initial attempt and one allowed consistency retry, the dialogue runner recorded
`simulator_failure` / `simulator_inconsistent:reveals_unknown_key`. Its approved opt-in
`stop_on_error` ended the whole run, before ON. Changing the disclosure schema alone would
address the identifier space, but does not guarantee truthful disclosure text.

### The 14 earlier warnings were unsupported claims

Replaying the saved outputs through the old validator at `6f650bf` reproduces all 14:

| Count | Claimed key | Actual message |
| ---: | --- | --- |
| 1 | preferred_color | Are these shirts suitable for a relaxed office day? |
| 4 | budget | I'd like to know if any of these shirts are within my budget. |
| 4 | budget | I'd like to know if any of these belts fit within my budget. |
| 1 | budget | I don't have a strong preference about that. |
| 4 | budget | I'd like to continue the search. |

None states the frozen color or numeric budget. These are not legitimate paraphrases
requiring looser validation. The old code logged these as warnings and excluded the
unverified keys from ledger updates; it still accepted the utterances. Product-type claims
were even weaker: the legacy checker treated them as stated without examining the text.
Partial multiword color matches could also pass. These are validator coverage gaps, distinct
from the model's inaccurate claims. Gray/grey spelling is a supported equivalence now tested
explicitly; it was not the cause of these 14 warnings.

All 36 expanded visits have the same potential namespace ambiguity because they carry
roleplay metadata alongside a fact-key list. This is a structural risk, not evidence that
36 live sessions failed. Deterministic tests verify that every visit's new enum contains
only its actual current facts. Gifts use recipient keys; future preferences stay private.

## Selected fix

1. `simulators.reply_schema()` builds a fresh per-visit enum from the immutable profile.
   It retains natural-language messages and the same three actions, caps claims at two,
   permits an empty claim list, and rejects extra object fields. Empty profiles permit no
   disclosure. The original template is never mutated across customers.
2. The shopper prompt explicitly distinguishes metadata from allowed disclosure keys,
   explains `reveals=[]`, and prohibits using context goals to replace fixed requirements.
   The user payload and retry both include the valid-key list.
3. Claimed disclosures require their actual values. Missing claims are errors in both
   protocols and use the existing consistency retry/failure route. Multiword values require
   complete token evidence, color spelling aliases are normalized, explicit negative facts
   retain their meaning, and the existing target budget-direction check is reused. No score
   or ground-truth predicate is changed and no semantic similarity threshold is introduced.
4. Retry feedback includes the rejected reply and unsupported fact's existing statement.
   A rejected attempt establishes nothing, including its otherwise valid claims. On the
   correction only, the model is told to include each claimed fact's provided sentence or
   omit that claim if it is merely commenting. It still chooses the facts, action and prose;
   code never substitutes a valid answer or strips invalid keys from an invalid reply.
   Correction instructions are in the system context and counted by the existing context
   budget. The retry count remains one; no extra repair-model call is introduced.
5. Preference and target sessions now both log structured attempts, raw returned content,
   violations and hashes in `simulator_audit` entries. Rejected attempts remain distinct
   from accepted conversation. Context windows continue to exclude audit entries.
6. Frozen simulator settings record `shopper-v2-scoped-disclosures`. Historical manifests
   are untouched. Reproduce the original behavior from the old revision, not by treating
   old and new simulator outputs as interchangeable.

These changes enforce disclosure integrity; they do not demonstrate that ASTRA recommends
better products or that its memory helps. Category singular/plural retrieval failures and
missing structured attributes in lexical query text remain separate, unchanged findings.

## Verification actually performed

- New disclosure-integrity suite: 12 deterministic tests, including the exact bad output,
  failed and successful retries, current-visit enums, unsupported claims, partial values,
  genuine budget/color paraphrases, contradictions, negative facts, repeated disclosures,
  unchanged ledgers after rejection, and future/truth isolation across all 36 visits.
- Existing evaluation tests: 164 passed after updating the transcript test to count the
  same 20 conversation entries plus nine newly preserved audit entries. The assertion was
  extended for observability; no expected recommendation or score was relaxed.
- Longitudinal runner/report/CLI: 18 passed. Expanded catalogue fixtures: 9 passed, including
  all 36 witnesses, suitability-set hashes and byte-reproduced inventory on the real catalogue.
- Full suite: **557 tests, 554 ordinary passes, one existing tokenizer skip, two existing
  watch/wristwatch expected failures**, in 23.521 seconds. Lint, formatting and diff checks pass.
- New 4-customer compact phase plan validates without network, credentials, profile stores or
  creation of the future `run/` directory: 24 sessions, 432 maximum agent calls.

### Real local model checks, including unsuccessful development trials

No DeepSeek client was constructed for these tests. Local model: `llama3.1:latest`,
Ollama 0.40.13; its model digest matches the failed pilot's saved digest.

1. Initial scoped-enum smoke: two attempts, then failure. The invalid `current_goal` key
   disappeared, but the model still claimed unsupported `type` text. Correctly rejected.
2. Adding concrete feedback without system-priority correction: two attempts, then failure.
   The retry claimed a budget without its amount. Correctly rejected; not silently repaired.
3. Final correction-context smoke: all three cases completed in four total local calls:

| Case | Outcome | Calls | Accepted disclosure |
| --- | --- | ---: | --- |
| Original failing interaction | Initial bad claim rejected; correction accepted | 2 | Message states under 70 USD; model declares only budget |
| Budget question | Accepted immediately | 1 | My budget is under 70 USD. |
| Already-disclosed budget asked again | Accepted immediately | 1 | Same under-70 fact repeated |

The final smoke recorded 3,853 prompt / 135 completion tokens and about 3.61 seconds of local
call latency. All eight local development calls, including the two earlier failed trials,
are preserved in sibling `simulator-v2-smoke*-20261101/` directories. Additional paid calls: 0.
A three-case smoke does not certify all shopper behavior; bounded failures must remain visible.

## Preserved evidence

All 51 files in the original failed pilot retain identical contents and the same file set.
Canonical sorted path/hash manifest SHA-256 before and after:

`643558d1f67ff2e59122f6c522e3035b14338078edd60e0ed7a07ee6e05dd6be`

All 170 pre-existing local data files and both original/expanded fixtures retain their hashes,
including catalogue, index, experience store, held-out/learning artifacts and previous results.
Of the initial 174-entry data/source inventory, 173 entries are unchanged; the only changed
entry is the intentionally updated `experiments/longitudinal/README.md` documentation. No model key, raw catalogue, transcript, local database or model asset
is committed. The small report quotations above are synthetic failure evidence only.

## Recovery decision

Restart both phases from scratch. `run_longitudinal()` intentionally refuses an existing
output directory and has no automatic resume. New shopper prompts, response schema and
validation alter generated conversations. Reusing the earlier OFF sessions with new ON
sessions would confound memory with simulator version. Do not pool the old partial data
with the new run. Keep it as a diagnostic artifact, with its original invalid classification.

For this small validity pilot, retain global stopping: an unexpected provider/simulator or
harness failure means inspect before spending more. A future preregistered larger design
could quarantine one customer/condition timeline and continue independent customers; it
must report invalid pairs and exclude subsequent visits whose memory history is compromised.
Do not choose that policy after seeing outcomes, and do not change the current stop rule.

### Prepared exact non-live command

The input below is already prepared as a byte-identical copy of the old selected four-customer
file. The future `run/` directory does not exist and no profile is copied or seeded.

```sh
.venv/bin/python -m astra_eval longitudinal \
  --customers data/eval/longitudinal/pilot-v2-restart-plan-20261101/customers.selected.json \
  --output data/eval/longitudinal/pilot-v2-restart-plan-20261101/run \
  --memory-format compact --execution-order off_then_on --stop-on-error \
  --headline-k 5 --session-max-model-calls 18 --max-model-calls 432 \
  --sim-model llama3.1:latest --sim-url http://127.0.0.1:11434 \
  --sim-temperature 0 --sim-seed 7 --sim-num-ctx 4096 \
  --sim-max-tokens 220 --sim-timeout 120 --window-turns 8
```

This was executed without `--live`. It validates all visits and the index; no DeepSeek or
Ollama endpoint is contacted. Customer order: Office Basics, Commuter Bags, Gift Shopper,
Bag Style Change. Each has three chronological visits. All 12 OFF sessions precede all
12 ON sessions. ON starts with an empty isolated user-memory root; OFF has no profile access.
Session memory stays enabled and procedural experience stays disabled in both arms.

### Future paid command — prepared, NOT executed or newly authorized

After a separately approved budget and model/configuration check, run the same command with
an explicit provider model and the live flag:

```sh
DEEPSEEK_MODEL=deepseek-flash .venv/bin/python -m astra_eval longitudinal \
  --customers data/eval/longitudinal/pilot-v2-restart-plan-20261101/customers.selected.json \
  --output data/eval/longitudinal/pilot-v2-restart-plan-20261101/run \
  --memory-format compact --execution-order off_then_on --stop-on-error \
  --headline-k 5 --session-max-model-calls 18 --max-model-calls 432 \
  --sim-model llama3.1:latest --sim-url http://127.0.0.1:11434 \
  --sim-temperature 0 --sim-seed 7 --sim-num-ctx 4096 \
  --sim-max-tokens 220 --sim-timeout 120 --window-turns 8 \
  --price-input-per-million 0.15 --price-output-per-million 0.60 \
  --env-file .env --live
```

Keep one frozen revision, catalogue, simulator version/model digest, generation settings,
prompt version, hidden profiles, six-turn budgets and K=5 across both arms. Existing full-feature
OFF/ON still has the explicitly approved memory-instruction/update-schema difference. Store
all new receipts, traces, profiles and logs under the new root; do not read old profiles.
The default malformed-output retry and consistency retry are each still one. The CLI stops
globally on invalid/provider/simulator/harness sessions. Ordinary agent-quality failures
remain outcomes. Cost values in the command are a cache-miss estimate, not an invoice.

### Resource and cost bounds

24 sessions × 18 calls = **432 maximum DeepSeek calls**, at most 216/phase; per-turn agent
limits stay 3 decisions / 2 searches. This is a request cap, not 24 requests. With 6 turns,
the existing two consistency attempts × two malformed attempts allow up to 480 Ollama
requests over 24 complete sessions (24 × 5 shopper responses × 2 × 2), usually fewer; Ollama
is local compute. No extra paid repair model is added.

Illustrative cache-miss Flash cost at 432 calls, assuming 5,000 input + 300 output tokens/call:
**US$0.402 off-peak / $0.804 peak**. With the 2,000-output-token cap and the same assumed input:
**$0.842 / $1.685**. Input length varies, so these are explicit estimates, not monetary ceilings.
[Official rates checked 2026-11-01](https://api-docs.deepseek.com/quick_start/pricing/).
The previous run's actual recorded token-rated cost was ~$0.012780; settled billing was not
verified by its rounded balance snapshots. No new DeepSeek balance request was made here.

## Remaining limits and next development cycle

- Enumeration constrains identifiers, not semantic honesty. The independent validator and
  bounded failure path remain required even when the local JSON grammar is obeyed.
- Disclosure support is lexical and conservative, not a semantic proof. Unrecognized category
  paraphrases can require correction; compound categories/negation remain limited. No embedding
  or LLM judge is added, and unseen material/brand/availability facts stay unverified.
- The shopper can still ask repetitive questions or fail to volunteer useful facts. Local tests
  do not establish realistic purchase acceptance or full 24-session completion.
- Failed malformed/transport attempts can still have incomplete aggregate usage accounting;
  available raw response receipts and audit attempts should accompany any paid run.
- There were no ON visits, so memory persistence, scope relevance, injection, application and
  stale-memory handling are **unobserved**, not failed or proven successful.

Ranked follow-ups, without implementing additional features:

| Priority | Opportunity | Evidence / expected value | Effort / complexity | Testability |
| --- | --- | --- | --- | --- |
| 1 (this PR) | Current-visit disclosure integrity and truthful claims | Removes the observed global-stop cause; prerequisite for a valid comparison, not a shopping-quality gain | Small, evaluation-only; no framework | Deterministic exact replay + small local smoke |
| 2 | Diagnose category inflection and attribute-query false negatives | Singular daypack/briefcase hard filters repeatedly returned zero; strong direct retrieval lead | Moderate; separate retrieval change | Frozen search/state replay, unchanged independent oracle |
| 3 | Measure actual memory scope/application before choosing retrieval technology | No ON data exists; semantic retrieval benefit remains a hypothesis | Diagnosis first, implementation undecided | Trace storage → retrieval → injection → selection on new valid timelines |

After a trustworthy restart, design the original-OFF / original-ON / improved-ON comparison
with a fixed simulator version in all arms and additional development customers. Measure
first versus returning visits separately, retain invalid/failure counts, and report preference
satisfaction and incorrect memory application alongside Success@5, nDCG, clarification turns,
retrieval accuracy, tokens and billed/estimated costs. No such paid comparison is run here.
