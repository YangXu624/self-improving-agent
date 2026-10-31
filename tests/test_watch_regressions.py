"""Synthetic regressions from the watch incident; no private traces or live API.

Three expected failures describe pending correctness fixes. They are deliberately
not correctness passes; remove each marker when its reviewed fix is implemented.
"""

import json
import tempfile
import unittest
from pathlib import Path

from test_agent import ScriptedPolicy, decision
from test_retrieval import product
from test_sessions import add

from shopping_agent.agent import ShoppingAgent
from shopping_agent.contracts import Search, ShoppingState
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore
from shopping_agent.state import apply_updates


class WatchRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rows = []
        for ident, title, categories, price in [
            (
                "wearable",
                "Men classic wristwatch watch",
                ["Men", "Watches", "Wrist Watches"],
                30,
            ),
            (
                "case",
                "Men wristwatch watch display case",
                ["Watch Accessories", "Cabinets & Cases"],
                10,
            ),
            ("band", "Watch band", ["Men", "Watches", "Watch Bands"], 5),
            (
                "unknown-price-wearable",
                "Men wristwatch watch",
                ["Men", "Watches", "Wrist Watches"],
                None,
            ),
        ]:
            row = product(ident, price)
            row.update(title=title, categories=categories)
            rows.append(row)
        source, index = root / "catalogue.jsonl", root / "index.sqlite"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        build_index(source, index)
        self.search = LexicalSearch(index)
        self.addCleanup(self.search.close)
        self.store = SessionStore(root / "sessions")
        self.sid = self.store.create("shopper")

    def type_state(self, value):
        return apply_updates(
            ShoppingState(),
            [add("product_type", "eq", value, value)],
            expected_version=0,
            user_message=value,
            source_event_id="synthetic-user-event",
        )

    def candidates(self, state):
        return self.search.search(
            Search(type="SEARCH", query="watch wristwatch", mode="any"), state
        )["candidates"]

    def replay(self, final_action):
        def search(ctx, query, mode="all", updates=None):
            return decision(
                ctx,
                {"type": "SEARCH", "query": query, "mode": mode, "limit": 10},
                updates,
            )

        first_policy = ScriptedPolicy(
            lambda c: search(
                c,
                "watch",
                updates=[
                    add("product_type", "eq", "watch", "watch").model_dump(),
                    add("recipient", "eq", "dad", "dad", "soft").model_dump(),
                ],
            ),
            lambda c: search(c, "watch men wristwatch"),
            lambda c: decision(
                c,
                {
                    "type": "CLARIFY",
                    "attribute": "product_type",
                    "question": "An actual wristwatch or an accessory?",
                },
            ),
        )
        first = ShoppingAgent(self.store, self.search, first_policy).turn(
            "shopper", self.sid, "buying a watch for my dad"
        )
        self.assertEqual(first["action"], "CLARIFY")

        def correct(ctx):
            old = next(
                r for r in ctx["state"]["requirements"] if r["field"] == "product_type"
            )
            update = add(
                "product_type", "eq", "wristwatch", "actual wristwatch"
            ).model_dump()
            update.update(op="REPLACE", target_id=old["id"])
            return search(ctx, "wristwatch", updates=[update])

        second_policy = ScriptedPolicy(
            correct,
            lambda c: search(c, "watch wristwatch", "any"),
            lambda c: decision(c, final_action),
        )
        result = ShoppingAgent(self.store, self.search, second_policy).turn(
            "shopper", self.sid, "need an actual wristwatch to wear"
        )
        return result, second_policy

    def test_unfiltered_bm25_finds_wearable_products(self):
        for query in ("watch", "wristwatch"):
            with self.subTest(query=query):
                result = self.search.search(
                    Search(type="SEARCH", query=query), ShoppingState()
                )
                self.assertIn("wearable", {p["id"] for p in result["candidates"]})

    def test_catalogue_wording_matches_without_weakening_price_gate(self):
        state = self.type_state("wrist watches")
        state = apply_updates(
            state,
            [add(value=40.0, quote="under 40")],
            expected_version=state.version,
            user_message="under 40",
            source_event_id="synthetic-budget-event",
        )
        self.assertEqual([p["id"] for p in self.candidates(state)], ["wearable"])

    def test_corrected_turn_can_finish_with_existing_budget(self):
        response, policy = self.replay(
            {"type": "RESPOND", "message": "Search stopped; no items recommended."}
        )
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["products"], [])
        self.assertEqual(response["budget_used"], {"model_calls": 3, "searches": 2})
        self.assertEqual(
            policy.contexts[-1]["remaining_budget"],
            {
                "model_calls": 1,
                "searches": 0,
            },
        )
        with self.store.open("shopper", self.sid) as session:
            requirements = session.state.requirements
            old = next(r for r in requirements if r.value == "watch")
            new = next(r for r in requirements if r.value == "wristwatch")
            self.assertEqual(session.state.version, 2)
            self.assertEqual(old.status, "superseded")
            self.assertEqual(new.status, "active")
            self.assertEqual(new.replaces_id, old.id)
            self.assertTrue(
                any(r.value == "dad" and r.status == "active" for r in requirements)
            )
            results = [e.payload for e in session.events if e.type == "search_result"]
            self.assertEqual([r["state_version"] for r in results], [1, 1, 2, 2])
            self.assertFalse(any(e.type == "recommendation" for e in session.events))

    @unittest.expectedFailure
    def test_singular_watch_does_not_filter_out_wearable_watch(self):
        """Pending: literal 'watch' currently admits accessories but drops 'Watches'."""
        ids = {p["id"] for p in self.candidates(self.type_state("watch"))}
        self.assertIn("wearable", ids)

    @unittest.expectedFailure
    def test_wristwatch_requirement_finds_wearable_and_excludes_accessories(self):
        """Pending: compound 'wristwatch' currently matches no category tokens."""
        ids = {p["id"] for p in self.candidates(self.type_state("wristwatch"))}
        self.assertEqual(ids, {"wearable", "unknown-price-wearable"})

    @unittest.expectedFailure
    def test_final_repeated_search_gets_safe_terminal_closure(self):
        """Pending: executor rejects the action but currently emits generic exhaustion."""
        response, policy = self.replay(
            {"type": "SEARCH", "query": "watch wristwatch", "mode": "any", "limit": 10}
        )
        self.assertEqual(len(policy.contexts), 3)
        self.assertEqual(response["budget_used"], {"model_calls": 3, "searches": 2})
        self.assertEqual(response["products"], [])
        self.assertEqual(response["status"], "ok")
        self.assertIn(response["action"], {"CLARIFY", "RESPOND"})
        self.assertNotIn("error", response)


if __name__ == "__main__":
    unittest.main()
