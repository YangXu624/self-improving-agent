"""Autonomous shopper acceptance and evidence tests: mocked models, real baseline tools."""

import json
import unittest
from unittest.mock import patch

import eval_fixtures as F
from longitudinal_fixtures import make_dataset
from test_eval_dialogue import BUDGET, COLOR, TYPE, scenario

from astra_eval.cli import main
from astra_eval.dialogue import DialogueRunner, card
from astra_eval.experiment import ModelCallBudget
from astra_eval.longitudinal import LongitudinalConfig, run_longitudinal
from astra_eval.memory import AssistantView, ContextBudgetError, ShopperMemory
from astra_eval.shopper_evidence import derive_disclosures
from astra_eval.shopper_providers import JsonShopperProvider, RequestJournal, V3Config
from astra_eval.shopper_v3 import AutonomousShopper, NaturalReply
from astra_eval.target_scoring import TargetRule
from shopping_agent.agent import ShoppingAgent


def profile(*facts):
    return scenario(facts, [], "FROZEN OPENING MUST NOT BECOME A TEMPLATE").profile


class EvidenceTests(unittest.TestCase):
    def test_budget_paraphrase_number_words_and_actual_evidence_span(self):
        fact = BUDGET.model_copy(update={"value": 70.0})
        text = "Hi! Please keep it below seventy dollars. Thanks."
        result = derive_disclosures(text, profile(fact))
        self.assertEqual(result.verified, ("budget",))
        span = result.observations[0]["evidence"]
        self.assertEqual(text[span["start"] : span["end"]], span["text"])
        self.assertFalse(result.violations)

    def test_natural_plural_colour_and_negative_evidence(self):
        grey = COLOR.model_copy(update={"value": "Grey"})
        negative = COLOR.model_copy(update={"value": "Blue", "op": "neq"})
        for text, facts, expected in [
            ("I'm looking for boots in gray.", [TYPE, grey], {"type", "color"}),
            ("I want boots without blue.", [TYPE, negative], {"type", "color"}),
        ]:
            with self.subTest(text=text):
                result = derive_disclosures(text, profile(*facts))
                self.assertEqual(set(result.verified), expected)
                self.assertFalse(result.violations)

    def test_known_contradictions_and_unsupported_requirements_are_rejected(self):
        for text, facts in [
            ("I need to spend over $50.", [BUDGET]),
            ("My budget is under $90.", [BUDGET]),
            ("I prefer blue.", [COLOR]),
            ("I don't want red.", [COLOR]),
            ("I want leather boots.", [TYPE]),
        ]:
            with self.subTest(text=text):
                self.assertTrue(derive_disclosures(text, profile(*facts)).violations)

    def test_product_questions_are_not_user_preferences(self):
        result = derive_disclosures("Are those boots red?", profile(TYPE, COLOR))
        self.assertEqual(result.verified, ())
        self.assertTrue(all(o["status"] == "unverified" for o in result.observations))
        self.assertFalse(result.violations)

    def test_unknown_paraphrase_is_explicitly_unverified_not_fabricated(self):
        result = derive_disclosures(
            "Something in a fiery shade would suit me.", profile(COLOR)
        )
        self.assertEqual(result.verified, ())
        self.assertEqual(result.observations[0]["status"], "unverified")
        self.assertFalse(result.violations)

    def test_private_identity_leak_remains_an_error(self):
        result = derive_disclosures(
            "I want B000000001.", profile(TYPE), forbidden=("B000000001",)
        )
        self.assertIn("target_leak", [v.code for v in result.violations])

    def test_budget_operator_phrases_are_not_misread_by_substring(self):
        for phrase, op in [
            ("no less than", "gte"),
            ("no more than", "lte"),
            ("less than", "lt"),
            ("more than", "gt"),
        ]:
            with self.subTest(phrase=phrase):
                fact = BUDGET.model_copy(update={"op": op})
                result = derive_disclosures(
                    f"I need to spend {phrase} fifty dollars.", profile(fact)
                )
                self.assertEqual(result.verified, ("budget",))
                self.assertFalse(result.violations)

    def test_declining_a_known_preference_is_a_contradiction(self):
        result = derive_disclosures(
            "I do not have a strong preference.",
            profile(COLOR),
            assistant_text="Any colour preference?",
        )
        self.assertIn("contradicts_profile", [v.code for v in result.violations])

    def test_model_disclosure_labels_are_not_accepted(self):
        with self.assertRaises(ValueError):
            NaturalReply.model_validate(
                {"message": "Boots please.", "action": "reply", "reveals": ["type"]}
            )


