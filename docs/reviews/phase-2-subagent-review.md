# Phase 2 independent QA and architecture review

Date: **31 October 2026**. Scope: session-only shopping baseline; no feature implementation
or production fixes. Runtime baseline: `ecf29008b5126db6c51d9bd8c1f00cd8a6e11193` (main after
PR 2). The later configuration checkpoint is `6f5bb59`; source/tests are unchanged between
them. The separate roadmap PR 3 was still open during this review and is not included here.

## Method and independence

Two subagents ran with fresh contexts and separately read their assigned TOML instructions:
`qa_tester` exercised functionality; `architecture_reviewer` traced interfaces and data flows.
They did not communicate or see one another's findings before returning reports. The parent
then inspected and reran both reproduction scripts and consolidated duplicate observations.
No tracked production/tests/AGENTS.md changes, credential access, original data/session access,
new dependencies or live shopping-provider requests were required. Codex reviewer execution
itself consumes Codex resources; it is not a live ASTRA shopping-quality test.

The current chat spawn API has no custom-agent selector. These tasks explicitly loaded the
configured role instructions; automatic custom-role loading and custom-file feature reductions
are not claimed as demonstrated. See [configuration and permission limits](../subagents.md).

## Consolidated findings

No P1 finding was reported. Two material **P2 defects** are reproduced below. The two P3
items later in this report are future integration risks, not default-path baseline defects.
No production fix has been made in this PR.

### F1 — P2: blank evidence permits unsupported state edits

**Found by:** QA; parent reproduced.

