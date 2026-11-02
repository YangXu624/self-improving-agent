"""Tests for Part B — Memory-Sensitive Target Benchmark & Evaluation Harness."""

import json
import unittest
from pathlib import Path

from astra_eval.customers import (
    CatalogueOracle,
    load_customers,
    validate_dataset,
)
from astra_eval.memory_sensitive_eval import (
    score_memory_sensitive_results,
)
from astra_eval.target_scoring import TargetRule


class MemorySensitiveBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = Path(
            "experiments/longitudinal/customers.memory-sensitive.json"
        )
        cls.catalogue_path = Path("data/catalogue/catalog.jsonl")
        cls.dataset = load_customers(cls.fixture_path)
        cls.oracle = CatalogueOracle(cls.catalogue_path)

    def test_fixture_integrity_and_cryptographic_evidence(self):
        """All benchmark targets exist in frozen catalogue and cryptographic evidence matches."""
        self.assertEqual(self.dataset.catalogue_sha256, self.oracle.sha256)
        compiled = validate_dataset(
            self.dataset, self.catalogue_path, require_evidence=True
        )
        self.assertEqual(len(compiled), 12)
        self.assertEqual(len(self.dataset.customers), 6)

    def test_three_scenario_groups_distribution_and_balance(self):
        """Benchmark is cleanly balanced across helpful, neutral, and conflicting groups."""
        groups = [v.scenario_group for c in self.dataset.customers for v in c.visits]
        self.assertEqual(groups.count("memory-helpful"), 4)
        self.assertEqual(groups.count("memory-neutral"), 4)
        self.assertEqual(groups.count("memory-conflicting"), 4)

    def test_memory_helpful_design_omits_preference_in_returning_opening(self):
        """In memory-helpful visits, returning opening does NOT repeat the historical preference."""
        for c in self.dataset.customers:
            helpful_v2 = next(
                (
                    v
                    for v in c.visits
                    if v.sequence == 2 and v.scenario_group == "memory-helpful"
                ),
                None,
            )
            if helpful_v2:
                # Historical persistent facts exist
                self.assertTrue(len(c.preferences) >= 1)
                pref = c.preferences[0].fact.value.lower()
                # The returning opening must NOT leak or repeat the preference
                self.assertNotIn(pref, helpful_v2.opening.lower())

    def test_memory_conflicting_design_explicitly_overrides_or_uses_gift(self):
        """In memory-conflicting visits, request either specifies gift recipient or overrides."""
        conflicting_v2 = [
            v
            for c in self.dataset.customers
            for v in c.visits
            if v.sequence == 2 and v.scenario_group == "memory-conflicting"
        ]
        self.assertEqual(len(conflicting_v2), 2)
        # One is gift
        gift_visit = next(v for v in conflicting_v2 if v.recipient == "gift")
        self.assertEqual(gift_visit.disclosure, "gift")
        # One is override
        override_visit = next(v for v in conflicting_v2 if v.recipient == "self")
        self.assertEqual(override_visit.disclosure, "announce_change")
        self.assertIn("now prefer", override_visit.opening.lower())

    def test_no_target_leakage_into_shopper_roleplay_or_prompts(self):
        """Witness/target IDs and titles are never leaked into shopper roleplay context."""
        compiled = validate_dataset(
            self.dataset, self.catalogue_path, require_evidence=True
        )
        for cv in compiled:
            shopper_ctx_str = json.dumps(cv.shopper_context)
            self.assertNotIn(cv.target_truth.target_id, shopper_ctx_str)
            if cv.target_truth.target_title:
                self.assertNotIn(cv.target_truth.target_title, shopper_ctx_str)
            # Acceptable target list also never leaked
            if cv.target_truth.acceptable_target_ids:
                for tid in cv.target_truth.acceptable_target_ids:
                    self.assertNotIn(tid, shopper_ctx_str)

    def test_frozen_acceptable_target_set_in_target_rule(self):
        """TargetRule supports frozen acceptable target sets rather than only single arbitrary target."""
        acceptable_set = ("target-A", "target-B", "target-C")
        rule = TargetRule(target_id=None, k=5, acceptable_target_ids=acceptable_set)

        # 1. Non-matching recommendations -> None
        response_miss = {
            "status": "ok",
            "action": "RECOMMEND",
            "products": [{"id": "other-1"}, {"id": "other-2"}],
        }
        self.assertIsNone(rule.check(response_miss, ["other-1", "other-2"]))

        # 2. Matching target-B at rank 2 -> returns 2
        response_hit = {
            "status": "ok",
            "action": "RECOMMEND",
            "products": [{"id": "other-1"}, {"id": "target-B"}, {"id": "other-3"}],
        }
        rank = rule.check(response_hit, ["other-1", "target-B", "other-3"])
        self.assertEqual(rank, 2)

    def test_deterministic_stopping_and_group_separated_scoring(self):
        """Validates deterministic success@6 and group-separated reporting."""
        # Simulated run results
        mock_results = [
            # mem-help-active-02: target found on turn 2
            {
                "task_id": "mem-help-active-02",
                "termination": "target_found",
                "target_hit": {"turn": 2, "rank": 1},
                "score": {
                    "violations": {},
                    "resources": {"model_calls": 2, "searches": 1},
                },
            },
            # mem-neut-travel-02: target found on turn 3
            {
                "task_id": "mem-neut-travel-02",
                "termination": "target_found",
                "target_hit": {"turn": 3, "rank": 2},
                "score": {
                    "violations": {},
                    "resources": {"model_calls": 3, "searches": 2},
                },
            },
            # mem-conf-override-02: failed after 6 turns
            {
                "task_id": "mem-conf-override-02",
                "termination": "max_turns_reached",
                "target_hit": None,
                "score": {
                    "violations": {"hard_fail": 1},
                    "resources": {"model_calls": 6, "searches": 3},
                },
            },
        ]

        report = score_memory_sensitive_results(self.fixture_path, mock_results)
        d = report.to_dict()

        self.assertEqual(d["groups"]["memory-helpful"]["successful_visits"], 1)
        self.assertEqual(d["groups"]["memory-helpful"]["target_success_at_6"], 1.0)
        self.assertEqual(d["groups"]["memory-helpful"]["mean_turns_to_success"], 2.0)

        self.assertEqual(d["groups"]["memory-neutral"]["successful_visits"], 1)
        self.assertEqual(d["groups"]["memory-neutral"]["target_success_at_6"], 1.0)
        self.assertEqual(d["groups"]["memory-neutral"]["mean_turns_to_success"], 3.0)

        self.assertEqual(d["groups"]["memory-conflicting"]["successful_visits"], 0)
        self.assertEqual(d["groups"]["memory-conflicting"]["target_success_at_6"], 0.0)
        self.assertEqual(d["groups"]["memory-conflicting"]["hard_violations"], 1)

        self.assertEqual(d["overall"]["successful_visits"], 2)
        self.assertEqual(d["overall"]["total_visits"], 3)


if __name__ == "__main__":
    unittest.main()
