# Experiential-Memory MVP Review

31 October 2026. Offline validation; no live model calls.

Independent architectural and QA review for the experiential-memory self-improvement vertical slice (`shopping_agent.experience`):

1. **Outcome vs. Lesson Separation and Explicit Confirmation:**
   - Evaluated sessions separate the observed outcome (e.g. `empty_search_zero_eligible`), hypothesized failure cause, bounded procedural directive ($\le 400$ characters), verifiable action signature, and provenance evidence.
   - Raw lessons extracted from session traces enter the SQLite store strictly in `candidate` status.
   - Candidates are excluded from retrieval until explicit supervisor confirmation (`store.confirm()`) promotes them to `active`.

2. **Cross-Category Behavioral Generalizability:**
   - Because learning and evaluation splits use disjoint product families, lessons index on behavioral triggers (`initial_query`, `empty_search_recovery`, `recommend_cutoff`, `attribute_clarification`) and decision context cues (`searches`, `calls`, `has_search`, `candidate_count`) rather than narrow product types.
   - Scoped lessons default to `*` (cross-category) while allowing specific category specialization where appropriate.

3. **Provenance, Versioning, and Retraction:**
   - SQLite store (`ExperienceStore`) tracks version numbers, creation timestamps, review notes, and superseding relationships.
   - `store.supersede()` atomically increments version, links `supersedes_id` and `superseded_by_id`, and archives the superseded record.
   - `store.retract()` and `store.reject()` mark lessons as inactive and exclude them from retrieval without destroying historical provenance.

4. **Anti-Contamination Enforcement:**
   - `validate_lesson` strictly enforces `source_split == "learning"`.
   - Structural and lexical validators reject ASIN patterns (`B0...`), product IDs, evaluator target product titles, and prompt injection attempts.
   - Held-out evaluations consume immutable, content-hashed snapshots (`ExperienceSnapshot`) and never write back to the experience store.

5. **Distinction of Retrieval, Injection, Application, and Improvement:**
   - Agent orchestration tracks:
     - `retrieved_experience`: lessons matching current decision triggers and context cues.
     - `injected_experience`: lessons formatted and bounded within prompt context (`procedural_guidance`).
     - `applied_experience`: lessons verified by `verify_decision_application` against concrete emitted decision action fields (e.g., query tokens, token mode, attribute names, product count).
   - Turn events, session records, and evaluation outputs (`results.jsonl`, `report.json`) record these phases separately.
   - Outcome improvement is measured strictly against paired frozen runs with memory disabled (`memory_off`).

6. **Evaluation Harness Integration:**
   - `Condition` supports frozen `ExperienceSnapshot` objects.
   - `experiential_agent_factory` injects snapshots into `ShoppingAgent` while preserving the unchanged baseline for `memory_off`.
   - CLI supports `--experience-snapshot <path>`, automatically configuring paired comparison conditions.

7. **Test Suite Verification:**
   - 429 total tests collected: 426 passed, 1 skipped (tokenizer asset), 2 expected failures (watch taxonomy regressions).
   - Unit tests (`tests/test_experience.py`) cover SQLite lifecycle, retraction, superseding, tampering detection, and validation guards.
   - End-to-end integration test (`tests/test_experiential_integration.py`) demonstrates the complete vertical slice: learning trace extraction, confirmation, snapshot creation, cross-category retrieval on development split, verified decision application, and measured outcome improvement over memory OFF.
   - Ruff lint and format checks pass with 0 errors.

**Limitations and Next Steps:**
- Procedural extraction heuristics currently target query formulation and cutoff patterns; broader extraction using structured LLM reflection prompts should be benchmarked during live trials.
- Real DeepSeek policy evaluation under live conditions (`--live --max-model-calls`) with local Ollama simulator will benchmark real-world transfer efficiency.
