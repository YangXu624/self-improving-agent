"""Independent offline regressions for scoped experience and reviewed-store integrity."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from test_agent import ScriptedPolicy, decision
from test_sessions import add

from astra_eval.dialogue import AgentTurn, SessionRecord
from astra_eval.disclosed_compliance import compliance
from astra_eval.models import Fact
from astra_eval.scoring import Judge
from shopping_agent.agent import ShoppingAgent
from shopping_agent.context import ContextLimitError, build_decision_context
from shopping_agent.experience.cues import catalogue_categories, decision_cues
from shopping_agent.experience.models import ExperienceSnapshot, Lesson
from shopping_agent.experience.store import ExperienceStore
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore


def fixture_lesson(**kwargs):
    base = Lesson(
        lesson_id="exp-qa-integrity",
        trigger_type="attribute_clarification",
        trigger_condition={"is_initial": True, "is_underspecified": True},
        directive="For a category-only opening, clarify budget before searching.",
        expected_action="CLARIFY",
        action_signature={"attribute": "price"},
        observed_outcome="Broad search needed clarification.",
        hypothesized_cause="Missing shopping constraints.",
        evidence={"source_split": "learning", "source_scenario_id": "qa-learning"},
        status="active",
        created_at="2026-01-01T00:00:00Z",
    )
    return replace(base, **kwargs)


class CaptureSnapshot:
    def __init__(self, lesson=None):
        self.lesson = lesson or fixture_lesson()
        self.snapshot = ExperienceSnapshot.from_lessons("qa-snapshot", [self.lesson])
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.snapshot.retrieve(**kwargs)


class PilotTriggerQATests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source, index = root / "catalogue.jsonl", root / "index.sqlite"
        rows = [
            {
                "parent_asin": f"qa-{category.lower()}",
                "title": category,
                "categories": ["Fashion", category],
                "features": [],
                "description": [],
                "details": {},
                "price": 20,
            }
            for category in ("Boots", "Bangles", "Wallets")
        ]
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        build_index(source, index)
        self.store = SessionStore(root / "sessions")
        self.sid = self.store.create("qa")
        self.tool = LexicalSearch(index)
        self.addCleanup(self.tool.close)

    @staticmethod
    def respond(ctx, updates=None):
        return decision(ctx, {"type": "RESPOND", "message": "Recorded."}, updates)

    @staticmethod
    def clarify(ctx):
        return decision(
            ctx, {"type": "CLARIFY", "attribute": "price", "question": "What budget?"}
        )

    def run_turn(self, message, *steps, memory=None, **kwargs):
        self.memory = memory or CaptureSnapshot()
        self.policy = ScriptedPolicy(*steps)
        return ShoppingAgent(
            self.store, self.tool, self.policy, experience=self.memory, **kwargs
        ).turn("qa", self.sid, message)

    def test_category_only_opening_gets_guidance(self):
        out = self.run_turn("I need boots", self.clarify)
        self.assertEqual(out["experience"]["retrieved"], [self.memory.lesson.lesson_id])
        self.assertTrue(self.memory.calls[0]["context_cues"]["is_underspecified"])
        self.assertTrue(self.policy.contexts[0]["procedural_guidance"])

    def test_noncategory_or_volunteered_openings_do_not_get_category_only_guidance(
        self,
    ):
        for text in (
            "Hello",
            "I need orange boots",
            "I need Nike boots",
            "I need boots for $50",
            "I need black boots under $50",
        ):
            with self.subTest(text=text):
                self.sid = self.store.create("qa")
                out = self.run_turn(text, self.respond)
                self.assertEqual(out["experience"]["retrieved"], [])
                self.assertFalse(
                    self.memory.calls[0]["context_cues"]["is_underspecified"]
                )
                self.assertFalse(self.policy.contexts[0].get("procedural_guidance"))

    def test_later_turn_does_not_become_initial_because_search_counter_resets(self):
        self.run_turn("I need boots", self.respond)
        out = self.run_turn("continue", self.respond)
        self.assertFalse(self.memory.calls[0]["context_cues"]["is_initial"])
        self.assertEqual(out["experience"]["retrieved"], [])

    def test_greeting_does_not_consume_first_shopping_category_decision(self):
        greeting = self.run_turn("Hello", self.respond)
        self.assertEqual(greeting["experience"]["retrieved"], [])
        out = self.run_turn("I need boots", self.clarify)
        self.assertTrue(self.memory.calls[0]["context_cues"]["is_initial"])
        self.assertEqual(out["experience"]["applied"], [self.memory.lesson.lesson_id])

    def test_unknown_category_request_consumes_first_shopping_decision(self):
        vocabulary = catalogue_categories(self.tool)
        with self.store.open("qa", self.sid) as session:
            session.append(
                "user_message", {"message": "I need something"}, "unknown-category"
            )
            first, _, _ = decision_cues(
                session, "I need something", None, 0, 0, vocabulary
            )
            self.assertTrue(first["is_initial"])
            self.assertFalse(first["is_underspecified"])
            session.append("model_request", {"messages": []}, "unknown-category")
            session.append(
                "user_message", {"message": "I need boots"}, "known-category"
            )
            later, _, _ = decision_cues(session, "I need boots", None, 0, 0, vocabulary)
            self.assertFalse(later["is_initial"])
            self.assertFalse(later["is_underspecified"])

    def test_provisional_new_goal_cues_do_not_surface_old_search_result(self):
        self.run_turn(
            "boots under 50 USD",
            lambda c: self.respond(
                c,
                [
                    add("product_type", "contains", "boots", "boots").model_dump(),
                    add(value=50.0, quote="under 50 USD").model_dump(),
                ],
            ),
        )
        with self.store.open("qa", self.sid) as session:
            session.append(
                "user_message", {"message": "New goal: I need wallets"}, "new-goal"
            )
            old_result = {
                "search_id": "old-goal-search",
                "state_version": session.state.version,
                "candidates": [{"id": "old-goal-product"}],
                "counts": {"verified_eligible": 1},
            }
            cues, _, provenance = decision_cues(
                session,
                "New goal: I need wallets",
                old_result,
                0,
                0,
                catalogue_categories(self.tool),
            )
            self.assertTrue(provenance["provisional_goal"])
            self.assertTrue(cues["is_initial"])
            self.assertFalse(cues["has_search"])
            self.assertFalse(cues["has_candidates"])
            self.assertFalse(cues["empty_search"])
            self.assertEqual(cues["candidate_count"], 0)
            self.assertEqual(session.state.goal_epoch, 0)
            self.assertTrue(
                any(
                    r.status == "active" and r.field == "price"
                    for r in session.state.requirements
                )
            )

    def test_committed_new_goal_is_not_initial_again_on_repair_or_later_turn(self):
        self.run_turn(
            "boots under 50 USD",
            lambda c: self.respond(
                c,
                [
                    add("product_type", "contains", "boots", "boots").model_dump(),
                    add(value=50.0, quote="under 50 USD").model_dump(),
                ],
            ),
        )

        def commit_then_rejected_recommendation(ctx):
            return decision(
                ctx,
                {
                    "type": "RECOMMEND",
                    "search_id": "no-current-search",
                    "product_ids": ["unseen"],
                },
                [
                    {"op": "NEW_GOAL", "quote": "New goal"},
                    add("product_type", "contains", "wallets", "wallets").model_dump(),
                ],
            )

        self.run_turn(
            "New goal: I need wallets",
            commit_then_rejected_recommendation,
            self.respond,
        )
        self.assertTrue(self.memory.calls[0]["context_cues"]["is_initial"])
        repair_cues = [
            c["context_cues"]
            for c in self.memory.calls
            if c["context_cues"]["calls"] == 1
        ]
        self.assertTrue(repair_cues)
        self.assertTrue(all(not c["is_initial"] for c in repair_cues))
        self.assertFalse(self.policy.contexts[1].get("procedural_guidance"))
        with self.store.open("qa", self.sid) as session:
            self.assertEqual(session.state.goal_epoch, 1)
        self.run_turn("continue", self.respond)
        self.assertFalse(self.memory.calls[0]["context_cues"]["is_initial"])

    def test_new_goal_opening_does_not_inherit_old_budget_for_trigger(self):
        self.run_turn(
            "boots under 50 USD",
            lambda c: self.respond(
                c,
                [
                    add("product_type", "contains", "boots", "boots").model_dump(),
                    add(value=50.0, quote="under 50 USD").model_dump(),
                ],
            ),
        )
        out = self.run_turn(
            "New goal: I need wallets",
            lambda c: self.respond(
                c,
                [
                    {"op": "NEW_GOAL", "quote": "New goal"},
                    add("product_type", "contains", "wallets", "wallets").model_dump(),
                ],
            ),
        )
        self.assertTrue(self.memory.calls[0]["context_cues"]["is_initial"])
        self.assertTrue(self.memory.calls[0]["context_cues"]["is_underspecified"])
        self.assertEqual(out["experience"]["injected"], [self.memory.lesson.lesson_id])

    def test_legacy_context_that_drops_guidance_is_not_reported_injected_or_applied(
        self,
    ):
        def legacy(session, message, result, feedback, budget, edits_allowed):
            return build_decision_context(
                session, message, result, feedback, budget, edits_allowed
            )

        out = self.run_turn("I need boots", self.clarify, context_builder=legacy)
        self.assertEqual(out["experience"]["retrieved"], [self.memory.lesson.lesson_id])
        self.assertEqual(out["experience"]["injected"], [])
        self.assertEqual(out["experience"]["applied"], [])
        self.assertFalse(self.policy.contexts[0].get("procedural_guidance"))

    def test_unsent_context_failure_has_no_injected_or_applied_experience(self):
        def too_large(*args, **kwargs):
            raise ContextLimitError("fixture overflow")

        out = self.run_turn("I need boots", context_builder=too_large)
        self.assertEqual(out["experience"]["retrieved"], [self.memory.lesson.lesson_id])
        self.assertEqual(out["experience"]["injected"], [])
        self.assertEqual(out["experience"]["applied"], [])
        self.assertEqual(self.policy.contexts, [])

    def test_redundant_matching_clarification_is_not_applied(self):
        self.run_turn(
            "under 50 USD",
            lambda c: self.respond(
                c, [add(value=50.0, quote="under 50 USD").model_dump()]
            ),
        )
        memory = CaptureSnapshot(fixture_lesson(trigger_condition={"calls": 0}))
        out = self.run_turn(
            "continue", self.clarify, self.clarify, self.clarify, memory=memory
        )
        self.assertTrue(out["experience"]["injected"])
        self.assertEqual(out["experience"]["applied"], [])
        self.assertEqual(out["closure"], "redundant_clarification")

    def test_search_signature_without_executed_search_is_not_applied(self):
        memory = CaptureSnapshot(
            fixture_lesson(
                trigger_type="initial_query",
                trigger_condition={"is_initial": True},
                expected_action="SEARCH",
                action_signature={"mode": "all"},
            )
        )
        out = self.run_turn(
            "I need boots",
            lambda c: decision(c, {"type": "SEARCH", "query": "boots", "mode": "all"}),
            memory=memory,
            max_calls=1,
        )
        self.assertTrue(out["experience"]["injected"])
        self.assertEqual(out["experience"]["applied"], [])
        self.assertEqual(out["budget_used"]["searches"], 0)

    def test_accepted_matching_clarification_is_applied(self):
        out = self.run_turn("I need boots", self.clarify)
        self.assertEqual(out["experience"]["retrieved"], [self.memory.lesson.lesson_id])
        self.assertEqual(out["experience"]["injected"], [self.memory.lesson.lesson_id])
        self.assertEqual(out["experience"]["applied"], [self.memory.lesson.lesson_id])


class ReviewedStoreQATests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ExperienceStore(Path(temporary.name) / "qa-only.sqlite")
        self.addCleanup(self.store.close)
        self.serial = 0

    def reviewed(self, status):
        self.serial += 1
        original = fixture_lesson(
            lesson_id=f"exp-qa-integrity-{status}-{self.serial}", status="candidate"
        )
        self.store.add_candidate(original)
        if status == "active":
            self.store.confirm(original.lesson_id, review_notes="QA fixture reviewed")
        elif status == "rejected":
            self.store.reject(original.lesson_id, reason="QA fixture rejected")
        elif status == "retracted":
            self.store.confirm(original.lesson_id)
            self.store.retract(original.lesson_id, reason="QA fixture retracted")
        elif status == "superseded":
            self.store.confirm(original.lesson_id)
            self.store.supersede(
                original.lesson_id,
                replace(
                    original,
                    lesson_id=original.lesson_id + "-replacement",
                    directive="For category-only requests, ask budget before search.",
                    status="active",
                ),
            )
        return original, self.store.get(original.lesson_id)

    def test_identical_reviewed_candidates_return_existing_reviewed_record(self):
        for status in ("active", "rejected", "retracted", "superseded"):
            with self.subTest(status=status):
                original, reviewed = self.reviewed(status)
                returned = self.store.add_candidate(original)
                self.assertEqual(returned, reviewed)
                self.assertEqual(self.store.get(original.lesson_id), reviewed)

    def test_changed_reviewed_payload_is_rejected_and_preserved(self):
        changes = (
            {"directive": "Ask a different focused question before search."},
            {"version": 2},
            {"trigger_condition": {"is_initial": False}},
            {"action_signature": {"attribute": "department"}},
            {
                "evidence": {
                    "source_split": "learning",
                    "source_scenario_id": "qa-other",
                }
            },
        )
        for status in ("active", "rejected", "retracted", "superseded"):
            for change in changes:
                with self.subTest(status=status, change=change):
                    original, reviewed = self.reviewed(status)
                    with self.assertRaises(ValueError):
                        self.store.add_candidate(replace(original, **change))
                    self.assertEqual(self.store.get(original.lesson_id), reviewed)

    def test_unreviewed_candidate_payload_can_still_change(self):
        original = fixture_lesson(status="candidate")
        self.store.add_candidate(original)
        changed = replace(
            original, directive="Ask one focused budget question before search."
        )
        returned = self.store.add_candidate(changed)
        self.assertEqual(returned, self.store.get(original.lesson_id))
        self.assertEqual(returned.directive, changed.directive)
        self.assertEqual(returned.status, "candidate")

    def test_approval_notes_survive_explicit_retraction(self):
        original = fixture_lesson(status="candidate")
        self.store.add_candidate(original)
        self.store.confirm(
            original.lesson_id, review_notes="Approved after source review."
        )
        retracted = self.store.retract(
            original.lesson_id, reason="Later scope evidence requires withdrawal."
        )
        self.assertEqual(retracted.status, "retracted")
        self.assertIn("Approved after source review.", retracted.review_notes)
        self.assertIn(
            "Later scope evidence requires withdrawal.", retracted.review_notes
        )
        self.assertEqual(retracted.evidence, original.evidence)

    def test_approval_notes_survive_explicit_supersession(self):
        original = fixture_lesson(status="candidate")
        self.store.add_candidate(original)
        self.store.confirm(
            original.lesson_id, review_notes="Approved after original review."
        )
        replacement = replace(
            original,
            lesson_id="exp-qa-revision",
            directive="Clarify the unresolved budget before search.",
            status="active",
        )
        old, new = self.store.supersede(
            original.lesson_id, replacement, reason="Reviewed narrower-scope revision."
        )
        self.assertEqual(old.status, "superseded")
        self.assertIn("Approved after original review.", old.review_notes)
        self.assertIn("Reviewed narrower-scope revision.", old.review_notes)
        self.assertEqual(old.superseded_by_id, new.lesson_id)
        self.assertEqual(new.supersedes_id, old.lesson_id)


class DisclosureComplianceQATests(unittest.TestCase):
    @staticmethod
    def oracle():
        rows = {
            "known": {
                "parent_asin": "known",
                "title": "Boots",
                "categories": ["Boots"],
                "price": 20,
                "details": {"Material": "Cotton"},
            },
            "unknown": {
                "parent_asin": "unknown",
                "title": "Boots",
                "categories": ["Boots"],
                "price": 20,
                "details": {},
            },
        }
        return SimpleNamespace(row=lambda ident: copy.deepcopy(rows.get(ident)))

    @staticmethod
    def turn(number, ids, requirements):
        return AgentTurn(
            number,
            f"qa-{number}",
            "ok",
            "RECOMMEND",
            "Catalogue matches.",
            presented_ids=ids,
            recommendation_requirements=requirements,
        )

    def test_hidden_requirement_failure_is_not_disclosed_compliance_failure(self):
        truth = SimpleNamespace(
            hard=[
                Fact(
                    key="material",
                    kind="hard",
                    field="material",
                    op="eq",
                    value="Leather",
                    statement="Leather only.",
                )
            ],
            soft=[],
        )
        self.assertEqual(Judge(self.oracle(), truth)("known")["hard"], "fail")
        record = SessionRecord(
            "qa", "memory_off", "qa", turns=[self.turn(1, ["known"], [])]
        )
        result = compliance(record, self.oracle())
        self.assertEqual(result["checked_occurrences"], 1)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["violations"], 0)
        self.assertIn("extraction_completeness_not_asserted", result["basis"])

    def test_each_presentation_uses_its_own_snapshot_not_final_corrected_budget(self):
        upper50 = [{"field": "price", "op": "lt", "value": 50.0, "strength": "hard"}]
        upper10 = [{"field": "price", "op": "lt", "value": 10.0, "strength": "hard"}]
        record = SessionRecord(
            "qa",
            "memory_off",
            "qa",
            turns=[self.turn(1, ["known"], upper50), self.turn(2, ["known"], upper10)],
            final_requirements=upper10,
        )
        result = compliance(record, self.oracle())
        self.assertEqual(result["checked_occurrences"], 2)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["violations"], 1)

    def test_missing_legacy_snapshot_unknown_fact_and_unknown_id_are_not_counted_as_passed(
        self,
    ):
        exclusion = [
            {
                "field": "material",
                "op": "not_contains",
                "value": "leather",
                "strength": "hard",
            }
        ]
        record = SessionRecord(
            "qa",
            "memory_off",
            "qa",
            turns=[
                self.turn(1, ["known"], None),
                self.turn(2, ["unknown", "absent"], exclusion),
            ],
        )
        result = compliance(record, self.oracle())
        self.assertEqual(result["missing_snapshot_occurrences"], 1)
        self.assertEqual(result["unknown_required"], 1)
        self.assertEqual(result["unknown_product_id"], 1)
        self.assertEqual(result["passed"], 0)


if __name__ == "__main__":
    unittest.main()
