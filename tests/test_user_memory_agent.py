"""Stage 1 acceptance through the real executor and mocked decision policy."""

import unittest

import test_agent as fixtures
from test_agent import decision, recommend, search
from test_user_memory import preference

from shopping_agent.agent import ShoppingAgent
from shopping_agent.context import PROMPT_VERSION, build_context
from shopping_agent.user_memory import MemoryDecision, UserMemoryStore


class UserMemoryAgentTests(unittest.TestCase):
    def setUp(self):
        fixtures.AgentTests.setUp(self)
        self.memory = UserMemoryStore(self.root / "user-memory")

    def agent(self, *steps, **kwargs):
        kwargs.setdefault("user_memory", self.memory)
        self.policy = fixtures.ScriptedPolicy(*steps)
        return ShoppingAgent(self.store, self.search, self.policy, **kwargs)

    def events(self):
        return fixtures.AgentTests.events(self)

    def remember(self):
        def response(ctx):
            result = decision(ctx, {"type": "RESPOND", "message": "Preference noted."})
            result["user_memory_updates"] = [preference().model_dump()]
            return result

        return self.agent(response).turn(
            "alice", self.sid, preference().quote, request_id="remember"
        )

    def test_a_cross_session_actual_context_and_restart(self):
        self.remember()
        second = self.store.create("alice")
        self.memory = UserMemoryStore(self.root / "user-memory")
        agent = self.agent(
            lambda c: decision(c, {"type": "RESPOND", "message": "What kind of bags?"})
        )
        agent.turn("alice", second, "I need bags")
        context = self.policy.contexts[0]
        self.assertEqual(context["user_memory"]["records"][0]["value"], "blue")
        self.assertEqual(context["state"]["requirements"], [])
        self.assertEqual(self.memory.read("alice").revision, 1)

    def test_b_isolation_via_normal_agent_interface(self):
        self.remember()
        bob = self.store.create("bob")
        agent = self.agent(
            lambda c: decision(c, {"type": "RESPOND", "message": "Hello"})
        )
        agent.turn("bob", bob, "bags")
        self.assertEqual(self.policy.contexts[0]["user_memory"]["records"], [])
        with self.assertRaises(PermissionError):
            agent.turn("bob", self.sid, "bags")

    def test_c_temporary_and_gift_updates_reject_without_failing_shopping(self):
        proposal = preference(quote="I generally prefer blue bags for my dad")

        def response(ctx):
            result = decision(ctx, {"type": "RESPOND", "message": "Let's find a gift."})
            result["user_memory_updates"] = [proposal.model_dump()]
            return result

        result = self.agent(response).turn("alice", self.sid, proposal.quote)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["user_memory"]["rejected"])
        self.assertEqual(self.memory.read("alice").records, [])

    def test_d_explicit_correction_changes_next_session_recall(self):
        self.remember()
        self.sid = self.store.create("alice")
        quote = "Actually I now generally prefer black bags instead of blue"

        def correction(ctx):
            previous = ctx["user_memory"]["records"][0]
            result = decision(
                ctx, {"type": "RESPOND", "message": "Preference corrected."}
            )
            result["user_memory_updates"] = [
                preference(
                    value="black", quote=quote, op="REPLACE", target_id=previous["id"]
                ).model_dump()
            ]
            return result

        self.agent(correction).turn("alice", self.sid, quote)
        self.sid = self.store.create("alice")
        self.agent(lambda c: decision(c, {"type": "RESPOND", "message": "Hello"})).turn(
            "alice", self.sid, "bags"
        )
        self.assertEqual(
            [r["value"] for r in self.policy.contexts[0]["user_memory"]["records"]],
            ["black"],
        )
        self.assertEqual(
            [r.status for r in self.memory.read("alice").records],
            ["superseded", "active"],
        )

    def test_e_off_has_no_reads_writes_context_schema_or_audit(self):
        self.remember()
        before = (self.memory.directory("alice") / "profile.md").read_bytes()
        agent = self.agent(
            lambda c: decision(c, {"type": "RESPOND", "message": "Hello"}),
            user_memory=None,
        )
        agent.turn("alice", self.sid, "bags")
        self.assertNotIn("user_memory", self.policy.contexts[0])
        self.assertEqual(self.policy.contexts[0]["prompt_version"], PROMPT_VERSION)
        self.assertNotIn(
            "user_memory_updates",
            __import__(
                "shopping_agent.contracts", fromlist=["Decision"]
            ).Decision.model_fields,
        )
        self.assertEqual(
            (self.memory.directory("alice") / "profile.md").read_bytes(), before
        )

    def test_retries_do_not_write_twice(self):
        first = self.remember()
        second = self.agent().turn(
            "alice", self.sid, preference().quote, request_id="remember"
        )
        self.assertEqual(first, second)
        self.assertEqual(self.memory.read("alice").revision, 1)

    def test_legacy_builder_omission_not_injected_or_written(self):
        def legacy(*args):
            return build_context(*args)

        def response(ctx):
            result = decision(ctx, {"type": "RESPOND", "message": "Hello"})
            result["user_memory_updates"] = [preference().model_dump()]
            return result

        self.agent(response, context_builder=legacy).turn(
            "alice", self.sid, preference().quote
        )
        events = self.events()
        self.assertEqual(
            next(e for e in events if e.type == "user_memory_injection").payload[
                "injected"
            ],
            [],
        )
        self.assertEqual(self.memory.read("alice").records, [])

    def test_profile_guidance_does_not_change_hard_filters_or_products(self):
        self.remember()
        self.agent(search, recommend).turn("alice", self.sid, "boots")
        self.assertEqual(
            len(self.policy.contexts[-1]["latest_search"]["candidates"]), 3
        )

    def test_contract_and_procedural_guidance_can_coexist(self):
        from shopping_agent.context import build_decision_context

        with self.store.open("alice", self.sid) as session:
            view = self.memory.context(session, "bags")
            built = build_decision_context(
                session,
                "bags",
                None,
                [],
                {},
                True,
                procedural_guidance=[
                    {"lesson_id": "fixture", "directive": "Ask a useful question"}
                ],
                user_memory=view,
            )
            import json

            payload = json.loads(built.messages[-1]["content"])
            self.assertIn("procedural_guidance", payload)
            self.assertIn("user_memory", payload)
            self.assertIn("user_memory_updates", built.messages[0]["content"])
        self.assertIn("user_memory_updates", MemoryDecision.model_fields)

    def test_stage2_natural_preference_end_to_end_lifecycle_on_and_off(self):
        # Visit 1 (Memory ON): Exact customer utterance and proposal from Stage 2 canary
        visit1_sid = self.store.create("dev-activewear")
        utterance = (
            "Hi! I'm looking for a casual tank top to wear to the gym. Nothing fancy, "
            "and I'd like to keep it affordable, under $50 ideally. Black is usually "
            "my go-to for workout stuff if you have any."
        )
        quote = "Black is usually my go-to for workout stuff"
        proposal = {
            "category": "preference",
            "attribute": "color",
            "value": "black",
            "scope": "workout",
            "quote": quote,
            "basis": "confirmed",
        }

        def visit1_decision(ctx):
            res = decision(ctx, {"type": "RESPOND", "message": "I found workout options."})
            res["user_memory_updates"] = [proposal]
            return res

        agent_on = self.agent(visit1_decision)
        turn1_result = agent_on.turn(
            "dev-activewear", visit1_sid, utterance, request_id="v1-turn1"
        )
        self.assertEqual(turn1_result["status"], "ok")
        # Verify memory update was accepted and not rejected
        self.assertEqual(turn1_result["user_memory"]["rejected"], [])
        self.assertEqual(len(turn1_result["user_memory"]["updates"]), 1)

        # Verify persistent profile on disk was written with revision 1
        profile = self.memory.read("dev-activewear")
        self.assertEqual(profile.revision, 1)
        active_records = [r for r in profile.records if r.status == "active"]
        self.assertEqual(len(active_records), 1)
        self.assertEqual(active_records[0].value, "black")
        self.assertEqual(active_records[0].scope, "workout")
        self.assertEqual(active_records[0].quote, quote)

        # Visit 2 (Memory ON): Fresh subsequent session for the same returning customer
        visit2_sid = self.store.create("dev-activewear")
        fresh_memory_store = UserMemoryStore(self.root / "user-memory")
        policy_on = fixtures.ScriptedPolicy(
            lambda ctx: decision(ctx, {"type": "RESPOND", "message": "Looking for workout tops."})
        )
        agent_on_visit2 = ShoppingAgent(
            self.store, self.search, policy_on, user_memory=fresh_memory_store
        )
        agent_on_visit2.turn(
            "dev-activewear",
            visit2_sid,
            "I'm back looking for a workout top for the gym.",
            request_id="v2-turn1",
        )
        # Verify preference was retrieved and injected into ASTRA's model-visible context
        injected_context = policy_on.contexts[0]
        self.assertIn("user_memory", injected_context)
        memory_records = injected_context["user_memory"]["records"]
        self.assertEqual(len(memory_records), 1)
        self.assertEqual(memory_records[0]["value"], "black")
        self.assertEqual(memory_records[0]["scope"], "workout")

        # Memory OFF comparison: Session evaluated without persistent user memory
        visit_off_sid = self.store.create("dev-activewear")
        policy_off = fixtures.ScriptedPolicy(
            lambda ctx: decision(ctx, {"type": "RESPOND", "message": "Looking for tops."})
        )
        agent_off = ShoppingAgent(self.store, self.search, policy_off, user_memory=None)
        agent_off.turn(
            "dev-activewear",
            visit_off_sid,
            "I'm back looking for a workout top for the gym.",
            request_id="v-off-turn1",
        )
        # Verify memory OFF has no persistent profile access
        off_context = policy_off.contexts[0]
        self.assertNotIn("user_memory", off_context)
