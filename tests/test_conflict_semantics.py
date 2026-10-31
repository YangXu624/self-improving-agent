"""State conflict detection must agree with the eligibility gate's predicate semantics."""

import unittest

from test_sessions import add

from shopping_agent.contracts import ShoppingState
from shopping_agent.retrieval import assess
from shopping_agent.state import apply_updates


def state_of(*updates):
    quote = "needs"
    return apply_updates(
        ShoppingState(),
        [u for u in updates],
        expected_version=0,
        user_message=quote,
        source_event_id="conflict-event",
    )


def req(field, op, value):
    return add(field, op, value, "needs")


def record(categories=(), department=None):
    return {
        "categories": list(categories),
        "text": "",
        "facts": {"department": department},
    }


class AliasTableTests(unittest.TestCase):
    def test_conflict_aliases_match_the_gate_normaliser(self):
        from shopping_agent.retrieval import facet
        from shopping_agent.state import DEPARTMENT_ALIASES, canonical

        for text in [*DEPARTMENT_ALIASES, "Men", "WOMEN'S", "kids"]:
            with self.subTest(text=text):
                self.assertEqual(
                    canonical("department", text), facet("department", text)
                )
        self.assertEqual(canonical("color", "Mens"), "mens")


class CompatibleRequirementTests(unittest.TestCase):
    def test_department_aliases_are_not_a_conflict(self):
        state = state_of(
            req("department", "eq", "men"), req("department", "eq", "mens")
        )
        self.assertTrue(assess(record(department="mens"), state)["eligible"])
        self.assertEqual(state.conflicts, [])

    def test_department_alias_variants_normalise_like_the_gate(self):
        for left, right in [("women's", "womens"), ("unisex-adult", "unisex adult")]:
            with self.subTest(left=left):
                state = state_of(
                    req("department", "eq", left), req("department", "in", [right])
                )
                self.assertEqual(state.conflicts, [])

    def test_alias_does_not_hide_a_real_department_conflict(self):
        for updates in (
            [req("department", "eq", "men"), req("department", "eq", "womens")],
            [req("department", "eq", "mens"), req("department", "neq", "men")],
            [req("department", "eq", "men's"), req("department", "not_in", ["mens"])],
        ):
            with self.subTest(updates=[u.requirement.value for u in updates]):
                self.assertEqual(state_of(*updates).conflicts, ["department"])

    def test_overlapping_product_types_are_not_a_conflict(self):
        state = state_of(
            req("product_type", "eq", "boots"),
            req("product_type", "eq", "hiking boots"),
        )
        self.assertTrue(assess(record(["Hiking Boots"]), state)["eligible"])
        self.assertEqual(state.conflicts, [])

    def test_distinct_product_type_words_can_share_one_category_path(self):
        state = state_of(
            req("product_type", "eq", "boots"), req("product_type", "eq", "shoes")
        )
        self.assertTrue(assess(record(["Boots", "Shoes"]), state)["eligible"])
        self.assertEqual(state.conflicts, [])

    def test_product_type_in_list_has_a_satisfiable_alternative(self):
        state = state_of(
            req("product_type", "in", ["boots", "sandals"]),
            req("product_type", "neq", "boots"),
        )
        self.assertTrue(assess(record(["Sandals"]), state)["eligible"])
        self.assertEqual(state.conflicts, [])

    def test_narrower_exclusion_leaves_the_broader_type_satisfiable(self):
        state = state_of(
            req("product_type", "eq", "boots"),
            req("product_type", "not_contains", "snow boots"),
        )
        self.assertTrue(assess(record(["Boots", "Work"]), state)["eligible"])
        self.assertEqual(state.conflicts, [])


class GenuineConflictTests(unittest.TestCase):
    def assert_conflict_and_ineligible(self, state, categories):
        self.assertEqual(state.conflicts, ["product_type"])
        self.assertFalse(assess(record(categories), state)["eligible"])

    def test_type_and_its_exclusion_conflict(self):
        state = state_of(
            req("product_type", "eq", "boots"), req("product_type", "neq", "boots")
        )
        self.assert_conflict_and_ineligible(state, ["Boots"])

    def test_specific_type_with_broader_exclusion_conflicts(self):
        state = state_of(
            req("product_type", "eq", "hiking boots"),
            req("product_type", "not_contains", "boots"),
        )
        self.assert_conflict_and_ineligible(state, ["Hiking Boots"])

    def test_all_alternatives_excluded_conflicts(self):
        state = state_of(
            req("product_type", "in", ["boots", "sandals"]),
            req("product_type", "not_in", ["boots", "sandals"]),
        )
        self.assert_conflict_and_ineligible(state, ["Boots", "Sandals"])

    def test_oversized_alternative_sets_still_flag_a_provable_conflict(self):
        groups = [[f"g{i}v{j}" for j in range(8)] for i in range(5)]  # 8**5 > cap
        rows = [req("product_type", "in", g) for g in groups]
        rows += [req("product_type", "not_in", g) for g in groups[:1]]
        self.assertEqual(state_of(*rows).conflicts, ["product_type"])

    def test_numeric_and_other_text_conflicts_are_preserved(self):
        price = state_of(req("price", "lt", 50.0), req("price", "gte", 80.0))
        self.assertEqual(price.conflicts, ["price"])
        color = state_of(req("color", "eq", "red"), req("color", "eq", "blue"))
        self.assertEqual(color.conflicts, ["color"])


if __name__ == "__main__":
    unittest.main()
