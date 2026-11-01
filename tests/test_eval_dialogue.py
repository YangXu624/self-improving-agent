"""Multi-turn dialogues between the simulated shopper and a real ShoppingAgent (fixture policy)."""

import json
import unittest

import eval_fixtures as F

from astra_eval.dialogue import DialogueRunner
from astra_eval.experiment import ModelCallBudget
from astra_eval.models import Fact, Scenario, ShopperProfile
from astra_eval.simulators import OllamaShopper, ScriptedShopper, SimulatorConfig
from shopping_agent.agent import ShoppingAgent


def fact(key, kind, field, op, value, statement, keywords):
    return Fact(
        key=key,
        kind=kind,
        field=field,
        op=op,
        value=value,
        statement=statement,
        keywords=keywords,
    )


TYPE = fact(
    "type",
    "hard",
    "product_type",
    "contains",
    "boots",
    "I'm looking for boots.",
    ["kind", "type"],
)
BUDGET = fact(
    "budget",
    "hard",
    "price",
    "lt",
    50.0,
    "My budget is under $50.",
    ["budget", "price"],
)
DEPT = fact(
    "department",
    "hard",
    "department",
    "eq",
    "women",
    "It's for a woman.",
    ["who", "for whom"],
)
COLOR = fact(
    "color", "soft", "color", "eq", "red", "I'd like it in red.", ["color", "colour"]
)


def scenario(facts, opening_keys, opening, turns=6, kind="feasible"):
    return Scenario(
        id="t1",
        split="development",
        kind=kind,
        family="Boots",
        opening=opening,
        max_user_turns=turns,
        profile=ShopperProfile(
            scenario_id="t1",
            persona="Brief.",
            facts=tuple(facts),
            opening_keys=tuple(opening_keys),
        ),
    )


class DialogueCase(F.EvalCase):
    def runner(self, policy=None, simulator=None, **kw):
        self.policy = policy or F.HeuristicPolicy()
        agent = ShoppingAgent(self.store, self.search, self.policy)
        return DialogueRunner(
            agent, self.store, simulator or ScriptedShopper(), run_id="r", **kw
        )

    def roles(self, record):
        return [
            (e["role"], e.get("action") or e.get("status"))
            for e in record.transcript
            if e["role"] != "simulator_audit"
        ]


class SuccessfulConversationTests(DialogueCase):
    def test_clarification_answers_lead_to_recommendation_and_acceptance(self):
        s = scenario([TYPE, BUDGET, DEPT], ["type"], "Hi, I need some boots.")
        record = self.runner().run(s)
        self.assertEqual(record.termination, "accepted")
        self.assertEqual(
            [t.action for t in record.turns], ["CLARIFY", "CLARIFY", "RECOMMEND"]
        )
        self.assertEqual(sum(t.searches for t in record.turns), 1)
        self.assertEqual(
            record.turns[-1].recommended_ids,
            [p for p in record.turns[-1].recommended_ids],
        )
        self.assertTrue(record.turns[-1].recommended_ids)
        self.assertEqual(
            {r["field"] for r in record.final_requirements},
            {"product_type", "price", "department"},
        )
        shopper = [e for e in record.transcript if e["role"] == "shopper"]
        self.assertEqual(
            [e["reveals"] for e in shopper][:3], [["type"], ["budget"], ["department"]]
        )
        self.assertEqual(record.repeated_questions, 0)

    def test_each_agent_turn_is_traced_from_astras_own_event_log(self):
        record = self.runner().run(
            scenario([TYPE, BUDGET], ["type", "budget"], "Boots under $50 please.")
        )
        recommend = record.turns[-1]
        self.assertGreater(recommend.model_calls, 0)
        self.assertTrue(recommend.candidates_seen and recommend.candidates_seen[0])
        self.assertGreater(recommend.usage["prompt_tokens"], 0)
        self.assertTrue(
            set(recommend.recommended_ids) <= set(recommend.candidates_seen[0])
        )
        self.assertEqual(recommend.counts[0]["verified_eligible"] > 0, True)

    def test_unnecessary_clarification_is_counted(self):
        s = scenario([TYPE, BUDGET], ["type", "budget"], "Boots under $50 please.")
        record = self.runner().run(
            s
        )  # the policy still asks who it is for; the profile has nothing on that
        self.assertEqual(record.unmatched_questions, 1)
        self.assertEqual(record.termination, "accepted")
        replies = [e["text"] for e in record.transcript if e["role"] == "shopper"]
        self.assertIn("I don't have a strong preference about that.", replies)

    def test_the_shopper_never_dumps_the_whole_profile(self):
        record = self.runner().run(
            scenario([TYPE, BUDGET, DEPT, COLOR], ["type"], "Hi, I need some boots.")
        )
        for e in record.transcript:
            if e["role"] == "shopper":
                self.assertLessEqual(len(e["reveals"]), 2)
        self.assertNotIn(
            "color", record.ledger["revealed_so_far"]
        )  # never asked, never said


