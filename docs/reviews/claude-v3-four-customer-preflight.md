# Claude V3 four-customer memory evaluation: stopped at live preflight

Date: 1 November 2026 (Asia/Singapore). Code under test: `7cfb02b` from PR #24.
**The full experiment was not launched. No memory-effectiveness result exists.**

## Approved run and selected customers

The requested development comparison is 24 sessions: these four customers, three chronological
visits each, all 12 OFF visits before all 12 ON visits. All 12 definitions use preference-mode
scoring, six-turn visit caps and an ongoing color preference.

| Customer | Categories across visits | OFF completed/planned | ON completed/planned |
| --- | --- | --- | --- |
| `dev-capsule-wardrobe` | Active Shirts & Tees; Active Hoodies; Pants | 0/3 | 0/3 |
| `dev-activewear` | Tanks Tops; Active Shirts & Tees; Pants | 0/3 | 0/3 |
| `dev-footwear` | Cycling; Equestrian Sport Boots; Industrial & Construction Boots | 0/3 | 0/3 |
| `dev-jewelry-simple` | Anklets; Necklaces; Bangle | 0/3 | 0/3 |

An ignored temporary fixture selects those exact customer objects in that order from
`experiments/longitudinal/customers.dev-expanded.json`. No customer/visit requirement, product,
witness, suitability set or evidence hash was changed. The source fixture remains unchanged.

The successful dry plan validates the catalogue/index and selects 24 sessions with:

- DeepSeek `deepseek-flash`; Claude `claude-sonnet-5-5`, V3 protocol `shopper-v3-autonomous-1`.
- Compact memory representation, `off_then_on`, primary K=5, six shopper turns, 18 ASTRA calls
  per session, maximum 432 DeepSeek calls and 288 Claude attempts. One smoke attempt counts
  against the total shopper allowance; it is not an extra allowance beyond the approved cap.
- Session memory enabled, procedural experience disabled; separate customer/condition stores,
  empty initial ON profiles and chronological visits through the existing runner.
- Unchanged frozen 50k catalogue/index, BM25, policies, user memory and scoring.

These controls were inspected and dry-planned; no live timeline exercised them in this run.
The inherited OFF/ON design shares the compact base prompt version but ON includes memory
instructions/update schema. This is the existing full-feature comparison, not an identical-prompt
ablation. V3 generates its own openings instead of copying the frozen V2 opening/disclosure plan.

## Preflight actually executed

1. Clean repository and expected PR #24 ancestry confirmed. No production edits were made.
2. `python -m pip check`: no broken requirements. Pip emitted a nonfatal cache-permission
   warning; no dependency was installed or changed.
3. `python -m unittest discover -s tests -p 'test_shopper_v3*.py' -q`: **38 tests passed**.
4. `ruff check src tests`, `ruff format --check src tests`, `git diff --check`: passed.
5. CLI dry plan with the selected fixture: catalogue/evidence/index validation passed,
   24 sessions and exact OFF-then-ON timeline order confirmed. No live run directory created.
6. **One actual Claude-only connectivity request** through the unchanged V3 adapter, no
   retries. Minimal generic input, existing JSON message/action schema, 64 output-token cap.
   No private customer profile was needed for this smoke. No DeepSeek request was made.

## Observed blocker and root cause

The live request returned:

```text
HTTP 400
invalid_request_error
temperature: Extra inputs are not permitted
```

`JsonShopperProvider.complete()` always includes `temperature` in its Claude Messages payload.
The selected Sonnet 5.5 model rejects that parameter, as stated in its
[official model documentation](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).
The transport mock tests assert the shape but never validated it against this real model;
they therefore missed this compatibility defect. The request ID and complete redacted-safe
response body are preserved in the ignored local artifacts.

The existing adapter reports the generic safe error `shopper_provider_failure`. A smoke-only
transport observer saved the HTTP response body before re-raising the same exception; it did
not modify the request, simulator policy or production code. No fallback model, parameter
repair or retry was attempted. The preflight failed, so execution stopped as requested.

This establishes a request-compatibility problem. It does not establish anything about
Claude's shopper quality, the customer's preferences or ASTRA's memory effectiveness. No
successful generation/key/model-access test has yet completed.

## Overall comparison: unavailable

| Metric | Memory OFF | Memory ON |
| --- | --- | --- |
| Started/completed sessions | 0/0 | 0/0 |
| Success@5, nDCG@5, preference satisfaction | Not measured | Not measured |
| Disclosed hard-requirement compliance / hidden-profile mismatches | Not measured | Not measured |
| Clarifications, searches, shopping conversation turns | Not measured | Not measured |
| Memory persistence / retrieval / prompt injection / application | Not exercised | Not exercised |
| Incorrect/irrelevant/outdated memory use | Not evaluated | Not evaluated |
| Shopper session validity / premature termination | No sessions started | No sessions started |
| DeepSeek tokens and calls | No calls | No calls |

