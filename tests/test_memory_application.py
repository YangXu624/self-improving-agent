"""Unit and integration tests for Phase 3: Redesign How Memory Influences Shopping Decisions."""

import json
import tempfile
import unittest
from pathlib import Path

from shopping_agent.contracts import (
    Requirement,
    Search,
    ShoppingState,
    StateUpdate,
)
from shopping_agent.retrieval import LexicalSearch, build_index, file_hash
from shopping_agent.state import apply_updates


def make_product(asin, title, price=40.0, **details):
    return {
        "parent_asin": asin,
        "title": title,
        "features": ["activewear"],
        "description": ["breathable"],
        "categories": ["Clothing", "Shirts", "Activewear"],
        "details": details,
        "price": price,
        "average_rating": 4.5,
        "rating_number": 50,
        "store": "FitnessStore",
    }


class TestMemoryApplication(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Create a sample catalogue with 3 workout shirts:
        # 1. P_BLK: Black workout shirt ($40.0)
        # 2. P_BLU: Blue workout shirt ($35.0)
        # 3. P_RED: Red workout shirt ($30.0)
        # 4. P_UNK: Workout shirt with unknown color ($38.0)
        catalog_rows = [
            make_product(
                "P_BLK",
                "Black workout training gym shirt",
                40.0,
                Color="Black",
                Department="Men",
            ),
            make_product(
                "P_BLU",
                "Blue workout training gym shirt",
                35.0,
                Color="Blue",
                Department="Men",
            ),
            make_product(
                "P_RED",
                "Red workout training gym shirt",
                30.0,
                Color="Red",
                Department="Men",
            ),
            make_product(
                "P_UNK", "Classic breathable workout gym shirt", 38.0, Department="Men"
            ),
        ]
        src = self.root / "catalog.jsonl"
        dest = self.root / "index.sqlite"
        src.write_text("".join(json.dumps(r) + "\n" for r in catalog_rows))
        build_index(src, dest)
        self.search = LexicalSearch(dest, expected_catalogue_hash=file_hash(src))
        self.addCleanup(self.search.close)
        self.addCleanup(self.tmp.cleanup)

    def test_soft_preference_never_becomes_hard_filter(self):
        """Historical preference for black workout clothing does NOT filter out blue or red shirts."""
        action = Search(type="SEARCH", query="workout gym shirt", mode="all", limit=10)
        state = ShoppingState()

        # Memory with black preference
        user_memory = {
            "records": [
                {
                    "id": "um-pref-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothing",
                    "strength": "soft",
                    "confidence": 1.0,
                    "status": "active",
                }
            ]
        }

        res = self.search.search(
            action,
            state,
            user_memory=user_memory,
            personalization_strength=0.5,
        )

        candidate_ids = [c["id"] for c in res["candidates"]]
        # All 4 products MUST remain eligible in candidate pool
        self.assertIn("P_BLK", candidate_ids)
        self.assertIn("P_BLU", candidate_ids)
        self.assertIn("P_RED", candidate_ids)
        self.assertIn("P_UNK", candidate_ids)
        self.assertEqual(len(candidate_ids), 4)

    def test_personalized_reranking_promotes_matching_option(self):
        """Black shirt is promoted to rank 1 when black preference is active, without excluding others."""
        action = Search(type="SEARCH", query="workout gym shirt", mode="all", limit=10)
        state = ShoppingState()

        # 1. Baseline search (Memory OFF / strength = 0.0)
        res_off = self.search.search(
            action,
            state,
            user_memory=None,
            personalization_strength=0.0,
        )
        baseline_ids = [c["id"] for c in res_off["candidates"]]

        # 2. Personalized search with red preference
        red_memory = {
            "records": [
                {
                    "id": "um-pref-red",
                    "category": "preference",
                    "attribute": "color",
                    "value": "red",
                    "scope": "workout clothing",
                    "strength": "soft",
                    "confidence": 1.0,
                    "status": "active",
                }
            ]
        }
        res_red = self.search.search(
            action,
            state,
            user_memory=red_memory,
            personalization_strength=0.8,
        )
        personalized_ids = [c["id"] for c in res_red["candidates"]]

        # Red shirt should be ranked #1
        self.assertEqual(personalized_ids[0], "P_RED")
        # All other shirts remain in candidate pool
        self.assertEqual(set(personalized_ids), set(baseline_ids))

    def test_memory_off_equivalence(self):
        """When personalization_strength is 0.0, search order is strictly identical to Memory OFF."""
        action = Search(type="SEARCH", query="workout gym shirt", mode="all", limit=10)
        state = ShoppingState()

        user_memory = {
            "records": [
                {
                    "id": "um-pref-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothing",
                    "strength": "hard",
                    "confidence": 1.0,
                    "status": "active",
                }
            ]
        }

        res_off = self.search.search(
            action, state, user_memory=None, personalization_strength=0.0
        )
        res_zero = self.search.search(
            action, state, user_memory=user_memory, personalization_strength=0.0
        )

        self.assertEqual(
            [c["id"] for c in res_off["candidates"]],
            [c["id"] for c in res_zero["candidates"]],
        )

    def test_unknown_attributes_never_excluded_or_counted_as_confirmed(self):
        """Product with unknown color (P_UNK) is not excluded and gets 0.0 preference bonus."""
        action = Search(type="SEARCH", query="workout gym shirt", mode="all", limit=10)
        state = ShoppingState()

        user_memory = {
            "records": [
                {
                    "id": "um-pref-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothing",
                    "strength": "soft",
                    "confidence": 1.0,
                    "status": "active",
                }
            ]
        }

        res = self.search.search(
            action, state, user_memory=user_memory, personalization_strength=0.5
        )
        unk_candidate = next(c for c in res["candidates"] if c["id"] == "P_UNK")
        self.assertEqual(unk_candidate["preference_score"], 0.0)
        self.assertNotIn("um-pref-black", unk_candidate["matched_memory_ids"])

    def test_conflicting_current_request_overrides_historical_memory(self):
        """If user currently asks for Blue shirt, historical Black preference is NOT applied."""
        action = Search(type="SEARCH", query="workout gym shirt", mode="all", limit=10)
        state = ShoppingState()
        state.requirements.append(
            Requirement(
                id="req-blue",
                field="color",
                op="eq",
                value="blue",
                strength="hard",
                quote="I need a blue shirt",
                status="active",
                source_event_id="ev-1",
                created_version=1,
            )
        )

        user_memory = {
            "records": [
                {
                    "id": "um-pref-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothing",
                    "strength": "soft",
                    "confidence": 1.0,
                    "status": "active",
                }
            ]
        }

        res = self.search.search(
            action, state, user_memory=user_memory, personalization_strength=0.5
        )
        # Only blue shirt satisfies hard requirement
        self.assertEqual(len(res["candidates"]), 1)
        self.assertEqual(res["candidates"][0]["id"], "P_BLU")
        # Memory was not applied because current requirement contradicted it
        self.assertEqual(res["candidates"][0]["preference_score"], 0.0)

    def test_decision_level_evidence_logging(self):
        """Search result includes initial_candidate_pool, baseline_rankings, personalized_rankings, and audit."""
        action = Search(type="SEARCH", query="workout gym shirt", mode="all", limit=10)
        state = ShoppingState()

        user_memory = {
            "records": [
                {
                    "id": "um-pref-black",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothing",
                    "strength": "soft",
                    "confidence": 1.0,
                    "status": "active",
                }
            ]
        }

        res = self.search.search(
            action, state, user_memory=user_memory, personalization_strength=0.6
        )
        self.assertIn("initial_candidate_pool", res)
        self.assertIn("baseline_rankings", res)
        self.assertIn("personalized_rankings", res)
        self.assertIn("memory_decision_audit", res)
        self.assertGreater(len(res["memory_decision_audit"]), 0)
        audit = res["memory_decision_audit"][0]
        self.assertEqual(audit["memory_id"], "um-pref-black")
        self.assertEqual(audit["attribute"], "color")
        self.assertEqual(audit["value"], "black")
        self.assertIn("P_BLK", audit["affected_products"])

    def test_reconcile_contradictory_requirement_correction(self):
        """When customer changes preference (e.g. 'Actually show me blue instead of red'), old requirement is superseded."""
        initial_state = ShoppingState()
        # Initial turn: customer wanted red
        state1 = apply_updates(
            initial_state,
            [
                StateUpdate(
                    op="ADD",
                    requirement={
                        "field": "color",
                        "op": "eq",
                        "value": "red",
                        "strength": "hard",
                        "quote": "I want a red shirt",
                    },
                    quote="I want a red shirt",
                )
            ],
            expected_version=0,
            user_message="I want a red shirt",
            source_event_id="ev-1",
        )
        self.assertEqual(
            len([r for r in state1.requirements if r.status == "active"]), 1
        )
        self.assertEqual(state1.conflicts, [])

        # Second turn: customer corrects preference: "Actually show me blue instead of red"
        state2 = apply_updates(
            state1,
            [
                StateUpdate(
                    op="ADD",
                    requirement={
                        "field": "color",
                        "op": "eq",
                        "value": "blue",
                        "strength": "hard",
                        "quote": "show me blue instead of red",
                    },
                    quote="Actually show me blue instead of red",
                )
            ],
            expected_version=state1.version,
            user_message="Actually show me blue instead of red",
            source_event_id="ev-2",
        )

        active = [r for r in state2.requirements if r.status == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].value, "blue")
        self.assertEqual(state2.conflicts, [])
        superseded = [r for r in state2.requirements if r.status == "superseded"]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].value, "red")


if __name__ == "__main__":
    unittest.main()
