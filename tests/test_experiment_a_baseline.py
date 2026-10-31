import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_retrieval import product

from experiments.experiment_a.finalize import finalize
from experiments.experiment_a.prepare import prepare, state_for
from experiments.experiment_a.source_judgments import judge, raw_fact
from shopping_agent.retrieval import build_index, file_hash


class ExperimentBaselineTests(unittest.TestCase):
    def task(self):
        return {
            "id": "fixture",
            "family": "fixture",
            "split": "development",
            "stratum": "literal",
            "request": "boots under 30",
            "query": "boots",
            "mode": "all",
            "requirements": [
                {
                    "field": "price",
                    "op": "lt",
                    "value": 30.0,
                    "strength": "hard",
                    "quote": "under 30",
                }
            ],
            "relevance": {"category": "Boots"},
        }

    def test_raw_source_judgments_do_not_credit_unknown_or_invent_brand(self):
        task = self.task()
        self.assertTrue(judge(product("cheap", 20), task)["relevant"])
        self.assertFalse(judge(product("edge", 30), task)["relevant"])
        self.assertEqual(
            judge(product("unknown", None), task)["hard_verdict"], "unknown"
        )
        self.assertIsNone(raw_fact(product("store-only"), "brand")[0])
        for value in (False, 0, "from 5.99", float("inf")):
            self.assertIsNone(raw_fact({"price": value}, "price")[0])

    def test_prepare_physical_jsonl_lines_and_review_freeze(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, index, tasks = (
                root / "catalogue.jsonl",
                root / "index.sqlite",
                root / "tasks.json",
            )
            row = product("cheap", 20)
            row["description"] = ["Unicode\u2028separator stays inside JSON text"]
            source.write_text(json.dumps(row, ensure_ascii=False) + "\n")
            build_index(source, index)
            tasks.write_text(
                json.dumps(
                    {"catalogue_sha256": file_hash(source), "tasks": [self.task()]}
                )
            )
            draft, frozen = root / "draft", root / "frozen"
            prepare(source, index, draft, tasks)
            before = (draft / "baseline.json").read_bytes()
            with self.assertRaises(FileExistsError):
                prepare(source, index, draft, tasks)
            review = root / "review.json"
            doc = {
                "labels": {
                    "fixture": {
                        "cheap": {
                            "relevant": True,
                            "hard_verdict": "pass",
                            "support": ["categories.Boots", "price=20"],
                        }
                    }
                },
                "witnesses": {
                    "fixture": {"id": "cheap", "support": ["categories.Boots"]}
                },
            }
            review.write_text(json.dumps(doc))
            result = finalize(draft, review, frozen)
            self.assertEqual(result["review_sha256"], file_hash(review))
            self.assertEqual((draft / "baseline.json").read_bytes(), before)
            self.assertTrue(
                json.loads((frozen / "qrels.json").read_text())["fixture"]["feasible"]
            )
            with self.assertRaises(FileExistsError):
                finalize(draft, review, frozen)
            wrong = copy.deepcopy(doc)
            wrong["labels"]["fixture"] = {}
            review.write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError, "exact candidate pool"):
                finalize(draft, review, root / "bad")

    def test_public_pilot_is_fixed_and_has_no_cross_split_families_or_target_ids(self):
        path = (
            Path(__file__).resolve().parents[1] / "experiments/experiment_a/tasks.json"
        )
        tasks = json.loads(path.read_text())["tasks"]
        self.assertEqual(len(tasks), 36)
        self.assertEqual(sum(t["split"] == "held_out" for t in tasks), 24)
        groups = {}
        for task in tasks:
            self.assertEqual(
                groups.setdefault(task["family"], task["split"]), task["split"]
            )
            self.assertNotIn("positive_ids", task)
            self.assertNotIn("product_ids", task)
            for r in task["requirements"]:
                self.assertTrue(r["quote"].strip())
                self.assertIn(r["quote"], task["request"])
            for requirement in state_for(task).requirements:
                self.assertRegex(requirement.id, r"^[a-f0-9]{32}$")
                self.assertNotIn(task["id"], requirement.id)


if __name__ == "__main__":
    unittest.main()