Visit 1 has zero completed observations in either arm. Visits 2–3 have zero completed
observations in either arm. There are no recommendation examples, learned profiles or memory
lifecycle chains to inspect. Absence of profile writes here is **lack of execution**, not lack
of a learning opportunity and not a memory-system failure. Unstarted sessions are not zero
scores, invalid shopping sessions or failures of recommendation quality.

For each of the eight returning visit definitions, all lifecycle stages remain unobserved:
customer disclosure → accepted profile write → new session → retrieval → injection → search
planning → recommendation. The frozen audit matrix records this explicitly rather than
fabricating trace evidence. No conclusion favoring either memory condition is possible.

## Usage and financial accounting

| Quantity | Observed |
| --- | --- |
| Claude attempts | 1, failed HTTP 400; no retry |
| DeepSeek attempts | 0 |
| Smoke wall time | Approximately 0.604 seconds |
| Claude input/output/cache tokens | Unknown: error response supplied no usage |
| Actual billed cost | Unknown; **not recorded as US$0** |
| Smoke accounting allowance | US$0.05 reserved within the approved US$10 ceiling; not a bill |
| Full-run spend | Not initiated |

Prices checked before launch: Sonnet 5.5 US$2 input / US$10 output per million tokens,
cache reads US$0.10 and cache writes US$2.50 (5m) / US$4 (1h), from the
[official Claude model page](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).
DeepSeek Flash's conservative peak planning rates are US$0.30 uncached input / US$1.20 output
and US$0.006 cached input per million tokens, from
[official DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/).

The existing runner enforces call counts, not a combined dollar ceiling. A full-run financial
bound was **not certified**, and the full run was not launched. Its input-token consumption
cannot be treated as a fixed count from the character/context estimates. Before a relaunch,
validate the reservation/monitoring method against actual wire inputs and model output caps,
account for prompt/schema overhead and cache usage, and stop if remaining allowance cannot
cover a request. Missing/error usage must retain an upper allowance until billing reconciliation.
Do not infer a full 24-session cost or memory benefit from this failed minimal request.

## Preserved evidence

Local artifact directory (ignored by Git):

`data/eval/longitudinal/claude-v3-four-customer-20261101-preflight/`

- `customers.selected.json`: exact four-customer subset, before any live reply.
- `preflight.json`: code/model identities, input hashes, resource limits and environment versions.
- `dry-plan.txt`: validated 24-session configuration and exact timeline order.
- `v3-tests.txt`: actual deterministic test output.
- `smoke.py`: one-attempt observer/reproduction script; contains no credentials.
- `smoke.shopper-v3.jsonl`: complete request payload, provider error/status and latency;
  request headers/credentials are excluded.
- `smoke-http-error.json`: actual HTTP status, request ID and response body.
- `smoke-result.json`, `smoke-budget.json`: failure, missing-usage flag and reserved allowance.
- `execution-summary.json`, `memory-lifecycle-audit.json`: stopped status and explicit
  not-run lifecycle observations.
- `protected-before.json`, `protected-after.json`: matching hashes of all **236 existing
  protected files**, including the original failed pilot, catalogue/index, customer fixtures
  and experience SQLite. Canonical inventory fingerprint before = after:
  `9cc319715f418914d630ca04b21492f27df2e4fb3d27edbc5d3a4e4a78ef3790`.

No new shopping transcripts, user profiles, ASTRA execution traces or per-session scores exist,
because no shopping session started. No protected artifacts or original scores were overwritten.

## Recommended next checkpoint

The highest-priority prerequisite is a narrow, separately reviewed **Sonnet transport
compatibility fix**, with a regression that rejects unsupported wire parameters and a successful
one-request live smoke before any longitudinal run. Verify Sonnet's thinking/output-cap behavior
and schema support without changing the shopper's roleplay policy or scoring. Do not switch
providers/models silently. Also validate combined per-request cost reservations/accounting
without changing any policy, retrieval, memory or scoring semantics.

This is not evidence for a memory redesign. After approval and verified preflight, use a new
output directory and the same frozen four-customer subset for the full OFF-then-ON experiment.
Keep the failure evidence; count prior smoke spending against the approved allowance unless a
new budget explicitly supersedes it. No automatic merge or further paid request occurred.
