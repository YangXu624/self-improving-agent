# LangChain / LangGraph experimental comparison

Recommendation: **keep ASTRA's custom shopping core; consider LangGraph selectively for the
memory lifecycle after the primary redesign stabilizes.** The working alternative gives a
clear graph and standard model/tool hooks, but this implementation does not reduce overall
handwritten lifecycle code or show a runtime advantage. There is no evidence here to support
a broad migration or a claim of improved recommendations.

## Baseline, isolation and method

Comparison baseline: `6e7b42cb77b6389c9b154e5b967ee699385a7572` (merged PR #28).
Implementation checkpoint: `4e7ad5b`. Worktree: `/Users/yangxu/code/astra-langchain-refactor`,
branch `experiment/langchain-refactor`. Antigravity's worktree and uncommitted memory redesign
were neither modified nor copied. All experiment state is under this worktree's ignored
`data/langchain-experiment/`. No paid requests were made.

The runner uses the same pre-existing synthetic catalogue and scripted decision functions for
both implementations, with real SQLite BM25, real session files, and real framework execution.
It compares status/action, presented IDs/facts, state version, closure reason and model/search
counts. Random search/session/requirement IDs and wording of safe closure messages are excluded.
This tests equivalence under supplied decisions; it cannot establish that live models will
choose equivalent decisions after changing from JSON mode to native tools.

Six scenarios × 20 repeats × two implementations = **240 offline turns**, all paired checks
passed. Execution order alternates. Timings are medians from Python 3.14.3, macOS arm64; graph
construction is measured separately and checkpoints are disabled in this microbenchmark.
The benchmark's temporary sessions are deleted; the full local measurements are preserved in
`data/langchain-experiment/comparison-final.json`. A sanitized summary, environment description,
verification results and SHA-256 of those raw samples are committed at
[`experiments/langchain/comparison-summary.json`](../../experiments/langchain/comparison-summary.json).

Reproduce from the repository root, using the isolated environment:

```sh
.venv/bin/python -m experiments.langchain.compare --output data/langchain-experiment/comparison-new.json
```

The runner refuses to overwrite results and blocks socket connections. The ordinary baseline
application, evaluator, scorers, frozen datasets, catalogue and index implementation are unchanged.

## Runtime observations

| Scenario | Calls / searches, both | Custom turn ms | Framework turn ms | Custom request bytes | Framework request bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| Respond | 1 / 0 | 2.08 | 5.30 | 8,620 | 12,956 |
| Search → recommend | 2 / 1 | 4.08 | 8.13 | 18,554 | 27,226 |
| Hard-price filter | 2 / 1 | 4.47 | 8.52 | 18,311 | 26,983 |
| Unseen-ID rejection → repair | 3 / 1 | 5.61 | 10.73 | 28,544 | 41,552 |
| Repeated empty search | 3 / 1 | 4.87 | 9.58 | 26,538 | 39,546 |
| Search on last model call | 1 / 0 | 2.09 | 5.15 | 8,620 | 12,956 |

Framework construction adds roughly 2.7–2.8 ms per adapter, versus approximately 0.003–0.004 ms
for the custom executor. Applications can retain a compiled adapter rather than reconstruct
it on every message. These are local synthetic timings with no network/model latency; they
are not predictions of end-user response time. The benchmark includes audit and disk-write
work, so it is not an isolated measurement of scheduler overhead.

Request bytes are a **proxy**, calculated from equally serialized messages plus native tool
schemas. They are not tokenizer counts or exact provider billing. The original JSON schema
is removed from the native prompt, but four closed tool schemas still repeat common update
fields. Across these scenarios the framework representation is about 46–50% larger. Actual
live prompt/cache/completion token usage, latency and cost remain unmeasured. Mock provider
tests verify usage accounting but cannot supply live usage observations.

Neither implementation automatically retries a provider failure. A schema/tool validation
rejection may consume a later decision call within the same bound. The framework prevents
parallel actions, refuses uninspected IDs, rechecks current eligibility, and ends terminal
actions without an extra model call. Empty-search and stale-state fixtures match baseline
call counts. Exception types, node phases, model requests, tool-call IDs and rejections are
locally audited; arbitrary SDK exception text is not persisted.

## Code, abstractions and dependencies

Raw source lines include blanks and docstrings; they are an inventory, not a maintainability
score. The pinned implementation has:

| Scope | Lines / count | Interpretation |
| --- | ---: | --- |
| Original `shopping_agent/agent.py` | 770 lines | Existing orchestration, validation and optional memory integration |
| Alternative `engine.py` | 355 lines | Deterministic tool executor, state/search guards and staging |
| Alternative `middleware.py` | 149 lines | Model/tool dispatch guards, dynamic context and audit |
| Alternative `workflow.py` | 234 lines | Graph construction, session boundary and persistence |
| Alternative `memory.py` | 80 lines | Explicit session-end reconciliation/extraction |
| Alternative core subtotal | **818 lines** | 48 more than the original loop; responsibilities are split more visibly |
| Alternative provider | 65 lines | SDK adapter with unchanged accounting injected |
| Entire optional package | 1,083 lines | Includes provider, separate CLI, offline demo and package constant |
| Baseline orchestration lines actually deleted | **0** | Required parallel implementation is preserved |
| New declared Python types | 6 | Turn, middleware, graph state, adapter, provider, demo model |
| Direct optional framework dependencies | 4 | LangChain, LangGraph, DeepSeek integration, SQLite checkpointer |
| Framework dependency closure | 48 distributions | Pinned optional installation, including baseline Pydantic dependencies |
| Baseline runtime dependency closure | 5 distributions | Pydantic and its runtime dependencies; excludes UI/dev extras |
| Additional runtime distributions | **43** | Relative to the baseline runtime closure on the tested platform |

The visible model/tool loop is supplied by `create_agent`, but much of ASTRA's loop is trust
validation and persistence rather than generic orchestration. Those duties remain handwritten.
A candidate recommendation still needs a visibility receipt, valid IDs, current versions and
hard-constraint rechecks. Native tooling does not eliminate that responsibility.

New framework concepts include `BaseChatModel`, tool schemas/injected runtime, middleware hook
ordering, graph state/conditional edges, checkpointers, and SDK usage/error semantics. The
explicit graph helps inspect the workflow, but understanding the whole turn now requires
following both an outer workflow and an inner agent graph plus ASTRA's authoritative log.

Adding a tool is straightforward at the framework boundary, then still needs the shared
allowlist, contract mapping, deterministic executor, guard tests and audit semantics. Adding
or rearranging a memory phase is clearer in the graph: named nodes and a conditional edge
express continuation versus end consolidation. A change to atomicity or memory reconciliation
still belongs to ASTRA's stores and validators. The checkpoint is not a substitute for them.

## Behavioral coverage and limits

**30 new tests pass**, including integration through the unchanged `DialogueRunner` and
`target_score`. The complete suite ran **660 tests: 654 ordinary passes, five skips and one
expected failure**, with no unexpected failures/errors. Ruff lint/format, dependency checks
and an offline CLI smoke passed.

The five skips are explicit: one actual-catalogue taxonomy check, three expanded-customer
checks requiring the ignored 50k assets, and one pinned tokenizer-asset test. These assets
were not installed or copied into the isolated worktree. The known compound `wristwatch`
regression remains expected-failing. Results do not claim full real-catalogue validation.
Local full logs are in `data/langchain-experiment/verification/suite-final.log` and the
machine-readable skip list is included in the committed comparison summary.

| Requirement | Evidence | Remaining limitation |
| --- | --- | --- |
| Search, recommendation, hard constraints | Real BM25 fixtures, missing price excluded, unknown ID rejected, state changes invalidate search | Synthetic catalogue; live query selection unknown |
| Clarification and continuation | Two-turn budget clarification and resolved-state flow | Legacy context only; compact v7 aliases are not ported |
| Budgets and termination | Last-call search denied, duplicate empty search executes once, terminal action consumes no extra call | No live planner effectiveness measurement |
| User memory OFF/ON and owner isolation | OFF methods are patched to fail if touched; separate owners/sessions | Local ownership labels are not hosted authentication |
| Cross-session memory/correction | Staging → end persistence → new-session recall; explicit replacement supersedes prior fact | Pending same-session proposals have no durable IDs yet |
| End-of-session reconciliation | Explicit application end, evidence validation, revision-conflict refusal, disk-write interruption | No transaction spanning JSONL/profile/checkpoint; manual interrupted-turn recovery |
| Central procedural memory | Shared active lesson retrieved/injected/applied for two owners; new lesson stays candidate | Template extraction only; no autonomous generalized learning |
| Objective scoring | Existing target runner/scorer accepts actual presented IDs and stops at Hit@K | No change to ground truth/scoring, no live quality claim |
| Provider compatibility and spend | Exact configured endpoint/model tested through HTTP MockTransport; schemas exclude runtime; no SDK retries; unknown usage blocks | No paid smoke; provider estimates are not invoices |
| Debugging/checkpoints | Phase/tool/rejection logs, SQLite inspection after restart, completed request replay | Diagnostic checkpoints are not automatic safe replay |

Functional parity is bounded, not complete: session-end user-memory persistence deliberately
differs from the original per-turn writes; native tool transport changes prompts and malformed
response handling; compact context/card variants are not implemented. These differences are
listed in the [architecture and run guide](../langchain-experiment.md). The baseline lacks
embedding retrieval, so Antigravity's concurrent embedding work remains a future integration
point rather than a claimed feature of this branch.

## Adoption decision

What improves: the memory lifecycle has visible nodes/edges; model and tool instrumentation
has standard hooks; tool schemas and SDK integration are reusable; optional checkpoints expose
workflow phase/response without inventing another semantic memory store.

What becomes harder: thread-scoped SQLite connections, middleware order and terminal routing,
framework/SDK compatibility, a second workflow-state representation, native schema overhead,
43 additional distributions, and the need to reconcile checkpoint expectations with ASTRA's
existing fail-closed request log. The tested implementation is more code overall, despite
removing the handwritten decision loop from the alternative path.

Keep the catalogue, BM25, eligibility gates, user-memory evidence/reconciliation, event-log
ownership, procedural review lifecycle, independent scorers and cost accounting custom.
Consider adopting **LangGraph selectively** if a stable memory redesign develops enough
branching, review or inspection needs to justify it. This experiment supports that narrower
option as an engineering direction; it does not measure a standalone Graph-only implementation.

Before a broader migration, separately authorize a small controlled live comparison with
fixed models, equivalent state/context facts, frozen catalogue and tasks, identical call/money
caps and complete audit traces. Report transport/prompt differences, invalidity, memory
persistence/retrieval/injection/application and actual usage. Preserve previous runs and
keep held-out results outside learning. Broader adoption needs evidence of reduced maintenance
or improved reliability that exceeds the demonstrated dependency and integration cost.