**Locations:** [state.py:88](../../src/shopping_agent/state.py#L88) through the NEW_GOAL branch
at line 98; [contracts.py:44](../../src/shopping_agent/contracts.py#L44) and line 96 accept
quote strings based on character count without rejecting whitespace-only text.

Expected: both evidence quotes must contain a nonblank excerpt before any change is accepted.
Actual: whitespace normalizes to `""`; the empty string is a substring of every user message.
A mocked policy response to `show boots` can add hard price `< 60` using `" \t"` for both
quotes. A later `thank you` turn can use `"\n\t"` as a NEW_GOAL quote, increment the goal epoch
and retire that requirement. QA reproduced the complete ShoppingAgent flow with `status=ok`;
the parent independently reran that flow and the smaller linked reproduction below.

This bypasses the deterministic quoted-evidence check. It is separate from the documented
limitation that nonblank quoted text alone cannot prove semantic entailment. Live frequency
of such a policy proposal was not measured.

**Bounded recommendation:** reject normalized-empty update and requirement quotes before
state mutation. Add regressions for ADD and NEW_GOAL and test the two quote fields separately,
including tabs/newlines. Preserve acceptance of valid nonblank excerpts.

### F2 — P2: conflict detection and product matching disagree

**Found by:** QA for both manifestations; architecture independently found the product-type
case; parent reproduced both. This is one shared semantic-contract issue, not three defects.

**Locations:** [state.py:58](../../src/shopping_agent/state.py#L58)–70 intersects nonnumeric
`eq`/`in` values as exclusive scalar sets. [retrieval.py:38](../../src/shopping_agent/retrieval.py#L38)–49
normalizes department aliases; [retrieval.py:233](../../src/shopping_agent/retrieval.py#L233)–264
uses category-token containment for product types. [agent.py:153](../../src/shopping_agent/agent.py#L153)–159
blocks search/recommendation when the stored state reports any conflict.

Expected: a requirement set with an actual satisfying product should not be classified as
contradictory under the same supported field/operator semantics.

| Stored hard requirements | Matching fixture evidence | Actual baseline behaviour |
| --- | --- | --- |
| department `eq men` and `eq mens` | `Department=mens`; retrieval maps both aliases to `men` | Department conflict despite `assess().eligible=True` |
| product_type `eq boots` and `eq hiking boots` | Categories contain `Hiking Boots`; both category-token predicates pass | Product-type conflict despite `assess().eligible=True` |

QA ran each case through three bounded ShoppingAgent decisions: `status=error`, `searches=0`,
feedback `resolve_state_conflicts_before_search_or_recommendation`. The architecture probe
independently confirmed both product-type predicates match the same product while state
conflicts include `product_type`. Accepted edits persist, so a false conflict survives the
turn and needs correction/retraction rather than another identical SEARCH attempt.

**Bounded recommendation:** align field normalization/predicate semantics across conflict
classification and eligibility, or make conflict detection conservative where a contradiction
cannot be proven. Preserve hard gates and genuinely incompatible-value detection. Add
regressions for aliases and overlapping category predicates. A new ontology/framework or
broad solver is not justified by this finding.

## Reproduce the confirmed baseline defects

From the repository with the existing environment:

```sh
.venv/bin/python -W error::ResourceWarning docs/reviews/reproduce_phase_2_findings.py
```

Observed output:

```text
F1 blank ADD accepted: state_version=1, hard price < 60
F1 blank NEW_GOAL accepted on 'thank you': active_count=0, goal_epoch=1
F2 department: eligible=True, conflict=department, search rejected
F2 product_type: eligible=True, conflict=product_type, search rejected
```

The checked-in script uses only synthetic inputs and temporary files. Its assertions capture
these baseline defects; exit 0 means reproduction succeeded, not that correctness passed.
After a fix the observations should change; replace this snapshot with appropriate regression
coverage rather than preserve incorrect behaviour. It is not an evaluation framework.

## Architecture: future integration cautions

- **P3, context authority/result visibility:** [agent.py:84](../../src/shopping_agent/agent.py#L84)
  passes a mutable live Session to an injected context builder. The executor assumes the
  supplied current result was included for the policy; custom builders could mutate state
  or omit evidence. The default builder includes the result and does not mutate the session.
  At the first real memory integration, define/test no-mutation and mandatory-result-inclusion
  obligations or pass a read-only projection. Do not add speculative memory interfaces now.
- **P3, context provenance:** [agent.py:103](../../src/shopping_agent/agent.py#L103) logs a fixed
  baseline prompt-version constant independently of the injected builder. A future alternate
  builder could produce a different version. Actual messages and hashes are already recorded,
  so baseline evidence is retained. When adding an alternate builder, derive version metadata
  from its configuration/output and record actual included memory IDs where required.

The architecture reviewer otherwise found policy/context/tool/storage responsibilities small
and sufficiently separated for later scoped context integration. Existing actions already let
experience affect questions, queries, matching mode, eligible ranking and recovery. No future
memory layer is implemented, and these observations do not establish its correctness.

## Executed checks and successful scenarios

QA independently executed:

| Check | Result |
| --- | --- |
| `.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v` | 45 passed; no failures/skips |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check src tests` | Passed |
| `.venv/bin/python -m pip check` | No broken requirements; pip cache disabled with a permissions warning |
| Generated-fixture multi-turn probe | Five scenario groups passed; four manifestations of F1/F2 reproduced |

The five additional scenario groups covered: clarification plus hard/soft requirements,
correction and exclusion withdrawal; explicit new-goal retirement; provider failure after
commit plus restart/request replay/recovery; same-owner new-session and foreign-owner
isolation; and empty-result/invented-ID rejection followed by bounded clarification recovery.
They used the actual agent, temporary SQLite search and temporary session store with a mocked
policy. They are functionality evidence, not live shopping-success measurements.

Architecture performed a focused production-function contract probe, not a duplicate QA suite.
Parent reran both independent probe scripts and the checked-in minimal reproduction. Parent
also ran the existing 45-test suite and lint for the configuration checkpoint. TOML parsing,
required documented field/name checks and the two-role/concurrency check passed. Local
`codex features list` exited 0 without unknown-field diagnostics; that checks config startup,
not native role selection. `codex debug prompt-input` could not render under the current app
sandbox (`Operation not permitted`); this does not establish a role-format failure or success.

## Limits and next action

Unverified: live DeepSeek compatibility, extraction quality, prompt-injection resistance,
shopping success, actual shopping-provider cost/latency, original full-catalogue integration
in this review, remote images, additional OS/Python versions, disk-full/kill recovery and
native custom-role selection/feature enforcement. Existing full-data smoke evidence remains
historical and separate in [milestone notes](../milestone-1.md).

Recommend a separately scoped fix for F1/F2 with regressions before Phase 2 live validation.
The review does not authorise fixing them, starting a memory/evaluation/UI phase, or merging
this PR. `AGENTS.md`, runtime source/tests, original data and sessions remain unchanged.
