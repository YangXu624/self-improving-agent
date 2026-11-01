# Claude Sonnet 5.5 compatibility and evaluation readiness

Date: 1 November 2026 (Asia/Singapore). Scope: evaluator transport, configuration and budget
accounting only. No shopper prompt, disclosure auditor, scoring, catalogue, ASTRA production
code, frozen scenario or user/agent-memory implementation was changed.

## Root cause and fix

The original adapter unconditionally sent `temperature: 0`. Sonnet 5.5 rejects all three
sampling fields (`temperature`, `top_p`, `top_k`), including zero. Claude requests now omit
these fields. Ollama retains its temperature, seed, context and output limits.

Claude `V3Config.temperature` is `None`; an explicitly supplied temperature (CLI, environment
or constructor), including zero, is rejected with a clear error. This avoids recording a
sampling control that the provider does not honor. Ollama's default remains 0.0. The transport
version is now `shopper-transport-2`; shopper prompt/auditor versions are unchanged.

Verified against official documentation and the live responses:

- POST `https://api.anthropic.com/v1/messages`, `anthropic-version: 2026-10-21`, top-level
  system prompt and message array. [Messages reference](https://platform.claude.com/docs/en/api/messages).
- `output_config.format` with `type: json_schema`, the existing message/action schema,
  required fields and `additionalProperties: false`. [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
- Sonnet 5.5 has adaptive thinking on by default. The adapter selects `thinking.type:
  between_tools` and `output_config.effort: low` for this model. With no tools, this avoids
  up-front thinking and returns text. This is the documented alternative to `disabled`;
  there is no unsupported manual thinking budget. [Sonnet migration behavior](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5).
- `max_tokens` caps thinking plus answer output. The original 220 cap is not guaranteed
  sufficient for every structured reply. Proposed experimental settings use **512** explicitly
  in both arms, preserving Ollama defaults and the existing 1,000-character reply validator.
  [Thinking cost controls](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost).

The response parser requires `end_turn` and exactly one nonempty text block, ignoring thinking
blocks. Truncation, refusal, malformed envelopes and malformed reply JSON fail safely. Usage
is recorded **before** rejecting incomplete/refused envelopes, since those can be billed.
Missing counts remain absent/unknown. No malformed-output retry was added.

## Deterministic checks

- Focused `test_shopper_v3*.py`: **44 passed**. Covers Claude sampling omission, version/schema,
  valid and thinking-plus-text envelopes, refusal/truncation, malformed blocks and JSON,
  secret-safe HTTP errors, attempt caps and missing usage. Existing multi-turn, target cutoff,
  condition/owner isolation and V2 regressions remain covered.
- `test_api_budget.py`: **7 passed**, including shared accounting, denial before I/O, unknown
  usage retaining reserves, failed transport, verified-model restriction, finite limits,
  accounting-bound breaches and unchanged delegated DeepSeek messages.
- Additional V3 tests run an eight-session mocked longitudinal comparison through the **same
  shared budget** for both providers/arms and verify monetary denial becomes an infrastructure
  stop before another shopper call. No DeepSeek network request is involved.
- Full suite, lint, formatting and final counts are recorded at the completed checkpoint below.

## Actual Claude-only smoke

Two actual calls, no retries or settings changes between calls. Both used the unchanged
`AutonomousShopper` persona prompt and independent auditor, with the first frozen Capsule
Wardrobe visit. The follow-up assistant question was authored for this smoke, not generated
by DeepSeek. It deliberately asks about budget and color to exercise a real response.
No search, recommendation or ASTRA policy call was made.

Configuration: Sonnet 5.5, API version above, between-tools/low effort, output cap 512,
context budget 4096, window eight turns, no Claude sampling/seed parameter. Claude returned
`model: claude-sonnet-5-5`, standard/global inference, no thinking tokens.

| Call | Result | Input | Output | Cache read/write | Raw JSON chars | Stop reason | Latency | Estimated USD |
| --- | --- | ---: | ---: | --- | ---: | --- | ---: | ---: |
| Generated opening | Valid message/action JSON | 1,014 | 50 | 0 / 0 | 131 | `end_turn` | 2.066s | 0.002528 |
| Follow-up | Valid message/action JSON | 1,115 | 40 | 0 / 0 | 107 | `end_turn` | 1.736s | 0.002630 |
| Total | 2 successful attempts, 0 retries | 2,129 | 90 | 0 / 0 | — | — | 3.802s | **0.005158** |

Actual generated opening:

> Hi, I'm looking for an everyday casual top, something like an active tee or shirt. Under $45 please.

Follow-up question: “What budget and color preference should I keep in mind?”

> Budget is under $45, as I mentioned. I usually go with black if you have it.

Manual inspection against frozen evidence: the goal is an everyday casual top in Active Shirts
& Tees; budget is under US$45 and ongoing clothing color preference is Black. Both replies
match those facts, are conversational rather than copied disclosure statements, and contain
no observed invented brand, size, material, price or unsupported product property. This is a
two-message inspection, not evidence of general simulator fidelity.

**Auditor limitation preserved:** budget was verified twice. The natural category paraphrase
and “I usually go with black” remained unverified by the bounded lexical checker. It emitted
no contradiction/error. The text still reaches ASTRA normally; unverified ledger evidence is
not proof that the preference was undisclosed or unavailable to ASTRA. Future learning audits
must inspect actual dialogue and ASTRA's accepted quoted memory writes, rather than equating
these unverified labels with a lack of learning opportunity. The auditor was not changed.

## Financial controls

A new evaluation-only `ApiCostBudget` is shared by the Claude adapter and a `BudgetedPolicy`
delegating to the existing DeepSeek policy with identical messages. No production policy code
changed. The opt-in longitudinal CLI records `--max-cost-usd` and `--prior-cost-usd`; live Claude
requires the ceiling. Both actual provider objects must share the recorded fresh budget.

Before each request, reserve conservative input/output expense. Reservations use ASCII-escaped
wire-body bytes plus 4,096 framing/schema tokens, output-token caps, and the most expensive
supported input rate. Reconcile reported counts afterward. Unknown usage/transport errors
retain the full reservation and block further calls. Monetary denial occurs before I/O and
becomes a safe provider failure so the existing error policy stops. Journals cannot overwrite
or resume an old budget. Client limits are not a provider-side billing guarantee: unexpected
billing/token-bound overruns stop subsequent calls and must be reconciled manually.

Rates are restricted to the verified model IDs. Sonnet pricing used: US$2 input / US$10 output
per million tokens, US$0.10 cache read and a conservative US$4 cache-write upper rate (1h;
5m writes actually cost US$2.50). [Claude pricing](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).
DeepSeek Flash uses conservative peak US$0.30 uncached / US$0.006 cached input and US$1.20
output per million, even if actual requests qualify for off-peak pricing. Without a cache
breakdown, total reported input is charged at the uncached upper rate. [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/).
No unknown **total** input/output is converted to zero.

Smoke ceiling was **US$0.25**, shared across two attempts and the previous **US$0.05 uncertain
allowance**. Actual known token-based smoke estimate is **US$0.005158**, so accounted expenditure
plus old uncertainty is **US$0.055158**. This is not a provider invoice. The failed PR #25
request's actual usage/cost remains unknown. The next run must carry forward this allowance,
leaving **US$9.944842** under the previously proposed US$10 ceiling.

No fixed worst-case promise that all 24 sessions fit US$10 is justified. The guard can end
an expensive run early instead of exceeding its accounting ceiling. Provider price changes,
service-tier/geography multipliers, unrelated account activity and taxes are outside the
client ledger. Verify rates before approval; use an account-side cap too if an absolute billed
limit is required. No full DeepSeek evaluation was started.

## Readiness and exact commands

**Transport: GO for review. Controlled pilot: conditional GO after human approval.** The two
live replies prove the corrected wire contract works for this configuration. They do not
establish multi-turn shopper validity, 24-session completion, memory learning or improved
recommendations. Auditor false negatives remain visible. No launch is authorized by this report.

The selected fixture is copied byte-for-byte from the stopped preflight and revalidated:
`data/eval/longitudinal/claude-sonnet55-readiness-20261101/customers.selected.json`.
It has only Capsule Wardrobe, Activewear, Footwear and Simple Jewelry, three visits each.
SHA-256: `3dfc1344fb38483f595c151c192ac16bcce4a7a406ebbefae5b9e0af40ac30d4`.
Ground truth and evidence are unchanged; all visits use preference scoring.

The command below has been run **without `--live`** and validates 24 sessions, chronological
visits, all OFF before ON, isolated fresh stores, compact memory and procedural experience OFF:

```sh
.venv/bin/python -m astra_eval longitudinal \
  --customers data/eval/longitudinal/claude-sonnet55-readiness-20261101/customers.selected.json \
  --output data/eval/longitudinal/claude-sonnet55-readiness-20261101/live-24 \
  --shopper-version v3 --shopper-provider claude --sim-model claude-sonnet-5-5 \
  --sim-max-tokens 512 --sim-num-ctx 4096 --sim-seed 7 \
  --memory-format compact --execution-order off_then_on \
  --headline-k 5 --turn-budget 6 --session-max-model-calls 18 \
  --max-model-calls 432 --max-shopper-calls 285 \
  --max-cost-usd 10 --prior-cost-usd 0.055158 --stop-on-error
```

Only **after explicit approval**, repeat the same command with `--live` appended. The 285
shopper-attempt allowance conservatively leaves room for the three already consumed preflight
attempts under the original cumulative 288 maximum. A newly approved separate full-run attempt
budget could instead permit 288; do not silently reset prior calls/spending. The seed remains
an Ollama-compatible recorded field and is not sent to Claude. No temperature option is valid.

Do not reuse existing output/journal paths. Do not continue automatically after a provider,
simulator or financial stop. Inspect first versus returning visits separately and preserve
incomplete pairs. The existing OFF/ON comparison retains ON-specific memory instructions/schema;
it is not an identical-prompt ablation. V3 may naturally repeat preferences in either arm.

## Local evidence and integrity

Ignored artifact root: `data/eval/longitudinal/claude-sonnet55-readiness-20261101/`.
Includes the two-response raw request/response/usage/evidence journal, smoke configuration,
result, script and shared financial ledger; exact subset and validated dry plan; deterministic
test logs and before/after protected-artifact hashes. No environment values or credential
headers are committed or written to provider journals. Original preflight artifacts remain intact.

## Completed checkpoint

Full suite: **608 run — 605 ordinary passes, one missing-tokenizer skip, two existing expected
watch/wristwatch retrieval failures**. Lint, format and diff checks passed. All **280** protected
pre-existing artifact files have matching before/after hashes. Canonical inventory fingerprint:
`7205d3d15da445006fd0872d80017f8a9bd50e5dffa1e0a470532d164ed8a8b7`. No live-24 directory, memory stores or DeepSeek calls were created.
