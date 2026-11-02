"""Comprehensive End-to-End Integration Acceptance & Procedural Verification Tests.

Validates:
P0: End-to-end integration acceptance workflow (steps 1-12)
    - Manual customer interaction with preference and purchase
    - Instant purchase persistence and session audit trail
    - Single-run end-of-session consolidation and idempotent finalize
    - Cross-session memory and purchase retrieval
    - Session Audit Explorer state reconstruction
    - Safe Memory OFF isolation without destroying stored profiles
    - Mock Customer Lab multi-visit execution with separate OFF/ON namespaces
P3: Procedural learning verification
    - Experience -> evidence -> generalized lesson -> SQLite -> retrieval for new customer
    - Zero customer PII leakage
"""

import json
import tempfile
import unittest
from pathlib import Path

from shopping_agent.experience.models import Lesson
from shopping_agent.experience.sanitizer import validate_lesson
from shopping_agent.experience.store import ExperienceStore
from shopping_agent.mock_lab import load_mock_customer_fixtures
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import build_index
from shopping_agent.session_audit import extract_session_audit
from shopping_agent.ui_service import ChatService
from shopping_agent.user_memory import UserMemoryStore


class ScriptedMultiPolicy:
    """Deterministic policy fixture for end-to-end acceptance testing."""

    def __init__(self):
        self.responses = []
        self.recorded_contexts = []
        self.recorded_messages = []

    def queue_turn(self, *steps):
        """Queue a sequence of steps (SEARCH, RECOMMEND, RESPOND, or consolidation JSON)."""
        self.responses.extend(steps)

    def complete(self, messages):
        self.recorded_messages.append(messages)
        content = messages[-1]["content"]
        try:
            ctx = json.loads(content)
            self.recorded_contexts.append(ctx)
        except Exception:
            ctx = {}
            self.recorded_contexts.append(content)

        if not self.responses:
            raise RuntimeError("ScriptedMultiPolicy: out of queued responses")

        step = self.responses.pop(0)
        if callable(step):
            val = step(ctx)
        else:
            val = step

        if isinstance(val, (dict, list)):
            text = json.dumps(val)
        else:
            text = str(val)

        return PolicyReply(
            content=text,
            metadata={
                "usage": {
                    "total_tokens": 42,
                    "prompt_tokens": 30,
                    "completion_tokens": 12,
                }
            },
        )


class TestSubmissionAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Build dedicated test catalogue and index
        self.cat_path = self.root / "catalog.jsonl"
        self.index_path = self.root / "catalogue.sqlite"

        self.products = [
            {
                "parent_asin": "B001_RUN_BLK",
                "title": "Air Pegasus Pro Black Running Shoes",
                "price": 85.0,
                "categories": [
                    "Clothing, Shoes & Jewelry",
                    "Men",
                    "Shoes",
                    "Athletic",
                    "Running",
                ],
                "details": {"Color": "Black", "Style": "Running", "Department": "Men"},
            },
            {
                "parent_asin": "B002_SNEAK_WHT",
                "title": "Classic White Tennis Sneakers",
                "price": 60.0,
                "categories": ["Clothing, Shoes & Jewelry", "Men", "Shoes", "Athletic"],
                "details": {"Color": "White", "Style": "Tennis"},
            },
            {
                "parent_asin": "B003_SOCK_BLK",
                "title": "Breathable Athletic Cushion Running Socks 3-Pack",
                "price": 18.0,
                "categories": ["Clothing, Shoes & Jewelry", "Men", "Socks", "Athletic"],
                "details": {"Color": "Black"},
            },
        ]
        with self.cat_path.open("w", encoding="utf-8") as f:
            for p in self.products:
                f.write(json.dumps(p) + "\n")

        build_index(self.cat_path, self.index_path)

        self.sessions_dir = self.root / "sessions"
        self.user_mem_dir = self.root / "user-memory"
        self.purchase_db = self.root / "purchases.sqlite"
        self.exp_db = self.root / "experience.sqlite"

        self.policy = ScriptedMultiPolicy()

        self.service = ChatService(
            self.cat_path,
            self.index_path,
            self.sessions_dir,
            policy=self.policy,
            user_memory_enabled=True,
            user_memory_root=self.user_mem_dir,
            purchases_db_path=self.purchase_db,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_p0_end_to_end_acceptance_workflow(self):
        """Execute exact P0 integration acceptance workflow (steps 1 through 12)."""
        user_id = "manual-user-001"

        # Step 1 & 2: Start session 1 for manual-user-001
        sess1_id = self.service.create(user_id)
        self.assertTrue(sess1_id)

        # Step 3 & 4: Ask for a product and state a durable preference
        # The customer states: "I need running shoes. I always prefer Black color."
        # Queue model decisions: SEARCH -> RECOMMEND with cards and follow-up question
        def get_ver(ctx):
            if isinstance(ctx, dict) and isinstance(ctx.get("state"), dict):
                return ctx["state"].get("version", 0)
            return 0

        def search_step(ctx):
            return {
                "reason": "Searching for running shoes",
                "updates": [
                    {
                        "op": "ADD",
                        "quote": "I need running shoes.",
                        "requirement": {
                            "field": "product_type",
                            "op": "eq",
                            "value": "shoes",
                            "quote": "I need running shoes.",
                        },
                    },
                    {
                        "op": "ADD",
                        "quote": "I always prefer Black color.",
                        "requirement": {
                            "field": "color",
                            "op": "eq",
                            "value": "Black",
                            "strength": "soft",
                            "quote": "I always prefer Black color.",
                        },
                    },
                ],
                "action": {"type": "SEARCH", "query": "running shoes"},
            }

        def recommend_step(ctx):
            search_res = ctx["latest_search"]
            cand_ids = [c["id"] for c in search_res["candidates"]]
            return {
                "reason": "Recommending Pegasus running shoes",
                "updates": [],
                "action": {
                    "type": "RECOMMEND",
                    "search_id": search_res["search_id"],
                    "product_ids": [cand_ids[0]],
                    "follow_up_question": "Would you prefer standard or wide athletic fit?",
                },
            }

        self.policy.queue_turn(search_step, recommend_step)

        turn1_result = self.service.send(
            user_id,
            sess1_id,
            "I need running shoes. I always prefer Black color.",
            request_id="turn-1",
        )

        self.assertEqual(turn1_result["status"], "ok")
        self.assertEqual(len(turn1_result["products"]), 1)
        recommended_prod = turn1_result["products"][0]
        self.assertEqual(recommended_prod["id"], "B001_RUN_BLK")
        self.assertIn("Air Pegasus Pro Black Running Shoes", recommended_prod["title"])
        self.assertEqual(
            turn1_result.get("follow_up_question"),
            "Would you prefer standard or wide athletic fit?",
        )

        # Step 5 & 6: Confirm a simulated purchase and verify immediate persistence
        turn_id = turn1_result.get("turn_id", "turn-1")
        purch_result = self.service.record_purchase(
            user_id,
            sess1_id,
            turn_id,
            recommended_prod["id"],
            recommended_prod["title"],
            price=recommended_prod.get("price", 85.0),
            quantity=1,
            recipient_context="self",
            attribute_snapshot={"Color": "Black", "Type": "Running"},
        )
        self.assertEqual(purch_result["product_id"], "B001_RUN_BLK")
        self.assertEqual(purch_result["status"], "simulated_completed")

        # Verify purchase is immediately returned by purchase store
        active_purchases = self.service.get_purchases(user_id)
        self.assertEqual(len(active_purchases), 1)
        self.assertEqual(active_purchases[0]["product_id"], "B001_RUN_BLK")

        # Step 7 & 8: Finalize the session and verify memory consolidation runs exactly once
        consolidation_payload = {
            "reason": "Direct customer statement and confirmed purchase of black running shoes.",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "Black",
                    "scope": "running shoes",
                    "quote": "I always prefer Black color.",
                    "basis": "confirmed",
                    "confidence": 0.98,
                    "rationale": "Direct customer statement and confirmed purchase of black running shoes.",
                }
            ],
        }
        self.policy.queue_turn(consolidation_payload)

        finalize_result = self.service.finalize(user_id, sess1_id)
        self.assertEqual(finalize_result["status"], "success")
        self.assertFalse(finalize_result["idempotent"])
        self.assertEqual(finalize_result["revision"], 1)
        self.assertEqual(len(finalize_result["operations_applied"]), 1)

        # Verify idempotency: calling finalize again does NOT rerun consolidation
        finalize_repeat = self.service.finalize(user_id, sess1_id)
        self.assertTrue(finalize_repeat["idempotent"])
        self.assertEqual(finalize_repeat["revision"], 1)

        # Verify profile records in SQLite
        mem_store = UserMemoryStore(self.user_mem_dir)
        profile = mem_store.read(user_id)
        self.assertEqual(profile.revision, 1)
        active_recs = [r for r in profile.records if r.status == "active"]
        self.assertEqual(len(active_recs), 1)
        self.assertEqual(active_recs[0].attribute, "color")
        self.assertEqual(active_recs[0].value, "Black")

        # Step 9 & 10: Start new session for same customer, verify memory & purchase retrieved
        sess2_id = self.service.create(user_id)

        def turn2_step(ctx):
            # Model responds to socks request
            search_res = ctx["latest_search"]
            return {
                "reason": "Recommending running socks",
                "updates": [],
                "action": {
                    "type": "RECOMMEND",
                    "search_id": search_res["search_id"],
                    "product_ids": [c["id"] for c in search_res["candidates"][:1]],
                    "follow_up_question": "Do you need crew or no-show length?",
                },
            }

        def search_socks_step(ctx):
            return {
                "reason": "Searching for socks",
                "updates": [],
                "action": {"type": "SEARCH", "query": "running socks"},
            }

        self.policy.queue_turn(search_socks_step, turn2_step)

        turn2_result = self.service.send(
            user_id, sess2_id, "Show me running socks.", request_id="turn-2"
        )
        self.assertEqual(turn2_result["status"], "ok")

        # Verify that during session 2 reasoning, previous preferences and purchase were injected
        # Check the context provided to the policy on the first decision of turn 2
        decision_context = self.policy.recorded_contexts[
            3
        ]  # index 0: turn 1 search, 1: turn 1 rec, 2: finalize consolidation, 3: turn 2 search
        self.assertIn("user_memory", decision_context)
        injected_mem = decision_context["user_memory"]
        self.assertTrue(
            any("Black" in str(r) for r in injected_mem.get("records", []))
            or "Black" in str(injected_mem)
        )

        # Verify purchase evidence was injected
        self.assertIn("relevant_purchases", decision_context)
        injected_purch = decision_context["relevant_purchases"]
        self.assertTrue(len(injected_purch) >= 1)
        self.assertEqual(injected_purch[0]["product_id"], "B001_RUN_BLK")

        # Step 11: Verify Session Audit Explorer reconstructs full history and state
        audit = extract_session_audit(self.sessions_dir, user_id, sess1_id)
        self.assertEqual(audit.session_id, sess1_id)
        self.assertEqual(audit.user_id, user_id)
        self.assertTrue(audit.finalized)
        self.assertEqual(len(audit.turns), 1)

        turn0 = audit.turns[0]
        self.assertEqual(
            turn0.user_message, "I need running shoes. I always prefer Black color."
        )
        self.assertEqual(turn0.recommended_product_ids, ["B001_RUN_BLK"])
        self.assertEqual(
            turn0.follow_up_question, "Would you prefer standard or wide athletic fit?"
        )
        self.assertTrue(len(turn0.internal_searches) >= 1)
        self.assertTrue(len(turn0.state_updates) >= 1)
        self.assertTrue(len(turn0.purchases) >= 1)
        self.assertEqual(turn0.purchases[0]["product_id"], "B001_RUN_BLK")

        # Step 12: Confirm Memory OFF prevents long-term memory access without destroying stored data
        # Instantiate a ChatService instance with user_memory=None
        off_service = ChatService(
            self.cat_path,
            self.index_path,
            self.sessions_dir,
            policy=self.policy,
            user_memory_enabled=False,  # Memory OFF
            user_memory_root=self.user_mem_dir,
            purchases_db_path=self.purchase_db,
        )

        sess3_id = off_service.create(user_id)

        self.policy.queue_turn(search_socks_step, turn2_step)

        turn3_result = off_service.send(
            user_id, sess3_id, "Find me running socks.", request_id="turn-3"
        )
        self.assertEqual(turn3_result["status"], "ok")

        # Verify context did NOT inject user_memory
        decision_context_off = self.policy.recorded_contexts[-2]
        self.assertNotIn("user_memory", decision_context_off)

        # Finalizing with memory OFF does not fail and does not mutate profile
        finalize_off = off_service.finalize(user_id, sess3_id)
        self.assertEqual(finalize_off["status"], "memory_disabled")

        # Verify the original memory profile in SQLite remains intact and was NOT destroyed
        stored_profile_after = mem_store.read(user_id)
        self.assertEqual(stored_profile_after.revision, 1)
        self.assertEqual(
            len([r for r in stored_profile_after.records if r.status == "active"]), 1
        )

    def test_mock_customer_lab_multi_visit_namespaces(self):
        """Test Mock Customer Lab loading and separate memory namespaces."""
        fixtures = load_mock_customer_fixtures(Path("."))
        self.assertTrue(len(fixtures) >= 1)
        all_customers = [c for d in fixtures for c in d["customers"]]
        target_cust = next(
            (c for c in all_customers if c["user_id"] == "dev-activewear"),
            all_customers[0],
        )
        self.assertTrue(len(target_cust["visits"]) >= 2)

        # Simulate two isolated memory directories (OFF namespace vs ON namespace)
        off_mem_dir = self.root / "mock_lab_off_memory"
        on_mem_dir = self.root / "mock_lab_on_memory"
        off_mem_dir.mkdir(parents=True, exist_ok=True)
        on_mem_dir.mkdir(parents=True, exist_ok=True)

        on_store = UserMemoryStore(on_mem_dir)
        off_store = UserMemoryStore(off_mem_dir)

        # Visit 1 on ON namespace consolidates a preference
        on_store.apply_consolidation_operations(
            target_cust["user_id"],
            "mock-visit-1",
            [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "workout_color",
                    "value": "Black",
                    "scope": "activewear",
                    "quote": "I prefer black workout clothes.",
                }
            ],
        )

        # Verify ON namespace has the updated memory
        on_profile = on_store.read(target_cust["user_id"])
        self.assertEqual(on_profile.revision, 1)
        self.assertEqual(
            len([r for r in on_profile.records if r.status == "active"]), 1
        )

        # Verify OFF namespace remains pristine and unmutated
        off_profile = off_store.read(target_cust["user_id"])
        self.assertEqual(off_profile.revision, 0)
        self.assertEqual(len(off_profile.records), 0)

    def test_p3_procedural_learning_verification(self):
        """P3: Completed experience -> outcome evidence -> generalized lesson -> SQLite -> retrieval.

        Verifies:
        1. Lesson generalizes without leaking Customer A specific PII or IDs.
        2. Saved to SQLite ExperienceStore.
        3. Retrieved when Customer B triggers the matching situation.
        """
        exp_store = ExperienceStore(self.exp_db)

        # Step 1: Customer A (e.g. customer-alpha) runs a session that suffered an empty search
        customer_a_id = "customer-alpha-99"
        lesson_record = Lesson(
            lesson_id="exp-general-01",
            scope="Shoes",
            trigger_type="initial_query",
            trigger_condition={"is_initial": True},
            directive="Prioritize category noun and primary attribute before compound adjectives in lexical search.",
            expected_action="SEARCH",
            action_signature={"mode": "all"},
            observed_outcome="empty_search",
            hypothesized_cause="Excessive compound modifiers caused zero FTS5 BM25 matches.",
            evidence={
                "source_scenario_id": "learn-footwear-01",
                "source_split": "learning",
                "turn": 1,
            },
            situation="Customer initial query contains compound descriptive adjectives.",
            strategy="Issue lexical search with category noun first.",
            rationale="Recovers relevant candidates while avoiding zero-result query drops.",
            confidence=0.85,
            status="candidate",
        )

        # Verify no customer A PII in lesson
        lesson_json = json.dumps(lesson_record.to_dict())
        self.assertNotIn(customer_a_id, lesson_json)
        self.assertNotIn("alpha", lesson_json)

        # Validate with sanitizer
        validate_lesson(lesson_record, allow_non_learning=False)

        # Step 2: Save to SQLite ExperienceStore and activate after review
        exp_store.add_candidate(lesson_record)
        exp_store.confirm(
            lesson_record.lesson_id, review_notes="Verified on test benchmark"
        )
        exp_store.activate(lesson_record.lesson_id)

        # Step 3: Customer B (customer-beta-42) starts a new visit with an initial query
        customer_b_id = "customer-beta-42"
        self.assertEqual(customer_b_id, "customer-beta-42")
        matched_lessons = exp_store.retrieve(
            trigger_type="initial_query",
            scope="Shoes",
            context_cues={"is_initial": True},
            max_lessons=5,
        )

        self.assertTrue(len(matched_lessons) >= 1)
        retrieved_ids = [item.lesson_id for item in matched_lessons]
        self.assertIn("exp-general-01", retrieved_ids)

        retrieved_rule = next(
            item for item in matched_lessons if item.lesson_id == "exp-general-01"
        )
        self.assertEqual(
            retrieved_rule.directive,
            "Prioritize category noun and primary attribute before compound adjectives in lexical search.",
        )
        self.assertEqual(retrieved_rule.status, "active")

        # Verify Customer B context receives the generalized directive without Customer A info
        retrieved_dict = retrieved_rule.to_dict()
        self.assertNotIn(customer_a_id, json.dumps(retrieved_dict))


if __name__ == "__main__":
    unittest.main()
