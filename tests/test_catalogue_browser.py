"""Unit and acceptance tests for the Catalogue Browser."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deepseek_fixtures import TEST_KEY, completion
from test_retrieval import product

from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import build_index
from shopping_agent.ui_service import ChatService

try:
    from streamlit.testing.v1 import AppTest

    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

APP = Path(__file__).resolve().parent.parent / "streamlit_app.py"


class CatalogueBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.cat_file = self.root / "catalog.jsonl"
        self.index_file = self.root / "index.sqlite"
        self.sessions_dir = self.root / "sessions"

        def make_item(ident, price, title, category, **details):
            p = product(ident, price, **details)
            p["title"] = title
            p["categories"] = [category]
            return p

        # Create a sample catalogue with distinct titles and categories
        rows = [
            make_item(
                "boots-black", 120.0, "Black Leather Boots", "Boots", Color="Black"
            ),
            make_item(
                "boots-brown", 85.0, "Brown Winter Boots", "Boots", Color="Brown"
            ),
            make_item(
                "sneaker-white",
                45.0,
                "White Running Sneakers",
                "Sneakers",
                Color="White",
            ),
            make_item("dress-red", 60.0, "Red Evening Dress", "Dresses", Color="Red"),
            make_item("shirt-blue", 25.0, "Blue Casual Shirt", "Shirts", Color="Blue"),
            make_item(
                "accessory-belt", None, "Leather Belt", "Accessories", Color="Black"
            ),
        ]
        self.cat_file.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.cat_file, self.index_file)

        self.mock_policy = MagicMock()
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps({"updates": [], "action": {"type": "RESPOND", "message": "Hi"}}),
            {},
        )
        self.service = ChatService(
            self.cat_file,
            self.index_file,
            self.sessions_dir,
            policy=self.mock_policy,
        )

    def test_browse_all_and_pagination(self):
        res = self.service.browse_catalogue(limit=2, offset=0)
        self.assertEqual(res["total_count"], 6)
        self.assertEqual(len(res["products"]), 2)
        self.assertEqual(res["limit"], 2)
        self.assertEqual(res["offset"], 0)

        # Offset 4
        res2 = self.service.browse_catalogue(limit=4, offset=4)
        self.assertEqual(res2["total_count"], 6)
        self.assertEqual(len(res2["products"]), 2)

    def test_search_query(self):
        res = self.service.browse_catalogue(query="boots")
        self.assertEqual(res["total_count"], 2)
        ids = [p["id"] for p in res["products"]]
        self.assertIn("boots-black", ids)
        self.assertIn("boots-brown", ids)

    def test_price_filters_and_sorting(self):
        # Min and max price
        res = self.service.browse_catalogue(
            min_price=30.0, max_price=90.0, sort_by="price_asc"
        )
        prices = [p["facts"]["price"] for p in res["products"]]
        self.assertTrue(all(30.0 <= p <= 90.0 for p in prices))
        self.assertEqual(prices, sorted(prices))

        # Price known only
        res_known = self.service.browse_catalogue(price_known_only=True)
        self.assertEqual(res_known["total_count"], 5)  # 5 have price, 1 has None


@unittest.skipUnless(HAS_STREAMLIT, "Install the [ui] extra to run UI acceptance tests")
class CatalogueBrowserUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue = self.root / "catalog.jsonl"
        self.index = self.root / "index.sqlite"
        self.sessions = self.root / "sessions"
        rows = [
            product("red-boots", 45, Color="Red", Material="Cotton"),
            product("blue-sneakers", 80, Color="Blue", Material="Leather"),
            product("missing-price", None),
        ]
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.catalogue, self.index)
        self.environment = patch.dict(
            os.environ,
            {
                "ASTRA_CATALOGUE": str(self.catalogue),
                "ASTRA_INDEX": str(self.index),
                "ASTRA_UI_SESSIONS": str(self.sessions),
                "DEEPSEEK_API_KEY": TEST_KEY,
                "DEEPSEEK_MODEL": "deepseek-flash",
                "ASTRA_ENV_FILE": str(self.root / "absent.env"),
                "ASTRA_MEMORY_FORMAT": "legacy",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.network = patch(
            "shopping_agent.provider.urlopen",
            side_effect=completion,
        )
        self.transport = self.network.start()
        self.addCleanup(self.network.stop)

    def test_app_renders_catalogue_tab_without_exceptions(self):
        app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        # Check tabs exist
        self.assertTrue(len(app.tabs) >= 3)
