# ASTRA Memory Architecture and Lifecycle

ASTRA implements a **three-tier memory hierarchy** designed to balance real-time conversational precision, cross-session personalization, and generalized operational improvements across all customers.

```mermaid
flowchart TD
    subgraph Tier1["Tier 1: In-Session Working State"]
        A[User Message] --> B[State Machine (state.py)]
        B --> C[Active Requirements & Goal]
        B --> D[Attribute Tracker (asked/disclosed)]
        B --> E[Event-Sourced JSONL (sessions.py)]
    end

    subgraph Tier2["Tier 2: Persistent User Semantic Memory"]
        F[End-of-Session LLM Consolidation (consolidation.py)]
        E --> F
        F --> G[SQLite Profile Store (user_memory.py)]
        G --> H[Semantic Retrieval & Temporal Decay]
        H --> I[Prompt Context Injection (context.py)]
        J[Simulated Purchases (purchases.py)] --> G
    end

    subgraph Tier3["Tier 3: Centralized Procedural Experience Memory"]
        K[Offline Lesson Distiller (distiller.py)]
        E --> K
        K --> L[Lesson Sanitizer & Verifier]
        L --> M[SQLite Lessons Store (lessons.db)]
        M --> N[Trigger & Situation Matching]
        N --> I
    end
```

---

## 1. Tier 1: In-Session Working State

The in-session memory tier tracks conversational state within an individual shopping visit. It is strictly scoped to the active session.

- **Primary Module:** [`src/shopping_agent/state.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/state.py)
- **Persistence:** [`src/shopping_agent/sessions.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/sessions.py) (`events.jsonl` and `state.json`)
- **Key Responsibilities:**
  1. **Active Requirements:** Tracks hard and soft constraints extracted during the turn (e.g. `color eq Black`, `price le 50.0`, `product_type eq boots`).
  2. **Quoted Evidence:** Every state update (`ADD`, `REPLACE`, `RETRACT`, `NEW_GOAL`) requires a verbatim text quote from the current user turn. Updates without quote evidence are rejected.
  3. **Attribute Working Memory:** [`src/shopping_agent/attributes.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/attributes.py) records attributes asked by the agent and disclosed by the customer to prevent repetitive questions.
  4. **Conflict Detection:** Identifies contradictory requirements within the turn (e.g., mutually exclusive sizes or conflicting category tokens).
  5. **Event-Sourced Replay:** All session interactions are logged as immutable JSONL events. Rebuilding state via event replay is fully deterministic. Compact v2 encoding uses zlib compression for large prompt strings without loss.

---

## 2. Tier 2: Persistent User Semantic Memory

User Semantic Memory persists facts, preferences, dislikes, and purchase history across multiple visits for a specific customer.

- **Primary Modules:**
  - Storage & Retrieval: [`src/shopping_agent/user_memory.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/user_memory.py)
  - End-of-Session Synthesis: [`src/shopping_agent/consolidation.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/consolidation.py)
  - Simulated Purchases: [`src/shopping_agent/purchases.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/purchases.py)
- **Lifecycle & Storage:**
  - Stored in per-user SQLite databases (`data/user-memory/<hash>/profile.db`) with atomic file locking (`.lock`).
  - Automatically exports human-readable markdown (`profile.md`) for inspection and auditability.
  - Backward compatibility: Can seamlessly import and migrate legacy `profile.md` files.

### End-of-Session LLM Consolidation
Rather than performing brittle per-turn regex or heuristic updates, ASTRA executes an **asynchronous LLM consolidation pipeline** at the end of each session:
1. Gathers full session dialogue and accepted state transitions.
2. Prompts the LLM with the customer's prior active memory profile.
3. Emits structured operations:
   - `ADD`: New preference, fact, or dislike (e.g., favorite color, preferred fabric).
   - `REPLACE`: Updates a superseded preference (e.g., changing fit preference from Slim to Relaxed).
   - `RETRACT`: Removes an explicitly withdrawn preference or constraint.
   - `NOOP`: No durable customer profile updates found.
