# Coding-agent guidance

## Current phase

This repository contains the project foundation, research documentation and an ignored local
copy of the user-approved TechJam product catalogue/image-URL mapping in `data/catalogue/`.
No sessions or evaluation cases were imported. Application implementation has not begun.
Read `README.md` and the documents in `docs/` before proposing implementation work.
Do not add application features, speculative modules, dependencies or a technology stack
until the relevant architectural decisions have been discussed with the user.

## Research and development principles

- Understand the research objectives before proposing implementations.
- Prioritise measurable, transferable improvement from confirmed experience; do not assume
  that adding memory improves performance.
- Distinguish session state, user memory, agent experience and catalogue knowledge.
- Do not assume every interaction should produce permanent memory.
- Prefer deterministic outcome verification over LLM self-evaluation where possible.
  Schema validation alone does not establish that a lesson is true or transferable.
- Preserve memory provenance, applicable scope, evidence and correction/withdrawal history.
- Keep experience-generating tasks and held-out evaluation tasks separate. Evaluation must
  not silently update the memories being evaluated.
- Compare against credible baselines and report failures, abstentions and negative transfer.
- Discuss major architectural decisions and their trade-offs before implementing them.
- Avoid unnecessary abstractions, speculative boilerplate and premature complexity.

## Repository boundaries and hygiene

- The previous ASTRA project and supplied ZIP are read-only reference material. Do not
  modify them or copy code, datasets, weights or configuration without an explicit decision.
  The user has approved copying only the frozen 50k catalogue and its associated image references;
  this does not authorise copying sessions or any other ASTRA assets.
- Do not modify the separate AutoML project or other neighbouring repositories.
- Work within this repository and verify the target remote before pushing.
- Never commit API keys, environment files, credentials, private datasets or local databases.
  Inspect staged changes and keep generated experiment output out of routine commits.
- Do not run paid model calls or acquire external datasets without authorization.
- When implementation begins, validate changes with relevant checks and report what was
  actually executed. Do not claim unverified capabilities or fabricate experimental results.
