# ASTRA: Self-Improving Conversational Shopping Agent

ASTRA is a research-grade conversational shopping agent designed to investigate whether persistent multi-session memory and experiential learning can reliably improve an agent's future decision-making without negative transfer, hallucination, or cross-recipient contamination.

Operating over a frozen 50,000-product e-commerce catalogue, ASTRA combines foundation-model reasoning with deterministic Python safety gates outside the LLM, bounded turn execution loops, an event-sourced audit trail, and a three-tier memory architecture.

---

## Authoritative Documentation

| Document | Purpose |
| --- | --- |
| [**`README.md`**](file:///Users/yangxu/code/self-improving-agent/README.md) | Project overview, architecture, memory lifecycle, quickstart, and empirical results |
| [**`docs/reports/returning_customer_evaluation.md`**](file:///Users/yangxu/code/self-improving-agent/docs/reports/returning_customer_evaluation.md) | **Final Returning-Customer Evaluation Report** (22 paired visits, +9.1 pp Hit@10, case studies) |
| [**`docs/architecture.md`**](file:///Users/yangxu/code/self-improving-agent/docs/architecture.md) | Core system architecture, turn execution loop, contracts, and module boundaries |
| [**`docs/memory.md`**](file:///Users/yangxu/code/self-improving-agent/docs/memory.md) | Three-tier memory lifecycle: session state, persistent user semantic profiles, and procedural lessons |
| [**`docs/evaluation.md`**](file:///Users/yangxu/code/self-improving-agent/docs/evaluation.md) | Longitudinal evaluation benchmarks, scoring methodology, and ablation protocols |
| [**`docs/development.md`**](file:///Users/yangxu/code/self-improving-agent/docs/development.md) | Environment setup, 740+ offline tests, Streamlit Developer Console, and maintenance CLI tools |
| [**`docs/decisions/`**](file:///Users/yangxu/code/self-improving-agent/docs/decisions/README.md) | Architectural Decision Records (ADRs) and indexed historical review reports |

---

## Headline Returning-Customer Evaluation Findings

A controlled live longitudinal evaluation was conducted on November 2, 2026, comparing **Memory OFF vs. Memory ON across 22 matched pairs of returning visits** (`sequence >= 2`) spanning 10 diverse customer personas (44 sessions total) against the frozen 50,000-product catalogue.

| Metric | Memory OFF | Memory ON | Absolute Change | Relative Impact | Better Condition |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Target Hit@10 (Post-Hoc)** | 50.0% (11/22) | **59.1% (13/22)** | **+9.1 percentage points** | **+18.2%** | **Memory ON** |
| **Target Hit@1 (First Recommendation)** | 45.5% (10/22) | **59.1% (13/22)** | **+13.6 percentage points** | **+29.9%** | **Memory ON** |
| **Mean Reciprocal Rank (MRR)** | 0.4697 | **0.5909** | **+0.1212** | **+25.8%** | **Memory ON** |
| **Suitability NDCG@5** | 0.4861 | **0.5563** | **+0.0702** | **+14.4%** | **Memory ON** |
| **Penalized MTTC (Failures = 7)** | 4.00 turns | **3.50 turns** | **-0.50 turns** | **-12.5%** | **Memory ON** |
| **Estimated API Cost per Visit** | **$0.0146** | $0.0153 | +$0.0007 | +4.8% | **Memory OFF** |

> **Key Finding**: In Memory ON, **13 of 13 successful visits surfaced the target item at Rank #1** (59.1% of visits), with 12 of the 13 successes achieving this on the very first turn. In Memory OFF, the agent required exploratory turns or ranked targets lower down the list (MRR = 0.4697).

### Paired Visit Outcome Distribution
- **3 Net Gains (13.6%)**: Sessions that failed under Memory OFF but succeeded under Memory ON due to active preference reuse (`dev-bag-style-change/02`, `dev-capsule-wardrobe/02`, `dev-jewelry-simple/02`).
- **1 Target Rank Promotion**: Succeeded in both, but promoted the target from Rank #3 to Rank #1 under Memory ON (`dev-jewelry-simple/03`).
- **1 Regression (4.5%)**: Distraction from 4 injected historical memories induced agent hesitation, leading to dialogue stall (`dev-fashion/04`).
- **18 Unchanged (81.8%)**: 10 maintained successes and 8 catalogue-miss failures where the target product was not retrieved into the BM25 candidate pool.

All charts are available in PNG and SVG in [`docs/reports/charts/`](docs/reports/charts/):
- [**Hit@K Comparison Chart**](docs/reports/charts/hit_at_k_comparison.png) ([SVG](docs/reports/charts/hit_at_k_comparison.svg))
- [**Ranking Quality & NDCG Chart**](docs/reports/charts/ranking_quality_comparison.png) ([SVG](docs/reports/charts/ranking_quality_comparison.svg))
- [**Task Efficiency Comparison Chart**](docs/reports/charts/task_efficiency_comparison.png) ([SVG](docs/reports/charts/task_efficiency_comparison.svg))
- [**Paired Transition Breakdown Chart**](docs/reports/charts/paired_transition_breakdown.png) ([SVG](docs/reports/charts/paired_transition_breakdown.svg))

See the full [**Returning-Customer Evaluation Report**](docs/reports/returning_customer_evaluation.md) for detailed case studies, trace analysis, and statistical significance testing.

---

## What Problem ASTRA Solves

Conversational shopping agents face a fundamental dilemma across returning visits:
1. **The Amnesia Problem**: Without persistent memory, returning customers must repeatedly explain their sizes, budgets, brand preferences, and materials on every visit.
2. **The Hallucination & Contamination Danger**: Uncontrolled LLM memory frequently hallucinates constraints, leaks recipient details (e.g. applying a husband's gift sizing to the shopper herself), or rigidly over-filters searches when the shopper's intent changes.

**ASTRA solves this** by decoupling soft preference recall from hard deterministic filtering:
- Memory guides query generation and personalized candidate ranking, but **never hard-excludes catalogue items** unless explicitly confirmed in the current dialogue.
- Recipient-scoped memory namespaces prevent cross-recipient contamination.
- Verbatim quote evidence is mandatory for all requirement edits.

---

## System Architecture

```text
User Turn
  │
  ▼
[Python Orchestrator] ◄─── Read Active State (JSONL Replay)
  │                   ◄─── Retrieve Scoped Memories (SQLite profile.db + Embeddings)
  ▼
[DeepSeek Policy Agent] ─── Emits Structured JSON Proposal (SEARCH, CLARIFY, RECOMMEND, RESPOND)
  │
  ▼
[Deterministic Safety Gates]
  ├── Verbatim Quote Validation (prevents hallucinated requirements)
  ├── Hard Constraint Ledger Recheck (price ceilings, category exclusions)
  ├── Candidate Pool Verification (validates 10 distinct, verified catalogue IDs)
  └── Mandatory Follow-Up Question Contract (recommends products + conversational question)
  │
  ▼
[Multi-Stage Catalogue Retrieval]
  ├── Stage 1: BM25 Broad Candidate Generation over 50,000 Products (SQLite FTS5)
  ├── Stage 2: Deterministic Hard Filter Gate (drops ineligible items)
  ├── Stage 3: Personalized Memory-Aware Reranker (promotes preference-aligned candidates)
  └── Stage 4: Cap at exactly 10 eligible products (never pad, never hallucinate)
  │
  ▼
[Memory Consolidation & Persistence]
  ├── In-Session State: Append-only events.jsonl
  ├── User Profile: SQLite profile.db + human-readable profile.md
  └── End-of-Session: Centralized consolidation & procedural distillation
```

### Three-Tier Memory Architecture

1. **Tier 1 — In-Session Working Memory**:
   - Maintains active requirements, asked/disclosed attribute ledgers, and conflict detection.
   - Stored in append-only `events.jsonl` with lossless reference compaction and state snapshots.
2. **Tier 2 — Persistent User Semantic Memory**:
   - Stored in transactional SQLite (`profile.db`) and human-readable Markdown (`profile.md`).
   - Encodes customer preferences, sizes, brand affinities, budgets, and past purchases.
   - Employs cosine embedding similarity with temporal recency decay and lexical overlap bonus.
3. **Tier 3 — Procedural Experience Memory**:
   - Centralized lessons store (`lessons.db`) capturing cross-customer behavioral heuristics.
   - Enforces explicit verification gates before candidate lessons become active.

---

## Memory Lifecycle: Write, Consolidate, Retrieve, Apply

```text
       ┌────────────────────────────────────────────────────────┐
       │                   SESSION DIALOGUE                     │
       └───────────────────────────┬────────────────────────────┘
                                   │
                     1. EXTRACT & CONSOLIDATE
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │   Consolidation Engine (src/shopping_agent/user_memory.py) │
       │   - Extracts confirmed facts, preferences, and budgets │
       │   - Attaches verbatim quote evidence and confidence    │
       │   - Enforces first-person ownership & recipient tags   │
       │   - Resolves conflicts & supersedes outdated records   │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                2. WRITE
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │   Persistent User Store (data/user-memory/<SHA256>/)   │
       │   - profile.db (SQLite with vector embeddings)         │
       │   - profile.md (Human-auditable Markdown summary)      │
       └───────────────────────────┬────────────────────────────┘
                                   │
                     3. RETRIEVE (Next Visit)
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │   Contextual Retrieval & Selection                     │
       │   - Computes query-profile embedding similarity        │
       │   - Applies temporal decay & lexical overlap bonus     │
       │   - Filters by recipient scope (self vs. gift)         │
       │   - Formats compact memory cards into prompt context   │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                4. APPLY
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │   Execution & Reranking                                │
       │   - Informs DeepSeek query formulation                 │
       │   - Personalized candidate reranker boosts matches     │
       │   - Preserves deterministic hard gates without bias    │
       └────────────────────────────────────────────────────────┘
```

---

## Quickstart & Interactive Demo

### 1. Prerequisites and Installation
Requires macOS or Linux with Python 3.11+. Tested on macOS / Python 3.14 / SQLite 3.51.

```bash
# Clone the repository
git clone https://github.com/YangXu624/self-improving-agent.git
cd self-improving-agent

# Create virtual environment and install locked dependencies
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install -r requirements-ui-lock.txt
.venv/bin/python -m pip install --no-deps -e .
```

### 2. Build Catalogue Index
The catalogue consists of 50,000 products. Build the SQLite FTS5 index (no API key required):

```bash
.venv/bin/python -m shopping_agent index
```

### 3. Configure API Credentials
Create `.env` from `.env.example`:
```bash
cp .env.example .env
```
Edit `.env` and set your key:
```ini
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_MODEL=deepseek-chat
```

### 4. Launch the Streamlit Interactive UI
```bash
.venv/bin/python -m streamlit run streamlit_app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.
- **Persistent Memory Toggle**: Check "Remember me across chats" to test cross-session memory.
- **Product Cards**: Click "Buy (Demo)" to register immediate purchase reinforcement.
- **Developer Console**: Expand the drawer to inspect real-time execution traces, session events, memory cards, and the Mock Customer Lab.

### 5. Interactive CLI Chat
Run interactive shopping sessions directly from the terminal:
```bash
# Start a new session with persistent memory enabled
.venv/bin/python -m shopping_agent chat --user alice --user-memory
```

---

## Verification & Reproducibility

### 1. Reproduce Returning-Customer Evaluation Figures
Regenerate all headline metrics and visualization charts from the frozen evaluation artifacts:
```bash
python3 tools/analyze_returning_customers.py
```
Outputs the 4 publication charts to `docs/reports/charts/` and prints the verification table.

### 2. Run Full Test Suite (742 Tests)
Run all unit, integration, memory lifecycle, and regression tests:
```bash
PYTHONPATH=. pytest tests/ -q
```
*Expected: `742 passed, 1 skipped, 1 xfailed` (< 45s).*

### 3. Fast Standalone Smoke Test (< 0.1s)
Validate core deterministic safety gates without network or catalogue assets:
```bash
python tools/submission_smoke_test.py
```

### 4. Code Quality & Formatting
```bash
.venv/bin/ruff check src tests tools
.venv/bin/ruff format --check src tests tools
```

---

## Methodology, Caveats & Limitations

1. **Post-Hoc Hit@10 vs. K=5 Stopping Rules**:
   The live experiment evaluated dialogue stopping rules at $K=5$. Forensic trace inspection of all 64 sessions confirmed that zero target products occurred at ranks 6 through 10 in any turn. Consequently, post-hoc Hit@10 is mathematically identical to Hit@5.
2. **Clustered Data & Uncertainty**:
   The 22 returning visits originate from 10 distinct customer personas (2 to 4 visits per customer). Visits within a customer are correlated. A paired McNemar exact test on discordant pairs (3 gains vs. 1 regression) yields $p = 0.625$. A 1,000-iteration cluster bootstrap yields a 95% confidence interval of **$[-9.1\text{ pp}, +27.3\text{ pp}]$** for the Hit@10 delta.
3. **Causal Attribution**:
   While Memory ON achieved higher recommendation accuracy, dialogue paths naturally diverge across arms. Memory injection strongly correlates with ranking success, but does not constitute isolated causal proof for every visit.
4. **Compliance Auditor Lexical Flaw**:
   The compliance auditor flags violations using exact string subset matching (`tokens(wanted) <= tokens(actual)`). Natural language singular entity extraction (e.g., `necklace`, `button-down shirt`, `wallet`) fails against Amazon's plural category taxonomy (`Necklaces`, `Casual Button-Down Shirts`, `Wallets`). Qualitative review confirms recommendations satisfied user intent, but this metric is reported as an auditor limitation rather than an authoritative measure.
5. **Estimated vs. Billed API Costs**:
   Reported costs ($0.0146 OFF vs. $0.0153 ON per visit) are model execution estimates computed from recorded prompt, cache hit/miss, and completion tokens multiplied by provider list rates, rather than billed invoices.
