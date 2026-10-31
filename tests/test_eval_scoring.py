"""Scoring: independent of the shopper, graded relevance, failure handling, diagnostics."""

import math
import unittest

import eval_fixtures as F

from astra_eval.dialogue import AgentTurn, SessionRecord
from astra_eval.models import Fact, GroundTruth
from astra_eval.oracle import CatalogueOracle
from astra_eval.scoring import ScoreConfig, dcg, ndcg, represented, score_session


def fact(key, kind, field, op, value):
    return Fact(key=key, kind=kind, field=field, op=op, value=value, statement="s")


class MathTests(unittest.TestCase):
    def test_ndcg_known_values(self):
        self.assertAlmostEqual(dcg([3, 2, 0]), 7 / 1 + 3 / math.log2(3))
        self.assertAlmostEqual(ndcg([3, 3], [3, 3, 3], 2), 1.0)
        self.assertAlmostEqual(ndcg([1], [3, 3], 1), (2**1 - 1) / (2**3 - 1))
        self.assertAlmostEqual(ndcg([0, 3], [3], 2), (7 / math.log2(3)) / 7)
        self.assertIsNone(ndcg([1], [], 3))
        self.assertEqual(ndcg([0, 0, 0], [3], 3), 0.0)


class ScoringTests(F.EvalCase):
    """Products in the synthetic catalogue: id B0<type><i>; Boots are type 0."""

    def setUp(self):
        super().setUp()
        self.oracle = CatalogueOracle(self.catalogue)
        rows = {r["parent_asin"]: r for r in self.oracle.rows()}
        boots = [r for r in rows.values() if r["categories"][-1] == "Boots"]
        self.pass_ids = [
            r["parent_asin"]
            for r in boots
            if r["price"] and r["price"] < 50 and r["details"]["Department"] == "Women"
        ]
        self.expensive = [
            r["parent_asin"] for r in boots if r["price"] and r["price"] >= 50
        ][0]
        self.unpriced = [r["parent_asin"] for r in boots if r["price"] is None][0]
        self.sandal = next(
            r["parent_asin"] for r in rows.values() if r["categories"][-1] == "Sandals"
        )
        self.truth = GroundTruth(
            scenario_id="s",
            kind="feasible",
            hard=[
                fact("t", "hard", "product_type", "contains", "boots"),
                fact("b", "hard", "price", "lt", 50.0),
                fact("d", "hard", "department", "eq", "women"),
            ],
            soft=[],
            acceptable_count=len(self.pass_ids),
            unknown_required_count=0,
            ideal_grades=[3] * 20,
            acceptable_sample=[],
            catalogue_sha256=self.catalogue_sha,
            evidence_contract="c",
        )

    def turn(
        self,
        n,
        ids=(),
        action="RECOMMEND",
        seen=(),
        error=None,
        searches=0,
        calls=1,
        **kw,
    ):
        return AgentTurn(
            turn=n,
            request_id=f"r{n}",
            status="error" if error else "ok",
            action=action,
            message="m",
            recommended_ids=list(ids),
            candidates_seen=[list(seen)] if seen else [],
            searches=searches,
            model_calls=calls,
            error=error,
            **kw,
        )

    def record(self, turns, termination="accepted", requirements=None, **kw):
        base = [
            {
                "field": "product_type",
                "op": "contains",
                "value": "boots",
                "strength": "hard",
            },
            {"field": "price", "op": "lt", "value": 50.0, "strength": "hard"},
            {"field": "department", "op": "eq", "value": "women", "strength": "hard"},
        ]
        return SessionRecord(
            "s",
            "memory_off",
            "sid",
            termination,
            list(turns),
            requirements if requirements is not None else base,
            **kw,
        )

    def score(self, record, config=ScoreConfig(), truth=None, max_turns=6):
        return score_session(
            record, truth or self.truth, self.oracle, config, max_turns=max_turns
        )

    def test_correct_recommendation_is_a_verified_success_with_perfect_ndcg(self):
        ids = self.pass_ids[:3]
        s = self.score(
            self.record(
                [
                    self.turn(1, action="SEARCH", searches=1),
                    self.turn(2, ids, seen=ids, searches=1),
                ]
            )
        )
        self.assertEqual((s["outcome"], s["turns_to_first_success"]), ("success", 2))
        self.assertTrue(all(s["metrics"]["success_at_k_within_budget"].values()))
        self.assertAlmostEqual(s["metrics"]["ndcg_first"]["3"], 1.0)
        self.assertEqual(s["violations"]["hard_fail"], 0)
        self.assertIsNone(s["failure_category"])

    def test_wrong_recommendation_fails_and_counts_hard_violations(self):
        s = self.score(
            self.record(
                [
                    self.turn(
                        1,
                        [self.expensive, self.sandal],
                        seen=[self.expensive],
                        searches=1,
                    )
                ]
            )
        )
        self.assertEqual(s["outcome"], "failure")
        self.assertEqual(
            (s["violations"]["hard_fail"], s["violations"]["items"]), (2, 2)
        )
        self.assertEqual(s["violations"]["hard_fail_rate"], 1.0)
        self.assertTrue(s["violations"]["any_hard_fail"])
        self.assertEqual(s["metrics"]["ndcg_first"]["3"], 0.0)

    def test_unknown_price_is_not_credited_and_is_reported_separately(self):
        s = self.score(
            self.record(
                [self.turn(1, [self.unpriced], seen=[self.unpriced], searches=1)]
            )
        )
        self.assertEqual(s["outcome"], "failure")
        self.assertEqual(
            (s["violations"]["unknown_required"], s["violations"]["hard_fail"]), (1, 0)
        )

    def test_invented_product_ids_are_counted_and_never_acceptable(self):
        s = self.score(self.record([self.turn(1, ["B0NOTREAL1"], searches=1)]))
        self.assertEqual(s["violations"]["unknown_product_id"], 1)
        self.assertEqual(s["outcome"], "failure")

    def test_hit_at_k_depends_on_rank_not_presence(self):
        ids = [self.expensive, self.sandal, self.pass_ids[0]]
        s = self.score(self.record([self.turn(1, ids, seen=ids, searches=1)]))
        self.assertEqual(s["metrics"]["hit_at_k"], {"1": False, "3": True, "5": True})
        self.assertEqual(s["outcome"], "success")  # headline K=3
        self.assertEqual(
            self.score(
                self.record([self.turn(1, ids, seen=ids, searches=1)]),
                ScoreConfig(headline_k=1),
            )["outcome"],
            "failure",
        )

    def test_strict_success_requires_every_item_in_the_top_k_to_be_verified(self):
        mixed = [self.pass_ids[0], self.expensive, self.pass_ids[1]]
        s = self.score(self.record([self.turn(1, mixed, seen=mixed, searches=1)]))
        self.assertEqual(s["outcome"], "success")  # lenient headline: one verified hit
        strict = s["metrics"]["strict_success_at_k_within_budget"]
        self.assertEqual(strict, {"1": True, "3": False, "5": False})
        self.assertAlmostEqual(s["metrics"]["precision_first_at_k"]["3"], 2 / 3)
        clean = self.pass_ids[:3]
        s = self.score(self.record([self.turn(1, clean, seen=clean, searches=1)]))
        self.assertTrue(all(s["metrics"]["strict_success_at_k_within_budget"].values()))
        none = self.score(self.record([self.turn(1, action="CLARIFY")]))
        self.assertFalse(
            any(none["metrics"]["strict_success_at_k_within_budget"].values())
        )
        self.assertIsNone(none["metrics"]["precision_first_at_k"]["3"])

    def test_duplicate_ids_in_one_recommendation_cannot_inflate_ndcg_or_precision(self):
        a = self.pass_ids[0]
        s = self.score(self.record([self.turn(1, [a, a, a], seen=[a], searches=1)]))
        self.assertLess(s["metrics"]["ndcg_first"]["3"], 0.5)
        self.assertEqual(s["violations"]["items"], 1)
        self.assertEqual(s["metrics"]["precision_first_at_k"]["3"], 1.0)

    def test_turn_budget_decides_whether_a_late_success_counts(self):
        ids = self.pass_ids[:2]
        record = self.record(
            [self.turn(1), self.turn(2), self.turn(3, ids, seen=ids, searches=1)]
        )
        self.assertEqual(self.score(record)["outcome"], "success")
        late = self.score(record, ScoreConfig(turn_budget=2))
        self.assertEqual(
            (late["outcome"], late["turns_to_first_success"]), ("failure", None)
        )

    def test_first_recommendation_ndcg_differs_from_final(self):
        good = self.pass_ids[:2]
        s = self.score(
            self.record(
                [
                    self.turn(1, [self.expensive], searches=1),
                    self.turn(2, good, seen=good, searches=1),
                ]
            )
        )
        self.assertEqual(s["metrics"]["ndcg_first"]["3"], 0.0)
        self.assertGreater(s["metrics"]["ndcg_final"]["3"], 0.0)
        self.assertEqual(s["turns_to_first_success"], 2)

    def test_failure_categories_separate_retrieval_state_recommendation_and_search(
        self,
    ):
        def category(turns, requirements=None):
            return self.score(self.record(turns, "max_turns", requirements))[
                "failure_category"
            ]

        self.assertEqual(category([self.turn(1, action="CLARIFY")]), "no_search")
        self.assertEqual(
            category(
                [self.turn(1, action="RESPOND", seen=[self.expensive], searches=1)]
            ),
            "retrieval_failure",
        )
        self.assertEqual(
            category(
                [self.turn(1, action="RESPOND", seen=self.pass_ids[:2], searches=1)]
            ),
            "recommendation_failure",
        )
        wrong_state = [
            {
                "field": "product_type",
                "op": "contains",
                "value": "boots",
                "strength": "hard",
            },
            {"field": "price", "op": "lt", "value": 50.0, "strength": "hard"},
            {"field": "department", "op": "eq", "value": "men", "strength": "hard"},
        ]
        self.assertEqual(
            category(
                [self.turn(1, action="RESPOND", seen=[self.expensive], searches=1)],
                wrong_state,
            ),
            "state_extraction_failure",
        )
        self.assertEqual(
            category(
                [
                    self.turn(
                        1,
                        action="RESPOND",
                        searches=1,
                        error="decision_budget_exhausted",
                    )
                ]
            ),
            "agent_budget_exhausted",
        )
        self.assertEqual(
            category([self.turn(1, action="RESPOND", error="something_else")]),
            "agent_error",
        )

    def test_retrieval_diagnostics_record_candidate_quality_and_state_coverage(self):
        seen = [self.pass_ids[0], self.expensive]
        s = self.score(
            self.record(
                [self.turn(1, action="RESPOND", seen=seen, searches=1)], requirements=[]
            )
        )
        r = s["retrieval"]
        self.assertTrue(
            r["searched"] and r["acceptable_seen"] and r["acceptable_exists"]
        )
        self.assertEqual(r["hard_pass_rate_of_candidates"], 0.5)
        self.assertEqual(
            r["hidden_hard_fields_missing_from_state"],
            ["department", "price", "product_type"],
        )
        self.assertEqual(len(r["hidden_hard_facts_not_in_state"]), 3)

    def test_represented_compares_field_and_value_not_operator(self):
        f = fact("b", "hard", "price", "lt", 50.0)
        self.assertTrue(
            represented(f, [{"field": "price", "value": 50, "strength": "hard"}])
        )
        self.assertFalse(
            represented(f, [{"field": "price", "value": 60, "strength": "hard"}])
        )
        self.assertFalse(
            represented(f, [{"field": "price", "value": 50, "strength": "soft"}])
        )

    def test_no_valid_product_success_is_correct_abstention(self):
        truth = self.truth.model_copy(
            update={
                "kind": "no_valid_product",
                "acceptable_count": 0,
                "ideal_grades": [],
            }
        )
        ok = self.score(
            self.record(
                [self.turn(1, action="RESPOND", seen=[self.expensive], searches=1)],
                "accepted",
            ),
            truth=truth,
        )
        self.assertEqual(
            (ok["outcome"], ok["abstained_correctly"], ok["false_recommendation"]),
            ("success", True, False),
        )
        bad = self.score(
            self.record([self.turn(1, [self.expensive], searches=1)]), truth=truth
        )
        self.assertEqual(
            (bad["outcome"], bad["failure_category"], bad["false_recommendation"]),
            ("failure", "false_recommendation", True),
        )
        broken = self.score(
            self.record(
                [self.turn(1, action="RESPOND", error="decision_budget_exhausted")]
            ),
            truth=truth,
        )
        self.assertEqual(broken["failure_category"], "agent_budget_exhausted")

    def test_simulator_and_infrastructure_faults_are_invalid_not_agent_failures(self):
        for termination in (
            "simulator_failure",
            "provider_error",
            "run_budget_exhausted",
        ):
            s = self.score(self.record([self.turn(1, action="CLARIFY")], termination))
            self.assertEqual(
                (s["valid"], s["outcome"], s["failure_category"]),
                (False, "invalid", termination),
            )
        agent_fail = self.score(
            self.record([self.turn(1, action="CLARIFY")], "agent_error")
        )
        self.assertTrue(agent_fail["valid"])
        self.assertEqual(agent_fail["outcome"], "failure")

    def test_resource_counts_tokens_latency_and_cost(self):
        turns = [
            self.turn(
                1,
                action="CLARIFY",
                calls=1,
                usage={"prompt_tokens": 1000, "completion_tokens": 100},
                model_seconds=1.5,
                wall_ms=1600.0,
            ),
            self.turn(
                2,
                action="SEARCH",
                searches=1,
                calls=2,
                usage={"prompt_tokens": 3000, "completion_tokens": 200},
                model_seconds=2.0,
                wall_ms=2100.0,
            ),
        ]
        record = self.record(turns, repeated_questions=2, unmatched_questions=1)
        record.simulator = {"calls": 3, "attempts": 4, "usage": {"prompt_tokens": 500}}
        priced = self.score(
            record,
            ScoreConfig(price_input_per_million=0.3, price_output_per_million=1.2),
        )
        r = priced["resources"]
        self.assertEqual(
            (
                r["model_calls"],
                r["searches"],
                r["clarifications"],
                r["redundant_clarifications"],
                r["clarifications_about_nothing_in_profile"],
            ),
            (3, 1, 1, 2, 1),
        )
        self.assertEqual(
            r["agent_usage"], {"prompt_tokens": 4000, "completion_tokens": 300}
        )
        self.assertAlmostEqual(r["estimated_cost_usd"], (4000 * 0.3 + 300 * 1.2) / 1e6)
        self.assertAlmostEqual(r["agent_model_seconds"], 3.5)
        self.assertEqual(priced["simulator_audit"]["malformed_retries"], 1)
        self.assertIsNone(
            self.score(record)["resources"]["estimated_cost_usd"]
        )  # no invented prices


if __name__ == "__main__":
    unittest.main()
