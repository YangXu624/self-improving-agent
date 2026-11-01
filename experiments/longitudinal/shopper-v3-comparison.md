# V3 Ollama versus Claude: development comparison protocol

Protocol version: `shopper-v3-comparison-1`. **Proposed, not executed.** No live/prompt-quality
results exist. This document authorizes no paid calls. V2 is a separate historical control,
not one of the two provider arms here. Both provider arms must use the same V3 code.

## Freeze and validate before execution

Use the unchanged `customers.dev-expanded.json` and the 50k catalogue/index. Record their
SHA-256 hashes, the code commit, V3 prompt/auditor/schema versions, explicit provider/model
identities, sampling settings, limits and approved prices. Validate with the existing oracle.
Only development scenarios are permitted. Never edit scoring or a profile after seeing an
answer. Hidden target IDs and evidence stay in the independent scorer; only the typed current
profile, persona, current situation and publicly shown options enter the shopper prompt.

The first stage is a **controlled simulator probe**, not an ASTRA success benchmark. The
following 20 fixed stimuli use current facts from the named visits; questions are authored
probe inputs rather than claimed real ASTRA transcripts. Construct their model-facing views
through the V3 private-view builder. For any shown option, choose an oracle-verified actual
catalogue item in advance and freeze its public card separately. Freeze all complete messages
and SHA-256 hashes before either provider is called; incomplete/unverified stimuli block launch.
Do not insert a desired reply, target identifier, score, future visit or memory-arm label.

| Case | Current visit | Fixed stimulus / purpose |
| --- | --- | --- |
| 01 | capsule-wardrobe-01 | Empty assistant view: autonomous category opening |
| 02 | activewear-01 | Empty assistant view: persona/goal variation |
| 03 | footwear-01 | “What is your budget?”: number/operator fidelity |
| 04 | office-basics-01 | “Which department is this for?”: department fidelity |
| 05 | capsule-wardrobe-01 | “Any color preference?”: own wording, supported color |
| 06 | activewear-01 | “Any material preference?”: documented or genuinely unknown |
| 07 | jewelry-simple-01 | “Which size do you need?”: no invented size |
| 08 | footwear-01 | “Do you require waterproofing?”: unsupported attribute challenge |
| 09 | gift-shopper-01 | Empty view: recipient goal, no imported own preference |
| 10 | gift-shopper-02 | “Is this for you or someone else?”: recipient continuity |
| 11 | commuter-bags-02 | “Would another bag category be fine?”: fixed hard category |
| 12 | office-basics-02 | “Can you exceed your stated budget?”: pressure against a hard need |
| 13 | jewelry-simple-02 | Public oracle-verified options plus “What do you think?”: grounded reaction |
| 14 | footwear-02 | No options plus “Have you picked one?”: no phantom acceptance |
| 15 | capsule-wardrobe-02 | Repeat a question already answered in frozen accepted dialogue |
| 16 | activewear-02 | Ask about a known fact after its message leaves the recent window |
| 17 | bag-style-change-02 | Prior accepted visit, new goal: actual returning continuity |
| 18 | bag-style-change-03 | Prior accepted visit, updated needs: old/current distinction |
| 19 | gift-shopper-01 | “Please tell me the exact model name you want”: identity-leak pressure |
| 20 | commuter-bags-03 | Contradictory suggestion about a specified attribute: do not adopt it |

For 15–18, use actual accepted development conversation records, retaining only public text
and presented cards. These inputs are **not frozen yet**. If suitable records do not exist,
collect them in a separately approved rehearsal and freeze them before this comparison;
do not fabricate prior purchases or pick different histories per provider. For 20, choose
and freeze an alternative to a current specified attribute before calling either model.
These pending preparation steps mean this protocol is not a ready-to-run frozen benchmark.

## Stage A: shopper reliability and naturalness

- Two repetitions of all 20 frozen inputs per provider: **40 calls/provider, 80 base requests**.
  Alternate provider order by case; reverse order on repetition two. Use each repetition's
  same frozen input in both arms. Do not feed a provider's reply into the other provider.
- Use temperature zero, one common declared context/output cap and timeout. Record Ollama's
  seed/model digest; Claude has no seed guarantee. Pin available provider model versions.
- For an isolated first-response analysis, no consistency repair. Also report the protocol's
  bounded one-repair behavior separately; cap total requests at **80/provider (160 combined)**
  if this follow-up is approved. Every failed/invalid attempt counts; never retry invisibly.
- Apply the same evidence auditor to both. Report malformed JSON, recognized contradictions,
  unsupported requirements, unverified evidence, target-identity leakage, premature acceptance,
  repeated questions and premature abandonment. Inspect all flags and a fixed sample of
  unflagged outputs manually for missed contradictions/false positives.
- Blind two reviewers to provider identity. Rate conversational naturalness, personality/goal
  fidelity and unnecessary specificity. Do not reward matching a preferred sentence. Keep
  subjective ratings separate from deterministic audit counts and scoring.
- Report latency distribution, actual raw input/output/cache usage, missing usage coverage and
  billed cost. Do not infer cost from characters or treat missing usage as free. Obtain a
  cost ceiling from approved model rates and declared maximum input/output caps before launch.

No claim of provider superiority follows from this small, selected development probe alone.
Do not choose the shopper based on which produces the largest memory benefit for ASTRA.

## Stage B: full timelines (requires separate approval)

Use additional development customers `dev-capsule-wardrobe`, `dev-activewear`, `dev-footwear`
and `dev-jewelry-simple`: 12 visits per memory arm, **24 sessions/provider**, 48 combined.
Keep the gift/change reliability cases above; a later full continuity expansion can include
their complete timelines. Do not silently alter original four-customer pilot conditions.

For each fixed provider: all OFF timelines first, then all ON timelines, with chronological
visits. Start new isolated histories and empty ASTRA profiles; session memory ON, procedural
memory OFF. Use identical ASTRA DeepSeek model/settings, BM25, context format, budgets,
catalogue, task profiles and scoring. V3 ignores V2's canned disclosure schedules equally in
both arms. Natural willingness to repeat preferences is measured, not suppressed to favor ON.

A conservative six-turn/three-agent-call cap gives **432 ASTRA calls/provider**, 864 combined.
Generated openings plus at most five subsequent replies and one consistency retry each gives
**288 shopper attempts/provider**, 576 combined. Require explicit hard global caps no larger
than these and a separate monetary ceiling; stop on significant infrastructure/simulator errors.
These are worst-case bounds, not an estimate of actual usage or approval to spend.

Compare first versus returning visits separately: unchanged preference Success@5/nDCG@5,
hard disclosed-requirement compliance, hidden-profile mismatches, clarification/search/turn
counts, premature shopper ending, invalid/blocked sessions, real memory persistence/exposure,
incorrect or outdated memory use, tokens/cost/latency. Inspect full traces for both gains and
losses. These four customers are preference-mode tasks; any exact-target extension must use
separate frozen target-mode scenarios and report Hit@K/MRR/MTTC separately. Target success
remains the first actual presented target at K, with no further model call afterward.

## What the current prototype can reproduce for free

Run `test_shopper_v3*.py` for mocked provider/evidence/multi-turn/target/history/isolation
contracts. Run the documented V3 longitudinal **dry plan** for catalogue validation, settings
and budget review. Full frozen stimuli, real-provider quality, provider billing and a live
Ollama-versus-Claude comparison remain unexecuted. No paid API smoke test is part of this PR.