class AutonomousTests(F.EvalCase):
    def shopper(self, replies, *, provider="ollama", cap=20, **settings):
        self.requests = []
        outputs = iter(replies)

        def transport(url, payload, headers, timeout):
            self.requests.append(payload)
            raw = next(outputs)
            content = raw if isinstance(raw, str) else json.dumps(raw)
            if provider == "claude":
                return {
                    "content": [{"type": "text", "text": content}],
                    "stop_reason": "end_turn",
                    "model": "claude-fixture",
                    "usage": {"input_tokens": 20, "output_tokens": 5},
                }
            return {
                "message": {"content": content},
                "prompt_eval_count": 20,
                "eval_count": 5,
            }

        name = f"provider-{len(list(self.root.glob('provider-*')))}.jsonl"
        self.journal = RequestJournal(self.root / name, cap)
        config = V3Config(
            provider=provider,
            model="claude-fixture" if provider == "claude" else "fixture-local",
            **settings,
        )
        return AutonomousShopper(
            JsonShopperProvider(
                config,
                self.journal,
                api_key="fixture" if provider == "claude" else None,
                transport=transport,
            )
        )

    @staticmethod
    def reply(text, action="reply"):
        return {"message": text, "action": action}

    def runner(self, shopper, policy=None, **kwargs):
        self.policy = policy or F.HeuristicPolicy(ask_department=False)
        return DialogueRunner(
            ShoppingAgent(self.store, self.search, self.policy),
            self.store,
            shopper,
            run_id="v3-test",
            **kwargs,
        )

    def bind(self, shopper, *, owner="alice", condition="off"):
        shopper.start_session(owner, condition, "opaque-session")

    def test_typed_view_excludes_templates_private_ids_future_and_conditions(self):
        poisoned = TYPE.model_copy(
            update={"key": "SECRET-FACT-ID", "statement": "CANNED-SENTENCE"}
        )
        memory = ShopperMemory(
            profile(poisoned),
            private_context={
                "background": "Likes practical shopping.",
                "current_goal": "Find boots.",
                "recipient": "gift",
                "future_visits": "SECRET-FUTURE",
                "target_id": "SECRET-TARGET",
                "persistent_preferences": "SECRET-IRRELEVANT",
            },
        )
        shopper = self.shopper([])
        self.bind(shopper, condition="SECRET-CONDITION")
        messages, _ = shopper.build_messages(memory, AssistantView("", turn=0))
        encoded = json.dumps(messages)
        for secret in (
            "SECRET-FACT-ID",
            "CANNED-SENTENCE",
            "SECRET-TARGET",
            "SECRET-FUTURE",
            "SECRET-CONDITION",
            "SECRET-IRRELEVANT",
            "what_you_would_say",
            '"reveals"',
        ):
            self.assertNotIn(secret, encoded)
        user = json.loads(messages[1]["content"])
        self.assertEqual(user["verified_needs"][0]["value"], "boots")
        self.assertTrue(user["opening_request"])
        self.assertEqual(user["situation"]["recipient"], "gift")

    def test_generated_opening_drives_real_bm25_not_frozen_template(self):
        shopper = self.shopper(
            [
                self.reply("I need boots under $50."),
                self.reply("The first option works for me.", "accept"),
            ]
        )
        record = self.runner(shopper).run(
            scenario([TYPE, BUDGET], [], "FROZEN OPENING")
        )
        self.assertEqual(record.termination, "accepted")
        self.assertEqual(len(record.turns), 1)
        self.assertEqual(record.turns[0].action, "RECOMMEND")
        self.assertTrue(record.turns[0].recommended_ids)
        accepted = [e for e in record.transcript if e["role"] == "shopper"]
        self.assertEqual(accepted[0]["text"], "I need boots under $50.")
        self.assertEqual(set(accepted[0]["reveals"]), {"type", "budget"})
        self.assertNotIn("FROZEN OPENING", json.dumps(self.requests))
        self.assertEqual(record.simulator["attempts"], 2)
        self.assertEqual(record.simulator["usage"]["prompt_tokens"], 40)

    def test_target_found_stops_before_next_shopper_call(self):
        shopper = self.shopper([self.reply("I need boots under $50.")])
        # Resolve the deterministic fixture's presented order with a separate baseline run.
        probe = self.runner(
            self.shopper(
                [self.reply("I need boots under $50."), self.reply("Thanks.", "accept")]
            )
        ).run(scenario([TYPE, BUDGET], [], "unused"))
        target = probe.turns[0].presented_ids[0]
        record = self.runner(shopper).run(
            scenario([TYPE, BUDGET], [], "unused"), target_rule=TargetRule(target)
        )
        self.assertEqual(record.termination, "target_found")
        self.assertEqual(record.target_hit["rank"], 1)
        self.assertEqual(shopper.provider.journal.calls, 1)

    def test_rejected_contradiction_gets_generic_feedback_not_canned_sentence(self):
        shopper = self.shopper(
            [
                self.reply("I need boots under $90."),
                self.reply("I need boots under $50."),
                self.reply("Thanks.", "accept"),
            ]
        )
        record = self.runner(shopper).run(scenario([TYPE, BUDGET], [], "unused"))
        self.assertEqual(record.termination, "accepted")
        second = json.loads(self.requests[1]["messages"][1]["content"])
        self.assertTrue(second["validation_feedback"])
        self.assertNotIn(BUDGET.statement, json.dumps(second))
        self.assertFalse(second["current_dialogue"])
        self.assertEqual(record.simulator["attempts"], 3)
        self.assertEqual(
            len([e for e in record.transcript if e["role"] == "shopper"]), 2
        )

    def test_malformed_opening_never_reaches_astra_and_is_fully_journaled(self):
        shopper = self.shopper(['{"message":"boots","reveals":[],"action":"reply"}'])
        record = self.runner(shopper).run(scenario([TYPE], [], "unused"))
        self.assertEqual(record.termination, "simulator_failure")
        self.assertFalse(record.turns)
        self.assertEqual(record.simulator["calls"], 1)
        self.assertEqual(record.simulator["usage"]["prompt_tokens"], 20)
        self.assertFalse(shopper.history)
        self.assertIn("provider_response", self.journal.path.read_text())

    def test_accept_without_products_and_budget_exhaustion_fail_closed(self):
        shopper = self.shopper(
            [self.reply("I choose the first option.", "accept")], cap=1
        )
        record = self.runner(shopper).run(scenario([TYPE], [], "unused"))
        self.assertEqual(record.termination, "simulator_failure")
        self.assertIn("shopper_call_budget_exhausted", record.error)
        self.assertFalse(record.turns)
        self.assertEqual(record.simulator["calls"], 1)

    def test_actual_history_isolated_by_owner_and_arm_and_current_truth_updated(self):
        shopper = self.shopper([])
        old = ShopperMemory(profile(COLOR))
        old.record_shopper(1, "I used to prefer red.")
        old.record_assistant(
            AssistantView(
                "These were shown.",
                products=(
                    {"id": "PRIVATE-PRODUCT-ID", "title": "Shown boots", "price": 20},
                ),
            )
        )
        self.bind(shopper)
        shopper.finish_session(old, "max_turns")
        current = ShopperMemory(profile(COLOR.model_copy(update={"value": "Blue"})))
        self.bind(shopper)
        messages, _ = shopper.build_messages(current, AssistantView("", turn=0))
        user = json.loads(messages[1]["content"])
        self.assertIn("used to prefer red", json.dumps(user["prior_visits"]))
        self.assertEqual(user["verified_needs"][0]["value"], "Blue")
        self.assertNotIn("PRIVATE-PRODUCT-ID", json.dumps(messages))
        shopper.finish_session(current, "simulator_error")
        for owner, arm in [("alice", "on"), ("bob", "off")]:
            self.bind(shopper, owner=owner, condition=arm)
            messages, _ = shopper.build_messages(current, AssistantView("", turn=0))
            self.assertEqual(json.loads(messages[1]["content"])["prior_visits"], [])
            shopper.finish_session(current, "simulator_error")
        self.assertEqual(len(shopper.history[("alice", "off")]), 1)

    def test_history_trim_preserves_current_needs_and_rejects_essential_overflow(self):
        shopper = self.shopper([], num_ctx=2048)
        self.bind(shopper)
        shopper.history[("alice", "off")] = [{"conversation": [{"text": "x" * 9000}]}]
        memory = ShopperMemory(profile(TYPE))
        messages, info = shopper.build_messages(memory, AssistantView("", turn=0))
        self.assertEqual(info["prior_visits_sent"], 0)
        self.assertTrue(json.loads(messages[1]["content"])["verified_needs"])
        with self.assertRaises(ContextBudgetError):
            shopper.build_messages(memory, AssistantView("x" * 9000))

    def test_claude_and_ollama_share_policy_evidence_and_loop(self):
        for provider in ("ollama", "claude"):
            with self.subTest(provider=provider):
                shopper = self.shopper(
                    [
                        self.reply("I need boots under $50."),
                        self.reply("That works.", "accept"),
                    ],
                    provider=provider,
                )
                record = self.runner(shopper).run(
                    scenario([TYPE, BUDGET], [], "unused")
                )
                self.assertEqual(record.termination, "accepted")
                self.assertEqual(
                    set(record.ledger["revealed_so_far"]), {"type", "budget"}
                )

    def test_only_evidenced_product_fields_are_presented(self):
        product = {
            "id": "internal",
            "facts": {"price": 30, "color": "Blue", "material": "invented"},
            "evidence": {"price": {}, "color": {}},
        }
        self.assertNotIn("facts", card(product))  # V2 shape unchanged
        self.assertEqual(
            card(product, include_facts=True)["facts"], {"price": 30, "color": "Blue"}
        )

    def test_cli_dry_plan_is_network_key_and_output_free_and_requires_both_live_caps(
        self,
    ):
        root = self.root / "longitudinal"
        root.mkdir()
        source, catalogue, index, _ = make_dataset(root)
        output = root / "never-created"
        args = [
            "longitudinal",
            "--customers",
            str(source),
            "--catalogue",
            str(catalogue),
            "--index",
            str(index),
            "--output",
            str(output),
            "--shopper-version",
            "v3",
            "--shopper-provider",
            "claude",
            "--sim-model",
            "claude-fixture",
        ]
        with (
            patch("urllib.request.urlopen", side_effect=AssertionError("network")),
            patch(
                "astra_eval.shopper_providers.claude_key",
                side_effect=AssertionError("key read"),
            ),
            patch(
                "shopping_agent.provider.DeepSeekPolicy.from_env_file",
                side_effect=AssertionError("key read"),
            ),
        ):
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args + ["--live"]), 2)
            self.assertEqual(main(args + ["--live", "--max-model-calls", "5"]), 2)
            self.assertEqual(main(args + ["--max-shopper-calls", "0"]), 2)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_name(output.name + ".shopper-v3.jsonl").exists())

    def test_v2_cannot_silently_use_claude(self):
        self.assertEqual(
            main(
                [
                    "longitudinal",
                    "--output",
                    str(self.root / "unused"),
                    "--shopper-provider",
                    "claude",
                ]
            ),
            2,
        )

    def test_multi_turn_questions_use_actual_dialogue_and_derived_disclosures(self):
        shopper = self.shopper(
            [
                self.reply("I need boots."),
                self.reply("Please keep them under $50."),
                self.reply("Those suit me.", "accept"),
            ]
        )
        record = self.runner(shopper).run(scenario([TYPE, BUDGET], [], "unused"))
        self.assertEqual([t.action for t in record.turns], ["CLARIFY", "RECOMMEND"])
        self.assertEqual(record.termination, "accepted")
        second = json.loads(self.requests[1]["messages"][1]["content"])
        self.assertIn("I need boots.", json.dumps(second["current_dialogue"]))
        self.assertTrue(second["assistant"]["message"])
        self.assertEqual(record.ledger["revealed_so_far"]["budget"]["turn"], 2)

    def test_depleted_agent_budget_does_not_pay_for_a_shopper_opening(self):
        shopper = self.shopper([])
        record = self.runner(shopper, budget=ModelCallBudget(1)).run(
            scenario([TYPE], [], "unused")
        )
        self.assertEqual(record.termination, "run_budget_exhausted")
        self.assertEqual(shopper.provider.journal.calls, 0)
        self.assertEqual(record.simulator["calls"], 0)
        self.assertIsNone(shopper.identity)

    def test_ongoing_preferences_keep_scope_without_templates_and_gifts_exclude_them(
        self,
    ):
        frozen = COLOR.model_dump()
        memory = ShopperMemory(
            profile(COLOR),
            private_context={
                "recipient": "self",
                "current_persistent_preferences": [{"scope": "boots", "fact": frozen}],
            },
        )
        shopper = self.shopper([])
        self.bind(shopper)
        messages, _ = shopper.build_messages(memory, AssistantView("", turn=0))
        user = json.loads(messages[1]["content"])
        self.assertEqual(user["ongoing_preferences"][0]["scope"], "boots")
        self.assertEqual(user["ongoing_preferences"][0]["duration"], "ongoing")
        self.assertNotIn(COLOR.statement, json.dumps(messages))
        memory.private_context["recipient"] = "gift"
        messages, _ = shopper.build_messages(memory, AssistantView("", turn=0))
        self.assertEqual(json.loads(messages[1]["content"])["ongoing_preferences"], [])

    def test_evidence_negation_binds_to_values_and_correction_is_not_old_preference(
        self,
    ):
        current = COLOR.model_copy(update={"value": "Blue"})
        for text in (
            "I used to prefer red. I now prefer blue.",
            "I prefer blue, not red.",
        ):
            result = derive_disclosures(text, profile(current))
            self.assertFalse(result.violations)
            self.assertEqual(result.verified, ("color",))

    def test_longitudinal_v3_runs_both_modes_and_isolates_returning_history(self):
        root = self.root / "longitudinal-run"
        root.mkdir()
        source, catalogue, index, _ = make_dataset(root)
        # This fixed response exercises plumbing, not model quality or preference success.
        shopper = self.shopper(
            [self.reply("I need boots under $60."), self.reply("Thanks.", "accept")]
            * 8,
            cap=16,
        )
        config = LongitudinalConfig(
            customers=source,
            catalogue=catalogue,
            index=index,
            output=root / "run",
            simulator=shopper.config,
            max_model_calls=144,
            max_shopper_calls=16,
            execution_order="off_then_on",
        )
        result = run_longitudinal(
            config, simulator=shopper, policy=F.HeuristicPolicy(ask_department=False)
        )
        self.assertEqual(result["sessions"], 8)
        rows = [
            json.loads(line)
            for line in (config.output / "results.jsonl").read_text().splitlines()
        ]
        self.assertEqual(
            {r["condition"] for r in rows}, {"user_memory_off", "user_memory_on"}
        )
        self.assertTrue(all(r["score"]["valid"] for r in rows))
        frozen = json.loads((config.output / "run.json").read_text())
        self.assertEqual(
            frozen["shared_config"]["simulator"]["protocol_version"],
            "shopper-v3-autonomous-1",
        )
        self.assertEqual(frozen["shared_config"]["plan"]["shopper"]["max_calls"], 16)
        self.assertEqual(len(shopper.history[("alice", "user_memory_on")]), 4)
        self.assertEqual(len(shopper.history[("alice", "user_memory_off")]), 4)

    def test_longitudinal_cannot_record_a_different_shopper_budget(self):
        root = self.root / "cap-mismatch"
        root.mkdir()
        source, catalogue, index, _ = make_dataset(root)
        shopper = self.shopper([], cap=2)
        config = LongitudinalConfig(
            customers=source,
            catalogue=catalogue,
            index=index,
            output=root / "run",
            simulator=shopper.config,
            max_shopper_calls=3,
        )
        with self.assertRaisesRegex(ValueError, "cap must match"):
            run_longitudinal(config, simulator=shopper, policy=F.HeuristicPolicy())
        self.assertFalse(config.output.exists())

    def test_v3_rejects_reused_shopper_history_before_creating_a_new_run(self):
        root = self.root / "reused"
        root.mkdir()
        source, catalogue, index, _ = make_dataset(root)
        shopper = self.shopper([], cap=2)
        shopper.history[("alice", "off")] = [{"conversation": []}]
        config = LongitudinalConfig(
            customers=source,
            catalogue=catalogue,
            index=index,
            output=root / "run",
            simulator=shopper.config,
            max_shopper_calls=2,
        )
        with self.assertRaisesRegex(ValueError, "fresh shopper history"):
            run_longitudinal(config, simulator=shopper, policy=F.HeuristicPolicy())
        self.assertFalse(config.output.exists())

    def test_budget_flag_does_not_silently_promise_a_cap_for_v2(self):
        self.assertEqual(
            main(
                [
                    "longitudinal",
                    "--output",
                    str(self.root / "unused"),
                    "--max-shopper-calls",
                    "10",
                ]
            ),
            2,
        )

    def test_cost_budget_is_shared_across_real_longitudinal_loop_and_both_arms(self):
        from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy

        root = self.root / "budgeted-run"
        root.mkdir()
        source, catalogue, index, _ = make_dataset(root)
        shopper = self.shopper(
            [self.reply("I need boots under $60."), self.reply("Thanks.", "accept")]
            * 8,
            provider="claude",
            cap=16,
        )
        # Use the real verified model identity for the accounting seam; wire remains mocked.
        shopper.config = shopper.provider.config = V3Config(
            provider="claude", model="claude-sonnet-5-5"
        )

        def with_cache_counts(url, payload, headers, timeout):
            response = original(url, payload, headers, timeout)
            response["usage"].update(
                cache_read_input_tokens=0, cache_creation_input_tokens=0
            )
            return response

        original = shopper.provider.transport
        shopper.provider.transport = with_cache_counts
        budget = ApiCostBudget(root / "cost.jsonl", 1, 0.05)
        shopper.provider.cost_budget = budget
        base = F.HeuristicPolicy(ask_department=False)
        base.model = "deepseek-flash"
        config = LongitudinalConfig(
            customers=source,
            catalogue=catalogue,
            index=index,
            output=root / "run",
            simulator=shopper.config,
            max_model_calls=144,
            max_shopper_calls=16,
            max_cost_usd=1,
            prior_cost_usd=0.05,
            execution_order="off_then_on",
        )
        result = run_longitudinal(
            config, simulator=shopper, policy=BudgetedPolicy(base, budget)
        )
        self.assertEqual(result["sessions"], 8)
        self.assertFalse(budget.blocked)
        self.assertLess(budget.total, 1)
        rows = [json.loads(r) for r in budget.path.read_text().splitlines()]
        self.assertEqual(
            {r["provider"] for r in rows if r["kind"] == "usage_settled"},
            {"claude", "deepseek"},
        )

    def test_cost_limit_is_a_provider_failure_and_stops_before_shopper_followup(self):
        from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy

        shopper = self.shopper([self.reply("I need boots under $50.")])
        budget = ApiCostBudget(self.root / "tiny.jsonl", 0.00001)
        base = F.HeuristicPolicy(ask_department=False)
        base.model = "deepseek-flash"
        record = self.runner(shopper, policy=BudgetedPolicy(base, budget)).run(
            scenario([TYPE, BUDGET], [], "unused")
        )
        self.assertEqual(record.termination, "provider_error")
        self.assertIn("spending_budget_exhausted", record.error)
        self.assertEqual(shopper.provider.journal.calls, 1)
        self.assertFalse(base.contexts)
