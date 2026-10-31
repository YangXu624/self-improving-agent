"""Report statistics and strata; offline, deterministic, no provider."""

import json
import unittest
from unittest.mock import patch

import test_experiment_a_run as fixtures

from experiments.experiment_a import report, run


class StatisticsTests(unittest.TestCase):
    def test_rate_excludes_not_applicable_and_reports_empty_denominator(self):
        self.assertEqual(
            report.rate([True, False, None, True]), {"n": 3, "k": 2, "rate": 2 / 3}
        )
        self.assertEqual(report.rate([None, None]), {"n": 0, "k": 0, "rate": None})
        self.assertIsNone(report.mean([None]))
        self.assertIsNone(report.median([]))

    def test_exact_mcnemar_known_values(self):
        self.assertEqual(report.mcnemar_exact(0, 0), 1.0)
        self.assertEqual(report.mcnemar_exact(3, 3), 1.0)
        self.assertAlmostEqual(report.mcnemar_exact(5, 0), 0.0625)
        self.assertAlmostEqual(report.mcnemar_exact(0, 5), 0.0625)
        self.assertAlmostEqual(report.mcnemar_exact(1, 0), 1.0)

    def test_bootstrap_is_seeded_reproducible_and_undefined_for_one_pair(self):
        differences = [1, 0, 0, 1, -1, 0, 1, 0]
        first = report.bootstrap_interval(differences, resamples=500)
        self.assertEqual(first, report.bootstrap_interval(differences, resamples=500))
        self.assertLessEqual(first[0], sum(differences) / len(differences))
        self.assertGreaterEqual(first[1], sum(differences) / len(differences))
        self.assertIsNone(report.bootstrap_interval([1]))

    def test_paired_binary_counts_and_skips_missing_pairs(self):
        table = {
            "a": {"t": True, "r": False},
            "b": {"t": True, "r": True},
            "c": {"t": False, "r": True},
            "d": {"t": False, "r": False},
            "e": {"t": True},
            "f": {"t": None, "r": True},
        }
        result = report.paired_binary(table, "t", "r")
        self.assertEqual(
            (
                result["n_pairs"],
                result["both"],
                result["only_treatment"],
                result["only_reference"],
                result["neither"],
            ),
            (4, 1, 1, 1, 1),
        )
        self.assertEqual(result["mean_difference"], 0.0)
        self.assertEqual(report.paired_binary({}, "t", "r")["mean_difference"], None)

    def test_holm_adjustment_and_best_case_p(self):
        def cell(t_only, r_only):
            return report.paired_binary(
                {f"t{i}": {"t": True, "r": False} for i in range(t_only)}
                | {f"r{i}": {"t": False, "r": True} for i in range(r_only)},
                "t",
                "r",
            )

        paired = {
            "a": {"m": cell(6, 0)},
            "b": {"m": cell(3, 0)},
            "c": {"m": cell(1, 1)},
        }
        report.holm_adjust(paired, "m")
        raw = {k: v["m"]["mcnemar_exact_p"] for k, v in paired.items()}
        adjusted = {k: v["m"]["holm_adjusted_p"] for k, v in paired.items()}
        self.assertAlmostEqual(adjusted["a"], min(1.0, 3 * raw["a"]))
        self.assertAlmostEqual(adjusted["b"], min(1.0, max(3 * raw["a"], 2 * raw["b"])))
        self.assertEqual(adjusted["c"], 1.0)
        self.assertTrue(all(adjusted[k] >= raw[k] for k in raw))
        # With only 4 pairs the best possible p is 0.125, however the pairs fall.
        self.assertAlmostEqual(cell(4, 0)["min_achievable_p"], 0.125)
        self.assertAlmostEqual(cell(6, 0)["min_achievable_p"], 2 / 64)
        self.assertIsNone(report.paired_binary({}, "t", "r")["min_achievable_p"])

    def test_paired_numeric_difference(self):
        table = {"a": {"t": 5, "r": 9}, "b": {"t": 7, "r": 8}, "c": {"t": 1}}
        result = report.paired_numeric(table, "t", "r")
        self.assertEqual((result["n_pairs"], result["median_difference"]), (2, -2.5))

    def test_strata_split_feasible_from_no_witness(self):
        self.assertTrue(report.stratum_of(True, "feasible"))
        self.assertFalse(report.stratum_of(False, "feasible"))
        self.assertTrue(report.stratum_of(False, "no_witness"))
        self.assertFalse(report.stratum_of(True, "no_witness"))
        self.assertTrue(report.stratum_of(False, "all"))


