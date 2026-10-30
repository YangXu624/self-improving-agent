# Self-Improving Conversational Search Agent

A research project exploring whether an agent can learn useful procedures from confirmed
shopping interactions and apply them to new conversational search tasks.

The objective is measurable, transferable behavioural improvement—not merely persistent
chat history, product retrieval or user personalization:

**Complete a task → confirm the outcome → distil and validate experience → retrieve relevant
experience → evaluate its effect on a new task.**

The proposed context distinguishes session state, long-term user memory, reusable agent
experience and catalogue knowledge. These roles and their implementation remain open for
discussion. Memory is not assumed to improve performance; negative transfer and regressions
are outcomes to measure.

## Current status

Documentation-only foundation. No application features or dependencies have been added.
No agent framework, LLM provider, database implementation or frontend stack has been selected.

This is a new project inspired by [ASTRA](https://devpost.com/software/reimagining-the-digital-experience).
Its reference implementation and the earlier AutoML project remain separate and unchanged.
No reference code, datasets, model weights or configuration have been copied here.

## Research documents

- [Project context](docs/project-context.md): background, previous experiments and the new direction.
- [Research questions](docs/research-questions.md): hypotheses, selection criteria and evaluation concerns.
- [Open decisions](docs/open-decisions.md): unresolved architectural and experimental choices.
- [Agent guidance](AGENTS.md): principles for future coding-agent sessions.

The next discussion concerns the conversational agent's decision-making workflow and the
responsibilities of the three proposed memory layers. Implementation has not begun.
