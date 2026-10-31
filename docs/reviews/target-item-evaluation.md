# Target-item evaluation review

Part B, 31 October 2026. No live model calls.

Independent QA and architectural review for target-item evaluation mode (`--evaluation-mode target_item`):

1. **Target discovery and ambiguity partitioning:**
   Offline catalogue audit (`audit-targets`) verified the full 50,000 product catalogue without live model calls: 1,554 distinguishable products, 8,855 ambiguous products, and 39,591 products with insufficient evidence. Sampling partitions into disjoint family clusters across splits without title or ASIN leakage.

2. **Hidden target isolation:**
   Target IDs, titles, and hashes reside strictly in `TargetGroundTruth` and `TargetRule`. Verification confirms that shopping agent decision contexts and shopper simulator prompts/views never contain target identifiers, product titles, or ground-truth evidence hashes.

3. **Early cutoff and execution bounds:**
   When ASTRA recommends the target item within primary $K$ ($1 \le K \le 5$, default $K=5$), the dialogue runner terminates immediately with `termination="target_found"`. Regression tests confirm that no subsequent simulated-shopper response or shopping-agent turn execution occurs post-hit. Sessions enforce a uniform reservation cap via `--session-max-model-calls` (default 18), preventing unbudgeted calls.

4. **Conservative disclosure validation (`target-v1` protocol):**
   Literal disclosure verification normalizes NFKC unicode, accounts for negation, canonicalizes color spelling variants (e.g. gray/grey), and flags budget operator contradictions (`contradicts_budget_operator`). Messages stating more than two new profile facts trigger `over_reveal` retry errors. Unclaimed disclosures are recorded as warnings and added to verified disclosures.

5. **Scoring, abstention, and batch resilience:**
   Recomputed hit rank verifies recommendation events. Metrics record `Hit@K`, `First-Hit MRR@K`, `MTTC` (successes only and penalized $B+1$), cumulative success by turn, and search/clarification efficiency. Impossible tasks evaluate grounded abstention separately from hit rate. Invalid sessions (`harness_error`, `simulator_error`, `provider_error`) are recorded safely without crashing batch execution.

6. **Regression test suite:**
   Full test suite executes 408 tests: 405 passed, 1 skipped (tokenizer asset), and 2 expected failures (pre-existing watch taxonomy). Ruff lint and formatting checks pass completely.

**Limitations:**
- Semantic paraphrasing outside explicit keyword and attribute matching remains unverified.
- Live conversational quality and real LLM (Ollama/Llama 3.1 and DeepSeek) behavior remain to be evaluated in live runs.
- Exact-target discovery is not a substitute for broader recommendation quality and preferences.
