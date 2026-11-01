"""Real executor tests of compact policy payloads; providers are scripted fixtures."""

import json
import unittest

import test_agent as fixtures
from test_sessions import add
from test_user_memory import preference

from shopping_agent.agent import ShoppingAgent
from shopping_agent.context import build_decision_context
from shopping_agent.memory_views import COMPACT_PROMPT_VERSION
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore


def decision(action, updates=None, memory=None):
    value = {"updates": updates or [], "action": action, "reason": "Compact fixture"}
    if memory:
        value["user_memory_updates"] = memory
    return value


def search(_context):
    return decision({"type": "SEARCH", "query": "boots"})


def recommend(context):
    result = context["latest_search"]
    return decision(
        {
            "type": "RECOMMEND",
            "search_id": result["search_id"],
            "product_ids": [p["id"] for p in result["candidates"]],
        }
    )


class CompactMemoryAgentTests(unittest.TestCase):
    def setUp(self):
        fixtures.AgentTests.setUp(self)
        self.memory = UserMemoryStore(self.root / "users")

    def agent(self, *steps, **kwargs):
        self.policy = fixtures.ScriptedPolicy(*steps)
        return ShoppingAgent(
            self.store, self.search, self.policy, memory_format="compact", **kwargs
        )

    def events(self):
        return fixtures.AgentTests.events(self)

    def test_search_correction_invalidates_old_results_and_keeps_hard_gates(self):
        self.agent(
            lambda c: decision(
                {"type": "SEARCH", "query": "boots"}, [add().model_dump()]
            ),
            recommend,
        ).turn("alice", self.sid, "under 100")
        first = self.policy.contexts[1]
        self.assertEqual(first["state"]["hard"]["price"], [{"lt": 100.0}])
        self.assertNotIn("state_version", first["latest_search"])
        self.assertNotIn("applied_hard_filters", first["latest_search"])

        def correct(context):
            value = recommend(context)
            value["updates"] = [
                {
                    "op": "REPLACE",
                    "target_id": "hard.price.0",
                    "quote": "under 60",
                    "requirement": add(
                        value=60.0, quote="under 60"
                    ).requirement.model_dump(),
                }
            ]
            return value

        result = self.agent(correct, search, recommend).turn(
            "alice", self.sid, "Actually under 60"
        )
        self.assertEqual([p["id"] for p in result["products"]], ["cheap"])
        self.assertIsNone(self.policy.contexts[1]["latest_search"])
        self.assertEqual(result["state_version"], 2)
        requests = [e for e in self.events() if e.type == "model_request"]
        self.assertTrue(
            all(e.payload["prompt_version"] == COMPACT_PROMPT_VERSION for e in requests)
        )

    def test_text_memory_formation_recall_correction_and_audit(self):
        self.agent(
            lambda c: decision(
                {"type": "RESPOND", "message": "Noted"},
                memory=[preference().model_dump()],
            ),
            user_memory=self.memory,
        ).turn("alice", self.sid, preference().quote)
        self.sid = self.store.create("alice")
        quote = "Actually I now generally prefer Black bags instead of Blue"
        change = preference(
            value="Black", quote=quote, op="REPLACE", target_id="um-" + "1" * 32
        ).model_dump()
        change["target_id"] = "memory.0"
        self.agent(
            lambda c: decision(
                {"type": "RESPOND", "message": "Corrected"}, memory=[change]
            ),
            user_memory=self.memory,
        ).turn("alice", self.sid, quote)
        view = self.policy.contexts[0]
        self.assertEqual(set(view["user_memory"]["records"][0]), {"ref", "text"})
        self.assertIn("blue", view["user_memory"]["records"][0]["text"])
        records = self.memory.read("alice").records
        self.assertEqual(
            [(r.value, r.status) for r in records],
            [("blue", "superseded"), ("Black", "active")],
        )
        request = next(e for e in self.events() if e.type == "model_request")
        self.assertEqual(
            request.payload["user_memory_records"]["records"][0]["id"], records[0].id
        )
        injected = next(e for e in self.events() if e.type == "user_memory_injection")
        self.assertEqual(injected.payload["injected"], [records[0].id])

    def test_invalid_edit_reference_is_rejected_without_changes(self):
        bad = decision(
            {"type": "RESPOND", "message": "No"},
            [{"op": "RETRACT", "target_id": "hard.price.99", "quote": "remove budget"}],
        )
        response = self.agent(bad, bad, bad).turn("alice", self.sid, "remove budget")
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["state_version"], 0)
        self.assertTrue(
            any(
                e.type == "decision_rejected"
                and e.payload["feedback"][0]["code"]
                == "invalid_current_state_reference"
                for e in self.events()
            )
        )

    def test_compact_snapshot_is_rebuilt_from_full_unchanged_event_history(self):
        store = SessionStore(self.root / "compact-sessions", snapshot_format="compact")
        sid = store.create("alice")
        policy = fixtures.ScriptedPolicy(
            lambda c: decision(
                {"type": "RESPOND", "message": "Noted"}, [add().model_dump()]
            )
        )
        ShoppingAgent(store, self.search, policy, memory_format="compact").turn(
            "alice", sid, "under 100"
        )
        path = store.root / sid / "state.json"
        snapshot = json.loads(path.read_text())
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["state"]["hard"]["price"], [{"lt": 100.0}])
        self.assertNotIn("requirements", snapshot["state"])
        self.assertEqual(snapshot["_audit"]["state_version"], 1)
        before = (store.root / sid / "events.jsonl").read_bytes()
        path.write_text("corrupt cache")
        with store.open("alice", sid) as session:
            self.assertEqual(session.state.requirements[0].value, 100.0)
        self.assertEqual((store.root / sid / "events.jsonl").read_bytes(), before)

    def test_named_card_profiles_keep_visible_facts_and_receipt_checks(self):
        self.agent(
            lambda c: decision(
                {"type": "SEARCH", "query": "boots"}, [add().model_dump()]
            ),
            recommend,
        ).turn("alice", self.sid, "under 100")
        from shopping_agent.context import latest_search

        with self.store.open("alice", self.sid) as session:
            result = latest_search(
                session, self.search.catalogue_version, self.search.strategy_version
            )
            for name in ("baseline", "v3_k5", "shared_k5"):
                built = build_decision_context(
                    session,
                    "boots",
                    result,
                    [],
                    {},
                    True,
                    memory_format="compact",
                    cards_profile=name,
                )
                self.assertEqual(built.visible_search.product_ids, ("cheap", "costly"))
                self.assertEqual(built.visible_search.state_version, 1)

    def test_user_memory_omitted_by_custom_builder_cannot_be_written(self):
        def omit(*args, **kwargs):
            kwargs.pop("user_memory", None)
            return build_decision_context(*args, **kwargs)

        result = self.agent(
            lambda c: decision(
                {"type": "RESPOND", "message": "Okay"},
                memory=[preference().model_dump()],
            ),
            user_memory=self.memory,
            context_builder=omit,
        ).turn("alice", self.sid, preference().quote)
        self.assertIn(
            "user_memory_context_not_injected", result["user_memory"]["rejected"]
        )
        self.assertEqual(self.memory.read("alice").records, [])
