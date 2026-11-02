# ASTRA Architectural Decision Records (ADRs)

This directory indexes the key architectural decisions, design rationales, and empirical outcomes governing ASTRA.

Historical chronologies are maintained in [`docs/decisions.md`](file:///Users/yangxu/code/self-improving-agent/docs/decisions.md) and deep-dive technical reviews in [`docs/reviews/`](file:///Users/yangxu/code/self-improving-agent/docs/reviews/).

---

## Index of Architectural Decisions

### [ADR-01: Frozen 50k Catalogue Baseline](file:///Users/yangxu/code/self-improving-agent/docs/decisions.md#architectural-and-research-decisions)
- **Status:** Adopted
- **Decision:** Use a frozen snapshot of the TechJam 50,000-product catalogue indexed via SQLite FTS5 BM25.
- **Rationale:** Ensures all benchmark comparisons, retrieval ablations, and memory studies operate against an unchanging, reproducible product corpus.

### [ADR-02: Structured Turn Execution & Safety Gates](file:///Users/yangxu/code/self-improving-agent/docs/decisions.md#correctness-fixes-31-october-2026)
- **Status:** Adopted
- **Decision:** Model proposals (`SEARCH`, `CLARIFY`, `RECOMMEND`, `RESPOND`) are parsed as strict Pydantic schemas and executed through Python validation gates outside the LLM.
- **Rationale:** Prevents hallucinated products, ungrounded attribute claims, or infinite search loops. State updates require verbatim quote evidence.

### [ADR-03: Event-Sourced Session Storage & Compact Encoding](file:///Users/yangxu/code/self-improving-agent/docs/decisions.md#compact-durable-events-31-october-2026)
- **Status:** Adopted
- **Decision:** Persist session interactions as immutable, append-only JSONL event logs with JSON state snapshots.
- **Rationale:** Enables deterministic event replay, full auditing, and crash recovery. Storage version 2 applies lossless zlib compression to large prompt strings, reducing storage footprint without loss of evidence.

### [ADR-04: Provider-Agnostic LLM Policy Interface](file:///Users/yangxu/code/self-improving-agent/docs/decisions.md#live-ui-policy-31-october-2026)
- **Status:** Adopted
- **Decision:** Abstract LLM completions behind a unified `DecisionPolicy` interface supporting DeepSeek, Claude, Gemini, OpenAI, and Deterministic Mock providers.
- **Rationale:** Decouples core agent orchestration and memory from specific foundation models. Facilitates 100% offline testing via mock providers without requiring live API keys.

### [ADR-05: Three-Tier Memory Architecture](file:///Users/yangxu/code/self-improving-agent/docs/memory.md)
- **Status:** Adopted
- **Decision:** Partition memory into three distinct tiers:
  1. *Session Working State:* Atomic dialogue constraints and asked/disclosed attributes.
  2. *User Semantic Memory:* Persistent SQLite profile with vector retrieval, temporal decay, and end-of-session LLM consolidation.
  3. *Centralized Procedural Experience Memory:* SQLite lessons store (`lessons.db`) capturing cross-customer shopping heuristics.
- **Rationale:** Clear separation of concerns; prevents cross-talk between transient turn requirements and persistent customer traits.

### [ADR-06: Strict Mandatory Recommendation + Question Contract](file:///Users/yangxu/code/self-improving-agent/docs/architecture.md)
- **Status:** Adopted
- **Decision:** Every conversational recommendation turn must present verified product cards accompanied by an engaging follow-up question.
- **Rationale:** Ensures the shopping assistant maintains active customer engagement while grounding recommendations in confirmed catalogue items.

### [ADR-07: Simulated Purchase Tracking](file:///Users/yangxu/code/self-improving-agent/docs/memory.md#4-simulated-purchase-history)
- **Status:** Adopted
- **Decision:** Integrate a **Buy (Demo)** button on verified product recommendation cards in the Streamlit UI, immediately recording purchases to the customer profile.
- **Rationale:** Bridges conversational preference learning with transactional choice feedback, enabling immediate reinforcement of customer tastes.

### [ADR-08: Memory Evaluation Integrity & Sensitive Benchmarks](file:///Users/yangxu/code/self-improving-agent/docs/evaluation.md)
- **Status:** Adopted
- **Decision:** Separate general longitudinal tasks (where opening prompts fully state constraints) from targeted memory-sensitive benchmarks (where recurring preferences are unstated).
- **Rationale:** Avoids false claims that memory improves general search. Explicitly documents that memory provides zero gain when user prompts are fully specified, and provides substantial gains (+100% Target Hit@5) on memory-sensitive recurring tasks.

### [ADR-09: Developer Observability & Simulation Tooling](file:///Users/yangxu/code/self-improving-agent/docs/development.md#4-streamlit-ui-and-developer-console)
- **Status:** Adopted
- **Decision:** Provide an integrated Developer Console featuring runtime parameter overrides, execution tracing, a Session Audit Explorer, and a Mock Customer Lab.
- **Rationale:** Empowers developers and evaluators to inspect internal state transitions, tool invocations, and multi-visit simulations without third-party monitoring dependencies.

---

## Historical Technical Reviews

Published design investigations and empirical audits are preserved in [`docs/reviews/`](file:///Users/yangxu/code/self-improving-agent/docs/reviews/):
- **Compaction & Efficiency:** `compact-memory-views.md`, `context-and-storage-compaction.md`
- **Integrity & Diagnostics:** `watch-decision-budget-audit.md`, `shopper-disclosure-integrity.md`, `conversation-reliability.md`
- **Longitudinal Pilots:** `stage-1-user-memory.md`, `stage-2-longitudinal.md`, `longitudinal-live-pilot.md`, `claude-v3-memory-pilot.md`
- **Experiential Memory:** `experiential-learning-readiness.md`, `experiential-memory-mvp.md`, `experience-pilot-integrity.md`
