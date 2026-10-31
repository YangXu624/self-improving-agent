# Focused experience-integrity checkpoint and proposed development pilot

This checkpoint fixes interpretation and auditing; it establishes no measured transfer gain.
Lesson 1 remains a candidate. No real lesson was confirmed, no snapshot was frozen and no
paid request was made for this checkpoint. All test stores and snapshots are temporary fixtures.

## Implemented boundaries

- `is_initial` means the first policy decision for the current category-identified shopping
  goal, determined from canonical user/model events. Greetings do not start a shopping goal;
  retries and later turns are not initial decisions. Clear `New goal:` / `Start a new goal`
  markers (or `Now`/`Instead` with a different identified category) can provisionally scope
  cues before extraction. Only validated NEW_GOAL edits retire real requirements.
- Category-only opening recognition uses documented category labels from the unchanged,
  read-only catalogue index, normalized inflections and a small request grammar. It suppresses
  guidance for extra details, including unrecognized words, rather than guessing they are
  category-only. Validated active requirements and the asked/disclosed ledgers also suppress
  this cue. Unsupported paraphrases/adapters without category metadata may give conservative
  false negatives. There is no extra model call, brand inference or new search strategy.
- `retrieved` records snapshot matches selected for a decision. `injected` requires the exact
  lesson ID and directive in the actual serialized policy prompt. `applied` requires an
  injected lesson's observable signature to match an accepted/executed action after guards.
  `experience_selection`, `model_request`, and `experience_action_accepted` events provide
  per-decision evidence. This is behavioral conformance, not proof of causal influence.
- `add_candidate` accepts candidates only. Exact re-extraction is idempotent and returns
  the stored record, preserving status, timestamps, approval notes and lineage. Content
  changes to reviewed records require a new-ID explicit revision/supersession. SQL also guards
  reviewed status against races. Explicit review transitions retain earlier review notes.
- The existing `violations` score retains its historical meaning and numerical values:
  hidden-target-profile mismatches among distinct products. Reports label this explicitly.
  New recommendation events additionally capture the current confirmed hard requirements,
  state version and goal epoch. The independent oracle checks these per presentation, before
  later corrections. Missing legacy snapshots are unknown, never zero violations. Compliance
  with committed state does not establish completeness of natural-language extraction.
- The extractor selects among predefined procedural templates. Causes are hypotheses; failure
  after an initial search does not prove that missing clarification caused the failure.
  Shopper disclosure behavior, sparse evidence and retrieval coverage can still prevent
  target discovery after clarification. Simulator, profiles and benchmark scenarios are unchanged.

## Protected artifacts

The complete before/after inventory is `/tmp/astra-pilot-protected-before.json` and
`/tmp/astra-pilot-protected-after.json`: 38 original files under data/eval, data/experience,
data/catalogue and data/index. Inventory digest is SHA-256 of the path→file-hash mapping
serialized with Python `json.dumps(..., sort_keys=True)` (default separators).

| Artifact | Before SHA-256 | After |
|---|---|---|
| Complete 38-file inventory | `4fddf4d9a12e2e4538ee6e2a57d7e3e132c1bc1f0db64b9c030b9853ec9ad940` | `4fddf4d9a12e2e4538ee6e2a57d7e3e132c1bc1f0db64b9c030b9853ec9ad940` |
| pilot_store.sqlite | `b9f334a4c59e62c2363bcaa30e0f394968bd14dda06fb7933dca72c550702065` | `b9f334a4c59e62c2363bcaa30e0f394968bd14dda06fb7933dca72c550702065` |
| target_v1/scenarios.jsonl | `7f696d9eab110aaed398e473ebd94768c75be559505d8ffd3a5ff24b54a2cd42` | `7f696d9eab110aaed398e473ebd94768c75be559505d8ffd3a5ff24b54a2cd42` |
| target_v1/ground_truth.jsonl | `6b03d697029391df39d498145d8387bee2225b310e8ec02941cc19f089b3ef33` | `6b03d697029391df39d498145d8387bee2225b310e8ec02941cc19f089b3ef33` |
| catalogue/catalog.jsonl | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| index/catalogue.sqlite | `f0aac92a51c7618ac9df12a76cbe9e47358a28e530fdd6b2e913beb9d572e5bb` | `f0aac92a51c7618ac9df12a76cbe9e47358a28e530fdd6b2e913beb9d572e5bb` |

