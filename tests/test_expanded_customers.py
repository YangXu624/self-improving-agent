"""Development-fixture integrity; no model credentials or live calls are used."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from astra_eval.customers import (
    CustomerDataset,
    compile_visit,
    load_customers,
    validate_dataset,
)
from astra_eval.oracle import CatalogueOracle, judge, raw_facts

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "experiments/longitudinal"
ORIGINAL = FIXTURES / "customers.dev.json"
EXPANDED = FIXTURES / "customers.dev-expanded.json"
CATALOGUE = ROOT / "data/catalogue/catalog.jsonl"
INDEX = ROOT / "data/index/catalogue.sqlite"
NEW_IDS = {
    "dev-capsule-wardrobe",
    "dev-office-basics",
    "dev-activewear",
    "dev-footwear",
    "dev-commuter-bags",
    "dev-jewelry-simple",
    "dev-gift-shopper",
    "dev-bag-style-change",
}


class ExpandedCustomerTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(EXPANDED.read_text())
        self.data = CustomerDataset.model_validate(self.raw)
        self.new = self.data.customers[3:]

    def test_original_prefix_and_development_provenance_preserved(self):
        original = json.loads(ORIGINAL.read_text())
        self.assertEqual(self.raw["customers"][:3], original["customers"])
        self.assertEqual(self.data.catalogue_sha256, original["catalogue_sha256"])
        self.assertNotEqual(self.data.dataset_id, original["dataset_id"])
        self.assertIn("Human-directed DEVELOPMENT", self.data.provenance)
        self.assertEqual(len(self.data.customers), 11)
        self.assertEqual(sum(len(c.visits) for c in self.data.customers), 36)
        self.assertEqual({c.user_id for c in self.new}, NEW_IDS)
        self.assertTrue(all(len(c.visits) == 3 for c in self.new))

    def test_bad_order_duplicate_ids_and_heldout_rejected(self):
        mutations = [
            lambda x: x.update(split="held_out"),
            lambda x: x["customers"][3]["visits"][1].update(sequence=3),
            lambda x: x["customers"][3].update(user_id=x["customers"][0]["user_id"]),
            lambda x: x["customers"][3]["visits"][0].update(
                task_id=x["customers"][0]["visits"][0]["task_id"]
            ),
            lambda x: x["customers"][3].update(user_id="../unsafe"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                raw = copy.deepcopy(self.raw)
                mutate(raw)
                with self.assertRaises(ValueError):
                    CustomerDataset.model_validate(raw)

    def test_stable_disclosure_recall_and_only_one_new_change(self):
        self.assertEqual(
            [c.user_id for c in self.new if c.changes], ["dev-bag-style-change"]
        )
        for c in self.new:
            for visit in c.visits:
                compile_visit(c, visit)  # Literal disclosure/operator validation.
                self.assertEqual(visit.max_user_turns, 6)
            if not c.preferences:
                continue
            key = c.preferences[0].fact.key
            self.assertIn(key, c.visits[0].opening_keys)
            self.assertIn(c.preferences[0].fact.statement, c.visits[0].opening)
            self.assertNotIn(key, c.visits[1].opening_keys)
            self.assertEqual(c.visits[1].disclosure, "recall_probe")
            self.assertNotIn(c.preferences[0].fact.statement, c.visits[1].opening)
            if not c.changes:
                self.assertEqual(c.state_at(1), c.state_at(3))

    def test_change_boundary_does_not_leak_future_color(self):
        c = next(c for c in self.new if c.changes)
        key = c.preferences[0].fact.key
        old = c.state_at(1)[1][key].fact.value
        new = c.state_at(3)[1][key].fact.value
        self.assertNotEqual(old, new)
        self.assertEqual(c.state_at(2)[1][key].fact.value, old)
        _, private, _ = compile_visit(c, c.visits[1])
        self.assertNotIn(new, json.dumps(private))
        self.assertNotIn("changes", private)
        last = c.visits[2]
        self.assertEqual(last.disclosure, "announce_change")
        self.assertIn(c.state_at(3)[1][key].fact.statement, last.opening)
        self.assertIn(key, last.opening_keys)

    def test_recipient_and_scope_nontransfer(self):
        office = next(c for c in self.new if c.user_id == "dev-office-basics")
        self.assertTrue(office.visits[1].persistent_keys)
        self.assertFalse(office.visits[2].persistent_keys)
        _, _, belt_facts = compile_visit(office, office.visits[2])
        self.assertFalse(any(f.field == "color" for f in belt_facts))
        gift = next(c for c in self.new if c.user_id == "dev-gift-shopper")
        self.assertFalse(gift.preferences)
        self.assertFalse(gift.changes)
        self.assertEqual([v.recipient for v in gift.visits], ["gift", "gift", "self"])
        self.assertTrue(all(not v.persistent_keys for v in gift.visits))
        for visit in gift.visits[:2]:
            self.assertEqual(visit.disclosure, "gift")
            self.assertIn("gift", visit.opening)
            self.assertEqual(len(visit.soft), 1)
        _, _, self_facts = compile_visit(gift, gift.visits[2])
        self.assertFalse(any(f.field == "color" for f in self_facts))

    def test_all_current_roleplay_contexts_exclude_truth_and_other_customers(self):
        witness_ids = {v.witness_id for c in self.new for v in c.visits}
        for c in self.new:
            for visit in c.visits:
                scenario, context, _ = compile_visit(c, visit)
                text = json.dumps(context) + scenario.profile.model_dump_json()
                for witness_id in witness_ids:
                    self.assertNotIn(witness_id, text)
                for other in self.new:
                    self.assertNotIn(other.user_id, json.dumps(context))
                    if other != c:
                        self.assertNotIn(other.background, text)
                for forbidden in ("visits", "witness_id", "evidence", "changes"):
                    self.assertNotIn(forbidden, context)
                self.assertNotIn("sha256", text)


@unittest.skipUnless(
    CATALOGUE.exists() and INDEX.exists(), "Local approved 50k assets required"
)
class ExpandedCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_customers(EXPANDED)
        cls.oracle = CatalogueOracle(CATALOGUE)
        cls.compiled = validate_dataset(cls.data, CATALOGUE)

    def test_all_frozen_counts_hashes_and_witness_sources_validate(self):
        self.assertEqual(len(self.compiled), 36)
        for t in self.compiled[12:]:
            with self.subTest(task=t.visit.task_id):
                row = self.oracle.row(t.visit.witness_id)
                self.assertEqual(row["categories"][-1], t.visit.category)
                self.assertGreater(t.preference_truth.acceptable_count, 0)
                self.assertGreater(t.target_truth.compatible_count, 0)
                if t.preference_truth.soft:
                    # A scored preference must distinguish at least two feasible choices.
                    self.assertLess(
                        t.target_truth.compatible_count,
                        t.preference_truth.acceptable_count,
                    )
                facts = t.scenario.profile.facts
                self.assertEqual(judge(raw_facts(row), list(facts), [])["hard"], "pass")
                self.assertEqual(
                    set(t.visit.evidence.witness_sources), {f.key for f in facts}
                )
                for source in t.visit.evidence.witness_sources.values():
                    self.assertTrue(
                        source in {"categories", "price"}
                        or source.startswith("details.")
                    )

    def test_cycling_scope_excludes_sport_clothing_despite_root_label(self):
        task = next(t for t in self.compiled if t.visit.task_id == "footwear-01")
        matches = 0
        for row in self.oracle.rows():
            if judge(raw_facts(row), task.preference_truth.hard, [])["hard"] == "pass":
                matches += 1
                # The root "Clothing, Shoes & Jewelry" alone does not establish footwear.
                self.assertIn("Shoes", row["categories"])
                self.assertIn("Cycling", row["categories"])
        self.assertEqual(matches, task.preference_truth.acceptable_count)

    def test_inventory_reproduces_from_local_assets(self):
        spec = importlib.util.spec_from_file_location(
            "catalogue_inventory", FIXTURES / "catalogue_inventory.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            module.inventory(CATALOGUE, INDEX, ORIGINAL),
            (ROOT / "docs/reviews/longitudinal-catalogue-inventory.md").read_text(),
        )
