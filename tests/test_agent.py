import json
import tempfile
import unittest
from pathlib import Path

from test_retrieval import product
from test_sessions import add

from shopping_agent.agent import ShoppingAgent
from shopping_agent.context import ContextLimitError, build_context
from shopping_agent.provider import PolicyReply, ProviderError
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionError, SessionStore


def decision(ctx, action, updates=None):
    return {
        "based_on_state_version": ctx["state"]["version"],
        "updates": updates or [],
        "action": action,
        "reason": "Fixture decision",
    }


def search(ctx, updates=None):
    return decision(ctx, {"type": "SEARCH", "query": "boots"}, updates)


def recommend(ctx, ids=None):
    result = ctx["latest_search"]
    return decision(
        ctx,
        {
            "type": "RECOMMEND",
            "search_id": result["search_id"],
            "product_ids": ids or [p["id"] for p in result["candidates"]][:2],
        },
    )


class ScriptedPolicy:
    """Test-only decisions; never a production offline fallback."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.contexts = []

    def complete(self, messages):
        ctx = json.loads(messages[-1]["content"])
        self.contexts.append(ctx)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        value = step(ctx) if callable(step) else step
        return PolicyReply(
            value if isinstance(value, str) else json.dumps(value),
            {"provider": "fixture", "usage": {"total_tokens": 10}},
        )


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        src, db = self.root / "catalog.jsonl", self.root / "index.sqlite"
        src.write_text(
            "".join(
                json.dumps(p) + "\n"
                for p in [
                    product("cheap", 45, Material="Cotton", Color="Red"),
                    product("costly", 80, Material="Leather", Color="Blue"),
                    product("unknown", None),
                ]
            )
        )
        build_index(src, db)
        self.search = LexicalSearch(db)
        self.addCleanup(self.search.close)
        self.store = SessionStore(self.root / "sessions")
        self.sid = self.store.create("alice")

    def agent(self, *steps, **kwargs):
        self.policy = ScriptedPolicy(*steps)
        return ShoppingAgent(self.store, self.search, self.policy, **kwargs)

    def events(self):
        with self.store.open("alice", self.sid) as s:
            return list(s.events)

    def test_clarify_search_inspect_recommend_restart(self):
        a = self.agent(
            lambda c: decision(
                c,
                {
                    "type": "CLARIFY",
                    "attribute": "price",
                    "question": "What is your maximum budget in USD?",
                },
            )
        )
        first = a.turn("alice", self.sid, "I want boots")
        self.assertEqual(first["action"], "CLARIFY")
        a = self.agent(
            lambda c: search(c, [add(value=60.0, quote="under 60 USD").model_dump()]),
            recommend,
        )
        result = a.turn("alice", self.sid, "under 60 USD")
        self.assertEqual(result["budget_used"], {"model_calls": 2, "searches": 1})
        self.assertEqual([p["id"] for p in result["products"]], ["cheap"])
        self.assertEqual(result["products"][0]["evidence"]["price"]["value"], 45)
        ctx = self.policy.contexts[-1]
        self.assertEqual(ctx["latest_search"]["candidates"][0]["id"], "cheap")
        self.assertFalse(ctx["edits_allowed"])
        with SessionStore(self.root / "sessions").open("alice", self.sid) as s:
            self.assertEqual(s.state.version, 1)
            self.assertTrue(any(e.type == "recommendation" for e in s.events))
            self.assertEqual(len([e for e in s.events if e.type == "user_message"]), 2)

    def test_correction_invalidates_inspected_result_then_searches_again(self):
        self.agent(lambda c: search(c, [add().model_dump()]), recommend).turn(
            "alice", self.sid, "under 100"
        )

        def correct(c):
            old = c["state"]["requirements"][0]
            d = recommend(c)
            d["updates"] = [
                {
                    "op": "REPLACE",
                    "target_id": old["id"],
                    "quote": "under 60",
                    "requirement": add(
                        value=60.0, quote="under 60"
                    ).requirement.model_dump(),
                }
            ]
            return d

        a = self.agent(correct, search, recommend)
        response = a.turn("alice", self.sid, "Actually under 60")
        self.assertEqual([p["id"] for p in response["products"]], ["cheap"])
        self.assertIsNone(self.policy.contexts[1]["latest_search"])
        self.assertEqual(self.policy.contexts[1]["state"]["version"], 2)
        self.assertFalse(self.policy.contexts[1]["edits_allowed"])
        with self.store.open("alice", self.sid) as s:
            self.assertEqual(
                [r.status for r in s.state.requirements], ["superseded", "active"]
            )

    def test_exclusion_withdrawal_preserves_other_requirements(self):
        edits = [
            add().model_dump(),
            add("material", "neq", "leather", "no leather").model_dump(),
        ]
        self.agent(lambda c: search(c, edits), recommend).turn(
            "alice", self.sid, "under 100 no leather"
        )

        def retract(c):
            r = next(r for r in c["state"]["requirements"] if r["field"] == "material")
            return search(
                c, [{"op": "RETRACT", "target_id": r["id"], "quote": "leather is okay"}]
            )

        out = self.agent(retract, recommend).turn("alice", self.sid, "leather is okay")
        self.assertEqual({p["id"] for p in out["products"]}, {"cheap", "costly"})
        with self.store.open("alice", self.sid) as s:
            active = [r for r in s.state.requirements if r.status == "active"]
            self.assertEqual([r.field for r in active], ["price"])

    def test_repair_invalid_json_and_schema_is_bounded_and_traced(self):
        a = self.agent(
            "{not json",
            {"sql": "DROP TABLE products"},
            lambda c: decision(
                c,
                {
                    "type": "CLARIFY",
                    "question": "What product?",
                    "attribute": "product_type",
                },
            ),
        )
        out = a.turn("alice", self.sid, "hello")
        self.assertEqual(out["action"], "CLARIFY")
        self.assertEqual(out["budget_used"]["model_calls"], 3)
        rejected = [e for e in self.events() if e.type == "decision_rejected"]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(
            all(
                "input" not in err
                for err in rejected[1].payload["feedback"][0]["errors"]
            )
        )

    def test_invented_id_and_recommend_without_search_are_rejected(self):
        a = self.agent(
            lambda c: decision(
                c,
                {
                    "type": "RECOMMEND",
                    "search_id": "invented",
                    "product_ids": ["cheap"],
                },
            ),
            search,
            lambda c: recommend(c, ["invented"]),
        )
        out = a.turn("alice", self.sid, "boots")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["products"], [])
        codes = [
            e.payload["feedback"][0]["code"]
            for e in self.events()
            if e.type == "decision_rejected"
        ]
        self.assertEqual(
            codes,
            [
                "recommendation_requires_inspected_current_search",
                "recommendation_contains_unseen_product_id",
            ],
        )

    def test_conflict_blocks_search_and_accepted_state_survives(self):
        edits = [
            add().model_dump(),
            add(op="gte", value=120.0, quote="over 120").model_dump(),
        ]
        a = self.agent(lambda c: search(c, edits), search, search)
        out = a.turn("alice", self.sid, "under 100 over 120")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["state_version"], 1)
        self.assertEqual(out["budget_used"]["searches"], 0)
        with self.store.open("alice", self.sid) as s:
            self.assertTrue(s.state.conflicts)

    def test_repeated_search_cannot_loop_or_exceed_budget(self):
        a = self.agent(search, search, search)
        out = a.turn("alice", self.sid, "boots")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["budget_used"], {"model_calls": 3, "searches": 2})
        self.assertEqual(
            len([e for e in self.events() if e.type == "search_result"]), 2
        )

    def test_provider_error_has_no_retry_and_completed_replay_no_extra_call(self):
        a = self.agent(ProviderError("provider_http_401"))
        out = a.turn("alice", self.sid, "boots", request_id="once")
        replay = a.turn("alice", self.sid, "boots", request_id="once")
        self.assertEqual(out, replay)
        self.assertEqual(len(self.policy.contexts), 1)
        self.assertEqual(out["error"], "provider_http_401")
        with self.assertRaises(SessionError):
            a.turn("alice", self.sid, "different", request_id="once")

    def test_interrupted_retry_fails_closed(self):
        with self.store.open("alice", self.sid) as s:
            s.append("turn_started", {}, "crashed")
            s.append("user_message", {"message": "boots"}, "crashed")
        a = self.agent(search)
        with self.assertRaises(SessionError):
            a.turn("alice", self.sid, "boots", request_id="crashed")
        self.assertEqual(self.policy.contexts, [])

    def test_user_and_session_isolation(self):
        self.agent(lambda c: search(c, [add().model_dump()]), recommend).turn(
            "alice", self.sid, "under 100"
        )
        sid2 = self.store.create("alice")
        a = self.agent(lambda c: decision(c, {"type": "RESPOND", "message": "Hello"}))
        a.turn("alice", sid2, "hello")
        self.assertEqual(self.policy.contexts[0]["state"]["requirements"], [])
        self.assertIsNone(self.policy.contexts[0]["latest_search"])
        with self.assertRaises(PermissionError):
            a.turn("bob", self.sid, "hello")
        self.assertEqual(len(self.policy.contexts), 1)

    def test_essential_context_not_silently_truncated(self):
        with self.store.open("alice", self.sid) as s:
            with self.assertRaises(ContextLimitError):
                build_context(s, "hello", None, [], {}, True, max_chars=30)

    def test_empty_result_does_not_fabricate_recommendation(self):
        a = self.agent(
            lambda c: decision(c, {"type": "SEARCH", "query": "spaceship"}),
            lambda c: decision(
                c,
                {
                    "type": "CLARIFY",
                    "question": "Would boots be suitable?",
                    "attribute": "product_type",
                },
            ),
        )
        out = a.turn("alice", self.sid, "spaceship")
        self.assertEqual(out["products"], [])
        self.assertEqual(
            self.policy.contexts[-1]["latest_search"]["counts"]["verified_eligible"], 0
        )
