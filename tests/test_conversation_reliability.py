"""Whole-conversation regressions for observed failures; no network or protected-file edits."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eval_fixtures as F
import test_shopper_v3 as V3
from test_eval_dialogue import BUDGET

from astra_eval.memory import AssistantView, ShopperMemory
from astra_eval.models import ShopperReply
from astra_eval.simulators import SimulatorError, SimulatorResult

_network_patches = []


def setUpModule():
    for name in ("urllib.request.urlopen", "shopping_agent.provider.urlopen"):
        block = patch(
            name,
            side_effect=AssertionError("Integration tests must never use a live API"),
        )
        block.start()
        _network_patches.append(block)


def tearDownModule():
    for block in _network_patches:
        block.stop()


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
                        "facts": {"color": "Black"},
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

    def test_model_sees_bounded_sanitized_prior_offers_after_text_only_followup(self):
        shopper, memory, view = self.prepared()
        messages, _ = shopper.build_messages(memory, view)
        context = json.loads(messages[-1]["content"])
        options = context["assistant"]["previously_presented_options"]
        self.assertEqual(options[0]["price"], 27.99)
        self.assertNotIn("id", options[0])
        self.assertEqual(context["assistant"]["presented_options"], [])

    def test_acceptance_can_reference_verified_card_attributes_and_option_numbers(self):
        shopper, memory, view = self.prepared()
        # Facts came from trusted presented cards, even when absent from their short title.
        for text in ("I'll take the black one.", "I'll choose option number one."):
            _, flags = shopper.audit_reply(memory, view, self.accepted(text))
            self.assertFalse(flags)

    def test_never_shown_price_and_invented_product_identifier_rejected(self):
        shopper, memory, view = self.prepared()
        for text, code in [
            ("I'll accept the pants for $28.99.", "price_not_in_profile"),
            ("I'll accept B000000001.", "target_leak"),
            (
                "I will accept the Galactic Toaster for $27.99.",
                "unpresented_product_reference",
            ),
            ("I'll take the fifth option.", "unpresented_product_reference"),
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
        with self.assertRaisesRegex(SimulatorError, "shopper_session_memory_mismatch"):
            shopper.finish_session(ShopperMemory(memory.profile), "accepted")
        self.assertFalse(shopper.history)

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


class PipelineTests(F.EvalCase):
    shopper = V3.AutonomousTests.shopper
    bind = V3.AutonomousTests.bind
    reply = staticmethod(V3.AutonomousTests.reply)
    """Real compact executor, real BM25/session files, V3 loop and scripted model outputs."""

    def run_pipeline(self, messages, *steps, facts=None):
        from test_agent import ScriptedPolicy
        from test_eval_dialogue import TYPE, scenario

        from astra_eval.dialogue import DialogueRunner
        from shopping_agent.agent import ShoppingAgent

        self.policy = ScriptedPolicy(*steps)
        self.simulator = self.shopper(messages)
        self.agent = ShoppingAgent(
            self.store, self.search, self.policy, memory_format="compact"
        )
        self.record = DialogueRunner(
            self.agent, self.store, self.simulator, run_id="lifecycle"
        ).run(scenario(facts or [TYPE, BUDGET], [], "Unused frozen opening"))
        return self.record

    @staticmethod
    def choose(context):
        return {
            "updates": [],
            "action": {
                "type": "RECOMMEND",
                "search_id": context["latest_search"]["search_id"],
                "product_ids": [
                    p["id"] for p in context["latest_search"]["candidates"]
                ][:2],
            },
            "reason": "Choose from actual returned catalogue cards",
        }

    @staticmethod
    def decision(action, updates=None):
        return {
            "updates": updates or [],
            "action": action,
            "reason": "Scripted lifecycle decision",
        }

    @staticmethod
    def initial():
        from test_sessions import add

        return [
            add("product_type", "contains", "boot", "boots").model_dump(),
            add(value=50, quote="under $50").model_dump(),
        ]

    def test_full_search_recommend_followup_accept_previous_item(self):
        record = self.run_pipeline(
            [
                self.reply("I need boots under $50."),
                self.reply("Can you tell me more about the first option?"),
                self.reply("I'll take the first option.", "accept"),
            ],
            self.decision({"type": "SEARCH", "query": "boots"}, self.initial()),
            self.choose,
            self.decision(
                {
                    "type": "RESPOND",
                    "message": "The previously shown options remain available in our catalogue; live stock is unknown.",
                }
            ),
        )
        self.assertEqual(record.termination, "accepted")
        self.assertEqual([t.action for t in record.turns], ["RECOMMEND", "RESPOND"])
        self.assertEqual(sum(t.searches for t in record.turns), 1)
        self.assertFalse(record.simulator["violations"])

    def test_full_clarification_then_revised_requirements_and_recommendation(self):
        from test_sessions import add

        record = self.run_pipeline(
            [
                self.reply("I need boots."),
                self.reply("Under $50 please."),
                self.reply("The first option works.", "accept"),
            ],
            self.decision(
                {
                    "type": "CLARIFY",
                    "attribute": "price",
                    "question": "What is your budget?",
                },
                [self.initial()[0]],
            ),
            self.decision(
                {"type": "SEARCH", "query": "boots"},
                [add(value=50, quote="Under $50").model_dump()],
            ),
            self.choose,
        )
        self.assertEqual(record.termination, "accepted")
        self.assertEqual([t.action for t in record.turns], ["CLARIFY", "RECOMMEND"])
        self.assertEqual(
            {r["field"] for r in record.final_requirements}, {"product_type", "price"}
        )
        self.assertTrue(
            all(
                p["price"] < 50
                for e in record.transcript
                if e["role"] == "assistant"
                for p in e.get("products", [])
            )
        )

    def test_full_repeated_empty_search_ends_gracefully_without_more_shopper_calls(
        self,
    ):
        search = self.decision(
            {"type": "SEARCH", "query": "nonexistent galaxyitem"}, self.initial()
        )
        repeat = self.decision({"type": "SEARCH", "query": "galaxyitem nonexistent"})
        record = self.run_pipeline(
            [self.reply("I need boots under $50.")], search, repeat, repeat
        )
        self.assertEqual(record.termination, "search_stalled")
        self.assertEqual(record.turns[0].status, "ok")
        self.assertEqual(record.turns[0].searches, 1)
        self.assertEqual(record.simulator["calls"], 1)
        self.assertEqual(record.turns[0].recommended_ids, [])

    def test_full_invalid_shopper_response_has_one_bounded_retry_then_proceeds(self):
        record = self.run_pipeline(
            [
                self.reply("I need boots under $90."),
                self.reply("I need boots under $50."),
                self.reply("Those work.", "accept"),
            ],
            self.decision({"type": "SEARCH", "query": "boots"}, self.initial()),
            self.choose,
        )
        self.assertEqual(record.termination, "accepted")
        self.assertEqual(record.simulator["calls"], 3)
        self.assertEqual(
            len([e for e in record.transcript if e["role"] == "shopper"]), 2
        )

    def test_compact_soft_preference_correction_and_stale_retraction_keeps_valid_action(
        self,
    ):
        from test_agent import ScriptedPolicy
        from test_sessions import add

        from shopping_agent.agent import ShoppingAgent

        hard = add("color", "eq", "Black", "Black", "hard").model_dump()
        soft = add("color", "eq", "Black", "Black", "soft").model_dump()
        policy = ScriptedPolicy(
            self.decision(
                {"type": "SEARCH", "query": "boots"}, [self.initial()[0], hard]
            ),
            self.decision(
                {"type": "SEARCH", "query": "boots"}, [self.initial()[0], soft]
            ),
            self.choose,
            self.decision(
                {"type": "SEARCH", "query": "boots"},
                [
                    {
                        "op": "RETRACT",
                        "target_id": "preferences.color.0",
                        "quote": "Drop Black",
                    }
                ],
            ),
            self.decision(
                {
                    "type": "RESPOND",
                    "message": "I have refreshed the catalogue options.",
                }
            ),
            self.choose,
        )
        agent = ShoppingAgent(self.store, self.search, policy, memory_format="compact")
        sid = self.store.create("alice")
        first = agent.turn("alice", sid, "I need boots. Black if you have it.")
        self.assertEqual(first["action"], "RECOMMEND")
        second = agent.turn("alice", sid, "Drop Black, any color is fine.")
        self.assertEqual(second["status"], "ok")

        def stale(context):
            value = self.choose(context)
            value["updates"] = [
                {
                    "op": "RETRACT",
                    "target_id": "preferences.color.0",
                    "quote": "Any color is fine",
                }
            ]
            return value

        policy.steps[0] = stale
        third = agent.turn(
            "alice", sid, "Any color is fine; show me the previous options."
        )
        self.assertEqual(third["action"], "RECOMMEND")
        with self.store.open("alice", sid) as session:
            self.assertEqual(session.state.version, 2)
            self.assertFalse(
                any(
                    r.field == "color" and r.status == "active"
                    for r in session.state.requirements
                )
            )
            self.assertTrue(
                any(e.type == "redundant_retraction_ignored" for e in session.events)
            )
            self.assertEqual(
                [
                    e.payload["feedback"][0]["code"]
                    for e in session.events
                    if e.type == "decision_rejected"
                ],
                ["conditional_color_requires_soft_preference"],
            )

    def test_changed_requirements_permit_a_new_search_after_an_empty_result(self):
        from test_agent import ScriptedPolicy
        from test_sessions import add

        from shopping_agent.agent import ShoppingAgent

        policy = ScriptedPolicy(
            self.decision(
                {"type": "SEARCH", "query": "boots"},
                [self.initial()[0], add(value=1, quote="under $1").model_dump()],
            ),
            self.decision(
                {
                    "type": "RESPOND",
                    "message": "No verified options within that budget.",
                }
            ),
            self.decision(
                {"type": "SEARCH", "query": "boots"},
                [
                    {
                        "op": "REPLACE",
                        "target_id": "hard.price.0",
                        "quote": "under $50",
                        "requirement": {
                            "field": "price",
                            "op": "lt",
                            "value": 50,
                            "strength": "hard",
                            "quote": "under $50",
                        },
                    }
                ],
            ),
            self.choose,
        )
        agent = ShoppingAgent(self.store, self.search, policy, memory_format="compact")
        sid = self.store.create("alice")
        agent.turn("alice", sid, "I need boots under $1.")
        result = agent.turn("alice", sid, "Actually, under $50.")
        self.assertEqual(result["action"], "RECOMMEND")
        with self.store.open("alice", sid) as session:
            results = [e.payload for e in session.events if e.type == "search_result"]
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["candidates"], [])
            self.assertTrue(results[1]["candidates"])


class StateAndTaxonomyTests(F.EvalCase):
    def test_category_inflections_are_general_and_do_not_touch_attribute_matching(self):
        from shopping_agent.category_matching import category_contains
        from shopping_agent.retrieval import compare

        for category, request in [
            ("Active Shirts & Tees", "active shirt tee"),
            ("Active Hoodies", "active hoodie"),
            ("Dresses", "dress"),
            ("Watches", "watch"),
            ("Casual Daypacks", "casual daypack"),
            ("Accessories", "accessory"),
        ]:
            self.assertTrue(category_contains(category, request), (category, request))
        self.assertFalse(category_contains("Dress Shoes", "address"))
        self.assertFalse(category_contains("Watch Bands", "wristwatch"))
        self.assertFalse(compare("blacks", "eq", "black"))

    def test_actual_catalogue_taxonomy_has_the_plural_categories_in_the_incident(self):
        from pathlib import Path

        from shopping_agent.category_matching import category_contains

        path = Path(__file__).resolve().parents[1] / "data/catalogue/catalog.jsonl"
        if not path.exists():
            self.skipTest("Local catalogue is not installed")
        categories = {
            c
            for line in path.read_text().split("\n")
            if line.strip()
            for c in json.loads(line).get("categories", [])
        }
        for label, query in [
            ("Active Shirts & Tees", "active shirt"),
            ("Active Hoodies", "active hoodie"),
            ("Pants", "pants"),
        ]:
            self.assertIn(label, categories)
            self.assertTrue(category_contains(label, query))

    def test_conditional_color_guard_preserves_explicit_hard_needs(self):
        from test_sessions import add

        from shopping_agent.contracts import ShoppingState
        from shopping_agent.state import StateError, apply_updates

        for text in (
            "Black if you have it.",
            "Ideally Black.",
            "Black is only a preference.",
        ):
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(StateError, "conditional_color_requires_soft"),
            ):
                apply_updates(
                    ShoppingState(),
                    [add("color", "eq", "Black", "Black")],
                    expected_version=0,
                    user_message=text,
                    source_event_id="user",
                )
        state = apply_updates(
            ShoppingState(),
            [add("color", "eq", "Black", "Black")],
            expected_version=0,
            user_message="Black is required.",
            source_event_id="user",
        )
        self.assertEqual(state.requirements[0].strength, "hard")

    def test_absent_retraction_does_not_repair_live_targets_replacements_or_old_goals(
        self,
    ):
        from test_sessions import add

        from shopping_agent.contracts import ShoppingState
        from shopping_agent.memory_views import redundant_retractions
        from shopping_agent.state import apply_updates

        state = apply_updates(
            ShoppingState(),
            [add("color", "eq", "Black", "Black", strength="soft")],
            expected_version=0,
            user_message="Black",
            source_event_id="user",
        )
        content = json.dumps(
            {
                "updates": [
                    {
                        "op": "RETRACT",
                        "target_id": "preferences.color.0",
                        "quote": "drop Black",
                    }
                ],
                "action": {"type": "RESPOND", "message": "Done"},
                "reason": "fixture",
            }
        )
        self.assertFalse(redundant_retractions(content, state, "drop Black")[1])
        state.requirements[0].status = "retracted"
        self.assertTrue(redundant_retractions(content, state, "drop Black")[1])
        self.assertFalse(
            redundant_retractions(content, state, "drop Black", goal_start_version=2)[1]
        )
        self.assertFalse(
            redundant_retractions(
                content.replace("RETRACT", "REPLACE"), state, "drop Black"
            )[1]
        )
        self.assertFalse(
            redundant_retractions(
                content.replace("color", "material"), state, "drop Black"
            )[1]
        )
        self.assertFalse(
            redundant_retractions(content, state, "new message without evidence")[1]
        )
        self.assertEqual(redundant_retractions("[]", state, "drop Black"), ("[]", []))


class TimelineTests(unittest.TestCase):
    def setUp(self):
        from longitudinal_fixtures import make_dataset

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.catalogue, self.index, _ = make_dataset(
            self.root, second_customer=True
        )

    def run_timeline(self, shopper, policy=None, **options):
        from test_compact_memory_evaluation import CompactPolicy

        from astra_eval.longitudinal import LongitudinalConfig, run_longitudinal

        config = LongitudinalConfig(
            customers=self.source,
            catalogue=self.catalogue,
            index=self.index,
            output=self.root / "run",
            memory_format="compact",
            execution_order="off_then_on",
            stop_on_error=True,
            **options,
        )
        summary = run_longitudinal(
            config, simulator=shopper, policy=policy or CompactPolicy()
        )
        rows = [
            json.loads(line)
            for line in (config.output / "results.jsonl").read_text().splitlines()
        ]
        return summary, rows, config

    def test_one_isolated_invalid_customer_does_not_cancel_independent_customers(self):
        from astra_eval.simulators import ScriptedShopper

        class OneBadCustomer(ScriptedShopper):
            def respond(self, memory, view, feedback=()):
                if memory.profile.scenario_id == "visit-1":
                    raise SimulatorError("simulator_inconsistent")
                return super().respond(memory, view, feedback)

        summary, rows, _ = self.run_timeline(OneBadCustomer())
        self.assertIsNone(summary["stopped_early"])
        self.assertEqual(summary["sessions"], 10)
        self.assertEqual(len(summary["blocked_visits"]), 6)
        self.assertEqual(sum(r["customer_id"] == "bob" for r in rows), 8)
        self.assertTrue(
            all(
                not r["score"]["valid"] and r["failure_scope"] == "isolated_simulator"
                for r in rows
                if r["customer_id"] == "alice"
            )
        )
        self.assertFalse(
            any(r["customer_id"] == "alice" and r["sequence"] > 1 for r in rows)
        )
        # All OFF customer visits still precede every ON visit.
        arms = [r["condition"] for r in rows]
        self.assertEqual(arms, sorted(arms, key=lambda a: a == "user_memory_on"))

    def test_repeated_simulator_faults_stop_at_a_declared_global_threshold(self):
        from astra_eval.simulators import ScriptedShopper

        class Broken(ScriptedShopper):
            def respond(self, *args, **kwargs):
                raise SimulatorError("simulator_inconsistent")

        summary, rows, _ = self.run_timeline(
            Broken(), max_consecutive_simulator_failures=2
        )
        self.assertEqual(summary["stopped_early"], "simulator_failure_threshold")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not r["score"]["valid"] for r in rows))

    def test_transport_or_accounting_failure_stops_every_customer_immediately(self):
        from astra_eval.simulators import ScriptedShopper

        class Broken(ScriptedShopper):
            def respond(self, *args, **kwargs):
                raise SimulatorError("shopper_cost_usage_unknown")

        summary, rows, _ = self.run_timeline(Broken())
        self.assertEqual(summary["sessions"], 1)
        self.assertEqual(summary["stopped_early"], "session_error:simulator_failure")
        self.assertEqual(rows[0]["failure_scope"], "infrastructure")

    def test_returning_customer_memory_chain_and_other_arm_isolation_through_compact_runner(
        self,
    ):
        import re

        from test_compact_memory_evaluation import CompactPolicy

        from astra_eval.simulators import ScriptedShopper
        from shopping_agent.provider import PolicyReply
        from shopping_agent.sessions import Session

        class MemoryRankingPolicy(CompactPolicy):
            def complete(self, messages):
                response = super().complete(messages)
                context = json.loads(messages[-1]["content"])
                value = json.loads(response.content)
                records = context.get("user_memory", {}).get("records", [])
                color = next(
                    (
                        m.group(1)
                        for r in records
                        if (m := re.search(r"color: (Blue|Red)", r["text"]))
                    ),
                    None,
                )
                if value["action"]["type"] == "RECOMMEND" and color:
                    candidates = context["latest_search"]["candidates"]
                    matching = [
                        p["id"]
                        for p in candidates
                        if str(p.get("facts", {}).get("color")).casefold()
                        == color.casefold()
                    ]
                    value["action"]["product_ids"] = (
                        matching or value["action"]["product_ids"]
                    )[:1]
                return PolicyReply(json.dumps(value), response.metadata)

        summary, rows, config = self.run_timeline(
            ScriptedShopper(), MemoryRankingPolicy()
        )
        self.assertEqual(summary["sessions"], 16)
        on = [r for r in rows if r["condition"] == "user_memory_on"]
        off = [r for r in rows if r["condition"] == "user_memory_off"]
        self.assertTrue(
            all(
                not r["user_memory"]["updates"] and not r["user_memory"]["injected_ids"]
                for r in off
            )
        )
        for user in ("alice", "bob"):
            visits = [r for r in on if r["customer_id"] == user]
            self.assertTrue(visits[0]["user_memory"]["updates"])
            self.assertTrue(visits[1]["user_memory"]["retrieved_ids"])
            self.assertTrue(visits[1]["user_memory"]["injected_ids"])
            self.assertTrue(visits[1]["user_memory"]["recommendation_matches"])
            self.assertEqual(visits[1]["termination"], "target_found")
            path = (
                config.output
                / "astra/user_memory_on/sessions"
                / visits[0]["astra_session_id"]
            )
            session = Session(
                path, user, visits[0]["astra_session_id"], snapshot_format="compact"
            )
            prompts = [
                json.loads(e.payload["messages"][-1]["content"])
                for e in session.events
                if e.type == "model_request"
            ]
            self.assertEqual(prompts[0]["user_memory"]["records"], [])
            self.assertTrue(
                all(
                    "private-future-change" not in json.dumps(p)
                    and "verified_needs" not in p
                    and "persona" not in p
                    for p in prompts
                )
            )
        self.assertEqual(len({r["astra_session_id"] for r in rows}), 16)
