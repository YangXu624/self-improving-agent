import json
import tempfile
import unittest
from pathlib import Path

from shopping_agent.contracts import Requirement, Search, ShoppingState
from shopping_agent.retrieval import LexicalSearch, build_index, file_hash


def make_product(id, title, categories, price=50.0, **details):
    return {
        "parent_asin": id,
        "title": title,
        "features": details.pop("features", ["everyday wear"]),
        "description": details.pop("description", []),
        "categories": categories,
        "details": details,
        "price": price,
        "average_rating": 4.5,
        "rating_number": 20,
    }


def add_req(
    field="price",
    op="lt",
    value=100.0,
    quote="under 100",
    strength="hard",
    status="active",
):
    return Requirement(
        id=f"req-{field}",
        field=field,
        op=op,
        value=value,
        strength=strength,
        status=status,
        quote=quote,
        source_event_id="fixture",
        created_version=1,
    )


class SearchMemoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        rows = [
            make_product(
                "p_black_30",
                "Men's Active Workout Running Shirt Black",
                ["Clothing", "Men", "Activewear"],
                price=30.0,
                Color="Black",
                features=["gym", "compression", "workout"],
            ),
            make_product(
                "p_red_25",
                "Men's Active Workout Running Shirt Red",
                ["Clothing", "Men", "Activewear"],
                price=25.0,
                Color="Red",
                features=["gym", "workout"],
            ),
            make_product(
                "p_expensive_black_70",
                "Men's Luxury Active Workout Shirt Black",
                ["Clothing", "Men", "Activewear"],
                price=70.0,
                Color="Black",
                features=["gym", "workout"],
            ),
            make_product(
                "p_leather_boots",
                "Outdoor Rugged Hiking Boots Brown",
                ["Shoes", "Men", "Boots"],
                price=80.0,
                Color="Brown",
                Material="Leather",
                features=["hiking", "trails"],
            ),
            make_product(
                "p_rubber_boots",
                "Outdoor Waterproof Rain Boots Black",
                ["Shoes", "Men", "Boots"],
                price=45.0,
                Color="Black",
                Material="Rubber",
                features=["waterproof", "rain"],
            ),
        ]

        src, dest = self.root / "catalog.jsonl", self.root / "index.sqlite"
        src.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(src, dest)
        self.search = LexicalSearch(
            dest, expected_catalogue_hash=file_hash(src), fallback=True
        )
        self.addCleanup(self.search.close)

    def test_1_relevant_preferences_improving_ranking(self):
        """Relevant preferences elevate matching candidates over non-matching candidates."""
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
            ]
        )
        action = Search(type="SEARCH", query="workout shirt", mode="all", limit=5)

        # Baseline: Memory OFF
        res_off = self.search.search(action, state, user_memory=None)
        ids_off = [c["id"] for c in res_off["candidates"]]
        self.assertIn("p_black_30", ids_off)
        self.assertIn("p_red_25", ids_off)

        # Memory ON: User prefers black workout clothing
        user_memory = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout",
                    "status": "active",
                }
            ],
        }
        res_on = self.search.search(action, state, user_memory=user_memory)
        candidates_on = res_on["candidates"]
        self.assertEqual(candidates_on[0]["id"], "p_black_30")
        self.assertGreater(
            candidates_on[0]["preference_score"],
            candidates_on[1]["preference_score"],
        )
        self.assertIn("mem-black", candidates_on[0]["matched_memory_ids"])

    def test_2_historical_preferences_not_eliminating_eligible_products(self):
        """Historical preferences do not eliminate otherwise eligible products."""
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
            ]
        )
        action = Search(type="SEARCH", query="workout shirt", mode="all", limit=5)

        user_memory = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout",
                    "status": "active",
                }
            ],
        }
        res = self.search.search(action, state, user_memory=user_memory)
        candidate_ids = [c["id"] for c in res["candidates"]]

        # Red shirt is eligible despite not matching the preferred color
        self.assertIn("p_red_25", candidate_ids)
        red_candidate = next(c for c in res["candidates"] if c["id"] == "p_red_25")
        self.assertTrue(red_candidate["eligible"])

    def test_3_firm_price_and_product_constraints_remaining_enforced(self):
        """Firm price and product constraints are never relaxed by preferences or fallback."""
        # Price constraint: strictly under $50
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
                add_req("material", "neq", "leather", "no leather", "hard"),
            ]
        )
        action = Search(type="SEARCH", query="shirt boots", mode="any", limit=10)

        # User memory prefers black and luxury
        user_memory = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "status": "active",
                }
            ],
        }
        res = self.search.search(action, state, user_memory=user_memory)
        candidate_ids = [c["id"] for c in res["candidates"]]

        # p_expensive_black_70 costs $70 -> MUST BE EXCLUDED
        self.assertNotIn("p_expensive_black_70", candidate_ids)

        # p_leather_boots has Material="Leather" -> MUST BE EXCLUDED
        self.assertNotIn("p_leather_boots", candidate_ids)

        # Only products satisfying all hard constraints are present
        for c in res["candidates"]:
            self.assertTrue(c["eligible"])
            self.assertLess(c["facts"]["price"], 50.0)
            self.assertNotEqual(c["facts"].get("material"), "leather")

    def test_4_irrelevant_or_stale_memories_not_harming_current_search(self):
        """Irrelevant memory scopes do not distort search ranking or candidate recall."""
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 100.0, "under 100", "hard"),
            ]
        )
        action = Search(type="SEARCH", query="boots", mode="all", limit=5)

        # Memory is for handbags, irrelevant to boots
        user_memory_irrelevant = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-handbag",
                    "category": "preference",
                    "attribute": "color",
                    "value": "pink",
                    "scope": "handbags",
                    "status": "active",
                }
            ],
        }

        res_off = self.search.search(action, state, user_memory=None)
        res_irrelevant = self.search.search(
            action, state, user_memory=user_memory_irrelevant
        )

        # Candidate order and scores must be identical
        self.assertEqual(
            [c["id"] for c in res_off["candidates"]],
            [c["id"] for c in res_irrelevant["candidates"]],
        )
        for c in res_irrelevant["candidates"]:
            self.assertEqual(c["preference_score"], 0.0)
            self.assertEqual(c["matched_memory_ids"], [])

    def test_5_graceful_fallback_from_overly_restrictive_search(self):
        """Safe fallback relaxes remembered preference terms when mode=all yields 0 matches."""
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
            ]
        )
        # Search query over-constrained by stuffing remembered preference 'black'
        # with extra terms 'tactical' that don't co-occur with all words
        action = Search(
            type="SEARCH",
            query="active workout tactical shirt black",
            mode="all",
            limit=5,
        )

        user_memory = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout",
                    "status": "active",
                }
            ],
        }

        res = self.search.search(action, state, user_memory=user_memory)

        # Fallback must be triggered
        self.assertTrue(res["fallback_triggered"])
        # Candidates must be found
        self.assertGreater(len(res["candidates"]), 0)
        # The black shirt must be ranked #1 via preference ranking
        self.assertEqual(res["candidates"][0]["id"], "p_black_30")
        # Hard constraint still strictly enforced ($70 black shirt excluded)
        self.assertNotIn("p_expensive_black_70", [c["id"] for c in res["candidates"]])

    def test_6_equal_memory_off_on_behavior_when_no_applicable_memory_exists(self):
        """Memory OFF and Memory ON produce identical rankings when memory has no applicable records."""
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 100.0, "under 100", "hard"),
            ]
        )
        action = Search(
            type="SEARCH", query="active workout shirt", mode="all", limit=5
        )

        res_off = self.search.search(action, state, user_memory=None)
        res_empty = self.search.search(
            action, state, user_memory={"revision": 1, "records": []}
        )
        res_none_applicable = self.search.search(
            action,
            state,
            user_memory={
                "revision": 1,
                "records": [
                    {
                        "id": "mem-shoes",
                        "category": "preference",
                        "attribute": "brand",
                        "value": "NonExistentBrand",
                        "scope": "shoes",
                        "status": "active",
                    }
                ],
            },
        )

        off_ids = [c["id"] for c in res_off["candidates"]]
        empty_ids = [c["id"] for c in res_empty["candidates"]]
        none_ids = [c["id"] for c in res_none_applicable["candidates"]]

        self.assertEqual(off_ids, empty_ids)
        self.assertEqual(off_ids, none_ids)
        self.assertEqual(
            [c["bm25"] for c in res_off["candidates"]],
            [c["bm25"] for c in res_empty["candidates"]],
        )

    def test_7_gift_intent_suppresses_personal_memories(self):
        """When user is shopping for a gift, personal profile memories are suppressed from context."""
        from shopping_agent.user_memory import (
            MemoryRecord,
            UserMemoryStore,
        )

        store = UserMemoryStore(self.root / "memories")
        user_id = "customer-gift"
        # Seed a personal preference
        rec = MemoryRecord(
            id="mem-personal-fit",
            category="preference",
            attribute="size",
            value="EU 42",
            scope="shoes",
            quote="I wear EU 42",
            basis="confirmed",
            status="active",
        )
        with store._locked(user_id) as p:
            conn = store._init_db(p)
            profile = store.read(user_id)
            profile.records.append(rec)
            profile.revision = 1
            store.write_profile(profile, p, conn)
            conn.close()

        from shopping_agent.sessions import SessionStore

        session_store = SessionStore(self.root / "sessions")
        s_id = session_store.create(user_id)
        with session_store.open(user_id, s_id) as session:
            # 1. Normal shopping -> personal memory retrieved
            ctx_normal = store.context(session, "I'm looking for running shoes")
            self.assertEqual(len(ctx_normal["records"]), 1)

            # 2. Gift shopping message -> personal memory suppressed
            ctx_gift_msg = store.context(
                session, "I'm looking for a gift for my niece who likes shoes"
            )
            self.assertEqual(len(ctx_gift_msg["records"]), 0)

            # 3. Recipient requirement in state -> personal memory suppressed
            session.state.requirements.append(
                add_req("recipient", "eq", "niece", "for my niece", "soft")
            )
            ctx_gift_req = store.context(session, "I'm looking for shoes")
            self.assertEqual(len(ctx_gift_req["records"]), 0)

    def test_8_current_explicit_preference_overrides_contradictory_memory(self):
        """When current explicit customer preferences contradict historical memories, current preferences win."""
        user_memory = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout",
                    "status": "active",
                }
            ],
        }

        # Case A: Current session explicitly specifies soft preference for Red
        state_red = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
                add_req("color", "eq", "red", "prefer red", "soft"),
            ]
        )
        action = Search(type="SEARCH", query="workout shirt", mode="all", limit=5)
        res_red = self.search.search(action, state_red, user_memory=user_memory)
        # Red shirt must be ranked #1; contradictory black memory is suppressed
        self.assertEqual(res_red["candidates"][0]["id"], "p_red_25")
        self.assertEqual(res_red["candidates"][0]["matched_soft_ids"], ["req-color"])
        self.assertNotIn("mem-black", res_red["candidates"][1]["matched_memory_ids"])

        # Case B: Current session explicitly excludes Black (hard exclusion)
        state_no_black = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
                add_req("color", "neq", "black", "no black", "hard"),
            ]
        )
        res_no_black = self.search.search(
            action, state_no_black, user_memory=user_memory
        )
        self.assertNotIn("p_black_30", [c["id"] for c in res_no_black["candidates"]])
        self.assertEqual(res_no_black["candidates"][0]["id"], "p_red_25")

    def test_9_broad_fallback_enabled_identically_for_off_and_on(self):
        """Broad retrieval fallback is enabled identically for both Memory OFF and Memory ON."""
        state = ShoppingState(
            requirements=[
                add_req("price", "lt", 50.0, "under 50", "hard"),
            ]
        )
        # An over-constrained query where 'tactical' does not match in all-mode
        action = Search(
            type="SEARCH", query="tactical workout shirt", mode="all", limit=5
        )

        # In Memory OFF:
        res_off = self.search.search(action, state, user_memory=None)
        self.assertTrue(res_off["fallback_triggered"])
        self.assertEqual(res_off["effective_match_mode"], "any")
        self.assertGreater(len(res_off["candidates"]), 0)

        # In Memory ON (with no applicable memory):
        res_on_no_mem = self.search.search(
            action, state, user_memory={"revision": 1, "records": []}
        )
        self.assertTrue(res_on_no_mem["fallback_triggered"])
        self.assertEqual(res_on_no_mem["effective_match_mode"], "any")
        self.assertEqual(
            [c["id"] for c in res_off["candidates"]],
            [c["id"] for c in res_on_no_mem["candidates"]],
        )

        # In Memory ON (with black memory):
        user_memory = {
            "revision": 1,
            "records": [
                {
                    "id": "mem-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "status": "active",
                }
            ],
        }
        res_on = self.search.search(action, state, user_memory=user_memory)
        self.assertTrue(res_on["fallback_triggered"])
        # Same eligible products retrieved, but black shirt is ranked #1 by memory
        self.assertEqual(res_on["candidates"][0]["id"], "p_black_30")


if __name__ == "__main__":
    unittest.main()
