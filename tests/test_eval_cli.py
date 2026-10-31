"""CLI: offline by default, DeepSeek only with an explicit cap, Ollama only when asked."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import eval_fixtures as F

from astra_eval.cli import main


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTests(F.EvalCase):
    def generate(self, name="scn"):
        directory = self.root / name
        code, out, _ = run_cli(
            "generate",
            "--catalogue",
            str(self.catalogue),
            "--output",
            str(directory),
            "--seed",
            "5",
            "--learning",
            "2",
            "--development",
            "2",
            "--held-out",
            "3",
        )
        self.assertEqual(code, 0)
        return directory, json.loads(out)

    def test_generate_writes_a_frozen_set_and_refuses_to_overwrite(self):
        directory, manifest = self.generate()
        self.assertEqual(
            manifest["per_split"], {"learning": 2, "development": 2, "held_out": 3}
        )
        self.assertRegex(manifest["scenarios_sha256"], r"^[0-9a-f]{64}$")
        with self.assertRaises(FileExistsError):
            self.generate()

    def test_run_without_live_is_a_dry_run_that_contacts_nothing(self):
        directory, _ = self.generate()
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            code, out, _ = run_cli(
                "run",
                "--scenarios",
                str(directory),
                "--catalogue",
                str(self.catalogue),
                "--index",
                str(self.index),
                "--output",
                str(self.root / "o"),
                "--split",
                "held_out",
            )
        self.assertEqual(code, 0)
        self.assertIn('"sessions": 3', out)
        self.assertIn("Dry run", out)
        self.assertFalse((self.root / "o").exists())

    def test_live_requires_an_explicit_model_call_cap(self):
        directory, _ = self.generate()
        code, _, err = run_cli(
            "run",
            "--scenarios",
            str(directory),
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--output",
            str(self.root / "o"),
            "--live",
        )
        self.assertEqual(code, 2)
        self.assertIn("--max-model-calls", err)
        self.assertFalse((self.root / "o").exists())

    def test_live_run_end_to_end_with_a_stubbed_policy_and_the_scripted_shopper(self):
        directory, _ = self.generate()
        policy = F.HeuristicPolicy()
        with patch(
            "shopping_agent.provider.DeepSeekPolicy.from_env_file", return_value=policy
        ):
            code, out, _ = run_cli(
                "run",
                "--scenarios",
                str(directory),
                "--catalogue",
                str(self.catalogue),
                "--index",
                str(self.index),
                "--output",
                str(self.root / "o"),
                "--live",
                "--max-model-calls",
                "400",
                "--simulator",
                "scripted",
                "--split",
                "development",
                "--price-input-per-million",
                "0.3",
                "--price-output-per-million",
                "1.2",
            )
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "o" / "report.md").exists())
        self.assertTrue(policy.contexts)
        code, shown, _ = run_cli("report", str(self.root / "o"))
        self.assertIn("Simulated-shopper evaluation report", shown)
        first = json.loads(
            (self.root / "o" / "results.jsonl").read_text().splitlines()[0]
        )["scenario"]["id"]
        code, shown, _ = run_cli("show", str(self.root / "o"), first)
        self.assertIn("SHOPPER", shown)

    def test_bad_option_values_exit_cleanly_with_a_message_and_spend_nothing(self):
        directory, _ = self.generate()
        base = [
            "run",
            "--scenarios",
            str(directory),
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--output",
            str(self.root / "o"),
        ]
        for extra in (
            ["--limit", "0"],
            ["--window-turns", "0"],
            ["--turn-budget", "0"],
            ["--k", "2", "4", "--headline-k", "3"],
            ["--sim-timeout", "-1"],
        ):
            with self.subTest(extra=extra):
                code, _, err = run_cli(*base, *extra)
                self.assertEqual(code, 2)
                self.assertIn("error:", err)
        self.assertFalse((self.root / "o").exists())

    def test_live_run_checks_the_simulator_before_any_paid_call(self):
        directory, _ = self.generate()
        policy = F.HeuristicPolicy()
        down = {"probe_ok": False, "problems": ["Cannot reach Ollama."]}
        with (
            patch("astra_eval.cli.check_ollama", return_value=down),
            patch(
                "shopping_agent.provider.DeepSeekPolicy.from_env_file",
                return_value=policy,
            ) as deepseek,
        ):
            code, _, err = run_cli(
                "run",
                "--scenarios",
                str(directory),
                "--catalogue",
                str(self.catalogue),
                "--index",
                str(self.index),
                "--output",
                str(self.root / "o"),
                "--live",
                "--max-model-calls",
                "50",
            )
        self.assertEqual(code, 1)
        self.assertIn("nothing was sent to DeepSeek", err)
        deepseek.assert_not_called()
        self.assertEqual(policy.contexts, [])
        self.assertFalse((self.root / "o").exists())

    def test_check_simulator_reports_and_sets_the_exit_code(self):
        good = {"probe_ok": True, "problems": []}
        bad = {"probe_ok": False, "problems": ["Cannot reach Ollama."]}
        with patch("astra_eval.cli.check_ollama", return_value=good) as check:
            code, out, _ = run_cli(
                "check-simulator", "--sim-model", "llama3.1:latest", "--sim-seed", "3"
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                (check.call_args.args[0].model, check.call_args.args[0].seed),
                ("llama3.1:latest", 3),
            )
        with patch("astra_eval.cli.check_ollama", return_value=bad):
            self.assertEqual(run_cli("check-simulator")[0], 1)

    def test_simulator_environment_variables_reach_the_run_config(self):
        directory, _ = self.generate()
        with patch.dict(
            "os.environ", {"ASTRA_SIM_MODEL": "other:1", "ASTRA_SIM_WINDOW_TURNS": "10"}
        ):
            from astra_eval.cli import parser, sim_config

            args = parser().parse_args(
                ["run", "--scenarios", str(directory), "--output", "x"]
            )
            config = sim_config(args)
        self.assertEqual((config.model, config.window_turns), ("other:1", 10))


if __name__ == "__main__":
    unittest.main()
