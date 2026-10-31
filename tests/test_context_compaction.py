"""The compact prompt preserves correction handles, evidence and visible candidates."""

import copy
import json
import unittest
from types import SimpleNamespace

from test_sessions import add

from shopping_agent.context import (
    PROMPT_VERSION,
    build_context,
    compact_schema,
    dialogue_context,
    product_context,
    search_context,
    state_context,
)
from shopping_agent.contracts import Decision, ShoppingState
from shopping_agent.state import apply_updates


class ContextCompactionTests(unittest.TestCase):
    def product(self, ident="one"):
        return {
            "id": ident,
            "title": "Hiking boots",
            "categories": ["Shoes", "Boots"],
            "facts": {"price": 45.0, "material": "Leather", "color": None},
            "evidence": {
                "price": {"source": "price", "value": 45.0},
                "material": {"source": "details.Material", "value": "Leather"},
            },
            "snippet": "Hiking boots Shoes Boots Waterproof sole",
            "image_url": "https://example.test/a.jpg",
            "bm25": -12.123456789,
            "matched_hard_ids": ["hard"],
            "matched_soft_ids": ["soft"],
            "eligible": True,
            "unknown_ids": [],
            "failed_ids": [],
        }

    def test_product_projection_preserves_facts_sources_and_new_description(self):
        product = self.product()
        before = copy.deepcopy(product)
        view = product_context(product)
        self.assertEqual(view["facts"], {"price": 45, "material": "Leather"})
        self.assertEqual(view["sources"]["material"], "details.Material")
        self.assertEqual(view["snippet"], "Waterproof sole")
        self.assertEqual(view["matched_soft_ids"], ["soft"])
        self.assertNotIn("image_url", view)
        self.assertNotIn("bm25", view)
        self.assertNotIn("eligible", view)
        self.assertLess(len(json.dumps(view)), len(json.dumps(product)))
        self.assertEqual(product, before)

    def test_snippet_prefix_removed_only_if_exact_and_already_visible(self):
        product = self.product()
        for snippet in ("Hiking", "Hiking boots Shoes Boots"):
            product["snippet"] = snippet
            self.assertNotIn("snippet", product_context(product))
        product["snippet"] = "Different useful evidence"
        self.assertEqual(product_context(product)["snippet"], product["snippet"])

    def test_search_projection_retains_every_visible_id_order_and_filter_reference(
        self,
    ):
        result = {
            "search_id": "search",
            "state_version": 3,
            "query": "boots",
            "match_mode": "all",
            "counts": {"verified_eligible": 20},
            "applied_hard_filters": [{"id": "hard", "quote": "boots"}],
            "candidates": [self.product(str(i)) for i in range(20)],
            "catalogue_version": "catalogue",
            "strategy_version": "strategy",
        }
        before = copy.deepcopy(result)
        view = search_context(result)
        self.assertEqual(
            [p["id"] for p in view["candidates"]], [str(i) for i in range(20)]
        )
        self.assertEqual(view["applied_hard_filters"], ["hard"])
        self.assertEqual(view["counts"], result["counts"])
        self.assertEqual(view["search_id"], "search")
        self.assertEqual(result, before)

    def test_active_state_preserves_operator_strength_and_stable_edit_ids(self):
        state = apply_updates(
            ShoppingState(),
            [add()],
            expected_version=0,
            user_message="under 100",
            source_event_id="source",
        )
        view = state_context(state)
        self.assertEqual(view["version"], 1)
        self.assertEqual(
            view["requirements"],
            [
                {
                    "id": state.requirements[0].id,
                    "field": "price",
                    "op": "lt",
                    "value": 100.0,
                    "strength": "hard",
                }
            ],
        )
        self.assertEqual(state.requirements[0].quote, "under 100")
        self.assertEqual(state.requirements[0].source_event_id, "source")

    def test_history_omits_only_current_event_and_retains_ordered_recommendations(self):
        def event(kind, payload):
            return SimpleNamespace(type=kind, payload=payload)

        previous = event("user_message", {"message": "yes"})
        current = event("user_message", {"message": "yes"})
        session = SimpleNamespace(
            events=[
                previous,
                event(
                    "assistant_response",
                    {
                        "message": "Matches",
                        "action": "RECOMMEND",
                        "request_id": "private-audit-id",
                        "products": [self.product("first"), self.product("second")],
                    },
                ),
                current,
            ],
            state=ShoppingState(),
        )
        history = dialogue_context(session, "yes")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": "yes"})
        self.assertEqual(
            [p["id"] for p in history[1]["content"]["products"]], ["first", "second"]
        )
        self.assertNotIn("request_id", history[1]["content"])
        messages = build_context(session, "yes", None, [], {}, True)
        ctx = json.loads(messages[-1]["content"])
        self.assertEqual(ctx["current_user_message"], "yes")
        self.assertEqual(ctx["prompt_version"], PROMPT_VERSION)
        self.assertEqual(ctx["recent_dialogue"], history)

    def test_schema_compaction_removes_only_generated_titles(self):
        schema = Decision.model_json_schema()
        compact = compact_schema(schema)
        for key in ("required", "additionalProperties", "properties"):
            self.assertIn(key, compact)
        self.assertEqual(compact["required"], schema["required"])
        self.assertEqual(
            compact["$defs"]["Search"]["properties"]["limit"]["maximum"], 20
        )
        self.assertEqual(
            compact["$defs"]["Search"]["properties"]["limit"]["minimum"], 1
        )
        self.assertIn("discriminator", compact["properties"]["action"])
        self.assertEqual(
            compact_schema(
                {"properties": {"title": {"type": "string", "title": "Title"}}}
            ),
            {"properties": {"title": {"type": "string"}}},
        )
        self.assertLess(len(json.dumps(compact)), len(json.dumps(schema)))


if __name__ == "__main__":
    unittest.main()
