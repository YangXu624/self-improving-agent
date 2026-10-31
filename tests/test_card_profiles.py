"""Representation/count isolation, visible grounding and historical replay safeguards."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import test_context_compaction as context_fixtures
from test_agent import ScriptedPolicy, recommend, search
from test_retrieval import product

from shopping_agent.agent import ShoppingAgent
from shopping_agent.cards import EXPERIMENT_PROFILES, semantic_cards, share_metadata
from shopping_agent.context import (
    BuiltContext,
    ContextIntegrityError,
    bind_context,
    builder_for_profile,
    product_context,
    search_context,
)
from shopping_agent.contracts import Event, ShoppingState
from shopping_agent.event_codec import decode_event, encode_event
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore, dumps


class CardProfileTests(unittest.TestCase):
    def result(self):
        fixture = context_fixtures.ContextCompactionTests()
        cards = [fixture.product(str(i)) for i in range(10)]
        return {
            "search_id": "search",
            "state_version": 0,
            "catalogue_version": "catalogue",
            "strategy_version": "strategy",
            "query": "boots",
            "match_mode": "all",
            "counts": {"verified_eligible": 10},
            "applied_hard_filters": [],
            "candidates": cards,
        }

    def test_four_profiles_preserve_evidence_and_prefix_count_exactly(self):
        raw = self.result()
        before = copy.deepcopy(raw)
        for name in EXPERIMENT_PROFILES:
            with self.subTest(profile=name):
                view = search_context(raw, name)
                expected = 5 if name.endswith("k5") else 10
                self.assertEqual(
                    semantic_cards(view),
                    [product_context(p) for p in raw["candidates"][:expected]],
                )
                self.assertEqual(
                    [p["id"] for p in view["candidates"]],
                    [str(i) for i in range(expected)],
                )
        self.assertEqual(raw, before)

    def test_sharing_preserves_empty_missing_and_negated_evidence(self):
        cards = [
            {
                "id": "a",
                "categories": [],
                "sources": {},
                "facts": {},
                "snippet": "Not waterproof",
            },
            {"id": "b", "facts": {}},
        ]
        self.assertEqual(semantic_cards(share_metadata(cards)), cards)
        raw = self.result()
        raw["candidates"][-1]["categories"] = ["HIDDEN category"]
        view = search_context(raw, "shared_k5")
        self.assertNotIn("HIDDEN category", json.dumps(view))

    def test_receipts_bind_actual_serialized_visibility_and_semantic_content(self):
        raw = self.result()
        receipts = []
        for name in ("v3_k5", "shared_k5"):
            messages = [
                {
                    "role": "user",
                    "content": dumps({"latest_search": search_context(raw, name)}),
                }
            ]
            receipts.append(bind_context(messages, raw, name).visible_search)
        self.assertEqual(receipts[0].product_ids, tuple(str(i) for i in range(5)))
        self.assertEqual(receipts[0].semantic_sha256, receipts[1].semantic_sha256)
        self.assertNotEqual(
            receipts[0].projection_sha256, receipts[1].projection_sha256
        )
        view = search_context(raw)
        view["candidates"][0]["facts"]["price"] = 1
        with self.assertRaises(ContextIntegrityError):
            bind_context([{"content": dumps({"latest_search": view})}], raw)

    def test_hidden_raw_id_rejected_visible_cards_hydrated_and_replay_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, db = root / "catalogue.jsonl", root / "index.sqlite"
            source.write_text(
                "".join(json.dumps(product(f"p{i:02}")) + "\n" for i in range(10))
            )
            build_index(source, db)
            tool, store = LexicalSearch(db), SessionStore(root / "sessions")
            try:
                sid = store.create("owner")
                policy = ScriptedPolicy(
                    search,
                    lambda c: recommend(c, ["p06"]),
                    lambda c: recommend(c, ["p04"]),
                )
                agent = ShoppingAgent(
                    store,
                    tool,
                    policy,
                    context_builder=builder_for_profile("shared_k5"),
                )
                result = agent.turn("owner", sid, "boots", request_id="once")
                self.assertEqual([p["id"] for p in result["products"]], ["p04"])
                self.assertIn("image_url", result["products"][0])
                self.assertIn("evidence", result["products"][0])
                with store.open("owner", sid) as session:
                    events = [e.model_dump() for e in session.events]
                    self.assertEqual(
                        len(
                            next(
                                e for e in session.events if e.type == "search_result"
                            ).payload["candidates"]
                        ),
                        10,
                    )
                    rejected = [
                        e.payload
                        for e in session.events
                        if e.type == "decision_rejected"
                    ]
                    self.assertEqual(
                        rejected[0]["feedback"][0]["code"],
                        "recommendation_contains_unseen_product_id",
                    )
                    for e in session.events:
                        if e.type == "model_request":
                            self.assertEqual(
                                hashlib.sha256(
                                    dumps(e.payload["messages"]).encode()
                                ).hexdigest(),
                                e.payload["context_sha256"],
                            )
                replay = ShoppingAgent(
                    store,
                    tool,
                    ScriptedPolicy(),
                    context_builder=builder_for_profile("baseline"),
                ).turn("owner", sid, "boots", request_id="once")
                self.assertEqual(replay, result)
                with store.open("owner", sid) as session:
                    self.assertEqual([e.model_dump() for e in session.events], events)
            finally:
                tool.close()

    def test_receipt_rejects_boolean_fact_and_state_version_coercion(self):
        raw = self.result()
        raw["candidates"][0]["facts"]["price"] = 1.0
        view = search_context(raw)
        view["candidates"][0]["facts"]["price"] = True
        with self.assertRaises(ContextIntegrityError):
            bind_context([{"content": dumps({"latest_search": view})}], raw)
        raw["state_version"] = 1
        view = search_context(raw)
        view["state_version"] = True
        with self.assertRaises(ContextIntegrityError):
            bind_context([{"content": dumps({"latest_search": view})}], raw)

    def test_receipt_event_is_json_native_before_and_after_disk_encoding(self):
        raw = self.result()
        messages = [
            {
                "role": "user",
                "content": dumps({"latest_search": search_context(raw, "shared_k5")}),
            }
        ]
        receipt = bind_context(messages, raw).visible_search
        event = Event(
            event_id="event",
            seq=1,
            session_id="session",
            user_id="owner",
            timestamp="date",
            turn_id=None,
            type="model_request",
            payload={"messages": messages, "visible_search": receipt.trace()},
        )
        encoded = json.loads(dumps(encode_event(event, [], ShoppingState())))
        recovered = decode_event(encoded, [], ShoppingState())
        self.assertEqual(recovered, event)
        self.assertEqual(recovered.model_dump(), event.model_dump())

    def test_forged_receipt_is_rejected_before_model_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, db = root / "catalogue.jsonl", root / "index.sqlite"
            source.write_text(json.dumps(product("p")) + "\n")
            build_index(source, db)
            tool, store = LexicalSearch(db), SessionStore(root / "sessions")
            try:
                sid = store.create("owner")

                def forged(*args):
                    good = builder_for_profile("baseline")(*args)
                    return BuiltContext(good.messages, object(), "baseline")

                policy = ScriptedPolicy()
                response = ShoppingAgent(
                    store, tool, policy, context_builder=forged
                ).turn("owner", sid, "boots")
                self.assertEqual(response["error"], "invalid_context_visibility")
                self.assertEqual(policy.contexts, [])
            finally:
                tool.close()


if __name__ == "__main__":
    unittest.main()
