# Open decisions

These questions are intentionally unresolved. This document records discussion topics, not
an implementation plan, dependency list or approved architecture.

## Task scope and decision-making workflow

- What constitutes a shopping task, success, failure and appropriate abstention?
- Which decisions can the agent make: clarify, retrieve, filter, rank, recommend or recover?
- Which actions belong to trusted application logic, and how is their outcome verified?
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

- Agent framework or direct orchestration, if any.
- LLM provider/model, database/storage implementation and retrieval technology.
- Frontend stack, deployment environment and operating costs.
- Development milestones and criteria for moving from a minimal experiment to a live app.

The next discussion begins with the conversational agent's decision-making workflow and the
responsibilities of the three proposed memory layers. No application implementation is
authorised by these open questions alone.
