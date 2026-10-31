"""Target CLI/run/report integration with synthetic catalogue and mocked policies only."""

import json
from unittest.mock import patch

import eval_fixtures as F

from astra_eval.cli import main
from astra_eval.experiment import Condition, ExperimentConfig, plan, run_experiment
from astra_eval.report import build_report, render_markdown, write_report
from astra_eval.scenarios import save
from astra_eval.scoring import ScoreConfig
from astra_eval.simulators import ScriptedShopper
from astra_eval.target_scenarios import TargetPool, generate_targets, load_target_truth


class TargetIntegrationTests(F.EvalCase):
    def frozen(self):
        scenarios, truths, manifest = generate_targets(
            self.catalogue,
            19,
            {"learning": 2, "development": 3, "held_out": 2},
            group="all",
            no_target_per_split=1,
        )
        directory = self.root / "target"
        save(directory, scenarios, truths, manifest)
        return directory, scenarios, truths

    def test_generation_and_two_condition_mock_run_report(self):
        directory, scenarios, truths = self.frozen()
        policy = F.HeuristicPolicy(ask_department=False)
        cfg = ExperimentConfig(
            scenarios_dir=directory,
            catalogue=self.catalogue,
            index=self.index,
            output=self.root / "run",
            evaluation_mode="target_item",
            session_max_model_calls=18,
            score=ScoreConfig(headline_k=5),
            conditions=(Condition("control_a"), Condition("control_b")),
            split="development",
        )
        self.assertEqual(plan(cfg)["sessions"], 8)
        run_experiment(cfg, simulator=ScriptedShopper(), policy=policy)
        write_report(cfg.output)
        parsed = json.loads((cfg.output / "report.json").read_text())
        self.assertEqual(parsed["evaluation_mode"], "target_item")
        self.assertEqual(parsed["primary_k"], 5)
        self.assertTrue(parsed["cells"])
        self.assertTrue(parsed["no_target"])
        self.assertIn("Target-item", (cfg.output / "report.md").read_text())
        self.assertEqual(build_report(cfg.output), parsed)
        self.assertIn("not broader recommendation quality", render_markdown(parsed))
        loaded = load_target_truth(directory)
        payload = json.dumps(policy.contexts)
        # Designation/provenance fields never enter the shopping policy.
        for forbidden in (
            "target_id",
            "compatible_ids_sha256",
            "profile_sha256",
            "ambiguity",
        ):
            self.assertNotIn(f'"{forbidden}"', payload)
        self.assertEqual(len(loaded), len(scenarios))

    def test_cli_target_defaults_dry_run_and_invalid_options(self):
        directory, _, _ = self.frozen()
        base = [
            "run",
            "--scenarios",
            str(directory),
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--output",
            str(self.root / "unused"),
            "--evaluation-mode",
            "target_item",
        ]
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("Network forbidden")
        ):
            self.assertEqual(main(base), 0)
            self.assertEqual(main(base + ["--headline-k", "0"]), 2)
            self.assertEqual(
                main(base + ["--headline-k", "6", "--k", "1", "3", "5", "6"]), 2
            )
            self.assertEqual(main(base + ["--session-max-model-calls", "0"]), 2)
            self.assertEqual(main(base + ["--evaluation-mode", "preference"]), 2)
        self.assertFalse((self.root / "unused").exists())

    def test_pool_eligibility_and_freeze_no_overwrite(self):
        directory, scenarios, truths = self.frozen()
        pool = TargetPool(self.catalogue)
        self.assertEqual(sum(pool.audit()["counts"].values()), len(F.catalogue_rows()))
        again, _, _ = generate_targets(
            self.catalogue,
            19,
            {"learning": 2, "development": 3, "held_out": 2},
            group="all",
            no_target_per_split=1,
        )
        self.assertEqual(scenarios, again)
        with self.assertRaises(FileExistsError):
            save(directory, [], [], {})
