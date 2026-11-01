# Autonomous shopper V3: design and prototype boundary

Status: opt-in V3 prototype implemented; live provider quality is unverified. V2 remains available and is not replaced.
No new paid request, protected fixture/scoring edit, or automatic merge is authorized.

## Why V2 is insufficient

- Persona and goals are present, but model-facing facts are canned `what_you_would_say`
  sentences. Correction instructions force verbatim sentences, narrowing linguistic diversity.
- The model must both converse and label its disclosures. The failed pilot confused a private
  context field with a label. Enums fix labels, not faithful roleplay.
- Lexical validation mistakes some references/paraphrases for assertions and misses others.
  Stronger validation can make the shopper more mechanical without improving realism.
- Stable preferences are reloaded each visit; the shopper receives no actual previous-visit
  conversation. This is profile consistency, not returning-customer episodic continuity.
- Private preferences are duplicated and can include irrelevant personal facts for gift tasks.
- Shopper-visible recommendations contain short titles/prices, limiting product judgments.
- Neither paid API access nor natural language alone establishes a reliable evaluation.

## Proposed flow

Existing frozen customer/visit compiler + independent catalogue oracle
→ V3 private view (persona, current goal/recipient, typed verified requirements)
→ bounded actual prior conversation history, isolated by customer AND experimental condition
→ provider-neutral autonomous shopper (Ollama or Claude)
→ `{message, action}` only
→ independent deterministic dialogue-evidence audit
→ accepted utterance and verified disclosure evidence to existing dialogue runner
→ unchanged ASTRA, target cutoff and preference/target scorers.

The initial shopper request is model-generated too. Existing opening text remains frozen for
V2 and is not shown as a response template to V3. Output actions remain reply/accept/give_up
for lifecycle management; the model chooses wording, information timing, questions and reactions.
No action is selected by a predetermined disclosure order.

## Boundaries

- Model-facing requirements use field/operator/value/strength, not sentence templates, fact
  identifiers, witness IDs, target names, score labels, future visits or condition labels.
- Product descriptions derive only from already-validated fields. This prototype does not send
  a full target description/title; attribute-based targets may remain ambiguous, as recorded
  by the existing oracle. Preference shopping and exact-target scoring stay distinct modes.
- Agent-visible data is only the accepted shopper message. Python retains scoring and ground
  truth. A shopper acceptance never establishes target success.
- Prior-visit continuity comes only from accepted conversation and presented products; it does
  not invent purchases or prior dialogue. Current authoritative preferences override old ones;
  recipient preferences are not promoted to personal preferences.
- The model never outputs reveals. Python derives conservative evidence from actual text,
  with verified, contradicted and unverified outcomes. Unrecognized paraphrases are not silently
  marked disclosed. Known unsupported/contradictory attributes are rejected with bounded
  feedback, without inserting a correct sentence. Arbitrary semantic consistency remains an
  explicit limitation; no deterministic English parser can prove every free-form claim.
- Exact provider requests, outputs, usage, timing, validation and lifecycle transitions are
  journaled locally without credentials. Failed attempts consume an explicit shopper-call cap.
- Claude Messages API and local Ollama are thin transports under one contract. No agent
  framework/SDK dependency is needed. Provider construction is network-free. Claude requires
  an explicit model (CLI or configuration) and separately named credentials in a shared or explicit environment file.

## Naturalness versus reproducibility

V3 deliberately changes the conversation-generating process. Do not pool it with V2 results.
Freeze inputs, catalogue, code, provider/model, prompt/auditor versions, budgets and decoding
settings. Claude does not receive an Ollama seed or sampling parameters. Live
API output is not deterministic. Exact request/response replay is reproducible; repeated live dialogue is stochastic.
Unverified linguistic evidence must remain visible rather than being converted into a score.

## Smallest testable slice

1. Thin Ollama/Claude providers, bounded request journal and mocked transport tests.
2. Typed private view and free generated opening/replies without identifiers/templates.
3. Evidence derivation and safe integration with the existing loop; V2 default unchanged.
4. Actual cross-visit history isolated by owner/condition; no learning/permanent memory layer.
5. Deterministic end-to-end tests with mocked providers, unchanged scoring and catalogue gates.
6. Dry-run comparison protocol and optional future explicitly budgeted V3 longitudinal runs.

## Proposed provider comparison (not executed)

First compare shopper reliability, not ASTRA's success rate: freeze 20 development-only
situations before calling either provider, including budget/color paraphrases, unanswerable
questions, contradictory suggestions, gifts, repeated questions and preference changes.
Use identical V3 views/auditor/schema and alternating provider order. Keep oracle identities
outside model input. Have reviewers judge naturalness and persona/goal fidelity independently
of recommendation scores. Report verified/ambiguous disclosure coverage, contradictions,
unsupported facts, premature acceptance, repetition, latency, retries, tokens and API cost.
Use at least two repetitions; do not claim a small pilot proves provider superiority.

