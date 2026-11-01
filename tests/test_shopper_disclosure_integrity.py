"""No models: reproduce the failed pilot and enforce current-visit disclosure evidence."""

import json
import unittest
from dataclasses import asdict
from pathlib import Path

from astra_eval.consistency import check_reply, errors, target_disclosures
from astra_eval.customers import compile_visit, load_customers
from astra_eval.dialogue import DialogueRunner, SimulatorFailure
from astra_eval.memory import AssistantView, ShopperMemory
from astra_eval.models import Fact, ShopperProfile, ShopperReply
from astra_eval.simulators import (
    REPLY_SCHEMA,
    SHOPPER_PROTOCOL_VERSION,
    OllamaShopper,
    SimulatorConfig,
    reply_schema,
)


def profile():
    return ShopperProfile(
        scenario_id="synthetic-briefcase",
        persona="Brief and practical.",
        facts=(
            Fact(
                key="type",
                kind="hard",
                field="product_type",
                op="contains",
                value="Briefcases",
                statement="I need Briefcases.",
                keywords=["type"],
            ),
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=70,
                statement="My budget is under 70 USD.",
                keywords=["budget", "price"],
            ),
            Fact(
                key="preferred_color",
                kind="soft",
                field="color",
                op="eq",
                value="Black",
                statement="I generally prefer Black bags.",
                keywords=["color"],
            ),
        ),
        opening_keys=("type",),
    )


class ReplyTransport:
    def __init__(self, replies):
        self.replies, self.payloads = list(replies), []

    def __call__(self, url, payload, timeout):
        self.payloads.append(payload)
        reply = self.replies.pop(0)
        return {
            "message": {"content": json.dumps(reply)},
            "prompt_eval_count": 100,
            "eval_count": 20,
        }


