import unittest

from test_eval_memory import profile

from astra_eval.consistency import (
    ConsistencyConfig,
    check_reply,
    errors,
    prices_in,
    target_disclosures,
)
from astra_eval.models import ShopperReply


def check(message, reveals=(), action="reply", **kwargs):
    reply = ShopperReply(message=message, reveals=list(reveals), action=action)
    return check_reply(reply, profile(), **kwargs)


def codes(violations):
    return {v.code for v in violations}


class ConsistencyTests(unittest.TestCase):
    def test_faithful_replies_pass(self):
        self.assertEqual(errors(check("My budget is under $60.", ["budget"])), [])
        self.assertEqual(errors(check("I'd like it in red.", ["color"])), [])
        self.assertEqual(
            errors(check("I don't have a strong preference about that.")), []
        )

    def test_a_different_price_is_flagged(self):
        self.assertIn(
            "price_not_in_profile", codes(check("My budget is under $80.", ["budget"]))
        )
        self.assertEqual(prices_in("about 75 dollars or $12.50"), [75.0, 12.5])

    def test_prices_shown_by_the_assistant_may_be_quoted(self):
        self.assertEqual(
            errors(check("That one at $79.99 is too much.", shown_prices=[79.99])), []
        )

    def test_contradicting_a_known_attribute_is_flagged(self):
        v = check("Actually make it blue.")
        self.assertIn("contradicts_profile", codes(v))
        self.assertTrue(errors(v))

    def test_inventing_an_unprofiled_attribute_is_flagged(self):
        self.assertIn(
            "invented_attribute", codes(check("It should be made of leather."))
        )
        self.assertIn("invented_attribute", codes(check("It's for a woman.")))

    def test_department_synonyms_agree_with_the_profile_but_not_the_opposite(self):
        from astra_eval.models import Fact, ShopperProfile

        fact = Fact(
            key="department",
            kind="hard",
            field="department",
            op="eq",
            value="women",
            statement="It's for a woman.",
            keywords=["who"],
        )
        women = ShopperProfile(
            scenario_id="s", persona="p", facts=(fact,), opening_keys=()
        )
        ok = check_reply(ShopperReply(message="It's for a woman."), women)
        self.assertEqual(errors(ok), [])
        wrong = check_reply(ShopperReply(message="It's for my husband, a man."), women)
        self.assertIn("contradicts_profile", codes(wrong))

    def test_echoing_a_displayed_target_title_is_not_a_leak_but_an_unseen_one_is(self):
        title = "Acme Trail Boot"
        seen = check(
            "Is the Acme Trail Boot waterproof?", shown_titles=title, forbidden=[title]
        )
        self.assertNotIn("target_leak", codes(seen))
        unseen = check("Do you have the Acme Trail Boot?", forbidden=[title])
        self.assertIn("target_leak", codes(unseen))
        self.assertIn(
            "target_leak", codes(check("B001234567", shown_titles="B001234567"))
        )  # IDs never shown

    def test_adopting_an_attribute_only_the_assistant_suggested_is_a_warning(self):
        v = check("Yes, leather please.", shown_text="Would you like leather?")
        self.assertIn("adopted_assistant_suggestion", codes(v))
        self.assertEqual(errors(v), [])
        # but a suggested value that contradicts a profile attribute is still an error
        v = check("Yes, blue please.", shown_text="Would you like blue?")
        self.assertIn("contradicts_profile", codes(v))
        # a colour on a product card is fine to mention
        self.assertEqual(
            errors(check("The blue one is nice.", shown_titles="Blue boot")), []
        )

    def test_claimed_reveals_are_checked_for_price_and_department_too(self):
        self.assertIn("claimed_reveal_missing", codes(check("Sure.", ["budget"])))
        self.assertNotIn(
            "claimed_reveal_missing", codes(check("Under 60 please.", ["budget"]))
        )
        from astra_eval.models import Fact, ShopperProfile

        fact = Fact(
            key="department",
            kind="hard",
            field="department",
            op="eq",
            value="women",
            statement="It's for a woman.",
            keywords=["who"],
        )
        women = ShopperProfile(
            scenario_id="s", persona="p", facts=(fact,), opening_keys=()
        )
        said = check_reply(
            ShopperReply(message="For someone special.", reveals=["department"]), women
        )
        self.assertIn("claimed_reveal_missing", codes(said))
        ok = check_reply(
            ShopperReply(message="It's for a woman.", reveals=["department"]), women
        )
        self.assertNotIn("claimed_reveal_missing", codes(ok))

    def test_an_attribute_the_assistant_just_mentioned_may_be_echoed(self):
        self.assertEqual(
            errors(
                check("Leather is fine.", shown_text="Do you prefer leather or nylon?")
            ),
            [],
        )

    def test_revealing_unknown_keys_or_too_many_facts_is_flagged(self):
        self.assertIn("reveals_unknown_key", codes(check("Hi", ["shoe_size"])))
        self.assertIn(
            "over_reveal", codes(check("All of it.", ["type", "budget", "color"]))
        )
        self.assertEqual(errors(check("Boots under $60.", ["type", "budget"])), [])
        relaxed = ConsistencyConfig(max_reveals=3)
        self.assertNotIn(
            "over_reveal",
            codes(check("All.", ["type", "budget", "color"], config=relaxed)),
        )

    def test_negation_is_not_a_contradiction_but_the_wrong_value_still_is(self):
        self.assertEqual(
            errors(check("It is not for men.")), []
        )  # negated: excluded, not requested
        invented = [v.detail for v in errors(check("Not for men, for women."))]
        self.assertEqual(
            invented, ["department: ['women']"]
        )  # only the requested one is flagged
        self.assertEqual(errors(check("No brown please, red is fine.")), [])
        self.assertIn("contradicts_profile", codes(check("Make it brown.")))

    def test_colour_spelling_variants_and_full_width_text_are_normalised(self):
        from astra_eval.models import Fact, ShopperProfile

        fact = Fact(
            key="color",
            kind="soft",
            field="color",
            op="eq",
            value="grey",
            statement="s",
            keywords=["color"],
        )
        grey = ShopperProfile(
            scenario_id="s", persona="p", facts=(fact,), opening_keys=()
        )
        self.assertEqual(
            errors(check_reply(ShopperReply(message="Gray please."), grey)), []
        )
        self.assertIn(
            "contradicts_profile",
            codes(check_reply(ShopperReply(message="ｂｌａｃｋ please"), grey)),
        )

    def test_thousands_separators_and_family_words_for_departments(self):
        self.assertEqual(
            prices_in("About $1,000 total or 2,500.50 dollars"), [1000.0, 2500.5]
        )
        self.assertIn("invented_attribute", codes(check("It's for my husband.")))
        self.assertIn("invented_attribute", codes(check("for the guys")))

    def test_product_identifiers_are_case_insensitive_leaks(self):
        self.assertIn("target_leak", codes(check("try b012345678")))

    def test_product_identifiers_and_target_titles_are_leaks(self):
        self.assertIn("target_leak", codes(check("Maybe B001234567?")))
        self.assertIn(
            "target_leak",
            codes(
                check(
                    "Something like the Acme Trail Boot please",
                    forbidden=["acme trail boot"],
                )
            ),
        )

    def test_claimed_reveal_that_is_not_in_the_message_is_rejected(self):
        v = check("Sure, whatever.", ["color"])
        self.assertIn("claimed_reveal_missing", codes(v))
        self.assertTrue(errors(v))

    def test_accepting_without_products_is_a_warning(self):
        v = check("Great!", action="accept", has_products=False)
        self.assertIn("accepted_without_recommendation", codes(v))
        self.assertEqual(errors(v), [])
        self.assertEqual(
            codes(check("Great!", action="accept", has_products=True)), set()
        )


