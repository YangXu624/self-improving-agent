# Attribute working-memory review

Part A, 31 October 2026. No live model calls.

Independent QA added 27 adversarial tests covering executed-question provenance, volunteered
values, decline/no-preference/unanswered distinctions, correction/retraction, exact facets,
goal resets, long-history retention, legacy full/compact replay and bounded closure. The final
full suite executed 376 tests: 373 passed, one tokenizer-asset skip and two existing watch
expected failures. Ruff lint and formatting passed.

The independent architecture reviewer approved the event-derived projection: requirement
schema and codec are unchanged; question-only state does not invalidate current searches;
current-message goal changes reconcile correctly; simulator/evaluation imports are absent.
Independent lifecycle and currency probes passed. Findings fixed before the checkpoint:
mixed/sentence-separated dispositions, exclusion-only follow-ups, explicit reopening, newer
currency answers superseding declines, and currency questions falsely counted as commitments.

This verifies deterministic contracts with mocks. General semantic extraction, real model
question selection, unsupported language and live conversational quality remain unverified.