## Experiment specification — requires separate explicit approval

Use the fixed benchmark's first two development scenarios, selected before any paired results:

1. `dev-0057121054c00529`, Folding Umbrellas: OFF then ON.
2. `dev-00bbccf58868d1a6`, Pendants Only: ON then OFF.

The existing runner rotates the two conditions by scenario index. Four fresh sessions use
identical frozen profiles/catalogue/index, DeepSeek `deepseek-flash` (temperature 0, thinking
disabled, output cap 2000), Ollama `llama3.1:latest` (temperature 0, seed 7, context 4096,
reply cap 220, history window 8, malformed retry 1), primary K=5, six turns, three policy
calls and two searches per turn, 18 policy calls per session, and a 72-call whole-run cap.
Record code commit, input hashes, snapshot hash, actual returned model name and Ollama model
digest/version at execution; aliases/temperature zero do not guarantee reproducibility.

Primary endpoint: exact target Hit@5. Also inspect first qualifying rank/MRR, successful and
penalized MTTC, searches, CLARIFY actions, token use, hidden-profile mismatches and disclosed
compliance. Count OFF success/ON failure as negative transfer, and report extra cost, delay or
compliance regressions even when both arms fail. Inspect actual sent prompts and accepted
questions to establish whether behavior changed; signature conformance alone is insufficient.
Do not rerun only unfavorable sessions, alter lessons after seeing results, or learn from
these development results during the comparison. Two tasks are descriptive, not evidence of
statistical superiority; no target gain means no target-improvement claim.

## Exact commands — DO NOT execute before approval

After approval, use the reviewed commit and a fresh output path. The existing snapshot
command freezes all active lessons, so the preflight below requires zero currently active
lessons and the exact unchanged candidate. It then verifies the resulting snapshot has only
Lesson 1. These are operator commands; no activation is part of automated tests or startup.

