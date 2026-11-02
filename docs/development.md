# ASTRA Development, Testing, and Tooling Guide

This document describes local environment setup, testing standards, developer tooling, and debugging workflows for the ASTRA repository.

---

## 1. Environment Setup

ASTRA requires **Python 3.11+**.

### Clone and Virtual Environment
```bash
git clone https://github.com/YangXu624/self-improving-agent.git
cd self-improving-agent

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install locked dependencies in editable mode
pip install -r requirements-lock.txt
pip install -r requirements-ui-lock.txt
pip install --no-deps -e .
```

### Environment Configuration (`.env`)
ASTRA uses explicit file-based configuration without polluting process environments. Copy `.env.example`:
```bash
cp .env.example .env
```

Available keys (all optional for testing, required only for live model requests):
```bash
DEEPSEEK_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```
> [!NOTE]
> Tests run with deterministic mock providers and **never** invoke paid APIs or require live credentials.

---

## 2. Testing Suite

ASTRA maintains an extensive suite of over 700 regression, unit, and integration tests covering the shopping agent, state machines, memory stores, UI components, and evaluation harness.

### Running Tests
```bash
# Run the entire test suite
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests

# Run a specific test module
PYTHONPATH=src:tests .venv/bin/python -m unittest tests/test_agent.py
PYTHONPATH=src:tests .venv/bin/python -m unittest tests/test_session_audit_and_mock_lab.py
PYTHONPATH=src:tests .venv/bin/python -m unittest tests/test_memory_sensitive_benchmark.py
```

### Testing Guarantees
1. **100% Offline & Deterministic:** Tests use pinned mocks, simulated HTTP responses, or in-memory SQLite instances. No external network calls are made.
2. **Package Isolation:** `src/shopping_agent/` must never import `astra_eval` directly. This isolation boundary is enforced by `tests/test_eval_experiment.py`.
3. **No Weakened Assertions:** New features or refactors must pass existing tests without relaxing validation gates or thresholds.

---

## 3. Code Quality and Linting

ASTRA enforces strict linting and formatting via Ruff:

```bash
# Check for lint issues across source, tests, tools, and experiments
.venv/bin/ruff check src tests tools experiments

# Check code formatting
.venv/bin/ruff format --check src tests tools experiments

# Auto-fix fixable issues
.venv/bin/ruff check --fix src tests tools experiments
.venv/bin/ruff format src tests tools experiments
```

---

## 4. Streamlit UI and Developer Console

ASTRA provides a feature-rich Streamlit application for end-user shopping, customer profile management, and deep developer observability.

### Launching the Application
```bash
.venv/bin/streamlit run streamlit_app.py
```

### Developer Console Architecture
Located in the main application under the expandable **Developer Console** drawer (and powered by [`src/shopping_agent/dev_console.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/dev_console.py)):

1. **Parameters Tab:**
   - Modify active runtime configuration overrides ([`src/shopping_agent/runtime_config.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/runtime_config.py)).
   - Switch card presentation profiles (`baseline`, `v3_k10`, `v3_k5`, `shared_k10`, `shared_k5`).
   - Toggle memory serialization formats (`legacy`, `compact_v7`).
   - Adjust decision turn budgets and search limits.
2. **Execution Trace Tab:**
   - Real-time visualization of structured execution traces ([`src/shopping_agent/trace.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/trace.py)).
   - Turn latencies, LLM prompt and completion token counts, tool invocation details, and verification outcomes.
3. **Session Audit Explorer:**
   - Implemented in [`src/shopping_agent/session_audit.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/session_audit.py).
   - Allows selecting any customer (manual shopper or synthetic evaluation customer) and session ID.
   - Deep inspection of turns: full conversation message history, dialogue state changes (active requirements, goal, asked/disclosed attributes), tool calls, memory selections, and raw event payloads.
4. **Mock Customer Lab:**
   - Implemented in [`src/shopping_agent/mock_lab.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/mock_lab.py).
   - Select from pre-registered synthetic customer personas (e.g. from `customers.dev.json` or `customers.memory-sensitive.json`).
   - Inspect hidden persona traits, background, and multi-visit goals.
   - Step through or execute full multi-visit simulations visually to verify memory learning and cross-session retention.
5. **Results & Evaluation Tab:**
   - Inspect historical benchmark results, cost accounting ledgers, and comparative metrics.

---

## 5. Maintenance and CLI Tools

ASTRA includes several maintenance and inspection utilities:

### A. Memory Inspector CLI
[`src/shopping_agent/inspect_memory.py`](file:///Users/yangxu/code/self-improving-agent/src/shopping_agent/inspect_memory.py) allows inspecting customer profiles and procedural lessons without launching the UI:
```bash
# Inspect a customer's active, superseded, and deleted memory records
PYTHONPATH=src .venv/bin/python -m shopping_agent.inspect_memory user <user_id>

# Test semantic vector retrieval against a customer's profile
PYTHONPATH=src .venv/bin/python -m shopping_agent.inspect_memory query <user_id> "warm winter coats"

# Inspect centralized procedural lessons in the experience store
PYTHONPATH=src .venv/bin/python -m shopping_agent.inspect_memory experience
```

### B. Benchmark Generator
[`tools/generate_memory_sensitive_benchmark.py`](file:///Users/yangxu/code/self-improving-agent/tools/generate_memory_sensitive_benchmark.py) generates and cryptographically verifies the pre-registered memory-sensitive target benchmark fixture against the 50k-catalogue:
```bash
PYTHONPATH=src .venv/bin/python tools/generate_memory_sensitive_benchmark.py
```

### C. Interactive Terminal Agent
Run the shopping agent directly in the command line:
```bash
PYTHONPATH=src .venv/bin/python -m shopping_agent --user alice
```
