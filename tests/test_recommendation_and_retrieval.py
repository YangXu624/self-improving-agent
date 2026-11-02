import json
import tempfile
import unittest
from pathlib import Path

from astra_eval.target_scoring import TargetRule
from shopping_agent.agent import ShoppingAgent
from shopping_agent.contracts import (
    Search,
    ShoppingState,
)
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import LexicalSearch
from shopping_agent.sessions import SessionStore


class MockSearch:
    def __init__(self, candidates):
        self.candidates = candidates
        self.catalogue_version = "mock-v1"
        self.strategy_version = "mock-strat-v1"

    def search(self, action, state, **kwargs):
        limit = action.limit
        return {
            "search_id": "search-1",
            "query": action.query,
            "match_mode": "broad",
            "state_version": state.version,
            "catalogue_version": self.catalogue_version,
            "strategy_version": self.strategy_version,
            "candidates": self.candidates[:limit],
            "applied_hard_filters": [],
            "counts": {
                "lexical_matches": len(self.candidates),
                "verified_eligible": len(self.candidates),
                "products_with_unknown_required_attributes": 0,
                "products_failing_known_constraints": 0,
            },
        }

    def eligible(self, pid, state):
        return any(c["id"] == pid for c in self.candidates)


class TestRecommendationAndRetrieval(unittest.TestCase):
    def setUp(self):
        self.db_path = "data/index/catalogue.sqlite"
        self.search = LexicalSearch(self.db_path)

    def test_1_at_least_10_eligible_products_enforces_10_recommendations(self):
        """When at least 10 eligible products are available, exactly 10 are recommended."""
        # 15 mock eligible candidates
        candidates = [
            {
                "id": f"prod_{i}",
                "title": f"Test Product {i}",
                "facts": {"price": 10.0 + i},
                "categories": ["Clothing, Shoes & Jewelry", "Women", "Shoes"],
                "evidence": {},
                "snippet": f"Product snippet {i}",
                "image_url": None,
                "matched_hard_ids": [],
                "matched_soft_ids": [],
            }
            for i in range(15)
        ]
        mock_search = MockSearch(candidates)

        class PolicyRecommendingTen:
            def complete(self, messages):
                content = json.loads(messages[-1]["content"])
                if content.get("latest_search") is None:
                    d = {
                        "based_on_state_version": content["state"]["version"],
                        "updates": [],
                        "action": {"type": "SEARCH", "query": "shoes", "limit": 30},
                        "reason": "search",
                    }
                else:
                    d = {
                        "based_on_state_version": content["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "RECOMMEND",
                            "product_ids": [f"prod_{i}" for i in range(10)],
                            "message": "Here are top 10 shoes.",
                            "follow_up_question": "Do you prefer sneakers or flats?",
                            "search_id": "search-1",
                        },
                        "reason": "recommend",
                    }
                return PolicyReply(
                    json.dumps(d),
                    {"provider": "fixture", "usage": {"total_tokens": 10}},
                )

        temp_dir = tempfile.mkdtemp()
        store = SessionStore(Path(temp_dir) / "sessions.db")
        agent = ShoppingAgent(store, mock_search, PolicyRecommendingTen())
        resp = agent.turn("user1", store.create("user1"), "I need shoes")

        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["action"], "RECOMMEND")
        # Agent surfaces exactly 10 distinct products
        self.assertEqual(len(resp["products"]), 10)
        self.assertEqual(len(set(p["id"] for p in resp["products"])), 10)
        self.assertEqual(resp["follow_up_question"], "Do you prefer sneakers or flats?")

    def test_2_fewer_than_10_returns_only_available_without_fabrication(self):
        """When only 4 eligible products exist, exactly 4 are recommended without padding or fabrication."""
        candidates = [
            {
                "id": f"prod_{i}",
                "title": f"Rare Shoe {i}",
                "facts": {"price": 25.0 + i},
                "categories": ["Shoes"],
                "evidence": {},
                "snippet": f"Rare shoe snippet {i}",
                "image_url": None,
                "matched_hard_ids": [],
                "matched_soft_ids": [],
            }
            for i in range(4)
        ]
        mock_search = MockSearch(candidates)

        class PolicyRecommendingFour:
            def complete(self, messages):
                content = json.loads(messages[-1]["content"])
                if content.get("latest_search") is None:
                    d = {
                        "based_on_state_version": content["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "SEARCH",
                            "query": "rare shoes",
                            "limit": 30,
                        },
                        "reason": "search",
                    }
                else:
                    d = {
                        "based_on_state_version": content["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "RECOMMEND",
                            "product_ids": [f"prod_{i}" for i in range(4)],
                            "message": "Here are rare shoes.",
                            "follow_up_question": "What size do you need?",
                            "search_id": "search-1",
                        },
                        "reason": "recommend",
                    }
                return PolicyReply(
                    json.dumps(d),
                    {"provider": "fixture", "usage": {"total_tokens": 10}},
                )

        temp_dir = tempfile.mkdtemp()
        store = SessionStore(Path(temp_dir) / "sessions.db")
        agent = ShoppingAgent(store, mock_search, PolicyRecommendingFour())
        resp = agent.turn("user2", store.create("user2"), "I need rare shoes")

        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["action"], "RECOMMEND")
        # Exactly 4 products returned, never fabricated or padded to 10
        self.assertEqual(len(resp["products"]), 4)
        self.assertEqual(
            set(p["id"] for p in resp["products"]),
            {"prod_0", "prod_1", "prod_2", "prod_3"},
        )

    def test_3_broad_womens_nike_shoes_retrieves_multiple_subtypes(self):
        """Broad query 'womens nike shoes' finds multiple subtypes (running, training, casual, sandals)."""
        action = Search(type="SEARCH", query="womens nike shoes", mode="all", limit=30)
        state = ShoppingState(version=1, requirements=[])
        res = self.search.search(action, state, personalization_strength=0.0)

        self.assertGreaterEqual(res["counts"]["lexical_matches"], 50)
        self.assertGreaterEqual(len(res["candidates"]), 20)

        # Check subtypes present in candidates
        categories_represented = set()
        titles = []
        for c in res["candidates"]:
            titles.append(c["title"].lower())
            for cat in c.get("categories", []):
                categories_represented.add(cat.lower())

        # Multiple footwear categories/subtypes present
        has_running = any("running" in t for t in titles)
        has_training = any("train" in t or "tr" in t for t in titles)
        has_sneakers_or_casual = any(
            "sneaker" in t or "casual" in t or "essential" in t for t in titles
        )

        self.assertTrue(has_running, "Expected running shoes in candidates")
        self.assertTrue(has_training, "Expected training shoes in candidates")
        self.assertTrue(
            has_sneakers_or_casual, "Expected casual/lifestyle sneakers in candidates"
        )

    def test_4_unknown_prices_not_excluded_when_no_budget_specified(self):
        """Products with unknown prices are retained when the user specifies no price constraint."""
        action = Search(type="SEARCH", query="womens nike shoes", mode="all", limit=30)
        state = ShoppingState(version=1, requirements=[])
        res = self.search.search(action, state, personalization_strength=0.0)

        unknown_price_count = sum(
            1 for c in res["candidates"] if c.get("facts", {}).get("price") is None
        )
        self.assertGreater(
            unknown_price_count,
            0,
            "Expected products with unknown prices to be eligible",
        )

    def test_5_soft_memories_never_become_hard_filters(self):
        """Historical soft preferences never exclude baseline-eligible products."""
        # Unrelated historical memory for kitten heels
        memory_ctx = {
            "records": [
                {
                    "id": "mem_1",
                    "category": "preference",
                    "attribute": "style",
                    "value": "black kitten heels",
                    "scope": "shoes",
                    "status": "active",
                    "confidence": 0.9,
                }
            ]
        }
        action = Search(type="SEARCH", query="womens nike shoes", mode="all", limit=30)
        state = ShoppingState(version=1, requirements=[])

        # Baseline search without memory
        res_off = self.search.search(action, state, personalization_strength=0.0)
        # Search with memory enabled
        res_on = self.search.search(
            action, state, user_memory=memory_ctx, personalization_strength=0.5
        )

        # Baseline candidate count should not be reduced by soft memory
        self.assertEqual(
            res_off["counts"]["verified_eligible"],
            res_on["counts"]["verified_eligible"],
        )
        self.assertGreaterEqual(len(res_on["candidates"]), 20)

    def test_6_hit_at_10_and_deterministic_termination(self):
        """TargetRule supports k=10, validates recommendation lists up to 10, and terminates correctly."""
        rule = TargetRule(target_id="target_nike_1", k=10)

        # Valid response with 10 products, target at rank 7
        pids = (
            [f"prod_{i}" for i in range(6)]
            + ["target_nike_1"]
            + ["prod_7", "prod_8", "prod_9"]
        )
        rec_payload = {
            "status": "ok",
            "action": "RECOMMEND",
            "products": [{"id": pid} for pid in pids],
        }
        rank = rule.check(rec_payload, pids)
        self.assertEqual(rank, 7)
        self.assertLessEqual(rank, 10)

        # Target not in top 10
        pids_miss = [f"prod_{i}" for i in range(10)]
        rec_payload_miss = {
            "status": "ok",
            "action": "RECOMMEND",
            "products": [{"id": pid} for pid in pids_miss],
        }
        rank_miss = rule.check(rec_payload_miss, pids_miss)
        self.assertIsNone(rank_miss)


if __name__ == "__main__":
    unittest.main()
