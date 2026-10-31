# Development review subagents

These are **Codex development reviewers**, separate from ASTRA's shopping decision policy
and any future simulated shopper. They do not add runtime agents, memories or application
features. Configuration follows the [official Codex custom-agent format](https://learn.chatgpt.com/docs/agent-configuration/subagents),
checked on 31 October 2026 against local Codex CLI `0.165.0-alpha.1.2`.

## Configured roles

| Agent | Responsibility | Expected evidence | Boundary |
| --- | --- | --- | --- |
| `qa_tester` | Functional correctness and regressions, especially multi-turn shopping | Executed commands/results, expected vs actual behaviour, minimal reproduction and missing regression coverage | Does not redesign architecture or implement fixes |
| `architecture_reviewer` | Responsibilities, interfaces, ownership and dependency/data flows | Source references, traced contracts, concrete impact and bounded recommendations/trade-offs | Does not duplicate the QA suite or implement future memory layers |

Project-scoped definitions live in `.codex/agents/qa_tester.toml` and
`.codex/agents/architecture_reviewer.toml`. Each declares `name`, `description` and
`developer_instructions`; no model/provider is pinned. `.codex/config.toml` limits concurrent
spawned agents to two. There are no global/user configuration changes or new dependencies.
The installed and configured roles are not a mandate to invoke both on every change.

Both roles prohibit tracked-file/production edits unless explicitly authorised, live shopping
API requests, credential access, dependency installation, Git mutations and further delegation.
QA may use temporary fixtures/scripts and test output; architecture may use isolated contract
probes. Existing datasets and sessions remain untouched. Apps, plugins, persistent Codex
memories and the permission-request tool are disabled in each custom definition. Shell remains
available for local inspection/tests. These reductions apply when the client loads that custom
agent definition; they are not a substitute for sandbox controls.

**Permission boundary:** custom agents inherit the parent's sandbox/approvals. Read-only
instructions do not create an OS-enforced read-only sandbox, and putting `sandbox_mode` or
`approval_policy` into a custom file would not override parent permissions. For an enforced
read-only review, choose read-only permissions for the parent review session. In a normal
writable development chat, reviewers rely on the explicit no-edit instruction and parent
verification of the diff. Explicitly authorised fixes should be a separately scoped task;
this setup does not grant such permission.

## When and how to use

- Request QA for substantial changes to state/decisions, retrieval, persistence or recovery,
  or when a concrete failure needs independent reproduction.
- Request architecture review for cross-component contract changes, new ownership/data flows
  or a proposed memory integration. Ask for inspection of today's interfaces, not future code.
- Do not delegate typo, formatting or trivial documentation changes. Do not run both reviewers
  just because a commit exists. Match the review scope to the risk.
- Give each reviewer a baseline commit/diff, acceptance criteria, allowed commands and evidence
  limits. They work independently before the parent shares or reconciles conclusions.
- The parent checks reproduction evidence, distinguishes confirmed defects from future risks,
  deduplicates findings, reports limitations and proposes the next bounded fix. Reviewers do
  not approve merges or count test success as evidence of model quality or learning.

In a local Codex session using this project's custom definitions, a suitable request is:

> Use qa_tester to independently test the Phase 2 multi-turn shopping behaviour. Use
> architecture_reviewer to inspect policy/context/search/storage boundaries and compatibility
> with later memory layers. Work independently, make no tracked-file changes, use only local
> fixtures/mocked shopping responses, and consolidate evidence before proposing fixes.

No `AGENTS.md` edit was made to auto-trigger delegation. Current project instructions still
apply, including review/approval between phases and protected reference material.

## Demonstration and verification limits

The requested Phase 2 demonstration runs as two independent subagent tasks. Its consolidated
evidence will be recorded after both reports are checked; no findings are prewritten.

This chat's available spawn tool accepts a task name and instructions, not a custom-agent
selector. For this demonstration, each task explicitly reads and follows its committed TOML
instructions. This verifies the review workflow, not automatic custom-name discovery or the
feature reductions of a fresh local Codex session. The configured file format/fields are
checked against official documentation and parsed with Python `tomllib`. Native automatic
loading and OS-enforced read-only execution are not claimed as demonstrated here.

Codex subagents consume Codex model resources; this review does not call DeepSeek, Ollama or
other ASTRA shopping providers. A user-approved live shopping smoke test remains separate.

## Future roles — documentation only

| Role | Introduce when | Owns | Does not own |
| --- | --- | --- | --- |
| `evaluation_auditor` | Evaluation protocol/runner or benchmark claims are proposed | Experimental validity, scorer/denominator integrity, simulator leakage, splits, contamination and fair comparisons | Application regression testing or implementing the evaluator |
| `memory_auditor` | Persistent user/experience memory is designed or changed | Provenance, scope, write/withdrawal/correction/deletion lifecycle, conflicting lessons and user isolation | General architecture redesign, scorer validity or creating memory features |
| `security_reviewer` | Permissions, hosted access or candidate-code execution is proposed | Data/credential protection, access boundaries, untrusted content, sandbox/anti-gaming guardrails | Statistical evaluation or implementing unapproved security features |

No files, registrations or tasks for these three roles are created now. If a current reviewer
notices an adjacent concern, it may flag the evidence for later review without assuming that
future role's entire responsibility. Do not interpret this roster as approval of a new phase.