class ReportIntegrationTests(fixtures.RunnerCase):
    def make_inputs(self):
        offline = self.root / "offline"
        run.offline(self.frozen, self.index, offline, fixtures.FakeTokenizer())
        self.live()
        return offline / "offline.json", self.root / "out"

    def test_offline_and_live_report_has_prespecified_sections_and_denominators(self):
        offline, live = self.make_inputs()
        result = report.build_report(self.frozen, live, offline)
        self.assertEqual(
            result["tasks"], {"total": 6, "held_out": 4, "feasible": 5, "no_witness": 1}
        )
        self.assertEqual(result["live"]["run"]["observed_trials"], 16)
        self.assertTrue(result["live"]["run"]["finished"])
        for profile in report.PROFILE_ORDER:
            profile_summary = result["live"]["profiles"][profile]
            self.assertEqual(profile_summary["trials"], 4)
            # Feasible and no-witness denominators never mix.
            self.assertEqual(profile_summary["strict_success[feasible]"]["n"], 3)
            self.assertEqual(profile_summary["safe_abstention[no_witness]"]["n"], 1)
            # The fixture always recommends, so the no-witness task is never safely abstained.
            self.assertEqual(profile_summary["safe_abstention[no_witness]"]["k"], 0)
            self.assertEqual(profile_summary["prompt_tokens"]["reported"], 4000)
        self.assertEqual(
            set(result["live"]["paired"]),
            {f"{t}_vs_{r}" for t, r in report.COMPARISONS},
        )
        invariance = result["offline"]["invariance"]
        self.assertEqual(
            invariance["shared_k10_equals_v3_k10"], {"tasks": 6, "identical": 6}
        )
        count_only = result["offline"]["paired"]["v3_k5_vs_v3_k10"]
        self.assertLess(count_only["content_tokens"]["median_difference"], 0)

    def test_report_files_are_deterministic_and_never_overwritten(self):
        offline, live = self.make_inputs()
        a, b = self.root / "report-a", self.root / "report-b"
        report.write_report(self.frozen, a, live, offline)
        report.write_report(self.frozen, b, live, offline)
        for name in ("report.json", "report.md"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
        markdown = (a / "report.md").read_text()
        self.assertIn("Exploratory", markdown)
        self.assertIn("Paired differences", markdown)
        with self.assertRaises(FileExistsError):
            report.write_report(self.frozen, a, live, offline)
        with self.assertRaises(ValueError):
            report.write_report(self.frozen, self.root / "none")

    def test_report_requires_a_verified_frozen_directory_and_calls_no_provider(self):
        offline, live = self.make_inputs()
        (self.frozen / "verification.json").unlink()
        with patch.object(
            run, "DeepSeekPolicy", side_effect=AssertionError("provider")
        ):
            with self.assertRaises(FileNotFoundError):
                report.build_report(self.frozen, live, offline)

    def test_unfinished_run_needs_explicit_permission_and_manifest_must_match(self):
        _, live = self.make_inputs()
        meta = json.loads((live / "run.json").read_text())
        (live / "run.json").write_text(
            json.dumps({**meta, "manifest_sha256": "0" * 64})
        )
        with self.assertRaisesRegex(ValueError, "different frozen manifest"):
            report.build_report(self.frozen, live)
        (live / "run.json").write_text(json.dumps(meta))
        (live / "completed.json").unlink()
        with self.assertRaisesRegex(ValueError, "not finished"):
            report.build_report(self.frozen, live)
        self.assertFalse(
            report.build_report(self.frozen, live, allow_partial=True)["live"]["run"][
                "finished"
            ]
        )
        records = (live / "outcomes.jsonl").read_text().splitlines()
        (live / "outcomes.jsonl").write_text("\n".join(records + records[:1]) + "\n")
        with self.assertRaisesRegex(ValueError, "duplicated or exceed"):
            report.build_report(self.frozen, live, allow_partial=True)

    def test_run_provenance_hashes_are_carried_into_the_report(self):
        offline, live = self.make_inputs()
        info = report.build_report(self.frozen, live, offline)["live"]["run"]
        self.assertEqual(info["tokenizer_sha256"], run.TOKENIZER_SHA256)
        self.assertRegex(info["verification_sha256"], r"^[0-9a-f]{64}$")

    def test_incomplete_run_is_labelled_not_finished_and_failures_are_counted(self):
        offline, live = self.make_inputs()
        (live / "completed.json").unlink()
        records = [json.loads(x) for x in run.read_lines(live / "outcomes.jsonl")]
        records[0]["outcome"]["status"] = "error"
        records[0]["metrics"]["failure"] = True
        (live / "outcomes.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in records[:8])
        )
        result = report.build_report(self.frozen, live, allow_partial=True)
        self.assertFalse(result["live"]["run"]["finished"])
        self.assertEqual(result["live"]["run"]["observed_trials"], 8)
        self.assertEqual(
            sum(
                p["invalid_or_error_trials"]
                for p in result["live"]["profiles"].values()
            ),
            1,
        )
        self.assertNotIn("offline", result)
        self.assertIn("NOT finished", report.render_markdown(result))


if __name__ == "__main__":
    unittest.main()
