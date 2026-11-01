# ASTRA: Codex handoff

Verified 1 November 2026. Repository: `YangXu624/self-improving-agent`, locally
`/Users/yangxu/code/self-improving-agent`. Read root `AGENTS.md` before working.

## Purpose and architecture

ASTRA is a conversational shopping research agent: understand requirements, clarify, retrieve
catalogue products and recommend grounded options. The objective is **measurable improvement
from experience**, not merely storing memories. It replaced an AutoML research direction;
the original TechJam ASTRA remains read-only reference material.

Python separates LLM decisions, context construction, validated state, deterministic retrieval
and persistence. CLI and Streamlit use DeepSeek; a separate `astra_eval` package owns private
shopper profiles, simulation and independent scoring. Production never imports evaluator
truth. See [architecture](../architecture.md), [decisions](../decisions.md),
[roadmap](../roadmap.md) and [research context](../project-context.md).

## Implemented components and storage

- **Shopping:** bounded `CLARIFY`, `SEARCH`, `RECOMMEND`, `RESPOND` loop; normally three model
  calls/two searches per turn. Python validates quoted state edits and recommendation IDs
  against actual model-visible, current, eligible candidates. No runtime scripted fallback.
- **Catalogue/retrieval:** 50,000 imported TechJam parent products, SQLite FTS5/BM25 plus
  deterministic hard filters. Missing required attributes are unknown. No production embeddings,
  bi-encoder, hybrid retrieval or cross-encoder. Card projections exist for controlled
  Experiment A. Sparse parent metadata cannot prove current availability or variant stock.
- **Session memory:** owned UUID directory containing authoritative append-only `events.jsonl`
  and rebuildable `state.json`; preserves conversation, actions, corrections, versions and
  asked/disclosed ledgers. Compact v7 prompts expose selected current state/recent dialogue,
  not exhaustive logs. CLI defaults to `data/sessions/`; UI uses `data/ui-sessions/deepseek/`.
- **Persistent user memory:** opt-in `data/user-memory/<SHA256(user_id)>/profile.md`: readable
  active facts/preferences/dislikes/purchases plus authoritative collapsed JSON audit history.
  Validated, evidence-backed updates; corrections/supersession preserved. Bounded lexical scope
  selection, not vector retrieval. OFF disables reads/writes. Recommendations do not imply purchases.
- **Procedural experience:** separate SQLite lessons, explicit review lifecycle and immutable
  hashed snapshots; extraction selects predefined templates, not autonomous code learning.
  Retrieval, actual prompt injection and accepted signature application are distinct from
  outcome improvement. Local `data/experience/pilot_store.sqlite` still has candidate
  `exp-e23002ac6fd9` and rejected `exp-ebffc34c0130`; neither may be activated without approval.
- **V3 shopper:** Claude/Ollama transports, generated opening/replies, private persona/current
  verified needs and condition/customer-isolated history. Python derives disclosures from text;
  the model does not self-report `reveals`. Claude Sonnet 5.5 omits sampling parameters and uses
  between-tools thinking/low effort, with the tested 512-output-token setting.

Details: [representations](../memory-representations.md), [user memory](../user-memory.md),
[experience integrity](../experience-pilot.md), [V3](../simulator-v3.md).

## Repository map

| Paths | Responsibility |
| --- | --- |
| `src/shopping_agent/agent.py`, `contracts.py`, `state.py`, `attributes.py` | Execution, schemas, validated edits, clarification ledgers |
| `context.py`, `memory_views.py`, `cards.py` | Bounded prompts, compact projections, candidate visibility |
| `retrieval.py`, `category_matching.py` | FTS5/BM25, eligibility, bounded category inflections |
| `sessions.py`, `event_codec.py`, `user_memory.py`, `experience/` | Separate persistence and memory lifecycles |
| `provider.py`, `configuration.py`, `cli.py`, `ui_service.py`, `ui.py` | DeepSeek adapter, configuration and application interfaces |
| `src/astra_eval/customers.py`, `oracle.py`, `scoring.py`, `target_scoring.py` | Frozen visit compilation, catalogue evidence, separate scoring modes |
| `dialogue.py`, `longitudinal.py`, `longitudinal_report.py`, `disclosed_compliance.py` | Session/timeline execution, reports, disclosed-state compliance |
| `shopper_v3.py`, `shopper_providers.py`, `shopper_evidence.py`, `api_budget.py` | Autonomous shopper, auditing, journals and shared cost reservations |
| `tests/`, `experiments/`, `docs/` | Deterministic suites, protocols/fixtures, documentation |

## Git and development state