class LongConversationConsistencyTests(DialogueCase):
    def test_answers_stay_consistent_after_old_dialogue_leaves_the_window(self):
        fake = F.FakeOllama("good")
        shopper = OllamaShopper(SimulatorConfig(window_turns=2), transport=fake)
        s = scenario([TYPE, COLOR], ["type"], "Hi, I need some boots.", turns=10)
        record = self.runner(F.AlwaysClarifyPolicy(), shopper).run(s)
        self.assertEqual(record.termination, "max_turns")
        shopper_lines = [
            e["text"] for e in record.transcript if e["role"] == "shopper"
        ][1:]
        self.assertEqual(len(shopper_lines), 9)
        self.assertTrue(all("red" in line.lower() for line in shopper_lines))
        self.assertFalse(
            any(
                w in line.lower()
                for line in shopper_lines
                for w in ("blue", "black", "purple")
            )
        )
        self.assertEqual(
            record.repeated_questions, 9
        )  # asked 10 times; only the first was new
        # The full transcript is complete while the model only ever saw a bounded window.
        dialogue = [
            e for e in record.transcript if e["role"] in {"shopper", "assistant"}
        ]
        self.assertEqual(len(dialogue), 20)  # 10 shopper + 10 assistant
        self.assertEqual(
            sum(e["role"] == "simulator_audit" for e in record.transcript), 9
        )
        last = json.loads(fake.payloads[-1]["messages"][1]["content"])
        self.assertLessEqual(len(last["recent_dialogue"]), 4)
        self.assertEqual(
            last["ledger_of_what_you_already_said"]["revealed_so_far"]["color"][
                "statement"
            ],
            "I'd like it in red.",
        )
        self.assertEqual(last["now"]["questions"][0]["answered_before"], True)
        system_prompts = {p["messages"][0]["content"] for p in fake.payloads}
        self.assertEqual(len(system_prompts), 1)

    def test_scripted_shopper_is_equally_consistent_over_a_long_conversation(self):
        record = self.runner(F.AlwaysClarifyPolicy()).run(
            scenario([TYPE, COLOR], ["type"], "Boots.", turns=12)
        )
        lines = [e["text"] for e in record.transcript if e["role"] == "shopper"][1:]
        self.assertTrue(all("red" in x for x in lines))
        self.assertEqual(record.simulator["violations"], {})


