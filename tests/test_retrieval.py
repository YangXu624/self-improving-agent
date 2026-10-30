import json
import tempfile
import unittest
from pathlib import Path

from test_sessions import add

from shopping_agent.contracts import Search, ShoppingState
from shopping_agent.retrieval import LexicalSearch, build_index, exact_price, file_hash
from shopping_agent.state import apply_updates


def product(id, price=50.0, **details):
    return {
        "parent_asin": id,
        "title": "Hiking boots",
        "features": ["walking outdoors"],
        "description": [],
        "categories": ["Shoes", "Boots"],
        "details": details,
        "price": price,
        "average_rating": 4.5,
        "rating_number": 20,
        "store": "not a brand",
    }


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def index(self, rows):
        src, dest = self.root / "catalog.jsonl", self.root / "index.sqlite"
        src.write_text("".join(json.dumps(r) + "\n" for r in rows))
        before = src.read_bytes()
        build_index(src, dest)
        self.assertEqual(src.read_bytes(), before)
        search = LexicalSearch(dest, expected_catalogue_hash=file_hash(src))
        self.addCleanup(search.close)
        return search

    def state(self, changes, message):
        return apply_updates(
            ShoppingState(),
            changes,
            expected_version=0,
            user_message=message,
            source_event_id="fixture",
        )

    def test_price_unknown_and_strict_boundary(self):
        search = self.index(
            [
                product("valid", 59.99),
                product("edge", 60),
                product("none", None),
                product("from", "from 12.99"),
                product("zero", 0),
            ]
        )
        state = self.state([add(value=60.0, quote="under 60")], "under 60")
        result = search.search(Search(type="SEARCH", query="boots"), state)
        self.assertEqual([r["id"] for r in result["candidates"]], ["valid"])
        self.assertEqual(
            result["counts"]["products_with_unknown_required_attributes"], 3
        )
        self.assertEqual(result["applied_hard_filters"][0]["value"], 60)

    def test_exclusion_does_not_treat_missing_attribute_as_safe(self):
        search = self.index(
            [
                product("leather", Material="Leather"),
                product("cotton", Material="Cotton"),
                product("unknown"),
            ]
        )
        state = self.state(
            [add("material", "neq", "leather", "no leather")], "no leather"
        )
        result = search.search(Search(type="SEARCH", query="boots"), state)
        self.assertEqual([r["id"] for r in result["candidates"]], ["cotton"])

    def test_filters_before_final_limit_and_repeatable_order(self):
        rows = [product(f"unknown-{i:03}", None) for i in range(40)]
        rows += [product("z", 20), product("a", 20)]
        search = self.index(rows)
        state = self.state([add()], "under 100")
        action = Search(type="SEARCH", query="boots", limit=1)
        one, two = search.search(action, state), search.search(action, state)
        self.assertEqual(one["candidates"], two["candidates"])
        self.assertEqual(one["candidates"][0]["id"], "a")
        self.assertEqual(one["counts"]["verified_eligible"], 2)

    def test_safe_query_no_sql_or_fts_execution(self):
        search = self.index([product("a")])
        out = search.search(
            Search(type="SEARCH", query='boots" OR 1=1; DROP TABLE products --'),
            ShoppingState(),
        )
        self.assertEqual(out["candidates"], [])
        self.assertEqual(search.count, 1)
        self.assertEqual(
            len(
                search.search(Search(type="SEARCH", query="boots"), ShoppingState())[
                    "candidates"
                ]
            ),
            1,
        )

    def test_soft_unknowns_not_mandatory_and_store_not_brand(self):
        search = self.index([product("a")])
        state = self.state(
            [add("color", "eq", "red", "prefer red", "soft")], "prefer red"
        )
        result = search.search(Search(type="SEARCH", query="boots"), state)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIsNone(result["candidates"][0]["facts"]["brand"])
        self.assertEqual(result["candidates"][0]["matched_soft_ids"], [])

    def test_conflicts_empty_query_and_stale_index(self):
        search = self.index([product("a")])
        with self.assertRaises(ValueError):
            search.search(Search(type="SEARCH", query=""), ShoppingState())
        state = self.state(
            [add(), add(op="gte", value=120.0, quote="over 120")], "under 100 over 120"
        )
        with self.assertRaises(ValueError):
            search.search(Search(type="SEARCH", query="boots"), state)
        with self.assertRaises(ValueError):
            LexicalSearch(self.root / "index.sqlite", expected_catalogue_hash="wrong")

    def test_images_and_explicit_details_keep_evidence(self):
        src, dest, images = (
            self.root / "c.jsonl",
            self.root / "i.sqlite",
            self.root / "images.json",
        )
        src.write_text(
            json.dumps(product("a", Size="9", Color="Red", Department="mens")) + "\n"
        )
        images.write_text(json.dumps({"a": "https://example.test/a.jpg"}))
        build_index(src, dest, images)
        search = LexicalSearch(dest)
        self.addCleanup(search.close)
        state = self.state([add("department", "eq", "men", "men")], "men")
        p = search.search(Search(type="SEARCH", query="boots"), state)["candidates"][0]
        self.assertEqual(p["image_url"], "https://example.test/a.jpg")
        self.assertEqual(
            p["evidence"]["size"], {"source": "details.Size", "value": "9"}
        )

    def test_unknown_price_parser(self):
        for bad in [None, "—", "from 5.99", 0, False, float("inf")]:
            self.assertIsNone(exact_price(bad))
        self.assertEqual(exact_price("19.99"), 19.99)


if __name__ == "__main__":
    unittest.main()
