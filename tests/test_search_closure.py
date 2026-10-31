"""A search request that cannot execute ends the turn safely instead of erroring."""

import unittest

import test_agent
from test_agent import decision, search


class SearchClosureTests(unittest.TestCase):
    # Borrow the agent fixture without inheriting (and re-running) its test cases.
    setUp = test_agent.AgentTests.setUp
    agent = test_agent.AgentTests.agent
    events = test_agent.AgentTests.events

    def respond(self, ctx):
        return decision(ctx, {"type": "RESPOND", "message": "Nothing found yet."})

    def closure_events(self):
        return [e for e in self.events() if e.type == "turn_closed_safely"]

    def test_search_after_search_budget_is_closed_without_error(self):
        out = self.agent(search, search, search).turn("alice", self.sid, "boots")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["action"], "RESPOND")
        self.assertEqual(out["products"], [])
        self.assertNotIn("error", out)
        self.assertEqual(out["closure"], "search_budget_exhausted")
        self.assertEqual(out["budget_used"], {"model_calls": 3, "searches": 2})
        types = [e.type for e in self.events()]
        self.assertEqual(types.count("search_result"), 2)
        self.assertEqual(types.count("tool_call"), 2)
        self.assertNotIn("recommendation", types)
        self.assertNotIn("turn_failed", types)
        self.assertEqual(len(self.closure_events()), 1)

    def test_search_without_a_remaining_decision_call_is_closed(self):
        out = self.agent(search, search, max_calls=2).turn("alice", self.sid, "boots")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["closure"], "search_requires_a_remaining_decision_call")
        self.assertEqual(out["budget_used"], {"model_calls": 2, "searches": 1})
        self.assertEqual(out["products"], [])

    def test_closure_message_states_no_recommendation_and_no_catalogue_facts(self):
        out = self.agent(search, search, search).turn("alice", self.sid, "boots")
        self.assertIn("no products", out["message"].lower())
        for product_id in ("cheap", "costly", "unknown"):
            self.assertNotIn(product_id, out["message"])

    def test_remaining_calls_still_allow_the_model_to_repair(self):
        out = self.agent(search, search, search, self.respond, max_calls=4).turn(
            "alice", self.sid, "boots"
        )
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["message"], "Nothing found yet.")
        self.assertNotIn("closure", out)
        self.assertEqual(self.closure_events(), [])

    def test_other_budget_exhaustion_still_reports_an_error(self):
        out = self.agent(search, "{not json", "{not json").turn(
            "alice", self.sid, "boots"
        )
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error"], "decision_budget_exhausted")
        self.assertNotIn("closure", out)

    def test_conflict_rejection_on_the_last_call_is_not_masked(self):
        edits = [
            add_(),
            add_(op="gte", value=120.0, quote="over 120"),
        ]
        out = self.agent(lambda c: search(c, edits), search, search).turn(
            "alice", self.sid, "under 100 over 120"
        )
        self.assertEqual(out["status"], "error")
        self.assertNotIn("closure", out)

    def test_closed_turn_replays_and_retains_accepted_state(self):
        edits = [add_(value=60.0, quote="under 60")]
        a = self.agent(lambda c: search(c, edits), search, search)
        first = a.turn("alice", self.sid, "boots under 60", request_id="closed")
        again = a.turn("alice", self.sid, "boots under 60", request_id="closed")
        self.assertEqual(first, again)
        self.assertEqual(len(self.policy.contexts), 3)
        self.assertEqual(first["state_version"], 1)


def add_(**kwargs):
    from test_sessions import add

    return add(**kwargs).model_dump()


if __name__ == "__main__":
    unittest.main()