```bash
cd /Users/yangxu/code/self-improving-agent
set -euo pipefail

# Read-only preflight: exact frozen task selection and original candidate/store state.
.venv/bin/python - <<'PY'
import hashlib, json, sqlite3
from contextlib import closing
from pathlib import Path
base = Path('data/eval/scenarios/target_v1')
assert hashlib.sha256((base/'scenarios.jsonl').read_bytes()).hexdigest() == '7f696d9eab110aaed398e473ebd94768c75be559505d8ffd3a5ff24b54a2cd42'
assert hashlib.sha256((base/'ground_truth.jsonl').read_bytes()).hexdigest() == '6b03d697029391df39d498145d8387bee2225b310e8ec02941cc19f089b3ef33'
assert hashlib.sha256(Path('data/catalogue/catalog.jsonl').read_bytes()).hexdigest() == 'da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67'
assert hashlib.sha256(Path('data/index/catalogue.sqlite').read_bytes()).hexdigest() == 'f0aac92a51c7618ac9df12a76cbe9e47358a28e530fdd6b2e913beb9d572e5bb'
dev = [json.loads(line) for line in (base/'scenarios.jsonl').read_text().splitlines() if json.loads(line)['split'] == 'development']
assert [s['id'] for s in dev[:2]] == ['dev-0057121054c00529', 'dev-00bbccf58868d1a6']
with closing(sqlite3.connect('file:data/experience/pilot_store.sqlite?mode=ro', uri=True)) as db:
    assert db.execute("SELECT count(*) FROM lessons WHERE status IN ('active','confirmed')").fetchone()[0] == 0
    assert db.execute("SELECT status FROM lessons WHERE lesson_id='exp-e23002ac6fd9'").fetchone()[0] == 'candidate'
    assert db.execute("SELECT status FROM lessons WHERE lesson_id='exp-ebffc34c0130'").fetchone()[0] == 'rejected'
assert not Path('data/experience/snapshots/lesson1-dev-v1.json').exists()
assert not Path('data/eval/runs/lesson1-dev-paired-v1').exists()
PY

# First mutating commands: only after explicit approval.
.venv/bin/python -m astra_eval review-lessons \
  --store data/experience/pilot_store.sqlite \
  --confirm exp-e23002ac6fd9 \
  --notes 'Approved for bounded development trial; causal explanation and benefit remain hypotheses.'
mkdir -p data/experience/snapshots
.venv/bin/python -m astra_eval freeze-lessons \
  --store data/experience/pilot_store.sqlite \
  --snapshot-id lesson1-dev-v1 \
  --output data/experience/snapshots/lesson1-dev-v1.json
.venv/bin/python - <<'PY'
from shopping_agent.experience import ExperienceStore
s = ExperienceStore.load_snapshot('data/experience/snapshots/lesson1-dev-v1.json')
assert [lesson.lesson_id for lesson in s.lessons] == ['exp-e23002ac6fd9']
assert s.lessons[0].status == 'active'
assert s.lessons[0].trigger_condition == {'is_initial': True, 'is_underspecified': True}
assert s.lessons[0].evidence['source_split'] == 'learning'
print('Single-lesson snapshot:', s.sha256)
PY

# Same command without --live is a free plan; it must show four sessions and <=72 calls.
# The command below is the separately approved LIVE experiment.
DEEPSEEK_MODEL=deepseek-flash .venv/bin/python -m astra_eval run \
  --scenarios data/eval/scenarios/target_v1 \
  --evaluation-mode target_item --split development --limit 2 \
  --catalogue data/catalogue/catalog.jsonl --index data/index/catalogue.sqlite \
  --experience-snapshot data/experience/snapshots/lesson1-dev-v1.json \
  --output data/eval/runs/lesson1-dev-paired-v1 \
  --k 1 3 5 --headline-k 5 --turn-budget 6 \
  --session-max-model-calls 18 --max-model-calls 72 \
  --simulator ollama --sim-model llama3.1:latest \
  --sim-temperature 0 --sim-seed 7 --sim-num-ctx 4096 \
  --sim-max-tokens 220 --sim-timeout 120 --window-turns 8 --live

.venv/bin/python -m astra_eval report data/eval/runs/lesson1-dev-paired-v1
.venv/bin/python -m astra_eval show data/eval/runs/lesson1-dev-paired-v1 dev-0057121054c00529 --condition memory_off
.venv/bin/python -m astra_eval show data/eval/runs/lesson1-dev-paired-v1 dev-0057121054c00529 --condition memory_on
.venv/bin/python -m astra_eval show data/eval/runs/lesson1-dev-paired-v1 dev-00bbccf58868d1a6 --condition memory_on
.venv/bin/python -m astra_eval show data/eval/runs/lesson1-dev-paired-v1 dev-00bbccf58868d1a6 --condition memory_off
```

The preflight deliberately fails after activation or if paths already exist. For an interrupted
run, inspect its preserved artifacts and request a new plan rather than overwriting or
silently resuming. Neither this guide nor an approved code PR authorizes paid execution.

## Verification actually executed

Full suite: 463 tests executed, 460 passed, one tokenizer-asset skip, two existing watch
expected failures. Independent QA added 21 passing regressions. Ruff lint/format and diff
checks passed. Architecture review independently checked provisional goal isolation, request
retry scope, accepted SEARCH/RECOMMEND compliance snapshots and exact canonical replay.
All 38 protected files match byte-for-byte before/after. A read-only real-catalogue preflight
confirms both selected development openings qualify under the corrected cue. No result for
real memory-guided DeepSeek behavior or transfer is claimed.