[PR #21](https://github.com/YangXu624/self-improving-agent/pull/21) expanded customers;
#22 phased evaluation; #23 disclosure integrity; #24 autonomous V3; #25 stopped preflight;
#26 Sonnet compatibility/accounting; #27 stopped live pilot; and
[PR #28](https://github.com/YangXu624/self-improving-agent/pull/28) reliability hardening
are **merged into main**. No open PR dependencies were returned by GitHub.
Main is `6e7b42c`; PR #28 head is `6589807`.

Handoff branch: `plan/staged-v3-canary`, based on that merge. Prior equivalent
rebased PR histories have different hashes; compare trees rather than assuming hash identity.
Before this documentation commit, only these files were untracked:
`experiments/longitudinal/staged_canary.py` and `tests/test_staged_canary.py`.
They remain **uncommitted draft canary orchestration**, not part of merged production.
Preserve and review them; do not restart their implementation blindly.

## Evaluation, evidence and limitations

Frozen original `experiments/longitudinal/customers.dev.json` contains three customers/12
visits; `customers.dev-expanded.json` preserves them and adds eight customers: 11/36 total.
Witnesses, budgets and evidence hashes are catalogue-oracle validated. Development results
must not alter held-out tasks. Target mode checks actually presented target IDs and stops
immediately at Hit@K; preference mode scores broader suitability separately. Hidden-profile
mismatches are distinct from disclosed-state hard violations. OFF/ON also differ in memory
instructions/schema; first-visit differences cannot establish recall benefit.

[PR #27 evidence](../reviews/claude-v3-memory-pilot.md): three Capsule OFF visits started,
two valid unsuccessful, third invalid after accepting a previously shown US$27.99 product
following text-only messages. ON never started: **no paired memory-effectiveness result**.
Preserve `data/eval/longitudinal/claude-sonnet55-readiness-20261101/` and all older artifacts.
Latest combined ledger accounts US$0.127290224, including US$0.05 historical uncertainty;
recheck before execution. Provider estimates are not invoices; missing usage is never free.

[PR #28 review](../reviews/conversation-reliability.md) documents session/goal-scoped prior
offers, category number matching, repeated-empty-search guards, conditional-color validation,
stale-retraction handling and isolated-versus-systemic stopping. **Live recovery is unverified.**
The compound `wristwatch` taxonomy regression remains expected-failing; singular `watch` passes.
Disclosure auditing remains bounded English/lexical reasoning, with possible false positives,
missed paraphrases and leakage. Memory exposure/product association does not prove causal use.

Latest working-tree suite actually executed: **641 tests, one skipped tokenizer asset, one
expected failure**; includes 11 uncommitted canary tests. PR #28 baseline recorded 630 tests
with the same skip/expected failure. Ruff lint/format passed. All 302 inventoried pre-existing
artifact files retained matching hashes. No paid canary calls occurred.

## Next steps and controls

Review merged PR #28 against #27, then finish reviewing the draft canary. Local
`data/eval/canaries/v3-staged-20261101/` contains only frozen subset JSON and a preparation
manifest, **no live sessions or pass receipt**. Dry plans validated:

1. Activewear tank-top and Simple Jewelry anklet first visits: two independent OFF sessions.
2. Only after reviewed Stage-1 success: Activewear visits 1–2, OFF then ON, four fresh sessions.

Proposed shared incremental cap: US$1; absolute accounting ceiling US$1.127290224, also below
US$10 global. Stage 1 reserves at most US$0.40 additional; Stage 2 carries actual spend forward.
Projected US$0.15–0.55 is provisional, not a completion guarantee. Maximum calls: 108 DeepSeek,
72 shopper attempts. **New explicit user approval is still required before any paid call.**
Systemic API/integrity/accounting errors stop globally; isolated invalid sessions remain labelled
and block dependent visits, not independent customers. Inspect actual memory disclosure →
persistence → retrieval → injection → search/recommendation. Only later consider the full
24-session pilot; tiny canaries cannot prove benefit.

Preserve scoring/ground truth, historical traces and catalogue hashes. No automatic merges,
force-pushes, lesson activation or experiment restarts. Keep arbitrary SQL/code execution and
score tailoring outside the agent. New frameworks, automatic experience learning and semantic
retrieval remain deferred decisions. Follow feature
branches, tested atomic commits and reviewable PRs. Do not edit `AGENTS.md` without approval.

## Useful commands

From repository root; installation commands are instructions, not newly executed setup:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m pip install -r requirements-ui-lock.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

Local ignored `.env` uses `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL=deepseek-flash`,
`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL=claude-sonnet-5-5`. Never print credentials.
A clone lacks ignored catalogue/index/memory/evidence assets.

Free draft canary plan: `.venv/bin/python -m experiments.longitudinal.staged_canary stage1
--root data/eval/canaries/v3-staged-20261101` (join onto one line). Stage 2 uses `stage2`.
Without `--live` neither contacts providers. After approval, review the draft driver and use
`--live`; Stage 2 additionally requires `--review` with matching Stage-1 evidence hashes.
For committed runner options use `.venv/bin/python -m astra_eval longitudinal --help` and
[longitudinal instructions](../longitudinal-evaluation.md). Historical readiness commands have
stale costs/output paths: never reuse them verbatim or overwrite stopped runs.
