"""Whole-conversation regressions for observed failures; no network or protected-file edits."""

import json

import eval_fixtures as F
import test_shopper_v3 as V3
from test_eval_dialogue import BUDGET

from astra_eval.memory import AssistantView, ShopperMemory
from astra_eval.models import ShopperReply
from astra_eval.simulators import SimulatorError, SimulatorResult


class OfferHistoryTests(F.EvalCase):
    shopper = V3.AutonomousTests.shopper
    bind = V3.AutonomousTests.bind
    reply = staticmethod(V3.AutonomousTests.reply)
    runner = V3.AutonomousTests.runner

    def prepared(self):
        shopper = self.shopper([])
        self.bind(shopper)
        memory = ShopperMemory(V3.profile(BUDGET.model_copy(update={"value": 60.0})))
        # PR #27 pattern, synthetic ID: a real presented price followed by a text-only reply.
        memory.record_assistant(
            AssistantView(
                "Catalogue matches.",
                products=(
                    {
                        "id": "offer-5",
                        "title": "Quick dry elastic-waist casual pants",
                        "price": 27.99,
                    },
                ),
                turn=1,
            ),
            extra={"action": "RECOMMEND", "status": "ok", "goal_epoch": 0},
        )
        view = AssistantView(
            "Color availability is unknown; check the product page.", turn=2
        )
        memory.record_assistant(view, extra={"action": "RESPOND", "goal_epoch": 0})
        return shopper, memory, view

    @staticmethod
    def accepted(
        message="I'll go with the quick dry elastic-waist pants at $27.99 and check the colors myself.",
    ):
        return SimulatorResult(ShopperReply(message=message, action="accept"))

    def test_pr27_accept_previous_offer_after_text_only_followup(self):
        shopper, memory, view = self.prepared()
        _, violations = shopper.audit_reply(memory, view, self.accepted())
        self.assertFalse(violations)
        event = json.loads(shopper.provider.journal.path.read_text().splitlines()[-1])
        self.assertEqual(event["offer_scope"]["presented_ids"], ["offer-5"])

    def test_never_shown_price_and_invented_product_identifier_rejected(self):
        shopper, memory, view = self.prepared()
        for text, code in [
            ("I'll accept the pants for $28.99.", "price_not_in_profile"),
            ("I'll accept B000000001.", "target_leak"),
        ]:
            _, flags = shopper.audit_reply(memory, view, self.accepted(text))
            self.assertIn(code, [v.code for v in flags])

    def test_previous_goal_offer_cannot_be_accepted(self):
        shopper, memory, _ = self.prepared()
        view = AssistantView("Let's shop for a new category.", turn=3)
        memory.record_assistant(view, extra={"action": "RESPOND", "goal_epoch": 1})
        _, flags = shopper.audit_reply(memory, view, self.accepted())
        self.assertIn("accepted_without_recommendation", [v.code for v in flags])
        self.assertIn("price_not_in_profile", [v.code for v in flags])

    def test_other_session_customer_or_condition_offer_cannot_be_accepted(self):
        shopper, memory, view = self.prepared()
        shopper.audit_reply(memory, view, self.accepted())
        shopper.finish_session(memory, "accepted")
        for user, condition in [("alice", "off"), ("alice", "on"), ("bob", "off")]:
            self.bind(shopper, owner=user, condition=condition)
            fresh = ShopperMemory(memory.profile)
            _, flags = shopper.audit_reply(
                fresh, AssistantView("No options yet."), self.accepted()
            )
            self.assertIn("accepted_without_recommendation", [v.code for v in flags])
            shopper.finish_session(fresh, "simulator_error")

    def test_memory_objects_cannot_be_swapped_inside_a_bound_session(self):
        shopper, memory, view = self.prepared()
        shopper.audit_reply(memory, view, self.accepted())
        with self.assertRaisesRegex(SimulatorError, "shopper_session_memory_mismatch"):
            shopper.audit_reply(ShopperMemory(memory.profile), view, self.accepted())

    def test_unpresented_search_candidates_do_not_authorize_acceptance(self):
        shopper = self.shopper([])
        self.bind(shopper)
        memory = ShopperMemory(V3.profile(BUDGET))
        memory.record_assistant(
            AssistantView(
                "Searching.", products=({"id": "unpresented", "price": 27.99},)
            ),
            extra={"action": "SEARCH"},
        )
        _, flags = shopper.audit_reply(
            memory, AssistantView("No recommendations."), self.accepted()
        )
        self.assertIn("accepted_without_recommendation", [v.code for v in flags])