4. Python verification verifies that all operations have valid quotes and conform to the Pydantic schema before committing transactions to SQLite.

### Vector Retrieval and Temporal Decay
When starting a new session or executing a turn:
- Memory entries are embedded using vector embeddings (`shopping_agent.embeddings`).
- Cosine similarity matches customer memories against the current user query or category.
- **Time-Decay Scoring:** Recency weighting ensures newer preferences rank higher than stale ones:
  $$\text{Score} = \text{CosineSimilarity} \times \exp(-\lambda \times \Delta t)$$
- Formatted compactly using [`src/shopping_agent/memory_views.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/memory_views.py) into concise Markdown injected into the prompt context.

---

## 3. Tier 3: Centralized Procedural Experience Memory

Procedural Experience Memory captures cross-customer behavioral lessons and shopping strategies learned from past session failures and successes.

- **Primary Package:** [`src/shopping_agent/experience/`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/)
  - Store: [`store.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/store.py) (`data/experience/lessons.db`)
  - Models: [`models.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/models.py) (`Lesson`, `ExperienceSnapshot`)
  - Distillation: [`distiller.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/distiller.py), [`extractor.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/extractor.py)
  - Sanitization: [`sanitizer.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/sanitizer.py)
  - Verification: [`verifier.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/experience/verifier.py)
- **Lesson Structure:**
  - **Situation:** Environmental context in which the rule applies (e.g. "Customer query contains ambiguous broad clothing nouns with multiple potential subcategories").
  - **Strategy:** Recommended action (e.g. "Ask a clarifying question to determine department before issuing broad lexical search").
  - **Rationale:** Underlying reason for the strategy.
  - **Triggers:** Structural conditions (e.g. `is_initial`, `empty_search`, `is_underspecified`).
  - **Confidence & Stats:** Running statistics tracking `usage_count`, `success_count`, and `failure_count`.
- **Promotion Lifecycle:**
  $$\text{Candidate} \xrightarrow{\text{Sanitizer + Verifier}} \text{Confirmed} \xrightarrow{\text{Evaluation Approval}} \text{Active}$$
  Lessons are scrubbed of any customer PII or test ground truth before entering the candidate pool. Active lessons are injected into the agent prompt context when trigger conditions match.

---

## 4. Simulated Purchase History

Simulated Purchases provide immediate feedback on customer selections:
- **Module:** [`src/shopping_agent/purchases.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/purchases.py)
- **UI Integration:** The Streamlit shopping interface displays a **Buy (Demo)** button on verified catalogue product recommendation cards.
- **Immediate Feedback Loop:**
  - Recording a purchase writes an immutable purchase record to the customer profile.
  - Automatically records product title, ASIN, price, categories, and timestamp.
  - Purchase records are immediately surfaced in the customer profile drawer under "Simulated Purchases".
  - Subsequent session consolidations and semantic retrieval factor in purchased items to reinforce established tastes.

---

## 5. Scientific Findings and Truth in Advertising

Across our extensive evaluations (including the 36-visit longitudinal benchmark and the 12-visit memory-sensitive benchmark), we establish the following empirical findings:

> [!IMPORTANT]
> **When Memory Matters vs When It Is Redundant:**
> 1. **Fully-Specified Tasks (Redundancy):** When customers state all their needs explicitly in the opening message of each visit (e.g. "I want black running shoes under $80"), enabling cross-session memory produces **zero change** in recommendation performance ($\Delta = 0.0$ in Hit@10). Memory does not replace search retrieval.
> 2. **Underspecified Recurring Tasks (Memory-Sensitive):** When customers omit recurring personal preferences in subsequent visits (e.g. "I need running shoes", omitting their previously stated preference for Black and size 10), cross-session memory improves Target Hit@5 from **0.0% to 100.0%** (+100% gain).
> 3. **Conflicting Tasks (Safety):** When customers explicitly override a prior preference (e.g. buying a gift or trying a new color), ASTRA's prompt and state machine respect the explicit turn instruction without memory interference (100% resolution).
