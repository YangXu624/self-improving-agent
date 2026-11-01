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
