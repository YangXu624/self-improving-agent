import unittest

from test_eval_memory import profile

from astra_eval.consistency import ConsistencyConfig, check_reply, errors, prices_in
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

    def test_claimed_reveal_that_is_not_in_the_message_is_only_a_warning(self):
        v = check("Sure, whatever.", ["color"])
        self.assertIn("claimed_reveal_missing", codes(v))
        self.assertEqual(errors(v), [])

    def test_accepting_without_products_is_a_warning(self):
        v = check("Great!", action="accept", has_products=False)
        self.assertIn("accepted_without_recommendation", codes(v))
        self.assertEqual(errors(v), [])
        self.assertEqual(
            codes(check("Great!", action="accept", has_products=True)), set()
        )


if __name__ == "__main__":
    unittest.main()
