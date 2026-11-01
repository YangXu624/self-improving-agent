# Stage 2 verification checkpoint

Base: merged PR #18 (`080dc4d` on main). Branch `feat/longitudinal-evaluation`.
No application rewrite, procedural activation, external learner, live model run or frozen
benchmark modification. AGENTS.md and the original reference projects were not edited.

## Implemented

- `customers.py`: private customer/visit/change contracts, boundary projection and compilation
  into existing Scenario/GroundTruth/TargetGroundTruth, raw-catalogue evidence validation.
- `longitudinal.py`: stable user IDs, fresh UUID sessions, isolated complete OFF/ON timelines,
  existing dialogue loop/scorers, budgets, blocked-history handling and complete output IDs.
- `longitudinal_report.py`: per-session/customer/condition metrics grouped by evaluation mode,
  explicit incomplete pairs and bounded memory exposure/recommendation diagnostics.
- Existing dialogue/shopper memory accept optional stable owner/current-private context;
  defaults preserve the single-session path. Existing CLI adds `longitudinal` and routes
  report rebuilding by run mode. Shopping execution/retrieval/user/procedural stores unchanged.
- Three invented four-visit development customers, with only derived requirements, witness
  IDs/source paths and evidence hashes; no raw catalogue rows or real personal data committed.

Documentation: README, architecture, evaluation, decisions, roadmap, Stage 1 interface status,
development fixture README and `docs/longitudinal-evaluation.md` (schema, diagram, commands,
metrics, artifact layout and limitations).

## Tests actually run

```text
.venv/bin/python -m unittest discover -s tests -p test_customers.py -q
7 tests passed

.venv/bin/python -m unittest discover -s tests -p 'test_longitudinal*.py' -q
13 tests passed

.venv/bin/python -m unittest discover -s tests -q
513 tests: OK (skipped=1, expected failures=2), 10.809 seconds

.venv/bin/ruff check src tests
All checks passed

.venv/bin/ruff format --check src tests
87 files already formatted

git diff --check
No whitespace errors
```

Full suite: 510 ordinary passes; existing missing pinned-tokenizer skip and two existing
watch/wristwatch expected failures. An intermediate full-suite run found six CLI regressions
from a new local variable shadowing the imported plan function (and Ruff removing its now-unused
import). Renaming the variable/restoring the import fixed them; existing CLI tests and the final
full suite were rerun successfully. No test expectation or scoring rule was relaxed.

The real catalogue source was independently validated offline: 3 customers, 12 visits. A free
CLI dry run for the first customer planned 8 sessions / at most 144 agent calls and created no
output directory. No keys, DeepSeek requests, Ollama requests or local model execution occurred.

A separate fully mocked demo ran one synthetic customer through four visits in both arms:
one user ID, eight distinct session UUIDs, 24 mocked policy calls. OFF injected/wrote no user
memory; ON formed Blue, recalled it, corrected to Red, then retained Red through the gift task.
Reports/transcripts were saved only in a temporary directory. This synthetic exercise verifies
wiring, not shopping performance or real personalisation benefit.

## Independent QA

The review-only QA agent independently ran customer and runner tests, a FakeOllama transport
timeline, CLI dry-run guards and existing dialogue/target/shopper-memory regressions. It found:

1. Disclosure statements could disagree with stored values/operators: fixed with reused
   literal disclosure checking and budget-operator validation; regression added.
2. Witness evidence could select an unusable alias: fixed using raw-fact usability rules;
   regression added.
3. Initial persona text mentioned future changes: removed; current-boundary tests retained.
4. Preference/dislike audit entries collided: category added to the key; regression added.

Final QA recheck passed 7 customer and 12 then-current runner/report/CLI tests, and reported no
unresolved newly introduced defect among reproduced cases. The final thirteenth CLI report
dispatch test also passed in the complete suite. Reviewers changed no files or real artifacts.

Inherited failed-shopper request/token accounting remains incomplete and is explicitly flagged.
Stale exposure can support correction, hidden mismatch differs from disclosed violations, and
full-feature ON/OFF changes schema/instructions and subsequent histories. No causal proof or
complete semantic memory-use detection is claimed.

## Artifact preservation

Before and after implementation, all 38 existing files under `data/catalogue`, `data/index`,
`data/experience`, `data/eval/scenarios`, `data/eval/runs` had identical SHA-256 hashes and an
identical file set. The sorted path/hash inventory SHA-256 was:

```text
4fddf4d9a12e2e4538ee6e2a57d7e3e132c1bc1f0db64b9c030b9853ec9ad940
```

The current frozen target_v1 benchmark, learning transcripts/database/candidate lessons and
historical reports were preserved. All new session/profile artifacts used temporary paths.
Stop for Stage 2 implementation and development-customer review before live use or expansion.
