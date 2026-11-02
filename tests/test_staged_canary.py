"""Offline orchestration checks; transport and ASTRA policy are deterministic fixtures."""

import contextlib
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from longitudinal_fixtures import make_dataset
from test_compact_memory_evaluation import CompactPolicy

from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy
from astra_eval.shopper_providers import JsonShopperProvider, RequestJournal
from astra_eval.shopper_v3 import AutonomousShopper
from experiments.longitudinal import staged_canary as C


class CanaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.catalogue, self.index, _ = make_dataset(
            self.root, second_customer=True
        )
        self.prior = self.root / "previous.jsonl"
        C.write(self.prior, {"accounted_usd": str(C.BASELINE)})
        # A ledger is JSONL, not pretty-printed JSON.
        self.prior.write_text(json.dumps({"accounted_usd": str(C.BASELINE)}) + "\n")
        self.addCleanup(patch.stopall)
        patch.object(C, "PRIOR_LEDGER", self.prior).start()
        patch(
            "urllib.request.urlopen", side_effect=AssertionError("No live calls")
        ).start()
        patch(
            "shopping_agent.provider.urlopen",
            side_effect=AssertionError("No live calls"),
        ).start()
        self.output = self.root / "canary"
        self.manifest = C.prepare(
            self.output,
            self.source,
            self.catalogue,
            self.index,
            stage1_ids=("alice", "bob"),
            memory_id="alice",
        )

    def cfg(self, stage="stage1", prior=C.BASELINE):
        return C.config(self.output, stage, prior, self.manifest)

    def dry(self, stage):
        captured = io.StringIO()
        with patch.object(C, "providers", side_effect=AssertionError("No providers")):
            with contextlib.redirect_stdout(captured):
                C.main([stage, "--root", str(self.output)])
        return json.loads(captured.getvalue())

    def test_fixtures_are_exact_prefixes_with_unchanged_evidence(self):
        source = json.loads(self.source.read_text())
        self.assertEqual(C.file_hash(self.source), self.manifest["source_sha256"])
        for stage, count in [("stage1", 1), ("stage2", 2)]:
            derived = json.loads((self.output / f"{stage}.customers.json").read_text())
            for customer in derived["customers"]:
                original = next(
                    c
                    for c in source["customers"]
                    if c["user_id"] == customer["user_id"]
                )
                self.assertEqual(customer["visits"], original["visits"][:count])
                self.assertEqual(customer["preferences"], original["preferences"])
                self.assertFalse(customer["changes"])
        with self.assertRaises(FileExistsError):
            C.prepare(self.output, self.source, self.catalogue, self.index)

    def test_dry_plans_exact_session_counts_no_providers_or_stores(self):
        first, second = self.dry("stage1"), self.dry("stage2")
        self.assertEqual(first["plan"]["sessions"], 2)
        self.assertEqual(first["plan"]["worst_case_agent_model_calls"], 36)
        self.assertEqual(
            first["plan"]["condition_order"],
            {"alice": ["user_memory_off"], "bob": ["user_memory_off"]},
        )
        self.assertEqual(second["plan"]["sessions"], 4)
        self.assertEqual(
            second["plan"]["condition_order"],
            {"alice": ["user_memory_off", "user_memory_on"]},
        )
        self.assertTrue(second["prior_cost_provisional_until_stage1_completed"])
        self.assertFalse((self.output / "stage1").exists())
        self.assertFalse((self.output / "stage2").exists())

    def test_stage2_live_requires_review_before_credentials(self):
        with patch.object(C, "providers", side_effect=AssertionError("No provider")):
            with self.assertRaisesRegex(ValueError, "passing Stage 1 review"):
                C.main(["stage2", "--root", str(self.output), "--live"])

    def test_original_input_and_accounting_mutation_block_launch(self):
        self.prior.write_text(self.prior.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Prior accounting changed"):
            C.validated(self.output)
        self.prior.write_text(json.dumps({"accounted_usd": str(C.BASELINE)}) + "\n")
        self.source.write_text(self.source.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "Frozen input changed"):
            C.validated(self.output)

    def test_runtime_mutation_blocks_launch(self):
        with patch.object(C, "fingerprint", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "Runtime changed"):
                C.validated(self.output)

    def run_stage1(self, *, invalid_first=False, text_only=False, unknown_usage=False):
        cfg = self.cfg()
        budget = ApiCostBudget(
            self.output / "stage1.api-cost.jsonl", cfg.max_cost_usd, cfg.prior_cost_usd
        )
        calls = []

        def transport(url, payload, headers, timeout):
            calls.append(payload)
            if invalid_first and len(calls) <= 2:
                reply = json.dumps(
                    {"message": "I need boots under $999999.", "action": "reply"}
                )
            else:
                reply = json.dumps(
                    {
                        "message": "I need boots under $60."
                        if len(calls) % 2
                        else "Thanks, I'm done shopping.",
                        "action": "reply" if len(calls) % 2 else "give_up",
                    }
                )
            return {
                "model": C.MODELS["shopper"],
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": reply}],
                "usage": {
                    "input_tokens": None if unknown_usage else 20,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            }

        class Policy(CompactPolicy):
            model = C.MODELS["astra"]

            def complete(self, messages):
                if text_only:
                    from test_compact_memory_agent import decision

                    from shopping_agent.provider import PolicyReply

                    return PolicyReply(
                        json.dumps(
                            decision(
                                {"type": "RESPOND", "message": "Please tell me more."}
                            )
                        ),
                        {
                            "usage": {
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                                "prompt_cache_hit_tokens": 0,
                            }
                        },
                    )
                result = super().complete(messages)
                result.metadata["usage"]["prompt_cache_hit_tokens"] = 0
                return result

        shopper = AutonomousShopper(
            JsonShopperProvider(
                cfg.simulator,
                RequestJournal(
                    self.output / "stage1.shopper-v3.jsonl", cfg.max_shopper_calls
                ),
                api_key="fixture",
                transport=transport,
                cost_budget=budget,
            )
        )
        policy = BudgetedPolicy(Policy(), budget)
        return C.reliability(cfg, shopper, policy)

    def receipt(self):
        review = self.output / "stage1-review.json"
        C.write(
            review,
            {
                "decision": "pass",
                "summary_sha256": C.file_hash(self.output / "stage1/summary.json"),
                "ledger_sha256": C.file_hash(self.output / "stage1.api-cost.jsonl"),
            },
        )
        return review

    def test_two_real_loops_are_off_only_with_separate_sessions_and_known_costs(self):
        summary = self.run_stage1()
        self.assertEqual(len(summary["results"]), 2)
        self.assertFalse(summary["systemic_stop"])
        self.assertTrue(all(r["score"]["valid"] for r in summary["results"]))
        self.assertEqual(len({r["session_id"] for r in summary["results"]}), 2)
        self.assertEqual(
            {r["condition"] for r in summary["results"]}, {"user_memory_off"}
        )
        self.assertFalse(list((self.output / "stage1").rglob("*profile*")))
        actual = C.stage1_end(self.output, self.receipt())
        self.assertGreater(actual, C.BASELINE)
        second = self.cfg("stage2", actual)
        self.assertEqual(Decimal(str(second.prior_cost_usd)), actual)
        self.assertEqual(Decimal(str(second.max_cost_usd)), C.BASELINE + 1)
        self.assertLess(second.max_cost_usd, 10)

    def test_valid_unsuccessful_session_is_scored_not_invalidated(self):
        summary = self.run_stage1(text_only=True)
        self.assertEqual(len(summary["results"]), 2)
        for row in summary["results"]:
            self.assertTrue(row["score"]["valid"])
            self.assertEqual(
                row["score"]["metrics"]["success_at_k_within_budget"]["5"], 0
            )

    def test_isolated_invalid_session_does_not_skip_independent_customer(self):
        summary = self.run_stage1(invalid_first=True)
        self.assertEqual(len(summary["results"]), 2)
        self.assertFalse(summary["systemic_stop"])
        self.assertFalse(summary["results"][0]["score"]["valid"])
        self.assertTrue(summary["results"][1]["score"]["valid"])
        with self.assertRaisesRegex(ValueError, "failed reliability"):
            C.stage1_end(self.output, self.receipt())

    def test_review_is_bound_to_evidence_and_unknown_cost_blocks_next_stage(self):
        self.run_stage1()
        review = self.receipt()
        with (self.output / "stage1.api-cost.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {
                        "kind": "usage_unknown_reservation_retained",
                        "accounted_usd": "0.2",
                    }
                )
                + "\n"
            )
        with self.assertRaisesRegex(ValueError, "evidence-bound"):
            C.stage1_end(self.output, review)
        with self.assertRaisesRegex(ValueError, "accounting is incomplete"):
            C.stage1_end(self.output, self.receipt())

    def test_unknown_cost_stops_before_independent_session(self):
        summary = self.run_stage1(unknown_usage=True)
        self.assertEqual(len(summary["results"]), 1)
        self.assertEqual(summary["results"][0]["failure_scope"], "infrastructure")
        self.assertTrue(summary["systemic_stop"])
        with self.assertRaisesRegex(ValueError, "failed reliability"):
            C.stage1_end(self.output, self.receipt())

    def test_stage1_budget_and_model_caps_are_fixed(self):
        first, second = self.cfg(), self.cfg("stage2")
        self.assertEqual(first.max_cost_usd, float(C.BASELINE + C.STAGE1_ALLOWANCE))
        self.assertEqual((first.max_model_calls, first.max_shopper_calls), (36, 24))
        self.assertEqual((second.max_model_calls, second.max_shopper_calls), (72, 48))
        self.assertEqual(first.simulator, second.simulator)
        self.assertEqual(first.simulator.claude_thinking, "between_tools")
        self.assertIsNone(first.simulator.temperature)
