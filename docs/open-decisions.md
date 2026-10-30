# Open decisions

The future-memory and evaluation questions below remain open. Milestone 1 has since been
approved and implemented for review: direct bounded LLM orchestration, DeepSeek first,
JSONL events/JSON snapshots, SQLite FTS5/BM25 and a local CLI. See `milestone-1.md` for the
chosen contracts, limitations and verification. No agent framework or frontend was introduced.
Persistent user memory, agent experience and evaluation remain outside the approved baseline.

## Task scope and decision-making workflow

- What constitutes a shopping task, success, failure and appropriate abstention?
- Baseline decisions are CLARIFY, SEARCH, RECOMMEND and RESPOND. How should later
  scoped experience influence these decisions and support recovery?
- Baseline state edits and search/recommendation gates execute in trusted Python. What
  independent outcome evidence will later verify shopping success and procedural learning?
- How are current hard constraints protected, and when could a relaxation be proposed?
- Initial catalogue selection is settled: the user approved the frozen TechJam 50k product
  records and associated image references, without sessions or other assets. Attribute quality,
  variant handling, evaluation suitability and any future category expansion remain open.
  Reuse of additional ASTRA data or components requires an explicit later decision.

## Responsibilities and boundaries of memory

- What belongs in session state, user memory, agent experience and catalogue knowledge?
- Which preferences are explicit, inferred, tentative, stable or context-dependent?
- What is private to a user, and what experience can legitimately generalize across users?
- How do current statements, historical preferences and general advice interact?

## Experience confirmation and lifecycle

- What evidence permits writing, confirming or promoting a candidate lesson?
- How are source success, procedural attribution and cross-task validation distinguished?
- What are the contracts for ADD, CONFIRM, REFINE, SUPERSEDE, RETRACT and NO_OP?
- How are contradictory evidence, scope changes, outdated advice and withdrawal handled?
- What role, if any, does human confirmation play?

## Retrieval and consolidation

- How are experiences represented, indexed, ranked and checked for applicability?
- When are raw episodes useful, and when is consolidation justified?
- How are context budgets, actual memory inclusion and conflicting advice managed?
- How can target-specific feasibility be checked before applying a source procedure?

## Evaluation design

- What information is hidden from the agent, and what can the shopper disclose and when?
- How are acceptable products, unknown attributes and unsatisfiable tasks represented?
- What are the primary metric, baseline conditions, checkpoints, budgets and held-out splits?
- Which generalisation claims are justified, and how are uncertainty and regressions reported?
- How would human evaluation complement a simulator?

## Technology and delivery

- Whether future complexity justifies a framework beyond the current direct orchestration.
- Later provider adapters and retrieval strategies beyond the DeepSeek/FTS5 baseline.
- Frontend stack, hosted deployment, authentication and operating costs.
- Acceptance criteria for Level 2, Level 3 and controlled memory evaluation.

Future memory and evaluation work requires further design discussion and approval. The
user-authorised Milestone 1 baseline does not authorise implementing these future layers.
