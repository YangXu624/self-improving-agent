import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_retrieval import product

from shopping_agent.retrieval import build_index
from shopping_agent.ui_service import ChatService


class UiServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue, self.index = (
            self.root / "catalog.jsonl",
            self.root / "index.sqlite",
        )
        rows = [
            product("cotton", 45, Color="Red", Material="Cotton"),
            product("leather", 75, Color="Blue", Material="Leather"),
            product("unknown", None),
        ]
        rows.append(
            {
                **product("bag", 25),
                "title": "Backpack",
                "categories": ["Bags", "Backpack"],
            }
        )
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.catalogue, self.index)
        self.service = ChatService(self.catalogue, self.index, self.root / "sessions")
        self.sid = self.service.create("alice")
        self.number = 0

    def send(self, message):
        self.number += 1
        return self.service.send("alice", self.sid, message, f"request-{self.number}")

    def test_clarify_real_search_recommend_without_network_or_credentials(self):
        with patch(
            "shopping_agent.provider.urlopen",
            side_effect=AssertionError("No live transport"),
        ):
            self.assertEqual(self.send("hello")["action"], "CLARIFY")
            response = self.send("boots under $60")
        self.assertEqual(response["action"], "RECOMMEND")
        self.assertEqual([p["id"] for p in response["products"]], ["cotton"])
        view = self.service.view("alice", self.sid)
        self.assertEqual(
            [m["role"] for m in view["messages"]],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertTrue(any(e["type"] == "search_result" for e in view["events"]))
        meta = next(
            e["payload"]["metadata"]
            for e in view["events"]
            if e["type"] == "model_response"
        )
        self.assertEqual(meta["provider"], "mock")

    def test_budget_replacement_and_persistent_resume(self):
        self.send("boots under $100")
        response = self.send("actually under $60")
        self.assertEqual([p["id"] for p in response["products"]], ["cotton"])
        another = ChatService(self.catalogue, self.index, self.root / "sessions")
        another.resume("alice", self.sid)
        view = another.view("alice", self.sid)
        prices = [r for r in view["state"]["requirements"] if r["field"] == "price"]
        self.assertEqual([r["status"] for r in prices], ["superseded", "active"])
        self.assertEqual(prices[-1]["value"], 60)
        self.assertEqual(len(view["messages"]), 4)

    def test_soft_preference_does_not_replace_hard_need(self):
        self.send("red boots under $100")
        response = self.send("prefer blue")
        self.assertEqual([p["id"] for p in response["products"]], ["cotton"])
        active = [
            r
            for r in self.service.view("alice", self.sid)["state"]["requirements"]
            if r["status"] == "active"
        ]
        self.assertEqual(
            {(r["value"], r["strength"]) for r in active if r["field"] == "color"},
            {("red", "hard"), ("blue", "soft")},
        )

    def test_exclusion_withdrawal_and_new_goal(self):
        response = self.send("boots under $100 no leather")
        self.assertEqual([p["id"] for p in response["products"]], ["cotton"])
        response = self.send("leather is okay")
        self.assertEqual({p["id"] for p in response["products"]}, {"cotton", "leather"})
        response = self.send("new goal: backpack")
        self.assertEqual([p["id"] for p in response["products"]], ["bag"])
        state = self.service.view("alice", self.sid)["state"]
        self.assertEqual(state["goal_epoch"], 1)
        self.assertEqual(
            [r["field"] for r in state["requirements"] if r["status"] == "active"],
            ["product_type"],
        )

    def test_empty_results_are_visible_without_fake_products(self):
        response = self.send("boots under $1")
        self.assertEqual(response["action"], "RESPOND")
        self.assertEqual(response["products"], [])
        self.assertIn("No verified matches", response["message"])
        search = next(
            e
            for e in self.service.view("alice", self.sid)["events"]
            if e["type"] == "search_result"
        )
        self.assertEqual(search["payload"]["counts"]["verified_eligible"], 0)

    def test_user_session_isolation_listing_and_bad_resume(self):
        self.send("boots under $100")
        second = self.service.create("alice")
        bob = self.service.create("bob")
        self.assertEqual(
            {s["id"] for s in self.service.sessions("alice")}, {self.sid, second}
        )
        self.assertEqual({s["id"] for s in self.service.sessions("bob")}, {bob})
        self.assertEqual(self.service.view("alice", second)["messages"], [])
        with self.assertRaises(PermissionError):
            self.service.resume("bob", self.sid)
        with self.assertRaises(ValueError):
            self.service.resume("alice", "../../escape")

    def test_completed_request_replay_does_not_duplicate_messages(self):
        first = self.service.send("alice", self.sid, "boots", "same")
        second = self.service.send("alice", self.sid, "boots", "same")
        self.assertEqual(first, second)
        self.assertEqual(len(self.service.view("alice", self.sid)["messages"]), 2)

    def test_service_opens_sqlite_in_each_calling_thread(self):
        other = self.service.create("alice")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.service.send, "alice", sid, "boots under $60", "one")
                for sid in [self.sid, other]
            ]
            responses = [f.result() for f in futures]
        self.assertTrue(all(r["status"] == "ok" for r in responses))

    def test_stale_index_refused_and_unrecognised_text_explained(self):
        response = self.send("boots")
        before = response["state_version"]
        response = self.send("please teleport it")
        self.assertIn("scripted demo", response["message"])
        self.assertEqual(response["state_version"], before)
        self.catalogue.write_text(self.catalogue.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Stale catalogue"):
            ChatService(self.catalogue, self.index, self.root / "other")
