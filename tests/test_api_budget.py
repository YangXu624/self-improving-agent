"""Shared evaluation cost controls with mock transports/policies only."""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy, CostLimitError
from astra_eval.shopper_providers import JsonShopperProvider, RequestJournal, V3Config
from astra_eval.simulators import SimulatorError
from shopping_agent.provider import PolicyReply, ProviderError


class BudgetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def budget(self, amount=1, prior=0):
        return ApiCostBudget(self.root / "cost.jsonl", amount, prior)

    def test_shared_providers_reserve_reconcile_and_keep_prior_uncertainty(self):
        budget = self.budget(prior="0.05")
        a = budget.reserve("claude", "claude-sonnet-5-5", {"messages": ["hello"]}, 512)
        c = budget.settle(
            a,
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cache_read_tokens": 30,
                "cache_write_tokens": 10,
            },
        )
        self.assertEqual(c, Decimal("0.000443"))
        b = budget.reserve("deepseek", "deepseek-flash", {"messages": ["world"]}, 2000)
        d = budget.settle(
            b,
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 50,
            },
        )
        self.assertEqual(d, Decimal("0.0000393"))
        self.assertEqual(budget.total, Decimal("0.05") + c + d)
        self.assertFalse(budget.blocked)
        self.assertEqual(
            [json.loads(r)["kind"] for r in budget.path.read_text().splitlines()],
            [
                "budget_open",
                "request_reserved",
                "usage_settled",
                "request_reserved",
                "usage_settled",
            ],
        )

    def test_insufficient_funds_denies_before_transport_and_no_call_is_charged(self):
        budget = self.budget("0.001")
        sent = []
        journal = RequestJournal(self.root / "shopper.jsonl", 2)
        provider = JsonShopperProvider(
            V3Config(provider="claude", model="claude-sonnet-5-5"),
            journal,
            api_key="fixture",
            cost_budget=budget,
            transport=lambda *args: sent.append(args),
        )
        with self.assertRaisesRegex(SimulatorError, "spending_budget_exhausted"):
            provider.complete([{"content": "system"}, {"content": "user"}], {}, {})
        self.assertEqual(journal.calls, 0)
        self.assertFalse(sent)
        self.assertEqual(budget.total, 0)
        self.assertTrue(budget.blocked)

    def test_missing_usage_retains_reservation_and_blocks_future_spending(self):
        budget = self.budget()
        r = budget.reserve("claude", "claude-sonnet-5-5", {}, 512)
        held = budget.total
        with self.assertRaisesRegex(CostLimitError, "usage_unknown"):
            budget.settle(r, {"prompt_tokens": 5, "completion_tokens": 10})
        self.assertEqual(budget.total, held)
        self.assertTrue(budget.blocked)
        with self.assertRaises(CostLimitError):
            budget.reserve("deepseek", "deepseek-flash", {}, 2000)
        self.assertIn("usage_unknown_reservation_retained", budget.path.read_text())

    def test_transport_failure_keeps_allowance_with_no_zero_usage_invention(self):
        budget = self.budget()

        def fail(*args):
            raise OSError("sensitive-fixture")

        journal = RequestJournal(self.root / "shopper.jsonl", 1)
        provider = JsonShopperProvider(
            V3Config(provider="claude", model="claude-sonnet-5-5"),
            journal,
            api_key="fixture",
            cost_budget=budget,
            transport=fail,
        )
        with self.assertRaises(SimulatorError):
            provider.complete([{"content": "system"}, {"content": "user"}], {}, {})
        self.assertTrue(budget.blocked)
        self.assertGreater(budget.total, 0)
        self.assertNotIn("sensitive-fixture", budget.path.read_text())
        self.assertNotIn("prompt_tokens", provider.usage)
        self.assertEqual(journal.calls, 1)

    def test_nonfinite_limits_and_unsupported_model_fail_closed(self):
        for amount in ("nan", "inf", "-1", "0"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.budget(amount)
        with self.assertRaises(ValueError):
            self.budget(1, prior=1)
        budget = self.budget()
        with self.assertRaisesRegex(CostLimitError, "rates_not_verified"):
            budget.reserve("claude", "claude-unverified", {}, 512)
        with self.assertRaises(FileExistsError):
            self.budget()

    def test_accounting_bound_violation_stops_instead_of_silently_undercounting(self):
        budget = self.budget()
        r = budget.reserve("deepseek", "deepseek-flash", {}, 5)
        with self.assertRaisesRegex(CostLimitError, "exceeds_reserved"):
            budget.settle(r, {"prompt_tokens": 50, "completion_tokens": 6})
        self.assertTrue(budget.blocked)
        self.assertEqual(budget.total, Decimal(r["reserved_usd"]))

    def test_deepseek_delegate_gets_identical_messages_and_unknowns_are_errors(self):
        class Policy:
            model = "deepseek-flash"

            def complete(self, messages):
                self.seen = messages
                return PolicyReply(
                    "original", {"usage": {"prompt_tokens": 20, "completion_tokens": 5}}
                )

        budget = self.budget()
        base = Policy()
        policy = BudgetedPolicy(base, budget)
        messages = [{"role": "user", "content": "original text"}]
        result = policy.complete(messages)
        self.assertIs(base.seen, messages)
        self.assertEqual(result.content, "original")
        base.complete = lambda messages: PolicyReply("{}", {"usage": {}})
        with self.assertRaisesRegex(ProviderError, "cost_usage_unknown"):
            policy.complete(messages)
        self.assertTrue(budget.blocked)
