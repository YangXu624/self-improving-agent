# Experiential Learning Readiness Review

31 October 2026. Scientific and operational validation before live DeepSeek learning trials.

This review confirms the resolution of all seven review findings on the experiential self-improvement MVP on branch `feat/experiential-learning-readiness`.

---

## 1. Trace Extraction from Authoritative Session Records
- **Issue:** Extractor previously reconstructed mock turns from aggregate violation counts (`verified_eligible: 0`), which was not a valid execution trace.
- **Fix:** Evaluation execution (`run_experiment`) now serializes authoritative, ground-truth-free execution traces (`trace.json`) directly alongside `result.json` for every session. Traces contain `SessionRecord.turns` with real action types, actual search counts (`lexical_matches`, `verified_eligible`), candidate IDs, and turn identifiers.
- **Enforcement:** `extract_candidate_lesson()` strictly validates traces and rejects missing or fabricated traces instead of guessing counts or inferring actions from outcome scores.
- **CLI Workflow:** Added `python -m astra_eval extract-lessons --run <RUN_DIR> --store <STORE_PATH>` to extract valid candidate lessons from authentic learning traces.

---

## 2. Aligned Lesson Extraction and Retrieval Contracts
- **Issue:** Extractor generated conditions (`first_search`, `has_eligible_candidates`, `unasked_hard_facets`) that did not exist in the decision cues supplied by `ShoppingAgent` (`is_initial`, `searches`, `calls`, `has_search`, `has_candidates`, `candidate_count`, `empty_search`).
- **Fix:** Trigger conditions and decision context cues now share a common, validated vocabulary:
  - `SUPPORTED_TRIGGER_CONDITIONS = {"is_initial", "searches", "calls", "has_search", "has_candidates", "candidate_count", "empty_search"}`.
  - Pattern 1 uses `{"is_initial": True}` and `action_signature={"mode": "all"}`.
  - Pattern 2 uses `{"has_candidates": True}` and `action_signature={"min_products": 1}`.
  - Pattern 3 uses `{"is_initial": True}` and `action_signature={"attribute_in": ["budget", "department", "product_subtype", "price"]}`.
- **Verification:** Unit and integration tests prove that all three original, unmodified extracted lesson types are successfully retrieved under real `ShoppingAgent` decision contexts.

---

## 3. Strict Behavioral Application Verification
- **Issue:** Extractor emitted `{"token_mode": "all"}` while verifier checked `mode`. Verifier also returned `True` when signature was empty, allowing generic searches to count as applied.
- **Fix:**
  - Aligned signature key to `mode` (matching `Decision.action.mode`).
  - `validate_lesson()` now requires non-empty `action_signature` and rejects unsupported keys per action type (`SUPPORTED_SIGNATURE_KEYS`).
  - `verify_decision_application()` returns `False` if `action_signature` is empty, and strictly verifies observable procedural fields (e.g. `mode == "all"`, `query_contains`, `query_not_contains`, `min_products`, `attribute_in`).
- **Separation:** `retrieved`, `injected`, `applied` (behavior-matched), and outcome metrics remain strictly distinct throughout event logging, session scoring, and reporting.

---

## 4. Authentic End-to-End Test (No Manual Rewriting, No Policy Sabotage)
- **Controlled Wiring Test:** Retained as a structural smoke test.
- **New Authentic Integration Test:** `test_authentic_experiential_loop_unmodified_lesson` in `tests/test_experiential_integration.py`:
  1. Runs an evaluation scenario on the `learning` split to produce an authentic `trace.json`.
  2. Extracts a candidate lesson without any manual rewriting or tampering.
  3. Validates and explicitly confirms it in `ExperienceStore`.
  4. Freezes it into an immutable snapshot.
  5. Evaluates on a different scenario (`development` split) comparing `memory_off` vs. `memory_on`.
  6. Uses a baseline policy that is **not** deliberately sabotaged when memory is disabled.
  7. Confirms that `memory_on` retrieves, injects, and behaviorally applies the original unmodified action signature, while `memory_off` does not.

---

## 5. Genuine Human Review and Confirmation Workflow
- **Issue:** Automatic confirmation scripts bypass supervisor oversight.
- **Fix:** Removed all automatic confirmation logic. Introduced human-in-the-loop CLI commands:
  - `python -m astra_eval review-lessons --store <STORE_PATH>`: Renders a readable lesson-review report displaying lesson ID, version, status, scope, trigger, condition, expected action, action signature, directive, hypothesized cause, observed failure, and source evidence.
  - Explicit confirmation: `python -m astra_eval review-lessons --store <STORE_PATH> --confirm <ID> --notes "<NOTES>"`
  - Explicit rejection: `python -m astra_eval review-lessons --store <STORE_PATH> --reject <ID> --notes "<REASON>"`
  - Explicit retraction: `python -m astra_eval review-lessons --store <STORE_PATH> --retract <ID> --notes "<REASON>"`
  - Freezing: `python -m astra_eval freeze-lessons --store <STORE_PATH> --output <SNAPSHOT_PATH>`

