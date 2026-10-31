"""Independent offline adversarial coverage for scoped attribute working memory."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_agent import ScriptedPolicy, decision
from test_sessions import add

from shopping_agent.agent import ShoppingAgent
from shopping_agent.attributes import attribute_ledger, compact_ledger
from shopping_agent.context import builder_for_profile
from shopping_agent.contracts import Event, ShoppingState
from shopping_agent.event_codec import encode_event
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore


class AttributeQATests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source, index = self.root / "catalogue.jsonl", self.root / "index.sqlite"
        row = {
            "parent_asin": "fixture-boots",
            "title": "Hiking boots",
            "categories": ["Shoes", "Boots"],
            "features": [],
            "description": [],
            "details": {"Color": "Blue", "Size": "9", "Material": "Cotton"},
            "price": 45,
        }
        source.write_text(json.dumps(row) + "\n")
        build_index(source, index)
        self.search = LexicalSearch(index)
        self.addCleanup(self.search.close)
        self.store = SessionStore(self.root / "sessions")
        self.sid = self.store.create("owner")

    def turn(self, message, *steps, request_id=None):
        self.policy = ScriptedPolicy(*steps)
        return ShoppingAgent(
            self.store,
            self.search,
            self.policy,
            context_builder=builder_for_profile("shared_k5"),
        ).turn("owner", self.sid, message, request_id=request_id)

    def ledger(self):
        with self.store.open("owner", self.sid) as session:
            return attribute_ledger(session)

    @staticmethod
    def respond(ctx, updates=None):
        return decision(ctx, {"type": "RESPOND", "message": "Recorded."}, updates)

    @staticmethod
    def clarify(attribute, question=None):
        return lambda c: decision(
            c,
            {
                "type": "CLARIFY",
                "attribute": attribute,
                "question": question or f"What {attribute}?",
            },
        )

    def test_answered_repetition_is_bounded_and_never_records_rejected_question(self):
        self.turn("boots", self.clarify("color"))
        original_question = self.ledger()["asked_attributes"]["color"]["question"]
        self.turn(
            "Blue",
            lambda c: self.respond(
                c, [add("color", "eq", "Blue", "Blue").model_dump()]
            ),
        )
        out = self.turn("continue", *[self.clarify("color")] * 3)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["closure"], "redundant_clarification")
        self.assertEqual(out["budget_used"]["model_calls"], 3)
        ledger = self.ledger()
        self.assertEqual(ledger["asked_attributes"]["color"]["status"], "answered")
        self.assertEqual(
            ledger["asked_attributes"]["color"]["question"], original_question
        )
        self.assertEqual(ledger["asked_attributes"]["color"]["answer"]["quote"], "Blue")
        with self.store.open("owner", self.sid) as session:
            executed = [
                e
                for e in session.events
                if e.type == "assistant_response" and e.payload["action"] == "CLARIFY"
            ]
            self.assertEqual(len(executed), 1)

    def test_invalid_question_never_becomes_asked_evidence(self):
        invalid = {
            "based_on_state_version": 0,
            "action": {"type": "CLARIFY", "attribute": "material", "question": 123},
            "reason": "Invalid fixture proposal",
        }
        self.turn("boots", invalid, self.clarify("size"))
        self.assertEqual(set(self.ledger()["asked_attributes"]), {"size"})
        self.assertEqual(
            self.ledger()["asked_attributes"]["size"]["status"], "asked_unanswered"
        )

    def test_volunteered_size_does_not_block_distinct_width_and_short_answer(self):
        self.turn(
            "size 9",
            lambda c: self.respond(c, [add("size", "eq", "9", "size 9").model_dump()]),
        )
        self.assertNotIn("size", self.ledger()["asked_attributes"])
        out = self.turn("continue", self.clarify("width", "What shoe width?"))
        self.assertEqual(out["action"], "CLARIFY")
        self.turn("wide", self.respond)
        ledger = self.ledger()
        self.assertEqual(ledger["disclosed_attributes"]["width"]["status"], "answered")
        self.assertEqual(ledger["disclosed_attributes"]["width"]["value"], "wide")
        self.assertEqual(ledger["asked_attributes"]["width"]["answer"]["quote"], "wide")
        self.assertEqual(
            ledger["disclosed_attributes"]["size"]["requirements"][0]["value"], "9"
        )

    def test_currency_is_distinct_unknown_until_explicit_short_answer(self):
        self.turn(
            "under 80",
            lambda c: self.respond(c, [add(value=80.0, quote="under 80").model_dump()]),
        )
        self.assertNotIn("currency", self.ledger()["disclosed_attributes"])
        self.turn("continue", self.clarify("currency"))
        self.turn("USD", self.respond)
        ledger = self.ledger()
        self.assertEqual(ledger["disclosed_attributes"]["currency"]["value"], "USD")
        self.assertEqual(ledger["asked_attributes"]["currency"]["status"], "answered")
        self.assertEqual(ledger["disclosed_attributes"]["price"]["status"], "answered")

    def test_later_explicit_currency_supersedes_old_no_preference(self):
        self.turn("No preference on currency", self.respond)
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["currency"]["status"], "no_preference"
        )
        self.turn("Actually in USD", self.respond)
        currency = self.ledger()["disclosed_attributes"]["currency"]
        self.assertEqual(currency["value"], "USD")
        self.assertEqual(currency["status"], "answered")
        self.assertIn("in usd", currency["answer"]["quote"].lower())

    def test_declined_currency_can_be_reopened_by_explicit_answer(self):
        self.turn("boots", self.clarify("currency"))
        self.turn("I prefer not to answer", self.respond)
        self.assertEqual(
            self.ledger()["asked_attributes"]["currency"]["status"], "declined"
        )
        self.turn("Actually currency is SGD", self.respond)
        ledger = self.ledger()
        self.assertEqual(ledger["asked_attributes"]["currency"]["status"], "answered")
        self.assertEqual(ledger["disclosed_attributes"]["currency"]["value"], "SGD")

    def test_uncertain_or_negated_currency_is_not_confirmed(self):
        for answer in (
            "Maybe in USD",
            "I am unsure whether currency is USD",
            "not in USD",
            "currency is USD or SGD",
        ):
            with self.subTest(answer=answer):
                self.sid = self.store.create("owner")
                self.turn("boots", self.clarify("currency"))
                self.turn(answer, self.respond)
                ledger = self.ledger()
                self.assertNotEqual(
                    ledger["asked_attributes"]["currency"]["status"], "answered"
                )
                self.assertNotIn(
                    "value", ledger["disclosed_attributes"].get("currency", {})
                )
                self.assertEqual(
                    self.turn("continue", self.clarify("currency"))["action"], "CLARIFY"
                )

    def test_currency_question_is_not_a_disclosure_but_affirmative_request_is(self):
        self.turn("Can I pay in SGD?", self.respond)
        self.assertNotIn("currency", self.ledger()["disclosed_attributes"])
        self.turn("Please use SGD", self.respond)
        currency = self.ledger()["disclosed_attributes"]["currency"]
        self.assertEqual(currency["status"], "answered")
        self.assertEqual(currency["value"], "SGD")
        self.assertIn("Please use SGD", currency["answer"]["quote"])

    def test_non_usd_budget_search_closes_without_calling_engine(self):
        def search(ctx, updates=None):
            return decision(ctx, {"type": "SEARCH", "query": "boots"}, updates)

        with patch.object(
            self.search, "search", side_effect=AssertionError("Engine must not execute")
        ) as engine:
            out = self.turn(
                "under 80 SGD",
                lambda c: search(
                    c, [add(value=80.0, quote="under 80 SGD").model_dump()]
                ),
                search,
                search,
            )
        engine.assert_not_called()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["closure"], "budget_currency_not_supported")
        self.assertEqual(out["products"], [])
        self.assertEqual(out["budget_used"], {"model_calls": 3, "searches": 0})
        self.assertIn("USD", out["message"])
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["currency"]["value"], "SGD"
        )
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["price"]["requirements"][0]["value"],
            80,
        )

    def test_explicit_usd_budget_still_searches_and_recommends(self):
        def recommend(ctx):
            return decision(
                ctx,
                {
                    "type": "RECOMMEND",
                    "search_id": ctx["latest_search"]["search_id"],
                    "product_ids": ["fixture-boots"],
                },
            )

        out = self.turn(
            "under 80 USD",
            lambda c: decision(
                c,
                {"type": "SEARCH", "query": "boots"},
                [add(value=80.0, quote="under 80 USD").model_dump()],
            ),
            recommend,
        )
        self.assertEqual(out["action"], "RECOMMEND")
        self.assertEqual(out["budget_used"], {"model_calls": 2, "searches": 1})
        self.assertEqual([p["id"] for p in out["products"]], ["fixture-boots"])

    def test_product_type_answer_does_not_block_distinct_subtype_question(self):
        self.turn(
            "boots",
            lambda c: self.respond(
                c, [add("product_type", "contains", "boots", "boots").model_dump()]
            ),
        )
        out = self.turn(
            "continue", self.clarify("product_subtype", "Which kind of boots?")
        )
        self.assertEqual(out["action"], "CLARIFY")
        self.assertEqual(out["attribute"], "product_subtype")
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["product_type"]["status"], "answered"
        )
        self.assertEqual(
            self.ledger()["asked_attributes"]["product_subtype"]["status"],
            "asked_unanswered",
        )

    def test_no_preference_does_not_erase_active_exclusion(self):
        self.turn(
            "no leather",
            lambda c: self.respond(
                c,
                [add("material", "not_contains", "leather", "no leather").model_dump()],
            ),
        )
        self.turn("No material preference", self.respond)
        material = self.ledger()["disclosed_attributes"]["material"]
        self.assertEqual(material["status"], "no_preference")
        self.assertEqual(material["requirements"][0]["op"], "not_contains")
        self.assertEqual(material["requirements"][0]["value"], "leather")
        with self.store.open("owner", self.sid) as session:
            active = [r for r in session.state.requirements if r.status == "active"]
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].op, "not_contains")

    def test_sentence_separated_disposition_does_not_disappear(self):
        self.turn(
            "No color preference. Brand must be Nike.",
            lambda c: self.respond(
                c, [add("brand", "eq", "Nike", "Brand must be Nike").model_dump()]
            ),
        )
        disclosed = self.ledger()["disclosed_attributes"]
        self.assertEqual(disclosed["color"]["status"], "no_preference")
        self.assertEqual(disclosed["brand"]["status"], "answered")

    def test_mixed_clause_no_preference_does_not_contaminate_confirmed_brand(self):
        self.turn(
            "No color preference; brand must be Nike.",
            lambda c: self.respond(
                c, [add("brand", "eq", "Nike", "brand must be Nike").model_dump()]
            ),
        )
        disclosed = self.ledger()["disclosed_attributes"]
        self.assertEqual(disclosed["color"]["status"], "no_preference")
        self.assertEqual(disclosed["brand"]["status"], "answered")
        self.assertEqual(disclosed["brand"]["requirements"][0]["value"], "Nike")

    def test_mixed_clause_no_preference_preserves_explicit_material_exclusion(self):
        self.turn(
            "No color preference; no leather material.",
            lambda c: self.respond(
                c,
                [
                    add(
                        "material", "not_contains", "leather", "no leather material"
                    ).model_dump()
                ],
            ),
        )
        disclosed = self.ledger()["disclosed_attributes"]
        self.assertEqual(disclosed["color"]["status"], "no_preference")
        self.assertEqual(disclosed["material"]["status"], "needs_followup")
        self.assertEqual(disclosed["material"]["requirements"][0]["op"], "not_contains")
        out = self.turn(
            "continue", self.clarify("material", "Which material is wanted?")
        )
        self.assertEqual(out["action"], "CLARIFY")
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["material"]["requirements"][0][
                "value"
            ],
            "leather",
        )

    def test_no_preference_list_resolves_only_the_named_attributes(self):
        self.turn("No preference on color and material", self.respond)
        disclosed = self.ledger()["disclosed_attributes"]
        self.assertEqual(set(disclosed), {"color", "material"})
        self.assertEqual(disclosed["color"]["status"], "no_preference")
        self.assertEqual(disclosed["material"]["status"], "no_preference")

    def test_decline_can_be_explicitly_reopened_without_erasing_history(self):
        self.turn("boots", self.clarify("brand"))
        self.turn("I prefer not to answer", self.respond)
        self.turn("I am ready to answer brand now", self.respond)
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["brand"]["status"], "needs_followup"
        )
        out = self.turn("continue", self.clarify("brand", "Which brand now?"))
        self.assertEqual(out["action"], "CLARIFY")
        with self.store.open("owner", self.sid) as session:
            questions = [
                e
                for e in session.events
                if e.type == "assistant_response" and e.payload["action"] == "CLARIFY"
            ]
            self.assertEqual(len(questions), 2)
            self.assertTrue(
                any(
                    e.type == "user_message"
                    and e.payload["message"] == "I prefer not to answer"
                    for e in session.events
                )
            )

    def test_no_preference_can_be_explicitly_reopened(self):
        self.turn("No brand preference", self.respond)
        self.turn("I can answer brand now", self.respond)
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["brand"]["status"], "needs_followup"
        )
        self.assertEqual(
            self.turn("continue", self.clarify("brand"))["action"], "CLARIFY"
        )

    def test_validated_subtype_answer_links_to_new_product_type_requirement(self):
        self.turn(
            "boots",
            lambda c: self.respond(
                c, [add("product_type", "contains", "boots", "boots").model_dump()]
            ),
        )
        self.turn("continue", self.clarify("product_subtype", "Which kind of boots?"))

        def replace(ctx):
            update = add(
                "product_type", "contains", "hiking boots", "hiking boots"
            ).model_dump()
            update.update(op="REPLACE", target_id=ctx["state"]["requirements"][0]["id"])
            return self.respond(ctx, [update])

        self.turn("hiking boots", replace)
        ledger = self.ledger()
        self.assertEqual(
            ledger["asked_attributes"]["product_subtype"]["status"], "answered"
        )
        subtype = ledger["disclosed_attributes"]["product_subtype"]["requirements"]
        self.assertEqual([r["value"] for r in subtype], ["hiking boots"])
        self.assertEqual(
            subtype, ledger["disclosed_attributes"]["product_type"]["requirements"]
        )

    def test_declined_and_unanswered_remain_distinct(self):
        self.turn("boots", self.clarify("brand"))
        self.turn("I prefer not to answer", self.respond)
        self.turn("continue", self.clarify("size"))
        ledger = self.ledger()
        self.assertEqual(ledger["asked_attributes"]["brand"]["status"], "declined")
        self.assertEqual(
            ledger["asked_attributes"]["size"]["status"], "asked_unanswered"
        )
        self.assertNotIn("size", ledger["disclosed_attributes"])
        out = self.turn("please continue", self.clarify("size", "Still need a size?"))
        self.assertEqual(out["action"], "CLARIFY")
        self.assertEqual(
            self.ledger()["asked_attributes"]["brand"]["status"], "declined"
        )

    def test_uncertainty_allows_followup_then_explicit_value_resolves(self):
        self.turn("boots", self.clarify("color"))
        self.turn("Maybe red or blue", self.respond)
        self.assertEqual(
            self.ledger()["asked_attributes"]["color"]["status"], "needs_followup"
        )
        self.turn("continue", self.clarify("color", "Which color is confirmed?"))
        self.turn(
            "Blue is confirmed",
            lambda c: self.respond(
                c, [add("color", "eq", "Blue", "Blue is confirmed").model_dump()]
            ),
        )
        self.assertEqual(
            self.ledger()["asked_attributes"]["color"]["status"], "answered"
        )

    def test_lower_price_bound_does_not_prevent_maximum_budget_followup(self):
        self.turn(
            "at least 50",
            lambda c: self.respond(
                c, [add(op="gte", value=50.0, quote="at least 50").model_dump()]
            ),
        )
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["price"]["status"], "needs_followup"
        )
        self.assertEqual(
            self.turn("continue", self.clarify("price"))["action"], "CLARIFY"
        )

    def test_correction_then_explicit_retraction_keeps_only_current_resolution(self):
        self.turn(
            "Blue",
            lambda c: self.respond(
                c, [add("color", "eq", "Blue", "Blue").model_dump()]
            ),
        )

        def replace(ctx):
            old = ctx["state"]["requirements"][0]
            update = add("color", "eq", "Red", "Red instead").model_dump()
            update.update(op="REPLACE", target_id=old["id"])
            return self.respond(ctx, [update])

        self.turn("Red instead", replace)
        current = self.ledger()["disclosed_attributes"]["color"]["requirements"]
        self.assertEqual([r["value"] for r in current], ["Red"])

        def retract(ctx):
            return self.respond(
                ctx,
                [
                    {
                        "op": "RETRACT",
                        "target_id": ctx["state"]["requirements"][0]["id"],
                        "quote": "no color preference",
                    }
                ],
            )

        self.turn("Actually no color preference", retract)
        row = self.ledger()["disclosed_attributes"]["color"]
        self.assertEqual(row["status"], "no_preference")
        self.assertEqual(row["requirements"], [])
        with self.store.open("owner", self.sid) as session:
            self.assertEqual(
                [r.status for r in session.state.requirements],
                ["superseded", "retracted"],
            )

    def test_same_turn_new_goal_drops_old_scope_but_keeps_fresh_values(self):
        self.turn("boots", self.clarify("color"))
        self.turn("no preference", self.respond)
        self.turn(
            "New goal: blue shoes",
            lambda c: self.respond(
                c,
                [
                    {"op": "NEW_GOAL", "quote": "New goal"},
                    add("color", "eq", "Blue", "blue shoes").model_dump(),
                ],
            ),
        )
        ledger = self.ledger()
        self.assertEqual(ledger["goal_epoch"], 1)
        self.assertEqual(ledger["asked_attributes"], {})
        self.assertEqual(ledger["disclosed_attributes"]["color"]["status"], "answered")
        self.assertEqual(
            ledger["disclosed_attributes"]["color"]["requirements"][0]["value"], "Blue"
        )

    def test_ledgers_survive_history_window_restart_and_completed_retry(self):
        self.turn("boots", self.clarify("brand"))
        first = self.turn("I prefer not to answer", self.respond, request_id="declined")
        for index in range(14):
            self.turn(f"continuing {index}", self.respond)
        self.store = SessionStore(self.store.root)
        self.turn("last continuation", self.respond)
        state = self.policy.contexts[0]["state"]
        self.assertEqual(state["asked_attributes"]["brand"], "declined")
        self.assertEqual(state["disclosed_attributes"]["brand"]["status"], "declined")
        self.assertNotIn(
            "I prefer not to answer",
            json.dumps(self.policy.contexts[0]["recent_dialogue"]),
        )
        before = self.ledger()
        replay = self.turn("I prefer not to answer", request_id="declined")
        self.assertEqual(replay, first)
        self.assertEqual(self.policy.contexts, [])
        self.assertEqual(self.ledger(), before)
        snapshot = json.loads((self.store.root / self.sid / "state.json").read_text())
        self.assertEqual(snapshot["attribute_ledger"], before)
        other = self.store.create("owner")
        with self.store.open("owner", other) as session:
            self.assertEqual(attribute_ledger(session)["asked_attributes"], {})

    def test_negated_meta_statement_does_not_create_no_preference(self):
        self.turn("boots", self.clarify("color"))
        self.turn(
            "I didn't say I have no preference; Blue is confirmed",
            lambda c: self.respond(
                c, [add("color", "eq", "Blue", "Blue is confirmed").model_dump()]
            ),
        )
        self.assertEqual(
            self.ledger()["disclosed_attributes"]["color"]["status"], "answered"
        )

    def test_legacy_full_and_compact_reference_records_project_and_replay(self):
        for compact in (False, True):
            with self.subTest(compact=compact):
                sid = uuid4().hex
                response = {
                    "status": "ok",
                    "action": "CLARIFY",
                    "attribute": "color",
                    "message": "Which color?",
                    "products": [],
                    "session_id": sid,
                    "request_id": "legacy",
                    "state_version": 0,
                    "budget_used": {"model_calls": 1, "searches": 0},
                }
                proposal = {
                    "based_on_state_version": 0,
                    "updates": [],
                    "action": {
                        "type": "CLARIFY",
                        "attribute": "color",
                        "question": "Which color?",
                    },
                    "reason": "Legacy fixture",
                }
                payloads = [
                    ("session_created", {"state": ShoppingState().model_dump()}, None),
                    ("turn_started", {"max_calls": 3, "max_searches": 2}, "legacy"),
                    ("user_message", {"message": "boots"}, "legacy"),
                    ("model_response", {"content": json.dumps(proposal)}, "legacy"),
                    ("decision_validated", proposal, "legacy"),
                    ("assistant_response", response, "legacy"),
                    ("turn_completed", {"response": response}, "legacy"),
                ]
                events = []
                records = []
                for seq, (kind, payload, turn_id) in enumerate(payloads, 1):
                    event = Event(
                        event_id=f"legacy-{seq}",
                        seq=seq,
                        state_version=0,
                        session_id=sid,
                        user_id="owner",
                        timestamp="2026-10-31T00:00:00Z",
                        turn_id=turn_id,
                        type=kind,
                        payload=payload,
                    )
                    records.append(
                        encode_event(event, events, ShoppingState())
                        if compact
                        else event.model_dump()
                    )
                    events.append(event)
                destination = self.store.root / sid
                destination.mkdir()
                path = destination / "events.jsonl"
                path.write_text("".join(json.dumps(row) + "\n" for row in records))
                before = path.read_bytes()
                with self.store.open("owner", sid) as session:
                    self.assertEqual(
                        [e.model_dump() for e in session.events],
                        [e.model_dump() for e in events],
                    )
                    self.assertEqual(
                        attribute_ledger(session)["asked_attributes"]["color"][
                            "status"
                        ],
                        "asked_unanswered",
                    )
                    self.assertEqual(
                        compact_ledger(session)["asked_attributes"],
                        {"color": "asked_unanswered"},
                    )
                policy = ScriptedPolicy()
                out = ShoppingAgent(self.store, self.search, policy).turn(
                    "owner", sid, "boots", request_id="legacy"
                )
                self.assertEqual(out, response)
                self.assertEqual(policy.contexts, [])
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