Then run full chronological timelines under each fixed shopper provider with memory OFF/ON,
using fresh isolated stores and the same scoring. Add development customers beyond the original
four; keep target and preference results separate. First visits are controls, returning visits
probe memory. Preserve invalid sessions and negative transfer. No paid comparison is run now.

Provider documentation consulted: [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[Claude Messages](https://platform.claude.com/docs/en/api/messages),
[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

## Implementation and verification

Provider checkpoint: thin Ollama/Claude transports, separate Claude key loading, exact local
request/response journaling and an explicit failed-attempt-inclusive shopper-call cap are
implemented. Autonomous policy, text evidence, generated openings, condition-isolated actual
visit history and opt-in longitudinal CLI integration are implemented. Mocked end-to-end tests
exercise both providers and unchanged preference/target stopping. No live model was contacted
and no quality or memory benefit is claimed. See the [comparison protocol](../experiments/longitudinal/shopper-v3-comparison.md).

## Prototype interface and limitations

Implemented opt-in modules: `shopper_providers.py` (transport/budget/journal),
`shopper_v3.py` (policy/private view/history), `shopper_evidence.py` (independent text audit).
`DialogueRunner` reuses the original scoring lifecycle. The longitudinal CLI is the prototype
entry point; the application shopping agent and single-session CLI are unchanged. V2 remains
its default. No dependencies were added.

The private JSON contains persona, current situation, typed verified needs, relevant ongoing
preference scope, verified facts already communicated, bounded actual dialogue and up to three
prior visits. Ongoing preferences are selected from current compiled facts and omitted for
gifts. V3 ignores legacy disclosure schedules, frozen opening sentences, fact statements and
`no_preference_reply`. It does not force persistent-preference words into a message. Therefore
storage/recall frequency can change: measure it rather than assuming V2 and V3 equivalence.

Model output is only `message`/`action`. Existing transcript `reveals` fields are retained for
replay compatibility, populated **by Python** from verified text evidence, not model labels.
Each fact also has an observation: verified/contradicted/unverified and an actual character
span when recognized. Unknown paraphrases can reach ASTRA but are not promoted to verified
ledger evidence. A recognized contradiction is retried at most once with a generic error code;
no canonical answer is supplied. Malformed JSON fails the session without a hidden repair call.

The English audit handles literal attribute values, a few aliases, nearby negation, simple
numeric/number-word budgets and explicit historical preferences. It is intentionally bounded:
complex conjunctions, ranges, indirect language, novel brands/sizes, descriptions and subtle
contradictions need human inspection. It is **not** a general hallucination detector. Target
ID/full unseen-name guards remain; distinctive fragments and combination-based identity hints
still need manual leakage review. A more capable provider does not remove these limitations.

The shopper receives publicly presented product titles/prices plus only evidenced product
attributes; no target ID is transmitted. A title may naturally identify a product already
shown by ASTRA. Internal product IDs are stripped from shopper options and prior-visit cards.
The evaluator still receives real IDs and scores exactly the presented recommendation list.

History is held in the evaluator process by `(owner, condition)`, with accepted text and
presented cards mirrored to the journal. Invalid sessions do not become prior visits. A fresh
run starts empty; restarting a timeline from saved history is deliberately unsupported. Prompt
budgeting drops oldest prior visits then oldest dialogue; full records remain locally available.
There is no summarizer, persistent agent learning or change to ASTRA's memory implementations.

## Safe operation

A **dry plan**, with actual catalogue validation but no credentials/network/output creation:

```sh
.venv/bin/python -m astra_eval longitudinal \
  --customers experiments/longitudinal/customers.dev-expanded.json \
  --output data/eval/longitudinal/v3-ollama-review \
  --limit-customers 1 --memory-format compact --execution-order off_then_on \
  --shopper-version v3 --shopper-provider ollama --sim-model llama3.1:latest \
  --max-model-calls 144 --max-shopper-calls 96 --stop-on-error
```

For a Claude dry plan, replace provider/model with `--shopper-provider claude --sim-model
claude-sonnet-5-5`, or omit `--sim-model` and set `ANTHROPIC_MODEL` in `.env`.
A command-line model overrides the configured value; process `ANTHROPIC_MODEL` overrides the file.
The default shopper settings file is `--env-file` (`.env`); `--shopper-env-file` selects a separate file. Model availability
and real API compatibility have not been exercised. `num_ctx` controls our conservative input
budget in both providers; Claude receives no Ollama seed or `num_ctx` API parameter. Keep the
same context cap and output cap across the comparison; record provider-specific settings.

**Do not add `--live` until a separate budget is approved.** Live V3 requires both global
`--max-model-calls` (ASTRA/DeepSeek) and `--max-shopper-calls` (shopper, including failures and
validation retries). It also requires a fresh output and a fresh sibling journal path. Claude
reads `ANTHROPIC_API_KEY` from the process or the selected ignored environment file.
The shared `.env` accepts `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `ANTHROPIC_API_KEY` and
`ANTHROPIC_MODEL`; each provider uses its own fields. A separate `.env.shopper` remains optional
via `--shopper-env-file`. No keys should be pasted into logs or commands.

Exact provider payloads, raw responses, errors, elapsed time, returned model identity, usage,
text evidence and session lifecycle are written to `<output>.shopper-v3.jsonl`. These private
journals are ignored by Git. Request headers/credentials are never written. Transport errors
record safe exception type/status rather than potentially sensitive exception bodies. Failed
attempts consume the cap. Session attempt totals include malformed/transport failures; parsed
envelope usage is counted even if its message is malformed. Missing usage on failed or invalid
envelopes remains unknown: use raw journal/provider billing to reconcile costs. Existing
reports do not calculate Claude prices; count cache input/create/read separately using the
approved provider price sheet at execution time. Do not label an unknown cost zero.

## Verified checkpoint (1 November 2026)

- `python -m unittest discover -s tests -p 'test_shopper_v3*.py' -q`: **35 passed**.
  Includes six provider-contract tests and 29 autonomous/evidence/integration regressions.
- `python -W error::ResourceWarning -m unittest discover -s tests -q`: **592 run**:
  589 ordinary passes, one skipped pinned-tokenizer asset test and two existing expected
  watch/wristwatch category-matching failures. Those retrieval defects remain unresolved.
- `ruff check src tests`, `ruff format --check src tests`, `git diff --check`: passed.
- Both Ollama and Claude **dry plans** validated the actual expanded catalogue fixture/index;
  neither created its proposed run directory or journal. Claude used a fixture model string
  for planning, not an availability check. The expanded compiler validates all 36 visits
  before selecting the one-customer plan. No live Ollama, Claude or DeepSeek call was made.
- All **232 pre-existing protected files** from the interrupted-task inventory match their
  original hashes, including the original pilot's 51 files. The canonical sorted path/hash
  inventory fingerprint before and after is
  `885bcddd866cbc00b70002a1bda11c0094be3234b4fda76c36e3eb8686f02ae6`.

| Protected artifact | Before SHA-256 = after SHA-256 |
| --- | --- |
| Catalogue | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| Search index | `f0aac92a51c7618ac9df12a76cbe9e47358a28e530fdd6b2e913beb9d572e5bb` |
| Original development customers | `38f00c804c1062507429371cf7228f42dc3e55bffd29d94354ebcb9e14746c41` |
| Expanded development customers | `cc087acaf159c3d63a0cbc65fdb7934e6c12ce285d890280d4551874f3650dd4` |
| Procedural pilot SQLite | `b9f334a4c59e62c2363bcaa30e0f394968bd14dda06fb7933dca72c550702065` |

The functional tests use synthetic catalogues and mocked policies/transports. They verify
mechanics and deterministic safeguards, not autonomous model quality, real API compatibility,
linguistic-audit completeness, reduced simulator failures or improved ASTRA performance.
Original scoring source, benchmark fixtures, transcripts and databases were not edited.

### Shared local provider configuration

```dotenv
DEEPSEEK_API_KEY=your_local_deepseek_key
DEEPSEEK_MODEL=deepseek-flash
ANTHROPIC_API_KEY=your_local_claude_key
ANTHROPIC_MODEL=claude-sonnet-5-5
```

Sonnet's configured ID is from the [official model overview](https://platform.claude.com/docs/en/models/overview).
No model availability or key validity has been tested with a live call. Selecting Claude still
requires `--shopper-version v3 --shopper-provider claude`; adding configuration never starts a run.
Dry planning may read the model setting from the local file; it does not use credentials or
contact a provider. This supersedes the separate-file-only setup in the initial checkpoint.

Configuration follow-up verification: 38 focused V3 tests and four configuration tests passed;
full regression run: 595 tests, 592 ordinary passes, one missing-tokenizer skip and two existing
expected watch-retrieval failures. Lint, formatting and diff checks passed. Local key presence
was checked without displaying it; no provider request was made.

## Sonnet 5.5 compatibility follow-up

The [readiness checkpoint](reviews/claude-sonnet55-readiness.md) supersedes the initial transport
configuration: Claude omits sampling parameters and records temperature as null; specifying
a temperature, even zero, fails clearly. Sonnet uses between-tools thinking / low effort.
The proposed run explicitly uses a 512-token output cap. Two actual Claude responses passed
the schema and no-error audit, while some correct paraphrases remained unverified. Live Claude
longitudinal runs now require `--max-cost-usd`; use `--prior-cost-usd` to carry previous known
costs and unresolved allowances. No full DeepSeek evaluation has started.

## Session-offer reliability update

Acceptance/price auditing now uses accepted RECOMMEND offers in the current session and goal
epoch, including cards before text-only follow-ups. Prior visits, other conditions and search-only
results do not authorize acceptance. Bound memory identity and explicit unsupported references
are checked. The auditor remains lexical and can misinterpret novel paraphrases. See the
[full lifecycle tests and failure policy](reviews/conversation-reliability.md). Old failed pilot
labels remain unchanged; no live retry was made during this hardening pass.