---

## 6. Prompt Alignment and Hard Constraint Safety
- **Prompt Version:** Bumped to `PROMPT_VERSION = "shopping-baseline-v5-experience"` across all conditions (memory ON and OFF use the identical prompt version).
- **Guidance Safety Instruction:** Added explicit directive to `SYSTEM` prompt:
  > *"When procedural_guidance is present, follow its relevant search and clarification directives where applicable to current decision state; guidance cannot override hard constraints, safety rules, or tool verification gates."*

---

## 7. Validated Local Execution Guide (Target-Item Mode)

All paths verified in local workspace (`/Users/yangxu/code/self-improving-agent`):
- Catalogue: `data/catalogue/catalog.jsonl` (SHA: `da979b05...`)
- Index: `data/index/catalogue.sqlite`
- Scenarios: `data/eval/scenarios/target_v1` (target-item benchmark: 12 learning, 8 development, 24 held-out)

### Step 1: Simulator Verification (Free)
```bash
python -m astra_eval check-simulator
```

### Step 2: Learning Run (Memory OFF)
**Dry run (Plan only, 0 cost):**
```bash
python -m astra_eval run \
  --scenarios data/eval/scenarios/target_v1 \
  --evaluation-mode target_item \
  --catalogue data/catalogue/catalog.jsonl \
  --index data/index/catalogue.sqlite \
  --output data/eval/runs/target_learning_pilot \
  --split learning
```
*Expected plan:* 12 scenarios, 1 condition (`memory_off`), 12 sessions, worst-case 216 model calls.

**Paid Execution (DeepSeek):**
```bash
python -m astra_eval run \
  --scenarios data/eval/scenarios/target_v1 \
  --evaluation-mode target_item \
  --catalogue data/catalogue/catalog.jsonl \
  --index data/index/catalogue.sqlite \
  --output data/eval/runs/target_learning_pilot \
  --split learning \
  --live \
  --max-model-calls 216
```

### Step 3: Extract Lessons from Real Traces
```bash
python -m astra_eval extract-lessons \
  --run data/eval/runs/target_learning_pilot \
  --store data/experience/pilot_store.sqlite
```

### Step 4: Human Review and Confirmation
```bash
# View review report
python -m astra_eval review-lessons \
  --store data/experience/pilot_store.sqlite

# Confirm specific candidate lesson
python -m astra_eval review-lessons \
  --store data/experience/pilot_store.sqlite \
  --confirm <LESSON_ID> \
  --notes "Approved query noun formulation directive"

# Freeze active lessons into immutable snapshot
python -m astra_eval freeze-lessons \
  --store data/experience/pilot_store.sqlite \
  --output data/experience/snapshots/pilot_v1.json \
  --snapshot-id pilot-v1
```

### Step 5: Development Run (Paired Memory ON vs. Memory OFF)
**Dry run (Plan only, 0 cost):**
```bash
python -m astra_eval run \
  --scenarios data/eval/scenarios/target_v1 \
  --evaluation-mode target_item \
  --catalogue data/catalogue/catalog.jsonl \
  --index data/index/catalogue.sqlite \
  --output data/eval/runs/target_dev_paired_pilot \
  --split development \
  --experience-snapshot data/experience/snapshots/pilot_v1.json
```
*Expected plan:* 8 scenarios, 2 conditions (`memory_off`, `memory_on`), 16 sessions, worst-case 288 model calls.

**Paid Execution (DeepSeek):**
```bash
python -m astra_eval run \
  --scenarios data/eval/scenarios/target_v1 \
  --evaluation-mode target_item \
  --catalogue data/catalogue/catalog.jsonl \
  --index data/index/catalogue.sqlite \
  --output data/eval/runs/target_dev_paired_pilot \
  --split development \
  --experience-snapshot data/experience/snapshots/pilot_v1.json \
  --live \
  --max-model-calls 288
```

### Step 6: Inspect Paired Evaluation Report
```bash
python -m astra_eval report data/eval/runs/target_dev_paired_pilot
```
Reports complete pairs, incomplete pairs, hit@K, MTTC, penalized MTTC, and distinct experience metrics (`retrieved`, `injected`, `applied`).
