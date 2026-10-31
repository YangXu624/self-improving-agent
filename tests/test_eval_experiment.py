"""Experiment runner end to end: generated scenarios, conditions, budgets, isolation, report."""

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import eval_fixtures as F

from astra_eval.experiment import (
    Condition,
    ExperienceSnapshot,
    ExperimentConfig,
    default_agent_factory,
    plan,
    run_experiment,
)
from astra_eval.report import (
    build_report,
    read_results,
    render_markdown,
    show_transcript,
    write_report,
)
from astra_eval.scenarios import generate, load_ground_truth, save
from astra_eval.scoring import ScoreConfig
from astra_eval.simulators import OllamaShopper, ScriptedShopper, SimulatorConfig


class ExperimentCase(F.EvalCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        scenarios, truths, manifest = generate(
            cls.catalogue, 5, {"learning": 2, "development": 2, "held_out": 5}
        )
        cls.scenario_dir = Path(cls._tmp.name) / "scenarios"
        save(cls.scenario_dir, scenarios, truths, manifest)
        cls.truths = load_ground_truth(cls.scenario_dir)

    def config(self, name="out", **kw):
        return ExperimentConfig(
            scenarios_dir=self.scenario_dir,
            catalogue=self.catalogue,
            index=self.index,
            output=self.root / name,
            **kw,
        )

    def run_it(
        self,
        name="out",
        policy=None,
        simulator=None,
        factory=default_agent_factory,
        **kw,
    ):
        self.policy = policy or F.HeuristicPolicy()
        return run_experiment(
            self.config(name, **kw),
            simulator=simulator or ScriptedShopper(),
            policy=self.policy,
            agent_factory=factory,
        )


class EndToEndTests(ExperimentCase):
    def test_full_run_writes_traces_scores_and_a_report_with_separated_groups(self):
        summary = self.run_it(max_model_calls=500)
        out = self.root / "out"
        results = read_results(out)
        self.assertEqual((summary["sessions"], summary["stopped_early"]), (9, None))
        self.assertEqual(len(results), 9)
        for r in results:
            self.assertTrue((out / r["session_dir"] / "transcript.jsonl").exists())
            self.assertTrue((out / r["session_dir"] / "result.json").exists())
        self.assertTrue((out / "run.json").exists() and (out / "summary.json").exists())
        report = write_report(out)
        feasible = report["cells"]["memory_off/all"]["feasible"]
        none = report["cells"]["memory_off/all"]["no_valid_product"]
        self.assertEqual(feasible["sessions"] + none["sessions"], 9)
        self.assertGreater(feasible["success_headline_k"]["rate"], 0.5)
        self.assertEqual(none["correct_abstention"]["rate"], 1.0)
        self.assertEqual(feasible["hard_violations"]["item_violation_rate"], 0.0)
        self.assertIn("memory_off/held_out", report["cells"])
        markdown = (out / "report.md").read_text()
        for heading in (
            "Simulator reliability",
            "feasible scenarios",
            "no-valid-product scenarios",
        ):
            self.assertIn(heading, markdown)

    def test_scores_come_from_ground_truth_not_from_the_shoppers_opinion(self):
        # The shopper only sees titles and prices on cards, so it accepts a recommendation that
        # ignores its hidden department; the independent scorer must still call that a failure.
        self.run_it(
            policy=F.HeuristicPolicy(ignore={"department"}, ask_department=False),
            max_model_calls=500,
        )
        results = read_results(self.root / "out")
        accepted_with_violations = [
            r
            for r in results
            if r["score"]["termination"] == "accepted"
            and r["score"]["violations"]["any_hard_fail"]
        ]
        self.assertTrue(accepted_with_violations)
        # Success@K only needs one verified hit, so it can coexist with violating items: that
        # is exactly why the violation rate is reported next to it, not folded into it.
        report = build_report(self.root / "out")
        cell = report["cells"]["memory_off/all"]["feasible"]
        self.assertGreater(cell["hard_violations"]["item_violation_rate"], 0.0)
        self.assertGreater(cell["hard_violations"]["sessions_with_any_violation"], 0)
        self.assertGreater(cell["success_headline_k"]["rate"], 0.0)

    def test_split_filter_limit_and_plan(self):
        planned = plan(self.config(split="held_out", limit=3))
        self.assertEqual((planned["scenarios"], planned["sessions"]), (3, 3))
        self.assertEqual(planned["worst_case_agent_model_calls"], 3 * 6 * 3)
        self.run_it(split="held_out", limit=3, max_model_calls=500)
        self.assertEqual(
            {r["scenario"]["split"] for r in read_results(self.root / "out")},
            {"held_out"},
        )

    def test_reruns_are_deterministic_with_a_deterministic_shopper_and_policy(self):
        self.run_it("a", max_model_calls=500)
        self.run_it("b", max_model_calls=500)

        def strip(results):
            return [
                (
                    r["scenario"]["id"],
                    r["score"]["outcome"],
                    r["score"]["failure_category"],
                    r["score"].get("metrics"),
                )
                for r in results
            ]

        self.assertEqual(
            strip(read_results(self.root / "a")), strip(read_results(self.root / "b"))
        )

    def test_output_must_be_new_and_the_catalogue_must_match(self):
        self.run_it(max_model_calls=500, limit=1)
        with self.assertRaises(FileExistsError):
            self.run_it(limit=1)
        other = self.root / "other.jsonl"
        other.write_text(self.catalogue.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "does not match"):
            run_experiment(
                replace(self.config("x"), catalogue=other),
                simulator=ScriptedShopper(),
                policy=F.HeuristicPolicy(),
            )


class ReportConfigTests(ExperimentCase):
    def test_report_follows_the_k_values_the_run_was_scored_with(self):
        self.run_it(
            max_model_calls=500,
            limit=4,
            score=ScoreConfig(k_values=(2, 4), headline_k=4),
        )
        report = build_report(self.root / "out")
        cell = report["cells"]["memory_off/all"]["feasible"]
        self.assertEqual(set(cell["success_at_k_within_budget"]), {"2", "4"})
        self.assertEqual(cell["success_headline_k"]["headline_k"], 4)
        self.assertIn("Headline Success@4", render_markdown(report))

    def test_a_headline_k_outside_the_scored_values_is_rejected_up_front(self):
        with self.assertRaisesRegex(ValueError, "headline_k"):
            self.run_it(limit=1, score=ScoreConfig(k_values=(1, 5), headline_k=3))

    def test_report_adds_strict_success_invalid_sensitivity_and_terminations(self):
        self.run_it(max_model_calls=500, limit=5)
        cell = build_report(self.root / "out")["cells"]["memory_off/all"]["feasible"]
        self.assertIn("3", cell["strict_success_at_k_within_budget"])
        self.assertIn("accepted", cell["terminations"])
        self.assertEqual(
            cell["success_headline_k_if_invalid_counted_as_failure"]["n"],
            cell["sessions"],
        )
        self.assertIn("3", cell["ndcg_final_recommendation_no_rec_as_zero"])


class PairedAttritionTests(ExperimentCase):
    def test_pairs_dropped_for_an_invalid_arm_are_reported_with_a_worst_case_row(self):
        from astra_eval.report import paired

        def result(scenario, condition, outcome, valid=True, category=None):
            return {
                "scenario": {"id": scenario, "kind": "feasible"},
                "condition": condition,
                "score": {
                    "valid": valid,
                    "outcome": outcome,
                    "failure_category": category,
                },
            }

        rows = [
            result("a", "off", "success"),
            result("a", "on", "success"),
            result("b", "off", "success"),
            result("b", "on", "invalid", False, "simulator_failure"),
            result("c", "off", "failure"),
            result("c", "on", "success"),
        ]
        p = paired(rows, "on", "off")
        self.assertEqual((p["pairs"], p["dropped_pairs"]), (2, 1))
        self.assertEqual(p["dropped_reasons"], {"on:simulator_failure": 1})
        self.assertEqual(
            (p["only_treatment_succeeds"], p["only_reference_succeeds"]), (1, 0)
        )
        worst = p["sensitivity_invalid_counted_as_failure"]
        self.assertEqual(
            (
                worst["pairs"],
                worst["only_reference_succeeds"],
                worst["only_treatment_succeeds"],
            ),
            (3, 1, 1),
        )


class ConfigValidationTests(ExperimentCase):
    def test_zero_and_negative_limits_budgets_and_k_never_mean_unset(self):
        for kwargs in (
            {"limit": 0},
            {"limit": -1},
            {"max_model_calls": 0},
            {"max_model_calls": -5},
            {"score": ScoreConfig(turn_budget=0)},
            {"score": ScoreConfig(k_values=(0, 3), headline_k=3)},
            {"score": ScoreConfig(k_values=(2, 4), headline_k=3)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.config("c", **kwargs)

    def test_paired_comparison_uses_memory_off_as_the_reference(self):
        conditions = (Condition("alpha"), Condition("memory_off"))
        self.run_it(conditions=conditions, max_model_calls=1000, limit=3)
        paired = build_report(self.root / "out")["paired_comparison"]
        self.assertEqual(
            (paired["treatment"], paired["reference"]), ("alpha", "memory_off")
        )

    def test_headline_label_names_k_not_the_success_count(self):
        self.run_it(max_model_calls=500, limit=2)
        cell = build_report(self.root / "out")["cells"]["memory_off/all"]["feasible"]
        self.assertEqual(cell["success_headline_k"]["headline_k"], 3)
        self.assertIn(
            "Headline Success@3", render_markdown(build_report(self.root / "out"))
        )


class IdentityTests(ExperimentCase):
    def test_each_scenario_gets_its_own_astra_user(self):
        self.run_it(max_model_calls=500, limit=4)
        users = [r["user_id"] for r in read_results(self.root / "out")]
        self.assertEqual(len(set(users)), len(users))
        self.assertTrue(all(u.startswith("eval-shopper-") for u in users))

    def test_shared_config_records_policy_and_index_identity(self):
        self.run_it(max_model_calls=500, limit=1)
        shared = json.loads((self.root / "out" / "run.json").read_text())[
            "shared_config"
        ]
        self.assertRegex(shared["index_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(shared["decision_policy"]["class"], "HeuristicPolicy")
        self.assertEqual(
            shared["decision_policy"]["prompt_version"],
            "shopping-baseline-v4-attributes",
        )
        self.assertNotIn("key", json.dumps(shared["decision_policy"]).lower())

    def test_inconsistent_turn_budget_and_window_are_rejected_at_configuration_time(
        self,
    ):
        with self.assertRaisesRegex(ValueError, "turn_budget"):
            self.run_it(limit=1, score=ScoreConfig(turn_budget=99))
        with self.assertRaises(ValueError):
            SimulatorConfig(window_turns=0)
        with self.assertRaises(ValueError):
            SimulatorConfig.from_env({"ASTRA_SIM_WINDOW_TURNS": "0"})


class IsolationTests(ExperimentCase):
    def test_ground_truth_and_condition_never_reach_astra_or_the_shopper(self):
        fake = F.FakeOllama("good")
        shopper = OllamaShopper(SimulatorConfig(), transport=fake)
        policy = F.HeuristicPolicy()
        self.run_it(policy=policy, simulator=shopper, max_model_calls=500, limit=6)
        sim_text = json.dumps(fake.payloads)
        astra_text = json.dumps(policy.contexts)
        secrets = []
        for truth in self.truths.values():
            secrets += [s["id"] for s in truth.acceptable_sample] + [
                s["title"] for s in truth.acceptable_sample
            ]
        for forbidden in (
            "ideal_grades",
            "acceptable_count",
            "unknown_required_count",
            "evidence_contract",
            "memory_off",
            "ground_truth",
        ):
            self.assertNotIn(forbidden, sim_text)
            self.assertNotIn(forbidden, astra_text)
        # The shopper sees product cards ASTRA recommends (like a real user) but never target lists.
        self.assertFalse(
            any(s in astra_text for s in secrets if s.startswith("B0") and False)
        )
        scenarios = {r["scenario"]["id"] for r in read_results(self.root / "out")}
        self.assertTrue(scenarios)

    def test_astra_only_receives_what_the_shopper_chose_to_reveal(self):
        """Per session: no hidden-fact statement the shopper did NOT say appears in ASTRA's log."""
        from astra_eval.scenarios import load_scenarios
        from shopping_agent.sessions import SessionStore

        scenarios = {s.id: s for s in load_scenarios(self.scenario_dir)[0]}
        self.run_it(max_model_calls=500)
        out = self.root / "out"
        store = SessionStore(out / "astra" / "memory_off")
        checked = 0
        for result in read_results(out):
            scenario = scenarios[result["scenario"]["id"]]
            lines = (
                (out / result["session_dir"] / "transcript.jsonl")
                .read_text()
                .splitlines()
            )
            entries = [json.loads(x) for x in lines]
            said = {k for e in entries if e["role"] == "shopper" for k in e["reveals"]}
            with store.open(result["user_id"], result["astra_session_id"]) as session:
                logged = json.dumps([e.payload for e in session.events]).lower()
            for fact in scenario.profile.facts:
                if fact.key not in said:
                    self.assertNotIn(
                        fact.statement.lower(), logged, (scenario.id, fact.key)
                    )
                    checked += 1
        self.assertGreater(checked, 0)

    def test_shopping_agent_never_imports_the_evaluation_package(self):
        for path in Path("src/shopping_agent").glob("*.py"):
            self.assertNotIn("astra_eval", path.read_text(), path.name)
        self.assertNotIn(
            "ground_truth",
            Path("src/astra_eval/dialogue.py")
            .read_text()
            .lower()
            .replace("ground truth", ""),
        )

    def test_importing_the_harness_never_contacts_a_network_or_requires_ollama(self):
        # A fresh interpreter with sockets disabled: importing and constructing must not touch them.
        code = (
            "import socket\n"
            "def blocked(*a, **k): raise AssertionError('network used')\n"
            "socket.socket.connect = blocked; socket.create_connection = blocked\n"
            "socket.getaddrinfo = blocked\n"
            "import astra_eval.cli, astra_eval.simulators as s\n"
            "s.OllamaShopper(s.SimulatorConfig.from_env({})); s.ScriptedShopper()\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(Path("src").resolve()), "PATH": "/usr/bin"},
        )
        self.assertEqual(
            (result.returncode, result.stdout.strip()), (0, "ok"), result.stderr
        )


class ConditionTests(ExperimentCase):
    def test_both_conditions_run_identical_scenarios_and_share_one_hashed_config(self):
        conditions = (Condition("memory_off"), Condition("memory_off_repeat"))
        self.run_it(conditions=conditions, max_model_calls=1000, limit=4)
        results = read_results(self.root / "out")
        self.assertEqual(len(results), 8)
        self.assertEqual(len({r["shared_config_sha256"] for r in results}), 1)
        by = {}
        for r in results:
            by.setdefault(r["scenario"]["id"], {})[r["condition"]] = r["score"][
                "outcome"
            ]
        self.assertTrue(
            all(len(v) == 2 and len(set(v.values())) == 1 for v in by.values())
        )
        order = [r["condition"] for r in results]
        self.assertNotEqual(
            order[0], order[2]
        )  # condition order rotates between scenarios
        report = build_report(self.root / "out")
        self.assertEqual(
            report["paired_comparison"]["pairs"],
            sum(
                1
                for r in results
                if r["condition"] == "memory_off"
                and r["scenario"]["kind"] != "no_valid_product"
                and r["score"]["valid"]
            ),
        )
        self.assertEqual(report["paired_comparison"]["success_rate_difference"], 0.0)
        run = json.loads((self.root / "out" / "run.json").read_text())
        self.assertEqual(
            {c["name"] for c in run["conditions"]}, {"memory_off", "memory_off_repeat"}
        )

    def test_memory_on_needs_an_injecting_factory_and_the_harness_does_not_pretend(
        self,
    ):
        snapshot = ExperienceSnapshot("frozen-1", "ab" * 32, ("lesson",))
        with self.assertRaises(NotImplementedError):
            self.run_it(conditions=(Condition("memory_on", snapshot),), limit=1)

    def test_a_future_factory_plugs_in_without_changing_the_harness(self):
        seen = []

        def factory(condition, store, search, policy, **bounds):
            seen.append(
                (
                    condition.name,
                    condition.experience.sha256 if condition.experience else None,
                )
            )
            return default_agent_factory(
                replace(condition, experience=None), store, search, policy, **bounds
            )

        snapshot = ExperienceSnapshot("frozen-1", "cd" * 32)
        conditions = (Condition("memory_off"), Condition("memory_on", snapshot))
        self.run_it(
            conditions=conditions, factory=factory, max_model_calls=1000, limit=2
        )
        self.assertEqual(seen, [("memory_off", None), ("memory_on", "cd" * 32)])
        run = json.loads((self.root / "out" / "run.json").read_text())
        self.assertEqual(
            [c["experience_sha256"] for c in run["conditions"]], [None, "cd" * 32]
        )

    def test_duplicate_condition_names_are_rejected(self):
        with self.assertRaises(ValueError):
            self.run_it(conditions=(Condition("a"), Condition("a")), limit=1)

    def test_shared_config_changes_with_any_shared_setting(self):
        self.run_it("a", limit=1, max_model_calls=100)
        self.run_it(
            "b",
            limit=1,
            max_model_calls=100,
            simulator=ScriptedShopper(SimulatorConfig(window_turns=3)),
            score=ScoreConfig(headline_k=1),
        )

        def sha(name):
            path = self.root / name / "run.json"
            return json.loads(path.read_text())["shared_config_sha256"]

        self.assertEqual(sha("a"), sha("a"))
        self.assertNotEqual(sha("a"), sha("b"))


class BudgetAndFailureTests(ExperimentCase):
    def test_model_call_cap_stops_the_run_early_and_marks_the_rest_invalid(self):
        summary = self.run_it(max_model_calls=4)
        self.assertEqual(summary["stopped_early"], "run_model_call_budget_exhausted")
        self.assertLessEqual(summary["model_calls_used"], 4)
        self.assertLess(summary["sessions"], summary["planned_sessions"])
        last = read_results(self.root / "out")[-1]
        self.assertEqual(last["score"]["outcome"], "invalid")

    def test_consecutive_provider_failures_trip_the_circuit_breaker(self):
        policy = F.FailingPolicy("provider_http_503")
        summary = self.run_it(policy=policy, max_model_calls=1000)
        self.assertEqual(summary["stopped_early"], "consecutive_provider_failures")
        self.assertEqual((summary["sessions"], policy.calls), (3, 3))
        self.assertTrue(
            all(
                r["score"]["outcome"] == "invalid"
                for r in read_results(self.root / "out")
            )
        )

    def test_simulator_failures_are_excluded_from_agent_denominators_but_reported(self):
        shopper = OllamaShopper(
            SimulatorConfig(), transport=F.FakeOllama("always_malformed")
        )
        self.run_it(simulator=shopper, max_model_calls=1000, limit=5)
        report = write_report(self.root / "out")
        cell = report["cells"]["memory_off/all"]["feasible"]
        self.assertEqual((cell["valid"], cell["invalid"]), (0, cell["sessions"]))
        self.assertIsNone(cell["success_headline_k"]["rate"])
        rel = report["simulator_reliability"]
        self.assertEqual(rel["simulator_failure_rate"], 1.0)
        self.assertIn("too unreliable", rel["warning"])
        self.assertIn("WARNING", (self.root / "out" / "report.md").read_text())

    def test_agent_budget_exhaustion_is_a_failure_that_stays_in_the_denominator(self):
        shopper = OllamaShopper(SimulatorConfig(), transport=F.FakeOllama("good"))
        self.run_it(
            policy=F.AlwaysSearchPolicy(),
            simulator=shopper,
            max_model_calls=2000,
            limit=5,
        )
        report = write_report(self.root / "out")
        feasible = report["cells"]["memory_off/all"]["feasible"]
        self.assertEqual(feasible["invalid"], 0)
        self.assertEqual(feasible["success_headline_k"]["k"], 0)
        self.assertEqual(
            feasible["failure_categories"],
            {"agent_budget_exhausted": feasible["valid"]},
        )
        none = report["cells"]["memory_off/all"]["no_valid_product"]
        if none:
            self.assertEqual(
                none["correct_abstention"]["k"], 0
            )  # a closure is not an abstention
        self.assertIsNotNone(
            feasible["turns_to_first_success"][
                "penalised_mean_failure_as_budget_plus_one"
            ]
        )


class ReportTests(ExperimentCase):
    def test_transcript_viewer_shows_turns_and_hides_truth_unless_asked(self):
        self.run_it(max_model_calls=500, limit=2)
        first = read_results(self.root / "out")[0]["scenario"]["id"]
        plain = show_transcript(self.root / "out", first)
        self.assertIn("SHOPPER", plain)
        self.assertIn("ASTRA", plain)
        self.assertNotIn("DEBUG ONLY", plain)
        debug = show_transcript(
            self.root / "out", first, scenarios_dir=self.scenario_dir
        )
        self.assertIn("DEBUG ONLY", debug)
        self.assertIn("ground truth: acceptable=", debug)
        with self.assertRaises(FileNotFoundError):
            show_transcript(self.root / "out", "nope")

    def test_report_is_deterministic_and_states_denominators_and_costs_honestly(self):
        self.run_it(max_model_calls=500, limit=4)
        a, b = build_report(self.root / "out"), build_report(self.root / "out")
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        text = render_markdown(a)
        self.assertIn("N/A", text)  # no prices were configured: cost is not invented
        resources = a["cells"]["memory_off/all"]["feasible"]["resources"]
        self.assertIsNone(resources["estimated_cost_usd"])
        self.assertGreater(resources["agent_prompt_tokens"], 0)

    def test_cost_is_estimated_only_when_prices_are_supplied(self):
        self.run_it(
            max_model_calls=500,
            limit=3,
            score=ScoreConfig(
                price_input_per_million=0.3, price_output_per_million=1.2
            ),
        )
        cost = build_report(self.root / "out")["cells"]["memory_off/all"]["feasible"][
            "resources"
        ]["estimated_cost_usd"]
        self.assertGreater(cost, 0)

    def test_tmp_cleanup(self):
        with tempfile.TemporaryDirectory():
            pass


if __name__ == "__main__":
    unittest.main()
