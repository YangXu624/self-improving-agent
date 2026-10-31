"""Whitespace-only quotes must not satisfy the deterministic evidence check."""

import unittest

from test_sessions import add

from shopping_agent.contracts import ShoppingState, StateUpdate
from shopping_agent.state import StateError, apply_updates

BLANKS = [" \t", "\n\t", "   ", " ", "　"]


def apply(updates, message="show boots", state=None, version=0):
    return apply_updates(
        state or ShoppingState(),
        updates,
        expected_version=version,
        user_message=message,
        source_event_id="evidence-event",
    )


class BlankEvidenceTests(unittest.TestCase):
    def test_blank_update_and_requirement_quotes_are_rejected(self):
        for blank in BLANKS:
            with self.subTest(blank=blank), self.assertRaises(StateError):
                apply([add(quote=blank)])

    def test_blank_update_quote_alone_is_rejected(self):
        update = add(quote="under 60").model_dump()
        update["quote"] = " \t"
        with self.assertRaises(StateError):
            apply([update], message="show boots under 60")

    def test_blank_requirement_quote_alone_is_rejected(self):
        update = add(quote="under 60").model_dump()
        update["requirement"]["quote"] = "\n\t"
        with self.assertRaises(StateError):
            apply([update], message="show boots under 60")

    def test_blank_new_goal_quote_cannot_retire_requirements(self):
        state = apply([add(quote="under 60")], message="boots under 60")
        for blank in BLANKS:
            with self.subTest(blank=blank), self.assertRaises(StateError):
                apply(
                    [StateUpdate(op="NEW_GOAL", quote=blank)],
                    message="thank you",
                    state=state,
                    version=state.version,
                )
        self.assertEqual(state.goal_epoch, 0)
        self.assertEqual([r.status for r in state.requirements], ["active"])

    def test_blank_retract_and_replace_quotes_are_rejected(self):
        state = apply([add(quote="under 60")], message="boots under 60")
        target = state.requirements[0].id
        retract = StateUpdate(op="RETRACT", target_id=target, quote=" \t")
        replace = add(value=30.0, quote="under 30").model_dump()
        replace.update(op="REPLACE", target_id=target, quote="\n")
        for update in (retract, replace):
            with self.subTest(
                op=update["op"] if isinstance(update, dict) else update.op
            ):
                with self.assertRaises(StateError):
                    apply(
                        [update],
                        message="thanks, also under 30",
                        state=state,
                        version=1,
                    )

    def test_nonblank_excerpts_remain_accepted(self):
        state = apply([add(quote="  UNDER   60 ")], message="Boots under 60 please")
        self.assertEqual(state.version, 1)
        self.assertEqual(state.requirements[0].status, "active")
        fresh = apply(
            [StateUpdate(op="NEW_GOAL", quote="new gift")],
            message="a new gift",
            state=state,
            version=1,
        )
        self.assertEqual(fresh.goal_epoch, 1)


if __name__ == "__main__":
    unittest.main()


class InvisibleEvidenceTests(unittest.TestCase):
    def test_quotes_without_any_letter_or_digit_are_rejected(self):
        for junk in ["​", "﻿", "­", "\x00", ".", "​​"]:
            with self.subTest(junk=repr(junk)), self.assertRaises(StateError):
                apply([add(quote=junk)], message=f"show boots {junk} now")

    def test_symbol_adjacent_real_quotes_still_work(self):
        state = apply([add(quote="under $60")], message="boots under $60!")
        self.assertEqual(state.version, 1)
