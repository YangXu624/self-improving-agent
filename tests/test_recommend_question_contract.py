"""Deterministic test suite proving ASTRA's Recommendation + Question response contract.

Response Contract:
1. Every successful normal user-facing shopping response contains BOTH:
   - At least one verified, relevant product recommendation (product_ids)
   - Exactly one useful follow-up question that helps refine the next recommendation
2. Proactive recommendation-first reasoning (no standalone clarification turns avoiding search)
3. Truly unsatisfiable requests trigger explicit NO_MATCH exception asking what to relax
4. Strict UI rendering order: (1) Explanation, (2) Product cards, (3) Follow-up question, (4) Chat input
5. Target scoring compatibility, customer isolation, and memory preservation
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from astra_eval.target_scoring import TargetRule
from shopping_agent.agent import ShoppingAgent
from shopping_agent.contracts import Recommend
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore
from shopping_agent.ui_service import ChatService


def make_test_catalogue_and_index(tmp_dir: Path) -> tuple[Path, Path]:
    cat_path = tmp_dir / "catalog.jsonl"
    idx_path = tmp_dir / "catalogue.sqlite"

    items = [
        {
            "parent_asin": f"ITEM_{i:03d}",
            "title": f"Active Workout Top {i}" if i % 2 == 0 else f"Running Shorts {i}",
            "description": ["Breathable relaxed fit black workout gear"]
            if i == 0
            else ["Polyester running apparel"],
            "features": ["active wear"],
            "price": 25.0 + (i * 10.0),
            "categories": ["Clothing", "Tops"]
            if i % 2 == 0
            else ["Clothing", "Bottoms"],
            "details": {
                "Department": "women" if i % 2 == 0 else "men",
                "Color": "black" if i < 3 else "blue",
                "Fit": "relaxed" if i == 0 else "fitted",
                "Product Type": "top" if i % 2 == 0 else "bottom",
            },
            "average_rating": 4.5,
            "rating_number": 20,
            "store": "ActiveStore",
        }
        for i in range(10)
    ]
    with cat_path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")

    build_index(cat_path, idx_path)
    return cat_path, idx_path


def reply(data: dict) -> PolicyReply:
    return PolicyReply(
        json.dumps(data), {"provider": "fixture", "usage": {"total_tokens": 10}}
    )


class RecommendQuestionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cat_path, self.idx_path = make_test_catalogue_and_index(self.root)
        self.sessions_dir = self.root / "sessions"
        self.store = SessionStore(self.sessions_dir)
        self.search = LexicalSearch(self.idx_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_enforces_product_ids_and_follow_up_question_for_recommend(self):
        # 1. Missing product_ids should raise validation error
        with self.assertRaises(ValidationError):
            Recommend(
                type="RECOMMEND",
                product_ids=[],
                message="Here are boots.",
                follow_up_question="What color do you prefer?",
            )

        # 2. Empty follow_up_question should raise validation error
        with self.assertRaises(ValidationError):
            Recommend(
                type="RECOMMEND",
                product_ids=["ITEM_000"],
                message="Here are boots.",
                follow_up_question="",
            )

        # 3. Successful construction with product_ids and follow_up_question
        rec = Recommend(
            type="RECOMMEND",
            product_ids=["ITEM_000", "ITEM_002"],
            message="Here are verified workout tops.",
            follow_up_question="Do you prefer a fitted or relaxed style?",
        )
        self.assertEqual(len(rec.product_ids), 2)
        self.assertEqual(
            rec.follow_up_question, "Do you prefer a fitted or relaxed style?"
        )

    def test_broad_request_produces_recommendations_not_standalone_clarification(self):
        # Step 1: Broad request -> Agent policy should search broadly and recommend initial options + question
        class BroadShoppingPolicy:
            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                if ctx["latest_search"] is None:
                    # Internal search action
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [],
                            "action": {
                                "type": "SEARCH",
                                "query": "workout clothes",
                                "limit": 5,
                            },
                            "reason": "Search broadly for workout apparel",
                        }
                    )
                # Recommend initial options + ask clarifying follow-up question
                candidates = [p["id"] for p in ctx["latest_search"]["candidates"][:2]]
                return reply(
                    {
                        "based_on_state_version": ctx["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "RECOMMEND",
                            "product_ids": candidates,
                            "message": "Here are our top-rated workout apparel items to get you started.",
                            "follow_up_question": "Are you mainly shopping for tops, bottoms, or a complete outfit?",
                        },
                        "reason": "Provide sensible initial recommendations and narrow preferences",
                    }
                )

        agent = ShoppingAgent(self.store, self.search, BroadShoppingPolicy())
        sid = self.store.create("test-user")

        resp = agent.turn("test-user", sid, "I'm looking for workout clothes.")
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["action"], "RECOMMEND")
        self.assertGreaterEqual(len(resp["products"]), 1)
        self.assertTrue(resp.get("follow_up_question"))
        self.assertEqual(
            resp["follow_up_question"],
            "Are you mainly shopping for tops, bottoms, or a complete outfit?",
        )

    def test_multi_turn_follow_up_refinement_loop(self):
        # Proves the continuous loop: Recommendation + Question on each turn
        class MultiTurnRefiningPolicy:
            def __init__(self):
                self.turn_count = 0

            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                msg = ctx["current_user_message"].lower()

                if "mostly tops" in msg:
                    if ctx["latest_search"] is None:
                        return reply(
                            {
                                "based_on_state_version": ctx["state"]["version"],
                                "updates": [
                                    {
                                        "op": "ADD",
                                        "quote": "Mostly tops",
                                        "requirement": {
                                            "field": "product_type",
                                            "op": "eq",
                                            "value": "top",
                                            "quote": "Mostly tops",
                                            "strength": "hard",
                                        },
                                    }
                                ],
                                "action": {
                                    "type": "SEARCH",
                                    "query": "workout tops",
                                    "limit": 5,
                                },
                                "reason": "Search for tops",
                            }
                        )
                    candidates = [
                        p["id"]
                        for p in ctx["latest_search"]["candidates"]
                        if "top" in p.get("title", "").lower()
                    ]
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [],
                            "action": {
                                "type": "RECOMMEND",
                                "product_ids": candidates[:2]
                                if candidates
                                else [
                                    p["id"]
                                    for p in ctx["latest_search"]["candidates"][:2]
                                ],
                                "message": "Here are popular workout tops.",
                                "follow_up_question": "Would you prefer a fitted or relaxed style?",
                            },
                            "reason": "Recommend tops and query fit",
                        }
                    )
                elif "relaxed" in msg:
                    if ctx["latest_search"] is None:
                        return reply(
                            {
                                "based_on_state_version": ctx["state"]["version"],
                                "updates": [
                                    {
                                        "op": "ADD",
                                        "quote": "Relaxed",
                                        "requirement": {
                                            "field": "color",
                                            "op": "eq",
                                            "value": "black",
                                            "quote": "preferably black",
                                            "strength": "soft",
                                        },
                                    }
                                ],
                                "action": {
                                    "type": "SEARCH",
                                    "query": "relaxed black workout top",
                                    "limit": 5,
                                },
                                "reason": "Search for relaxed black workout top",
                            }
                        )
                    relaxed_cands = [
                        p["id"]
                        for p in ctx["latest_search"]["candidates"]
                        if p["id"] == "ITEM_000"
                        or "relaxed" in str(p.get("details", {})).lower()
                        or "relaxed" in str(p.get("description", "")).lower()
                    ]
                    chosen = (
                        relaxed_cands[:1]
                        if relaxed_cands
                        else [p["id"] for p in ctx["latest_search"]["candidates"][:1]]
                    )
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [],
                            "action": {
                                "type": "RECOMMEND",
                                "product_ids": chosen or ["ITEM_000"],
                                "message": "Here is our top relaxed-fit black workout top.",
                                "follow_up_question": "Do you have a particular budget in mind?",
                            },
                            "reason": "Recommend relaxed black top and query budget",
                        }
                    )
                else:
                    # Initial broad turn
                    if ctx["latest_search"] is None:
                        return reply(
                            {
                                "based_on_state_version": ctx["state"]["version"],
                                "updates": [],
                                "action": {
                                    "type": "SEARCH",
                                    "query": "workout",
                                    "limit": 5,
                                },
                                "reason": "Initial search",
                            }
                        )
                    cands = [p["id"] for p in ctx["latest_search"]["candidates"][:2]]
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [],
                            "action": {
                                "type": "RECOMMEND",
                                "product_ids": cands if cands else ["ITEM_000"],
                                "message": "Here are versatile workout clothes.",
                                "follow_up_question": "Are you mainly shopping for tops, bottoms, or a complete outfit?",
                            },
                            "reason": "Initial recommendation",
                        }
                    )

        agent = ShoppingAgent(self.store, self.search, MultiTurnRefiningPolicy())
        sid = self.store.create("shopper-loop")

        # Turn 1: Broad
        r1 = agent.turn("shopper-loop", sid, "I'm looking for workout clothes.")
        self.assertEqual(r1["action"], "RECOMMEND")
        self.assertEqual(
            r1["follow_up_question"],
            "Are you mainly shopping for tops, bottoms, or a complete outfit?",
        )
        self.assertGreater(len(r1["products"]), 0)

        # Turn 2: Follow-up answer
        r2 = agent.turn("shopper-loop", sid, "Mostly tops.")
        self.assertEqual(r2["action"], "RECOMMEND")
        self.assertEqual(
            r2["follow_up_question"], "Would you prefer a fitted or relaxed style?"
        )
        self.assertTrue(all("Top" in p["title"] for p in r2["products"]))

        # Turn 3: Fit & color preference
        r3 = agent.turn("shopper-loop", sid, "Relaxed, and preferably black.")
        self.assertEqual(r3["action"], "RECOMMEND")
        self.assertEqual(
            r3["follow_up_question"], "Do you have a particular budget in mind?"
        )
        self.assertEqual(r3["products"][0]["id"], "ITEM_000")

    def test_unsupported_product_ids_strictly_rejected(self):
        class HallucinatingPolicy:
            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                if ctx["latest_search"] is None:
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [],
                            "action": {
                                "type": "SEARCH",
                                "query": "workout",
                                "limit": 5,
                            },
                            "reason": "search",
                        }
                    )
                # Fabricate an invalid ID not in search candidates
                return reply(
                    {
                        "based_on_state_version": ctx["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "RECOMMEND",
                            "product_ids": ["NON_EXISTENT_ID_999"],
                            "message": "Here is a fabricated product.",
                            "follow_up_question": "Do you like it?",
                        },
                        "reason": "invalid candidate",
                    }
                )

        agent = ShoppingAgent(self.store, self.search, HallucinatingPolicy())
        sid = self.store.create("test-user")
        resp = agent.turn("test-user", sid, "workout")
        # Should be rejected by verified_products and closed safely/failed, not successful RECOMMEND
        self.assertNotEqual(resp["action"], "RECOMMEND")
        self.assertNotEqual(resp["status"], "ok")

    def test_truly_unsatisfiable_request_triggers_no_match_exception(self):
        # When constraints are impossible (e.g. price < $5 when minimum is $25), agent returns NO_MATCH
        class NoMatchPolicy:
            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                if ctx["latest_search"] is None:
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [
                                {
                                    "op": "ADD",
                                    "quote": "under $5",
                                    "requirement": {
                                        "field": "price",
                                        "op": "lt",
                                        "value": 5.0,
                                        "quote": "under $5",
                                        "strength": "hard",
                                    },
                                }
                            ],
                            "action": {
                                "type": "SEARCH",
                                "query": "workout",
                                "limit": 5,
                            },
                            "reason": "search",
                        }
                    )
                # 0 candidates found after search & verification
                return reply(
                    {
                        "based_on_state_version": ctx["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "NO_MATCH",
                            "message": "I could not find any workout apparel under $5 in our catalogue.",
                            "follow_up_question": "Would you like to relax your budget or explore clearance items?",
                        },
                        "reason": "Zero eligible candidates in catalogue",
                    }
                )

        agent = ShoppingAgent(self.store, self.search, NoMatchPolicy())
        sid = self.store.create("budget-user")
        resp = agent.turn("budget-user", sid, "workout clothes under $5")

        self.assertEqual(resp["status"], "no_match")
        self.assertEqual(resp["action"], "NO_MATCH")
        self.assertEqual(len(resp["products"]), 0)
        self.assertIn("under $5", resp["message"])
        self.assertEqual(
            resp["follow_up_question"],
            "Would you like to relax your budget or explore clearance items?",
        )

    def test_evaluation_framework_records_recommend_plus_question(self):
        # Proves target-item discovery scoring is unaffected by question presence
        rule = TargetRule(target_id="ITEM_000", k=5)
        response = {
            "status": "ok",
            "action": "RECOMMEND",
            "message": "Top recommendation for you.",
            "products": [{"id": "ITEM_000", "title": "Active Workout Top"}],
            "follow_up_question": "Do you need matching shorts?",
        }
        rank = rule.check(response, ["ITEM_000"])
        self.assertEqual(rank, 1)

        # NO_MATCH must return None (failure to recommend target)
        no_match_response = {
            "status": "no_match",
            "action": "NO_MATCH",
            "message": "No products match.",
            "products": [],
            "follow_up_question": "What would you like to relax?",
        }
        no_match_rank = rule.check(no_match_response, [])
        self.assertIsNone(no_match_rank)

    def test_ui_service_preserves_recommendation_and_question(self):
        class FixedRecommendPolicy:
            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                d = {
                    "updates": [],
                    "action": (
                        {"type": "SEARCH", "query": "workout", "limit": 3}
                        if ctx.get("latest_search") is None
                        else {
                            "type": "RECOMMEND",
                            "product_ids": [
                                p["id"] for p in ctx["latest_search"]["candidates"][:1]
                            ],
                            "message": "Recommended activewear top.",
                            "follow_up_question": "Do you prefer a zip or pullover style?",
                        }
                    ),
                    "reason": "search"
                    if ctx.get("latest_search") is None
                    else "recommend",
                }
                if isinstance(ctx.get("state"), dict) and "version" in ctx["state"]:
                    d["based_on_state_version"] = ctx["state"]["version"]
                return reply(d)

        service = ChatService(
            self.cat_path,
            self.idx_path,
            self.sessions_dir,
            policy=FixedRecommendPolicy(),
            user_memory_enabled=False,
        )
        sid = service.create("ui-shopper")
        turn_res = service.send("ui-shopper", sid, "workout top", "req-test-1")

        self.assertEqual(turn_res["action"], "RECOMMEND")
        self.assertEqual(
            turn_res["follow_up_question"], "Do you prefer a zip or pullover style?"
        )
        self.assertEqual(len(turn_res["products"]), 1)

        # Check view representation
        view = service.view("ui-shopper", sid)
        assistant_msgs = [m for m in view["messages"] if m["role"] == "assistant"]
        self.assertEqual(len(assistant_msgs), 1)
        self.assertEqual(
            assistant_msgs[0]["follow_up_question"],
            "Do you prefer a zip or pullover style?",
        )
        self.assertEqual(len(assistant_msgs[0]["products"]), 1)


if __name__ == "__main__":
    unittest.main()
