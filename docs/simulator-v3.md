# Autonomous shopper V3: design and prototype boundary

Status: design checkpoint before implementation. V2 remains available and is not replaced.
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
  an explicit model and separate credentials; no ASTRA environment-file parser changes.

## Naturalness versus reproducibility

V3 deliberately changes the conversation-generating process. Do not pool it with V2 results.
Freeze inputs, catalogue, code, provider/model, prompt/auditor versions, budgets and decoding
settings. Claude does not receive an Ollama seed. Temperature zero is not proof of deterministic
API output. Exact request/response replay is reproducible; repeated live dialogue is stochastic.
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
implemented. Six mocked-provider tests passed; no live model was contacted. Autonomous
policy, evidence derivation and loop integration are next. No quality or memory benefit is claimed.
