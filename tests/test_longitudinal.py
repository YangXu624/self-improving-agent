"""Returning users through real sessions, BM25, scorers and mocked policies only."""

import json
import tempfile
import unittest
from pathlib import Path

from longitudinal_fixtures import MemoryPolicy, make_dataset

from astra_eval.longitudinal import (
    LongitudinalConfig,
    plan_longitudinal,
    run_longitudinal,
)
from astra_eval.simulators import ScriptedShopper, SimulatorError
from shopping_agent.provider import ProviderError
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore


class CapturingShopper(ScriptedShopper):
    def __init__(self):
        super().__init__()
        self.memories = []

    def respond(self, memory, view, feedback=()):
        self.memories.append(memory)
        return super().respond(memory, view, feedback)


class LongitudinalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.catalogue, self.index, self.data = make_dataset(self.root)

    def config(self, name="run", **kwargs):
        return LongitudinalConfig(
            customers=self.source,
            catalogue=self.catalogue,
            index=self.index,
            output=self.root / name,
            **kwargs,
        )

    def run_it(self, config=None, policy=None):
        self.configured = config or self.config()
        self.policy, self.shopper = policy or MemoryPolicy(), CapturingShopper()
        self.summary = run_longitudinal(
            self.configured, simulator=self.shopper, policy=self.policy
        )
        self.rows = [
            json.loads(line)
            for line in (self.configured.output / "results.jsonl")
            .read_text()
            .splitlines()
        ]
        return self.summary

    def events(self, row):
        root = self.configured.output / "astra" / row["condition"] / "sessions"
        with SessionStore(root).open(
            row["user_id"], row["astra_session_id"]
        ) as session:
            return list(session.events)

    def test_a_b_c_stable_owner_distinct_sessions_natural_recall_and_off(self):
        self.run_it()
        self.assertEqual(len(self.rows), 8)
        self.assertEqual({r["user_id"] for r in self.rows}, {"alice"})
        self.assertEqual(len({r["astra_session_id"] for r in self.rows}), 8)
        for row in self.rows:
            events = self.events(row)
            prompts = [
                json.loads(e.payload["messages"][-1]["content"])
                for e in events
                if e.type == "model_request"
            ]
            if row["condition"] == "user_memory_off":
                self.assertTrue(all("user_memory" not in p for p in prompts))
            elif row["sequence"] == 1:
                self.assertEqual(prompts[0]["user_memory"]["records"], [])
            elif row["sequence"] == 2:
                self.assertEqual(
                    prompts[0]["user_memory"]["records"][0]["value"], "Blue"
                )
                self.assertNotIn("Blue", prompts[0]["current_user_message"])
        self.assertFalse(
            (self.configured.output / "astra/user_memory_off/user-memory").exists()
        )

    def test_d_condition_and_customer_isolation(self):
        other_root = self.root / "two-customers"
        other_root.mkdir()
        self.source, self.catalogue, self.index, self.data = make_dataset(
            other_root, second_customer=True
        )
        self.run_it()
        self.assertEqual(self.summary["sessions"], 16)
        root = self.configured.output / "astra/user_memory_on/user-memory"
        store = UserMemoryStore(root)
        profiles = [store.read(user) for user in ("alice", "bob")]
        source_sets = [{r.source_session_id for r in p.records} for p in profiles]
        self.assertTrue(source_sets[0].isdisjoint(source_sets[1]))
        for user, profile in zip(("alice", "bob"), profiles, strict=True):
            owners = {
                r["astra_session_id"] for r in self.rows if r["customer_id"] == user
            }
            self.assertTrue({r.source_session_id for r in profile.records} <= owners)
        order = [(r["customer_id"], r["condition"], r["sequence"]) for r in self.rows]
        self.assertEqual(order[0], ("alice", "user_memory_off", 1))
        self.assertEqual(order[8], ("bob", "user_memory_on", 1))

    def test_e_current_persona_only_no_future_or_private_prompt_leak(self):
        self.run_it()
        self.assertTrue(self.shopper.memories)
        for memory in self.shopper.memories:
            context = memory.private_context
            sequence = int(context["current_goal"].split()[-1])
            self.assertEqual(
                context["background"],
                "private-current-background"
                if sequence < 3
                else "private-future-change",
            )
            self.assertNotIn("witness_id", memory.system_prompt())
            self.assertNotIn("future", str(context) if sequence < 3 else "")
        for row in self.rows:
            for event in self.events(row):
                if event.type == "model_request":
                    self.assertNotIn("private-current-background", str(event.payload))
                    self.assertNotIn("private-future-change", str(event.payload))
                    self.assertNotIn(
                        "current_persistent_preferences", str(event.payload)
                    )

    def test_f_g_correction_gift_and_existing_catalogue_scores(self):
        self.run_it()
        profile = UserMemoryStore(
            self.configured.output / "astra/user_memory_on/user-memory"
        ).read("alice")
        self.assertEqual(
            [(r.value, r.status) for r in profile.records],
            [("Blue", "superseded"), ("Red", "active")],
        )
        self.assertTrue(all(r.category != "purchase" for r in profile.records))
        gifts = [r for r in self.rows if r["sequence"] == 4]
        self.assertTrue(all(not r["user_memory"]["updates"] for r in gifts))
        for row in self.rows:
            self.assertEqual(row["disclosed_requirement_compliance"]["violations"], 0)
            self.assertIn("ndcg_first", row["suitability"].get("metrics", {}))
            if row["evaluation_mode"] == "target_item":
                self.assertEqual(row["termination"], "target_found")
                self.assertTrue(row["score"]["hit_at_k"])
        flags = [f["type"] for r in self.rows for f in r["user_memory"]["flags"]]
        self.assertIn("outdated_record_injected", flags)
        self.assertIn("recipient_inapplicable_record_injected", flags)
        self.assertIn("potential_incorrect_reuse", flags)

    def test_i_outputs_and_j_reproducible_inputs(self):
        self.run_it()
        first = json.loads((self.configured.output / "run.json").read_text())
        self.assertEqual(
            (self.configured.output / "customers.frozen.json").read_bytes(),
            self.source.read_bytes(),
        )
        report = json.loads((self.configured.output / "report.json").read_text())
        self.assertEqual(report["started_sessions"], 8)
        self.assertEqual(len(report["pairs"]), 4)
        self.assertTrue(all(p["complete"] for p in report["pairs"]))
        self.assertEqual(set(report["customers"]), {"alice"})
        for row in self.rows:
            self.assertTrue(
                all(
                    k in row
                    for k in (
                        "customer_id",
                        "task_id",
                        "sequence",
                        "astra_session_id",
                        "condition",
                        "termination",
                    )
                )
            )
            directory = self.configured.output / row["session_dir"]
            self.assertTrue(
                all(
                    (directory / p).exists()
                    for p in ("result.json", "trace.json", "transcript.jsonl")
                )
            )
        self.run_it(self.config("again"))
        second = json.loads((self.configured.output / "run.json").read_text())
        self.assertEqual(first["shared_config_sha256"], second["shared_config_sha256"])
        self.assertTrue(
            all(
                not c["procedural_memory"]
                for c in first["shared_config"]["plan"]["conditions"]
            )
        )

    def test_invalid_prior_session_blocks_later_timeline(self):
        class BrokenPolicy:
            def complete(self, messages):
                raise ProviderError("provider_fixture_failure")

        self.run_it(policy=BrokenPolicy())
        self.assertEqual(self.summary["sessions"], 2)
        self.assertEqual(len(self.summary["blocked_visits"]), 6)
        self.assertTrue(all(r["termination"] == "provider_error" for r in self.rows))
        report = json.loads((self.configured.output / "report.json").read_text())
        self.assertEqual(sum(p["complete"] for p in report["pairs"]), 1)

    def test_budget_plan_and_refusal_to_overwrite(self):
        config = self.config(max_model_calls=3)
        plan = plan_longitudinal(config)
        self.assertEqual(plan["sessions"], 8)
        self.assertEqual(plan["worst_case_agent_model_calls"], 144)
        self.assertFalse(config.output.exists())
        self.run_it(config)
        self.assertLessEqual(self.summary["model_calls_used"], 3)
        self.assertEqual(
            self.summary["stopped_early"], "run_model_call_budget_exhausted"
        )
        with self.assertRaises(FileExistsError):
            self.run_it(config)

    def test_off_then_on_completes_all_off_timelines_before_on(self):
        other = self.root / "phase-fixture"
        other.mkdir()
        self.source, self.catalogue, self.index, self.data = make_dataset(
            other, second_customer=True
        )
        config = self.config(execution_order="off_then_on", stop_on_error=True)
        plan = plan_longitudinal(config)
        self.assertEqual(plan["execution_order"], "off_then_on")
        self.assertEqual(
            plan["timeline_order"],
            [
                {"customer_id": user, "condition": condition}
                for condition in ("user_memory_off", "user_memory_on")
                for user in ("alice", "bob")
            ],
        )
        self.run_it(config)
        self.assertEqual(
            [(r["customer_id"], r["condition"], r["sequence"]) for r in self.rows],
            [
                (user, condition, sequence)
                for condition in ("user_memory_off", "user_memory_on")
                for user in ("alice", "bob")
                for sequence in range(1, 5)
            ],
        )
        self.assertIsNone(self.summary["stopped_early"])
        # ON's first request sees an empty owner profile after every OFF session.
        for row in self.rows:
            if row["condition"] == "user_memory_on" and row["sequence"] == 1:
                prompt = next(e for e in self.events(row) if e.type == "model_request")
                sent = json.loads(prompt.payload["messages"][-1]["content"])
                self.assertEqual(sent["user_memory"]["records"], [])

    def test_stop_on_provider_error_does_not_start_on_phase(self):
        class BrokenPolicy:
            def complete(self, messages):
                raise ProviderError("provider_fixture_failure")

        self.run_it(
            self.config(execution_order="off_then_on", stop_on_error=True),
            policy=BrokenPolicy(),
        )
        self.assertEqual(self.summary["sessions"], 1)
        self.assertEqual(self.summary["stopped_early"], "session_error:provider_error")
        self.assertTrue(all(r["condition"] == "user_memory_off" for r in self.rows))

    def test_execution_order_is_validated(self):
        with self.assertRaisesRegex(ValueError, "execution order"):
            self.config(execution_order="interleaved-typo")

    def test_stop_on_simulator_error_preserves_partial_session(self):
        class BrokenShopper(ScriptedShopper):
            def respond(self, memory, view, feedback=()):
                raise SimulatorError("simulator_fixture_failure")

        config = self.config(execution_order="off_then_on", stop_on_error=True)
        summary = run_longitudinal(
            config, simulator=BrokenShopper(), policy=MemoryPolicy()
        )
        self.assertEqual(summary["sessions"], 1)
        self.assertEqual(summary["stopped_early"], "session_error:simulator_failure")
        rows = [
            json.loads(line)
            for line in (config.output / "results.jsonl").read_text().splitlines()
        ]
        self.assertEqual(rows[0]["condition"], "user_memory_off")
        path = config.output / rows[0]["session_dir"]
        self.assertTrue((path / "transcript.jsonl").exists())
        self.assertTrue((path / "trace.json").exists())
