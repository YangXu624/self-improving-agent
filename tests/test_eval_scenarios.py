"""Scenario generation: reproducible, grounded, verifiable, split-safe, leak-free."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import eval_fixtures as F

from astra_eval.models import Fact, Scenario, ShopperProfile
from astra_eval.oracle import CatalogueOracle, judge, raw_facts
from astra_eval.scenarios import (
    assign_types,
    cluster_types,
    generate,
    load_ground_truth,
    load_scenarios,
    nice_budget,
    save,
)

PER_SPLIT = {"learning": 3, "development": 2, "held_out": 4}


class ScenarioTests(F.EvalCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scenarios, cls.truths, cls.manifest = generate(cls.catalogue, 5, PER_SPLIT)

    def test_generation_is_reproducible_and_seed_sensitive(self):
        again = generate(self.catalogue, 5, PER_SPLIT)
        self.assertEqual(
            [s.model_dump() for s in self.scenarios], [s.model_dump() for s in again[0]]
        )
        self.assertEqual(
            [t.model_dump() for t in self.truths], [t.model_dump() for t in again[1]]
        )
        other, _, _ = generate(self.catalogue, 6, PER_SPLIT)
        self.assertNotEqual([s.id for s in self.scenarios], [s.id for s in other])

    def test_splits_have_the_requested_sizes_and_disjoint_product_families(self):
        counts = {s: sum(x.split == s for x in self.scenarios) for s in PER_SPLIT}
        self.assertEqual(counts, PER_SPLIT)
        families = {}
        for s in self.scenarios:
            families.setdefault(s.family, set()).add(s.split)
        self.assertTrue(all(len(v) == 1 for v in families.values()))

    def test_every_kind_is_present_including_no_valid_product(self):
        kinds = {s.kind for s in self.scenarios}
        self.assertEqual(kinds, {"feasible", "underspecified", "no_valid_product"})

    def test_acceptable_sets_match_an_independent_brute_force_over_raw_rows(self):
        oracle = CatalogueOracle(self.catalogue)
        for scenario, truth in zip(self.scenarios, self.truths):
            graded = [
                judge(raw_facts(row), truth.hard, truth.soft) for row in oracle.rows()
            ]
            acceptable = [g for g in graded if g["grade"] > 0]
            self.assertEqual(len(acceptable), truth.acceptable_count, scenario.id)
            if scenario.kind == "no_valid_product":
                self.assertEqual(truth.acceptable_count, 0)
            else:
                self.assertGreaterEqual(truth.acceptable_count, 3)
                self.assertEqual(
                    truth.ideal_grades,
                    sorted((g["grade"] for g in acceptable), reverse=True)[:20],
                )

    def test_unknown_attributes_stay_unknown_and_are_never_acceptable(self):
        oracle = CatalogueOracle(self.catalogue)
        feasible = next(t for t in self.truths if t.kind != "no_valid_product")
        unpriced = [r for r in oracle.rows() if r["price"] is None]
        self.assertTrue(unpriced)
        for row in unpriced:
            self.assertNotEqual(
                judge(raw_facts(row), feasible.hard, feasible.soft)["hard"], "pass"
            )
        self.assertGreater(feasible.unknown_required_count, 0)

    def test_no_valid_scenarios_are_a_verified_empty_variant_of_a_satisfiable_task(
        self,
    ):
        oracle = CatalogueOracle(self.catalogue)
        for scenario, truth in zip(self.scenarios, self.truths):
            if scenario.kind != "no_valid_product":
                continue
            relaxed = [
                f for f in truth.hard if f.key not in {"budget", "color", "brand"}
            ]
            near = [
                r
                for r in oracle.rows()
                if judge(raw_facts(r), relaxed, [])["grade"] > 0
            ]
            self.assertGreaterEqual(len(near), 3)

    def test_underspecified_openings_reveal_only_part_of_the_hidden_profile(self):
        for s in self.scenarios:
            hard = {f.key for f in s.profile.facts if f.kind == "hard"}
            if s.kind == "underspecified":
                self.assertLess(len(set(s.profile.opening_keys)), len(hard))
            self.assertTrue(
                set(s.profile.opening_keys) <= {f.key for f in s.profile.facts}
            )
            self.assertNotIn("$", s.opening) if s.kind == "underspecified" else None

    def test_scenario_file_contains_no_ground_truth_or_product_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "set"
            save(directory, self.scenarios, self.truths, self.manifest)
            text = (directory / "scenarios.jsonl").read_text()
            for forbidden in (
                "acceptable",
                "ideal_grades",
                "grade",
                "B00",
                "B01",
                "ground_truth",
            ):
                self.assertNotIn(forbidden, text)
            loaded, manifest = load_scenarios(directory)
            self.assertEqual([s.id for s in loaded], [s.id for s in self.scenarios])
            self.assertEqual(manifest["catalogue_sha256"], self.catalogue_sha)
            self.assertEqual(
                set(load_ground_truth(directory)), {s.id for s in self.scenarios}
            )
            self.assertEqual(
                [s.id for s in load_scenarios(directory, "held_out")[0]],
                [s.id for s in self.scenarios if s.split == "held_out"],
            )

    def test_frozen_sets_are_hash_checked_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "set"
            save(directory, self.scenarios, self.truths, self.manifest)
            with self.assertRaises(FileExistsError):
                save(directory, self.scenarios, self.truths, self.manifest)
            for name, loader in (
                ("scenarios.jsonl", load_scenarios),
                ("ground_truth.jsonl", load_ground_truth),
            ):
                path = directory / name
                original = path.read_text()
                path.write_text(original.replace("0", "1", 1))
                with self.assertRaisesRegex(ValueError, "manifest"):
                    loader(directory)
                path.write_text(original)

    def test_a_split_without_any_eligible_family_fails_loudly(self):
        weights = {"learning": 1.0, "development": 0.0, "held_out": 0.0}
        with self.assertRaisesRegex(ValueError, "No product families"):
            generate(
                self.catalogue,
                5,
                {"learning": 1, "development": 1, "held_out": 0},
                weights=weights,
            )

    def test_models_reject_malformed_profiles(self):
        fact = Fact(
            key="a", kind="hard", field="price", op="lt", value=5.0, statement="x"
        )
        with self.assertRaises(ValueError):
            ShopperProfile(
                scenario_id="s", persona="p", facts=(fact, fact), opening_keys=()
            )
        with self.assertRaises(ValueError):
            ShopperProfile(
                scenario_id="s", persona="p", facts=(fact,), opening_keys=("missing",)
            )
        with self.assertRaises(ValueError):
            Fact(
                key="a", kind="hard", field="weight", op="lt", value=5.0, statement="x"
            )
        profile = ShopperProfile(
            scenario_id="s", persona="p", facts=(fact,), opening_keys=("a",)
        )
        with self.assertRaises(ValueError):
            profile.persona = "changed"  # immutable

    def test_no_two_scenarios_are_identical_tasks(self):
        signatures = [
            (
                s.family,
                json.dumps([f.model_dump() for f in s.profile.facts], sort_keys=True),
            )
            for s in self.scenarios
        ]
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_overlapping_product_families_are_clustered_into_one_split(self):
        leaves = [
            "Necklaces",
            "Pendant Necklaces",
            "Sunglasses",
            "Replacement Sunglass Lenses",
            "Fashion Hoodies & Sweatshirts",
            "Hoodies",
            "Boots",
            "Hiking Boots",
            "Watches",
        ]
        clusters = {frozenset(c) for c in cluster_types(leaves)}
        self.assertIn(frozenset({"Necklaces", "Pendant Necklaces"}), clusters)
        self.assertIn(
            frozenset({"Sunglasses", "Replacement Sunglass Lenses"}), clusters
        )
        self.assertIn(frozenset({"Fashion Hoodies & Sweatshirts", "Hoodies"}), clusters)
        self.assertIn(frozenset({"Boots", "Hiking Boots"}), clusters)
        self.assertIn(frozenset({"Watches"}), clusters)
        for seed in range(6):
            split = assign_types(
                [(leaf, 50) for leaf in leaves],
                seed,
                {"learning": 0.4, "development": 0.2, "held_out": 0.4},
            )
            where = {leaf: name for name, group in split.items() for leaf in group}
            self.assertEqual(where["Necklaces"], where["Pendant Necklaces"])
            self.assertEqual(where["Boots"], where["Hiking Boots"])

    def test_generated_tasks_use_plausible_budgets_and_clean_departments(self):
        for scenario, truth in zip(self.scenarios, self.truths):
            budget = next(f.value for f in scenario.profile.facts if f.key == "budget")
            self.assertGreaterEqual(budget, 2.0)
            for f in scenario.profile.facts:
                if f.field == "department":
                    self.assertIn(f.value, {"men", "women", "boys", "girls", "unisex"})

    def test_nice_budget_rounds_up_to_human_numbers(self):
        self.assertEqual(
            [nice_budget(v) for v in (7, 33, 61, 140, 230)],
            [10.0, 40.0, 75.0, 150.0, 250.0],
        )

    def test_scenario_model_has_no_ground_truth_field(self):
        self.assertNotIn("ground_truth", Scenario.model_fields)
        self.assertEqual(
            set(Scenario.model_fields) & {"acceptable_count", "ideal_grades"}, set()
        )
        copy.deepcopy(self.scenarios[0])


if __name__ == "__main__":
    unittest.main()