class TargetDisclosureTests(unittest.TestCase):
    def make_memory(self, facts=None, revealed=None):
        from test_eval_memory import profile as base_profile

        from astra_eval.memory import ShopperMemory
        from astra_eval.models import ShopperProfile

        profile_facts = facts if facts is not None else base_profile().facts
        p = ShopperProfile(
            scenario_id="target-disc-test",
            persona="Target shopper.",
            facts=profile_facts,
            opening_keys=tuple(
                k for k in ("type",) if any(f.key == k for f in profile_facts)
            ),
        )
        mem = ShopperMemory(p, disclosure_protocol="target-v1")
        if revealed:
            for k in revealed:
                mem.revealed[k] = {"turn": 1, "statement": "stated"}
        return mem

    def test_faithful_literal_disclosures(self):
        mem = self.make_memory()
        reply = ShopperReply(
            message="Under $60, in red please.", reveals=["budget", "color"]
        )
        supported, flags = target_disclosures(reply, mem)
        self.assertIn("budget", supported)
        self.assertIn("color", supported)
        self.assertEqual(errors(flags), [])

    def test_price_matching_integer_float_and_thousands_separator(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=1000.0,
                statement="Under $1,000.",
                keywords=["budget"],
            ),
        )
        mem = self.make_memory(facts=facts)
        reply = ShopperReply(message="My budget is $1,000.", reveals=["budget"])
        supported, flags = target_disclosures(reply, mem)
        self.assertEqual(supported, ["budget"])
        self.assertEqual(errors(flags), [])

    def test_budget_operator_contradiction(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=60.0,
                statement="Under $60.",
                keywords=["budget"],
            ),
        )
        mem = self.make_memory(facts=facts)
        reply = ShopperReply(message="I need something over $60.", reveals=["budget"])
        supported, flags = target_disclosures(reply, mem)
        self.assertNotIn("budget", supported)
        self.assertIn("contradicts_budget_operator", codes(flags))
        self.assertTrue(errors(flags))

    def test_department_synonyms_and_negation(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="department",
                kind="hard",
                field="department",
                op="eq",
                value="women",
                statement="For women.",
                keywords=["who"],
            ),
        )
        mem = self.make_memory(facts=facts)
        reply = ShopperReply(message="It's for my wife.", reveals=["department"])
        supported, flags = target_disclosures(reply, mem)
        self.assertEqual(supported, ["department"])

        neg_reply = ShopperReply(message="Not for women.", reveals=["department"])
        supported, flags = target_disclosures(neg_reply, mem)
        self.assertEqual(supported, [])

    def test_color_canonicalization_and_full_width_text(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="color",
                kind="hard",
                field="color",
                op="eq",
                value="grey",
                statement="Grey color.",
                keywords=["color"],
            ),
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=60.0,
                statement="Under $60.",
                keywords=["budget"],
            ),
        )
        mem = self.make_memory(facts=facts)
        reply = ShopperReply(
            message="Under ＄60, ｇｒａｙ please.", reveals=["budget", "color"]
        )
        supported, flags = target_disclosures(reply, mem)
        self.assertIn("color", supported)
        self.assertIn("budget", supported)

    def test_negated_attribute_is_not_supported(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="material",
                kind="hard",
                field="material",
                op="eq",
                value="leather",
                statement="Leather.",
                keywords=["material"],
            ),
        )
        mem = self.make_memory(facts=facts)
        reply = ShopperReply(message="No leather please.", reveals=["material"])
        supported, flags = target_disclosures(reply, mem)
        self.assertEqual(supported, [])

    def test_over_reveal_triggers_error_for_more_than_two_new_facts(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="color",
                kind="hard",
                field="color",
                op="eq",
                value="red",
                statement="Red.",
                keywords=["color"],
            ),
            Fact(
                key="material",
                kind="hard",
                field="material",
                op="eq",
                value="cotton",
                statement="Cotton.",
                keywords=["material"],
            ),
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=50.0,
                statement="Under $50.",
                keywords=["budget"],
            ),
        )
        mem = self.make_memory(facts=facts)
        reply = ShopperReply(
            message="Red cotton under $50.", reveals=["color", "material", "budget"]
        )
        supported, flags = target_disclosures(reply, mem)
        self.assertEqual(len(supported), 3)
        self.assertIn("over_reveal", codes(flags))
        self.assertTrue(errors(flags))

    def test_repeating_known_fact_does_not_count_toward_over_reveal(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="type",
                kind="hard",
                field="product_type",
                op="contains",
                value="boots",
                statement="Boots.",
                keywords=["type"],
            ),
            Fact(
                key="color",
                kind="hard",
                field="color",
                op="eq",
                value="red",
                statement="Red.",
                keywords=["color"],
            ),
            Fact(
                key="material",
                kind="hard",
                field="material",
                op="eq",
                value="cotton",
                statement="Cotton.",
                keywords=["material"],
            ),
        )
        mem = self.make_memory(facts=facts, revealed=["type"])
        reply = ShopperReply(
            message="Boots in red cotton.", reveals=["type", "color", "material"]
        )
        supported, flags = target_disclosures(reply, mem)
        self.assertEqual(set(supported), {"type", "color", "material"})
        self.assertEqual(errors(flags), [])

    def test_claimed_reveal_missing_and_unclaimed_disclosure(self):
        from astra_eval.models import Fact

        facts = (
            Fact(
                key="color",
                kind="hard",
                field="color",
                op="eq",
                value="red",
                statement="Red.",
                keywords=["color"],
            ),
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=50.0,
                statement="Under $50.",
                keywords=["budget"],
            ),
        )
        mem = self.make_memory(facts=facts)
        missing_reply = ShopperReply(message="Hello there.", reveals=["color"])
        supported, flags = target_disclosures(missing_reply, mem)
        self.assertEqual(supported, [])
        self.assertIn("claimed_reveal_missing", codes(flags))
        self.assertTrue(errors(flags))

        unclaimed_reply = ShopperReply(message="I need red.", reveals=[])
        supported, flags = target_disclosures(unclaimed_reply, mem)
        self.assertEqual(supported, ["color"])
        self.assertIn("unclaimed_disclosure", codes(flags))
        self.assertEqual(errors(flags), [])


if __name__ == "__main__":
    unittest.main()
