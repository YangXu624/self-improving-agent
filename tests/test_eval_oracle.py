"""The independent oracle: exact semantics, unknown handling, agreement with the agent gate."""

import unittest

import eval_fixtures as F

from astra_eval.models import Fact
from astra_eval.oracle import CatalogueOracle, judge, positive_price, raw_facts, verdict
from shopping_agent.contracts import ShoppingState
from shopping_agent.retrieval import assess, project
from shopping_agent.state import apply_updates


def fact(field, op, value, kind="hard"):
    return Fact(key=field, kind=kind, field=field, op=op, value=value, statement="s")


class OracleTests(F.EvalCase):
    def row(self, **over):
        row = {
            "parent_asin": "X",
            "title": "t",
            "categories": ["A", "Women", "Boots"],
            "details": {"Department": "Womens", "Color": "Red", "Material": "Leather"},
            "price": 20.0,
            "features": [],
            "description": [],
        }
        row.update(over)
        return row

    def test_price_parsing_is_exact_and_positive_only(self):
        self.assertEqual(positive_price("19.99"), 19.99)
        for bad in (0, -1, "from 5", None, True, float("inf"), "1,5"):
            self.assertIsNone(positive_price(bad))

    def test_missing_attributes_are_unknown_and_block_hard_requirements(self):
        facts = raw_facts(self.row(price=None, details={}))
        for f in (
            fact("price", "lt", 50.0),
            fact("color", "eq", "red"),
            fact("brand", "eq", "acme"),
        ):
            self.assertEqual(verdict(facts, f), "unknown")
        graded = judge(facts, [fact("price", "lt", 50.0)], [])
        self.assertEqual((graded["hard"], graded["grade"]), ("unknown", 0))

    def test_soft_unknowns_lower_the_grade_but_do_not_fail_the_product(self):
        facts = raw_facts(self.row(details={"Department": "Women"}))
        hard = [fact("price", "lt", 50.0)]
        self.assertEqual(judge(facts, hard, [])["grade"], 3)
        self.assertEqual(
            judge(facts, hard, [fact("color", "eq", "red", "soft")])["grade"], 1
        )
        full = raw_facts(self.row())
        self.assertEqual(
            judge(full, hard, [fact("color", "eq", "red", "soft")])["grade"], 3
        )
        self.assertEqual(
            judge(full, hard, [fact("color", "eq", "blue", "soft")])["grade"], 1
        )

    def test_operator_semantics(self):
        facts = raw_facts(self.row())
        cases = [
            (fact("price", "lt", 20.0), "fail"),
            (fact("price", "lte", 20.0), "pass"),
            (fact("product_type", "contains", "boots"), "pass"),
            (fact("product_type", "contains", "sandals"), "fail"),
            (fact("product_type", "not_contains", "sandals"), "pass"),
            (fact("department", "eq", "women"), "pass"),
            (fact("department", "eq", "men"), "fail"),
            (fact("color", "in", ["red", "blue"]), "pass"),
            (fact("color", "not_in", ["red"]), "fail"),
            (fact("material", "contains", "leather"), "pass"),
            (fact("color", "neq", "red"), "fail"),
        ]
        for f, expected in cases:
            with self.subTest(f=f.model_dump()):
                self.assertEqual(verdict(facts, f), expected)

    def test_department_aliases_match_catalogue_wording(self):
        for wording in ("Men's", "Mens", "men"):
            self.assertEqual(
                raw_facts(self.row(details={"Department": wording}))["department"],
                "men",
            )

    def test_oracle_random_access_and_streaming_agree(self):
        oracle = CatalogueOracle(self.catalogue)
        rows = list(oracle.rows())
        self.assertEqual(len(rows), len(F.catalogue_rows()))
        self.assertEqual(oracle.row(rows[7]["parent_asin"])["title"], rows[7]["title"])
        self.assertIsNone(oracle.row("nope"))
        self.assertEqual(oracle.sha256, self.catalogue_sha)

    def test_oracle_agrees_with_the_agent_gate_on_supported_semantics(self):
        """Independence, not divergence: the two implementations should match here."""
        oracle = CatalogueOracle(self.catalogue)
        hard = [
            fact("product_type", "contains", "boots"),
            fact("price", "lt", 50.0),
            fact("department", "eq", "women"),
        ]
        state = apply_updates(
            ShoppingState(),
            [self._update(f) for f in hard],
            expected_version=0,
            user_message="boots under 50 for women",
            source_event_id="e",
        )
        for row in oracle.rows():
            theirs = assess(project(row), state)["eligible"]
            ours = judge(raw_facts(row), hard, [])["hard"] == "pass"
            self.assertEqual(ours, theirs, row["parent_asin"])

    @staticmethod
    def _update(f):
        from shopping_agent.contracts import StateUpdate

        quote = {"product_type": "boots", "price": "under 50", "department": "women"}[
            f.field
        ]
        return StateUpdate.model_validate(
            {
                "op": "ADD",
                "quote": quote,
                "requirement": {
                    "field": f.field,
                    "op": f.op,
                    "value": f.value,
                    "strength": "hard",
                    "quote": quote,
                },
            }
        )


if __name__ == "__main__":
    unittest.main()
