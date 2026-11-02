"""Unit tests for Visual Synthetic Customer Evaluation Runner."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from test_retrieval import product

from astra_eval.visual_runner import (
    execute_visual_evaluation,
    list_saved_runs,
    load_dataset_customers,
)
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import build_index
from shopping_agent.runtime_config import RuntimeConfig


class VisualEvalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.catalogue = self.root / "catalog.jsonl"
        self.index = self.root / "index.sqlite"
        self.out_dir = self.root / "eval_out"

        rows = [
            product("tank-black-01", 35, Color="Black", ProductType="Tanks Tops"),
            product("tank-red-01", 30, Color="Red", ProductType="Tanks Tops"),
            product("casual-shoe-01", 80, Color="Brown", ProductType="Shoes"),
        ]
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.catalogue, self.index)

        # Create a mini synthetic dataset fixture
        self.dataset_file = self.root / "customers.test.json"
        dataset_content = {
            "schema_version": 1,
            "dataset_id": "test-dataset-001",
            "catalogue_sha256": "da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67",
            "provenance": "Test synthetic customers",
            "customers": [
                {
                    "user_id": "cust-active-01",
                    "personality": "Athletic and direct",
                    "background": "Fitness enthusiast",
                    "preferences": [
                        {
                            "category": "preference",
                            "scope": "workout",
                            "fact": {
                                "key": "color_pref",
                                "kind": "soft",
                                "field": "color",
                                "op": "eq",
                                "value": "Black",
                                "statement": "I prefer Black workout clothes.",
                                "keywords": ["color"],
                            },
                        }
                    ],
                    "changes": [],
                    "visits": [
                        {
                            "task_id": "visit-01",
                            "sequence": 1,
                            "goal": "Buy a black tank top",
                            "category": "Tanks Tops",
                            "evaluation_mode": "target_item",
                            "opening": "I need Tanks Tops. I prefer Black workout clothes.",
                            "opening_keys": ["type", "color_pref"],
                            "disclosure": "progressive",
                            "hard": [
                                {
                                    "key": "type",
                                    "kind": "hard",
                                    "field": "product_type",
                                    "op": "contains",
                                    "value": "Tanks Tops",
                                    "statement": "I need Tanks Tops.",
                                    "keywords": ["type", "category"],
                                }
                            ],
                            "soft": [
                                {
                                    "key": "color_pref",
                                    "kind": "soft",
                                    "field": "color",
                                    "op": "eq",
                                    "value": "Black",
                                    "statement": "I prefer Black workout clothes.",
                                    "keywords": ["color"],
                                }
                            ],
                            "witness_id": "tank-black-01",
                        }
                    ],
                }
            ],
        }
        self.dataset_file.write_text(json.dumps(dataset_content))

    def test_dataset_discovery_and_customer_loading(self):
        """Discovers datasets and loads customer metadata correctly."""
        customers = load_dataset_customers(self.dataset_file)
        self.assertEqual(len(customers), 1)
        c = customers[0]
        self.assertEqual(c["user_id"], "cust-active-01")
        self.assertEqual(c["visit_count"], 1)
        self.assertEqual(c["visits"][0]["task_id"], "visit-01")

    def test_paired_evaluation_execution_and_isolation(self):
        """Paired evaluation executes OFF and ON arms in isolated namespaces with no target leakage."""
        # Mock policy to recommend the target item
        mock_policy = MagicMock()
        mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {
                        "type": "RECOMMEND",
                        "product_ids": ["tank-black-01"],
                    },
                    "reason": "recommend best candidate",
                }
            ),
            {},
        )

        res = execute_visual_evaluation(
            dataset_path=self.dataset_file,
            customer_id="cust-active-01",
            visit_sequence=[1],
            mode="paired",
            runner_type="offline",
            policy=mock_policy,
            catalogue_path=self.catalogue,
            index_path=self.index,
            output_dir=self.out_dir,
            config=RuntimeConfig(candidate_retrieval_limit=5),
        )

        self.assertIsNotNone(res.off_arm)
        self.assertIsNotNone(res.on_arm)
        self.assertEqual(res.off_arm.total_visits, 1)
        self.assertEqual(res.on_arm.total_visits, 1)

        # Verify separate storage paths exist
        self.assertTrue((self.out_dir / "user_memory_off").exists())
        self.assertTrue((self.out_dir / "user_memory_on").exists())

        # Verify comparison summary is populated
        self.assertIn("success_rate_off", res.comparison)
        self.assertIn("success_rate_on", res.comparison)

        # Verify result was persisted and can be listed
        saved = list_saved_runs(self.root)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["customer_id"], "cust-active-01")


if __name__ == "__main__":
    unittest.main()
