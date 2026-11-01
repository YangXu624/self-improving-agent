# Stage 1 user-memory checkpoint

Scope: persistent per-user Markdown profiles, controlled formation/correction, bounded recall
and explicit normal-application ON/OFF controls. No new evaluator, external learner, model
requests, procedural lesson activation, benchmark changes or code self-editing.

## Architecture mapping

| Existing responsibility | Stage 1 treatment |
| --- | --- |
| Session identity, events and state | Reused without replacing persistence or replay |
| Context/policy contract | Enabled-only memory projection and proposal schema; OFF preserved |
| BM25 and recommendation gates | Unchanged; memory is advisory |
| Procedural SQLite lessons | Unchanged, independent optional argument |
| User profile | New `UserMemoryStore`, one atomic Markdown file per owner |
| Normal UI/CLI | Explicit opt-in; same owner across new session UUIDs |
| Evaluator | Unchanged user-memory OFF; future timeline documented only |

`docs/user-memory.md` contains the data flow, source-event authority, file examples,
usage and future interface boundaries. README, architecture, roadmap, evaluation and
decision documentation were updated in the integration checkpoint. AGENTS.md is unchanged.

## Tests actually executed

```text
.venv/bin/python -m unittest discover -s tests -p 'test_user_memory*.py' -q
Ran 30 tests: OK

.venv/bin/python -m unittest discover -s tests -q
Ran 493 tests: OK (skipped=1, expected failures=2)

.venv/bin/ruff check src tests
All checks passed

.venv/bin/ruff format --check src tests
80 files already formatted

git diff --check
No whitespace errors
```

The skip is the existing missing pinned tokenizer asset. Expected failures are the existing
watch/wristwatch product-type regressions. The suite therefore has 490 ordinary passes,
one skip and two expected failures. Test transport is mocked; no paid or local model call
was needed. No personalisation-quality or shopping-performance gain is claimed.

## Independent review

QA independently verified recall in the actual policy payload, cross-owner isolation,
concurrent revision conflicts, corruption handling, OFF compatibility, UI toggles and CLI
defaults. It reproduced polarity, temporary-fact, storage-refusal, third-party quotation,
scope and history-limit defects during development. Regressions and fixes were added.
Its final recheck passed all 28 then-current memory tests plus a separate matrix rejecting
10 invalid statements and accepting four valid ones; two additional focused conflict/budget
tests subsequently passed in the final 30-test run.

Architecture review identified invisible correction targets, overly general scopes and
generic first-person facts being treated as persistent. The final review verified the fixes:
exact visible IDs, whole-statement scope checking, explicit persistence/frequency evidence,
and priority for mentioned older values. No remaining blocking finding was reported.
Reviewers did not modify production code or original artifacts.

The OFF prompt was independently compared byte-for-byte against main for an inspected fixture
(7,903 characters each). This fixture check plus regressions is not a proof of all possible
custom context-builder behaviours. Live memory formation remains unverified.

## Protected artifacts

Before implementation, SHA-256 hashes were recorded for all 38 existing files under:
`data/catalogue`, `data/index`, `data/experience`, `data/eval/scenarios`, `data/eval/runs`.
After final tests, the same file set and every individual hash matched; no additions,
removals or changes occurred in those trees.

The SHA-256 of the sorted path-to-hash JSON inventory was identical before and after:

```text
4fddf4d9a12e2e4538ee6e2a57d7e3e132c1bc1f0db64b9c030b9853ec9ad940
```

Profiles in tests use temporary directories. Dataset, run, session and memory files are
not committed. No original ASTRA/AutoML files outside this repository were modified.

## Remaining limits

Conservative English rules can reject valid paraphrases; they do not establish complete
semantic correctness. Current requirements override advisory records. Forgotten/superseded
records retain audit history; there is no automatic expiry or physical-erasure interface.
Local owner labels are not authentication. The multi-session evaluator and external LLM
learner are proposed documentation interfaces only. Stop after this stage for user review.