class ShopperDisclosureIntegrityTests(unittest.TestCase):
    def setup_reply(
        self,
        replies,
        question="No briefcases matched; would you broaden your requirements?",
    ):
        self.memory = ShopperMemory(
            profile(), private_context={"current_goal": "Buy a folio bag for work."}
        )
        self.memory.record_shopper(1, "I need Briefcases.", ["type"])
        self.view = AssistantView(question, turn=1, turns_left=5)
        self.memory.record_assistant(self.view)
        self.transport = ReplyTransport(replies)
        self.runner = DialogueRunner(
            None, None, OllamaShopper(transport=self.transport), run_id="no-model"
        )
        self.stats = {
            "calls": 0,
            "attempts": 0,
            "consistency_retries": 0,
            "context_entries_dropped": 0,
            "violations": {},
            "usage": {},
        }

    def respond(self):
        return self.runner.shopper_reply(self.memory, self.view, (), self.stats)

    def test_observed_unknown_key_is_never_accepted_or_repaired(self):
        bad = {
            "message": "I'm looking for a folio bag for work, not just briefcases.",
            "reveals": ["type", "current_goal"],
            "action": "reply",
        }
        self.setup_reply([bad, bad])
        with self.assertRaises(SimulatorFailure) as raised:
            self.respond()
        self.assertEqual(raised.exception.code, "simulator_inconsistent")
        self.assertEqual(self.stats["calls"], 2)
        self.assertEqual(self.stats["violations"]["reveals_unknown_key"], 2)
        self.assertEqual(set(self.memory.revealed), {"type"})
        audit = [
            e for e in self.memory.transcript.entries if e["role"] == "simulator_audit"
        ]
        self.assertEqual(len(audit), 2)
        self.assertTrue(all(e["parsed_reply"] == bad for e in audit))
        for payload in self.transport.payloads:
            enum = payload["format"]["properties"]["reveals"]["items"]["enum"]
            self.assertEqual(enum, ["type", "budget", "preferred_color"])
        retry = json.loads(self.transport.payloads[1]["messages"][-1]["content"])
        self.assertEqual(
            retry["valid_disclosure_keys"], ["type", "budget", "preferred_color"]
        )
        self.assertIn(
            "reveals_unknown_key: current_goal",
            retry["fix_these_problems_in_your_previous_attempt"],
        )

    def test_retry_must_supply_a_genuinely_valid_unchanged_reply(self):
        bad = {
            "message": "Within my budget, please.",
            "reveals": ["budget"],
            "action": "reply",
        }
        good = {
            "message": "Please keep it below 70 dollars.",
            "reveals": ["budget"],
            "action": "reply",
        }
        self.setup_reply([bad, good], "What is your budget?")
        reply, _, unverified = self.respond()
        self.assertEqual(reply.model_dump(), good)
        self.assertEqual(unverified, [])
        self.assertEqual(self.stats["calls"], 2)
        self.assertNotIn("budget", self.memory.revealed)
        self.memory.apply(2, reply)
        self.assertIn("budget", self.memory.revealed)

    def test_claims_need_values_not_acknowledgments_or_partial_values(self):
        for message, reveals in (
            ("I'd like to know if any of these are within my budget.", ["budget"]),
            ("I'd like to continue the search.", ["type"]),
            ("I don't have a strong preference about that.", ["preferred_color"]),
        ):
            with self.subTest(message=message):
                flags = check_reply(
                    ShopperReply(message=message, reveals=reveals), profile()
                )
                self.assertTrue(
                    any(v.code == "claimed_reveal_missing" for v in errors(flags))
                )
        grey = profile().model_copy(
            update={
                "facts": (
                    profile().facts[-1].model_copy(update={"value": "Cool Grey"}),
                ),
                "opening_keys": (),
            }
        )
        self.assertTrue(
            errors(
                check_reply(
                    ShopperReply(message="Cool please.", reveals=["preferred_color"]),
                    grey,
                )
            )
        )
        self.assertFalse(
            errors(
                check_reply(
                    ShopperReply(
                        message="I prefer cool gray.", reveals=["preferred_color"]
                    ),
                    grey,
                )
            )
        )

    def test_natural_paraphrases_and_repeated_disclosures_are_supported(self):
        for message, reveals in (
            ("Could you show me Briefcases?", ["type"]),
            ("Please keep it below 70 dollars.", ["budget"]),
            ("I'd rather have black.", ["preferred_color"]),
            ("Could you show more options?", []),
        ):
            self.assertFalse(
                errors(
                    check_reply(
                        ShopperReply(message=message, reveals=reveals), profile()
                    )
                )
            )
        good = {
            "message": "As I said, my budget is under 70 USD.",
            "reveals": ["budget"],
            "action": "reply",
        }
        self.setup_reply([good], "Sorry, what is your budget?")
        self.memory.record_shopper(1, "Under 70 USD.", ["budget"])
        reply, _, _ = self.respond()
        self.assertEqual(reply.reveals, ["budget"])
        self.assertEqual(self.stats["calls"], 1)

    def test_contradictory_values_negation_and_budget_directions_still_fail(self):
        for message, reveals in (
            ("Make it Blue.", ["preferred_color"]),
            ("Not Black.", ["preferred_color"]),
            ("My budget is over 70 dollars.", ["budget"]),
            ("My budget is under 90 dollars.", ["budget"]),
        ):
            with self.subTest(message=message):
                self.assertTrue(
                    errors(
                        check_reply(
                            ShopperReply(message=message, reveals=reveals), profile()
                        )
                    )
                )

    def test_department_claim_must_not_negate_the_profile(self):
        dept = profile().model_copy(
            update={
                "facts": (
                    Fact(
                        key="department",
                        kind="hard",
                        field="department",
                        op="eq",
                        value="women",
                        statement="For women.",
                        keywords=["who"],
                    ),
                ),
                "opening_keys": (),
            }
        )
        self.assertFalse(
            errors(
                check_reply(
                    ShopperReply(message="It is for a woman.", reveals=["department"]),
                    dept,
                )
            )
        )
        self.assertTrue(
            errors(
                check_reply(
                    ShopperReply(message="Not for women.", reveals=["department"]), dept
                )
            )
        )

    def test_schema_is_per_visit_and_empty_profiles_cannot_disclose(self):
        a = reply_schema(["type", "preferred_color"])
        b = reply_schema(["type", "recipient_color"])
        self.assertNotIn("preferred_color", b["properties"]["reveals"]["items"]["enum"])
        self.assertNotIn("enum", REPLY_SCHEMA["properties"]["reveals"]["items"])
        self.assertEqual(a["properties"]["reveals"]["maxItems"], 2)
        self.assertEqual(reply_schema([])["properties"]["reveals"]["maxItems"], 0)
        self.assertEqual(
            asdict(SimulatorConfig())["protocol_version"], SHOPPER_PROTOCOL_VERSION
        )

    def test_future_visit_and_ground_truth_remain_outside_model_context(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "experiments/longitudinal/customers.dev-expanded.json"
        )
        customer = next(
            c
            for c in load_customers(path).customers
            if c.user_id == "dev-bag-style-change"
        )
        scenario, private, _ = compile_visit(customer, customer.visits[1])
        memory = ShopperMemory(scenario.profile, private_context=private)
        messages, _ = memory.build_messages(
            AssistantView("What is your budget?", turn=1), 8000
        )
        text = json.dumps(messages)
        for forbidden in (
            "Cream",
            "witness_id",
            "best_ids_sha256",
            "user_memory_on",
            "before_sequence",
        ):
            self.assertNotIn(forbidden, text)
        for visit in customer.visits:
            self.assertNotIn(visit.witness_id, text)

    def test_missing_claim_exhaustion_keeps_raw_output_and_ledger_clean(self):
        bad = {
            "message": "Sure, that's within my budget.",
            "reveals": ["budget"],
            "action": "reply",
        }
        self.setup_reply([bad, bad])
        with self.assertRaises(SimulatorFailure):
            self.respond()
        self.assertNotIn("budget", self.memory.revealed)
        self.assertEqual(self.stats["consistency_retries"], 2)
        self.assertTrue(
            all(
                e["parsed_reply"] == bad
                for e in self.memory.transcript.entries
                if e["role"] == "simulator_audit"
            )
        )

    def test_a_rejected_attempt_does_not_establish_its_other_claims(self):
        first = {
            "message": "I need a folio bag under 70 USD.",
            "reveals": ["type", "budget"],
            "action": "reply",
        }
        second = {
            "message": "I'd like Briefcases within my budget.",
            "reveals": ["type", "budget"],
            "action": "reply",
        }
        self.setup_reply([first, second])
        with self.assertRaises(SimulatorFailure):
            self.respond()
        self.assertNotIn("budget", self.memory.revealed)
        correction = self.transport.payloads[1]["messages"][0]["content"]
        self.assertIn("CORRECTION REQUIRED", correction)
        self.assertIn("including keys that were valid previously", correction)
        self.assertIn("sentence verbatim", correction)
        self.assertIn("do not reveal more than two", correction)

    def test_explicit_negative_fact_is_not_misread_as_a_positive_preference(self):
        avoid = profile().model_copy(
            update={
                "facts": (
                    profile()
                    .facts[-1]
                    .model_copy(update={"op": "neq", "statement": "No Black."}),
                ),
                "opening_keys": (),
            }
        )
        self.assertFalse(
            errors(
                check_reply(
                    ShopperReply(
                        message="No Black, please.", reveals=["preferred_color"]
                    ),
                    avoid,
                )
            )
        )
        supported, flags = target_disclosures(
            ShopperReply(message="No Black, please.", reveals=["preferred_color"]),
            ShopperMemory(avoid),
        )
        self.assertEqual(supported, ["preferred_color"])
        self.assertFalse(errors(flags))
        self.assertTrue(
            errors(
                check_reply(
                    ShopperReply(message="I want Black.", reveals=["preferred_color"]),
                    avoid,
                )
            )
        )

    def test_every_expanded_visit_schema_excludes_context_and_future_keys(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "experiments/longitudinal/customers.dev-expanded.json"
        )
        count = 0
        for customer in load_customers(path).customers:
            for visit in customer.visits:
                scenario, context, _ = compile_visit(customer, visit)
                keys = [f.key for f in scenario.profile.facts]
                enum = reply_schema(keys)["properties"]["reveals"]["items"]["enum"]
                self.assertEqual(enum, keys)
                self.assertTrue(set(enum).isdisjoint(context))
                self.assertNotIn("current_goal", enum)
                count += 1
        self.assertEqual(count, 36)
