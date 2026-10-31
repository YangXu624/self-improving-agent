"""Shopper session memory: immutable profile, bounded window, ledger, full transcript."""

import json
import tempfile
import unittest
from pathlib import Path

from astra_eval.memory import (
    AssistantView,
    ContextBudgetError,
    ShopperMemory,
    estimate_tokens,
    matched_keys,
    questions_in,
)
from astra_eval.models import Fact, ShopperProfile, ShopperReply


def profile():
    facts = (
        Fact(
            key="type",
            kind="hard",
            field="product_type",
            op="contains",
            value="boots",
            statement="I'm looking for boots.",
            keywords=["kind", "type"],
        ),
        Fact(
            key="budget",
            kind="hard",
            field="price",
            op="lt",
            value=60.0,
            statement="My budget is under $60.",
            keywords=["budget", "price"],
        ),
        Fact(
            key="color",
            kind="soft",
            field="color",
            op="eq",
            value="red",
            statement="I'd like it in red.",
            keywords=["color", "colour"],
        ),
    )
    return ShopperProfile(
        scenario_id="s1", persona="Brief.", facts=facts, opening_keys=("type",)
    )


def view(text, turn, products=(), left=5):
    return AssistantView(text, tuple(products), turn, left)


class MemoryTests(unittest.TestCase):
    def conversation(self, turns, window=2, filler=300):
        memory = ShopperMemory(profile(), window_turns=window)
        memory.record_shopper(1, "I'm looking for boots.", ["type"])
        for t in range(1, turns + 1):
            text = ("Tell me more please. " * (filler // 20)) + (f"Marker-{t}. ")
            if t == 2:
                text = "What is your budget?"
            memory.record_assistant(view(text, t))
            if t == 2:
                memory.record_shopper(3, "My budget is under $60.", ["budget"])
            else:
                memory.record_shopper(t + 1, f"Shopper line {t}.", [])
        return memory

    def test_profile_is_sent_identically_on_every_call(self):
        memory = self.conversation(12)
        systems = {
            memory.build_messages(view(f"Q{n}?", 13 + n), 4000)[0][0]["content"]
            for n in range(3)
        }
        self.assertEqual(len(systems), 1)
        system = systems.pop()
        for fact in profile().facts:
            self.assertIn(fact.statement, system)
        self.assertIn("never override it", system)

    def test_window_drops_old_dialogue_but_the_ledger_keeps_what_was_revealed(self):
        memory = self.conversation(20, window=2)
        messages, info = memory.build_messages(view("What colour?", 21), 6000)
        user = messages[1]["content"]
        self.assertNotIn("Marker-3.", user)  # old dialogue left the window
        self.assertIn("Marker-20.", user)
        ledger = json.loads(user)["ledger_of_what_you_already_said"]
        self.assertIn("budget", ledger["revealed_so_far"])  # turn-3 answer survives
        self.assertEqual(
            ledger["revealed_so_far"]["budget"]["statement"], "My budget is under $60."
        )
        self.assertLessEqual(info["dialogue_entries_sent"], 4)

    def test_token_budget_trims_oldest_dialogue_first_and_reports_it(self):
        memory = self.conversation(14, window=14)
        loose, _ = memory.build_messages(view("Next?", 15), 50_000)
        tight_budget = estimate_tokens(loose[0]["content"]) + 700
        tight, info = memory.build_messages(view("Next?", 15), tight_budget)
        self.assertLessEqual(info["estimated_prompt_tokens"], tight_budget)
        self.assertGreater(info["dialogue_entries_dropped_for_budget"], 0)
        sent = json.loads(tight[1]["content"])["recent_dialogue"]
        full = json.loads(loose[1]["content"])["recent_dialogue"]
        self.assertEqual(sent, full[-len(sent) :])  # a suffix: newest messages kept

    def test_essential_context_that_cannot_fit_fails_instead_of_truncating(self):
        memory = self.conversation(3)
        with self.assertRaises(ContextBudgetError):
            memory.build_messages(view("Hi?", 4), 50)

    def test_full_transcript_is_complete_append_only_and_separate_from_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            from astra_eval.memory import Transcript

            memory = ShopperMemory(
                profile(), window_turns=1, transcript=Transcript(path)
            )
            memory.record_shopper(1, "Hello boots", ["type"])
            for t in range(1, 11):
                memory.record_assistant(view(f"Assistant {t}", t))
                memory.record_shopper(t + 1, f"Shopper {t}", [])
            lines = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(len(lines), 21)
            self.assertEqual(len(memory.transcript.entries), 21)
            self.assertEqual(len(memory.window()), 2)
            self.assertEqual(lines[0]["text"], "Hello boots")
            with self.assertRaises(AttributeError):
                memory.transcript.entries.append(
                    {}
                )  # tuple copy: not mutable from outside

    def test_repeated_questions_are_detected_and_flagged_to_the_shopper(self):
        memory = ShopperMemory(profile(), window_turns=4)
        memory.record_shopper(1, "Boots please", ["type"])
        memory.record_assistant(view("What is your budget?", 1))
        memory.record_shopper(2, "My budget is under $60.", ["budget"])
        again = view("Sorry, what is your budget?", 2)
        memory.record_assistant(again)
        self.assertEqual(memory.repeat_counts, {"budget": 1})
        self.assertTrue(memory.questions[-1]["repeat"])
        messages, _ = memory.build_messages(again, 4000)
        now = json.loads(messages[1]["content"])["now"]
        self.assertEqual(
            now["questions"],
            [{"question": "Sorry, what is your budget?", "answered_before": True}],
        )

    def test_questions_about_nothing_in_the_profile_are_counted(self):
        memory = ShopperMemory(profile(), window_turns=2)
        memory.record_assistant(view("Do you want free shipping?", 1))
        self.assertEqual(memory.unmatched_questions, 1)
        self.assertEqual(
            matched_keys(profile(), "Which colour do you like?"), ["color"]
        )
        self.assertEqual(
            questions_in("Hello. What budget? And colour?"),
            ["What budget?", "And colour?"],
        )

    def test_ledger_is_code_built_and_cannot_override_the_profile(self):
        memory = ShopperMemory(profile(), window_turns=2)
        # A reply claiming a fact the profile does not have is ignored by the ledger.
        memory.record_shopper(2, "I want it in purple", ["purple_key", "color"])
        self.assertEqual(set(memory.revealed), {"color"})
        self.assertEqual(memory.revealed["color"]["statement"], "I'd like it in red.")
        system = memory.system_prompt()
        self.assertIn("red", system)
        self.assertNotIn("purple", system)

    def test_nothing_outside_the_shoppers_world_enters_the_prompt(self):
        memory = self.conversation(6)
        messages, _ = memory.build_messages(
            view(
                "Which colour?",
                7,
                [{"title": "Boot", "price": 30.0, "id": "B0SECRET01"}],
            ),
            6000,
        )
        text = json.dumps(messages)
        for forbidden in (
            "B0SECRET01",
            "ground_truth",
            "ideal_grades",
            "acceptable",
            "memory_on",
            "experience",
            "score",
            "condition",
        ):
            self.assertNotIn(forbidden, text)

    def test_window_turns_must_be_positive(self):
        with self.assertRaises(ValueError):
            ShopperMemory(profile(), window_turns=0)

    def test_reveals_the_message_did_not_support_stay_out_of_the_ledger(self):
        memory = ShopperMemory(profile(), window_turns=2)
        memory.apply(
            2,
            ShopperReply(message="Sure.", reveals=["budget"]),
            flags=["claimed_reveal_missing"],
            unverified=["budget"],
        )
        self.assertNotIn("budget", memory.revealed)
        self.assertEqual(memory.transcript.entries[-1]["reveals"], [])
        self.assertEqual(
            memory.transcript.entries[-1]["flags"], ["claimed_reveal_missing"]
        )

    def test_apply_records_structured_reply(self):
        memory = ShopperMemory(profile(), window_turns=2)
        memory.apply(
            2,
            ShopperReply(message="Under $60.", reveals=["budget"], action="reply"),
            flags=["w"],
        )
        self.assertEqual(memory.transcript.entries[-1]["flags"], ["w"])
        self.assertIn("budget", memory.revealed)


if __name__ == "__main__":
    unittest.main()