class SimulatorFailureTests(DialogueCase):
    def run_with(self, mode, **kw):
        fake = F.FakeOllama(mode)
        record = self.runner(
            simulator=OllamaShopper(SimulatorConfig(**kw), transport=fake)
        ).run(scenario([TYPE, BUDGET], ["type"], "Hi, I need some boots."))
        return record, fake

    def test_malformed_output_is_retried_once_then_succeeds(self):
        record, fake = self.run_with("malformed_once")
        self.assertEqual(record.termination, "accepted")
        self.assertEqual(record.simulator["attempts"] - record.simulator["calls"], 1)

    def test_persistently_malformed_output_invalidates_the_session(self):
        record, _ = self.run_with("always_malformed")
        self.assertEqual(
            (record.termination, record.error),
            ("simulator_failure", "simulator_malformed_reply"),
        )
        self.assertTrue(any(e["role"] == "simulator_audit" for e in record.transcript))

    def test_unreachable_server_and_http_errors_invalidate_without_blaming_the_agent(
        self,
    ):
        for mode, code in (
            ("unreachable", "simulator_unreachable"),
            ("http_error", "simulator_http_500"),
        ):
            with self.subTest(mode=mode):
                record, _ = self.run_with(mode)
                self.assertEqual(
                    (record.termination, record.error), ("simulator_failure", code)
                )

    def test_a_contradictory_reply_is_re_asked_once_with_feedback(self):
        record, fake = self.run_with("contradict_once")
        self.assertEqual(record.termination, "accepted")
        self.assertEqual(record.simulator["consistency_retries"], 1)
        self.assertEqual(record.simulator["violations"], {"invented_attribute": 1})
        retry = json.loads(fake.payloads[1]["messages"][1]["content"])
        self.assertIn("fix_these_problems_in_your_previous_attempt", retry)
        self.assertNotIn(
            "purple",
            json.dumps(
                [e["text"] for e in record.transcript if e["role"] == "shopper"]
            ),
        )

    def test_persistent_contradiction_price_drift_leak_and_overreveal_invalidate(self):
        for mode, code in (
            ("contradict", "invented_attribute"),
            ("price_drift", "price_not_in_profile"),
            ("leak", "target_leak"),
            ("overreveal", "over_reveal"),
        ):
            with self.subTest(mode=mode):
                record, _ = self.run_with(mode)
                self.assertEqual(record.termination, "simulator_failure")
                self.assertIn(code, record.error)
                shopper = [
                    e["text"] for e in record.transcript if e["role"] == "shopper"
                ]
                self.assertEqual(
                    len(shopper), 1
                )  # the bad reply was never sent to ASTRA

    def test_leaked_target_titles_are_caught_by_the_audit(self):
        class Echo(ScriptedShopper):
            def respond(self, memory, view, feedback=()):
                result = super().respond(memory, view, feedback)
                result.reply.message += " like the Acme Trail Boot please"
                return result

        record = self.runner(simulator=Echo()).run(
            scenario([TYPE, BUDGET], ["type"], "Boots."), forbidden=["Acme Trail Boot"]
        )
        self.assertEqual(record.termination, "simulator_failure")
        self.assertIn("target_leak", record.error)


class AgentFailureTests(DialogueCase):
    @staticmethod
    def patient():
        """A shopper that keeps replying, so the agent's behaviour decides how the session ends."""
        return OllamaShopper(SimulatorConfig(), transport=F.FakeOllama("good"))

    def test_exhausted_agent_budget_is_recorded_as_a_closure_not_an_answer(self):
        record = self.runner(F.AlwaysSearchPolicy(), self.patient()).run(
            scenario([TYPE, BUDGET], ["type", "budget"], "Boots under $50.", turns=3)
        )
        self.assertEqual(record.termination, "max_turns")
        self.assertTrue(
            all(t.closure == "search_budget_exhausted" for t in record.turns)
        )
        self.assertTrue(
            all(t.model_calls == 3 and t.searches == 2 for t in record.turns)
        )

    def test_provider_failure_stops_immediately_without_further_paid_calls(self):
        policy = F.FailingPolicy("provider_http_500")
        record = self.runner(policy).run(scenario([TYPE], ["type"], "Boots."))
        self.assertEqual(
            (record.termination, record.error), ("provider_error", "provider_http_500")
        )
        self.assertEqual(policy.calls, 1)

    def test_repeated_non_provider_agent_errors_end_the_session(self):
        record = self.runner(
            F.FailingPolicy("not_a_provider_code"), self.patient()
        ).run(scenario([TYPE], ["type"], "Boots.", turns=6))
        self.assertEqual(record.termination, "agent_error")
        self.assertEqual(len(record.turns), 2)

    def test_run_budget_blocks_a_turn_before_any_model_call(self):
        policy = F.HeuristicPolicy()
        record = self.runner(policy, budget=ModelCallBudget(2)).run(
            scenario([TYPE], ["type"], "Boots.")
        )
        self.assertEqual(record.termination, "run_budget_exhausted")
        self.assertEqual(policy.contexts, [])

    def test_budget_is_charged_with_actual_model_calls(self):
        budget = ModelCallBudget(100)
        self.runner(budget=budget).run(
            scenario([TYPE, BUDGET], ["type", "budget"], "Boots under $50.", turns=4)
        )
        self.assertGreater(budget.used, 0)
        self.assertEqual(budget.used, len(self.policy.contexts))


if __name__ == "__main__":
    unittest.main()
