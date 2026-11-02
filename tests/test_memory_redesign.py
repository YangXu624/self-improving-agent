"""Comprehensive deterministic regression tests for the redesigned long-term memory architecture.

Covers:
- Vector-based semantic retrieval across paraphrases (workout clothing <-> workout shirt).
- Time-based decay weighting for changeable preferences vs stable facts.
- End-of-session user memory consolidation (ADD, REINFORCE, SUPERSEDE, DELETE, NOOP).
- Coexisting scoped preferences vs contradictory updates.
- Customer isolation and source provenance.
- Immediate withdrawal on explicit customer forgetting requests.
- Centralized procedural experience distillation, anti-leakage sanitization, and semantic retrieval.
- Target-item evaluation immediate termination and consolidation lifecycle triggering.
"""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_agent import decision

from astra_eval.dialogue import DialogueRunner
from astra_eval.target_scoring import TargetRule
from shopping_agent.agent import ShoppingAgent
from shopping_agent.consolidation import consolidate_session
from shopping_agent.embeddings import (
    DeterministicEmbeddingProvider,
)
from shopping_agent.experience.distiller import (
    distill_session_experience,
)
from shopping_agent.experience.store import ExperienceStore
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import (
    DecayConfig,
    MemoryRecord,
    UserMemoryStore,
    calculate_decay_factor,
)


class MockLLMPolicy:
    """Mock policy returning predetermined JSON responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        resp = self.responses.pop(0) if self.responses else {}
        if callable(resp):
            try:
                ctx = json.loads(messages[-1]["content"])
            except Exception:
                ctx = {}
            resp = resp(ctx)
        if isinstance(resp, str):
            content = resp
        else:
            content = json.dumps(resp)
        return PolicyReply(content, {"usage": {"total_tokens": 50}})


class TestMemoryRedesign(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sessions_dir = self.root / "sessions"
        self.memory_dir = self.root / "user-memory"
        self.exp_db = self.root / "experience.db"

        # Deterministic embedding provider for instantaneous, repeatable tests
        self.emb_provider = DeterministicEmbeddingProvider(dim=128)
        self.user_store = UserMemoryStore(
            self.memory_dir,
            embedding_provider=self.emb_provider,
        )
        self.exp_store = ExperienceStore(
            self.exp_db,
            embedding_provider=self.emb_provider,
        )
        self.session_store = SessionStore(self.sessions_dir)

        # Build minimal catalogue index for search/agent
        self.cat_path = self.root / "catalog.jsonl"
        products = [
            {
                "parent_asin": "B001",
                "title": "Black Workout Shirt Gym Tee",
                "price": 25.0,
                "categories": ["Clothing", "Active", "Shirts"],
                "details": {"Color": "Black"},
            },
            {
                "parent_asin": "B002",
                "title": "Cream Formal Silk Shirt",
                "price": 40.0,
                "categories": ["Clothing", "Formal", "Shirts"],
                "details": {"Color": "Cream"},
            },
            {
                "parent_asin": "B003",
                "title": "Yellow Windproof Folding Umbrella",
                "price": 18.0,
                "categories": ["Accessories", "Umbrellas"],
                "details": {"Color": "Yellow"},
            },
        ]
        self.cat_path.write_text("\n".join(json.dumps(p) for p in products) + "\n")
        self.index_path = self.root / "catalogue.sqlite"
        build_index(self.cat_path, self.index_path)
        self.search = LexicalSearch(self.index_path)

    def tearDown(self):
        self.search.close()
        self.exp_store.close()
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. User Memory Semantic Retrieval & Paraphrasing
    # =========================================================================
    def test_semantic_retrieval_across_paraphrases(self):
        user_id = "alice"
        # Seed memory: "Usually prefers black workout clothing"
        rec = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            scope="workout clothing",
            quote="I generally prefer black workout clothing.",
            status="active",
        )
        with self.user_store._locked(user_id) as p:
            conn = self.user_store._init_db(p)
            profile = self.user_store.read(user_id)
            profile.records.append(rec)
            profile.revision = 1
            self.user_store.write_profile(profile, p, conn)
            conn.close()

        # Query 1: Paraphrase without literal token "clothing" -> "workout shirt"
        matches = self.user_store.retrieve(
            user_id,
            "I'm looking for a workout shirt under $45",
            min_similarity=0.45,
        )
        self.assertEqual(len(matches), 1)
        record, score = matches[0]
        self.assertEqual(record.value, "black")
        self.assertEqual(record.attribute, "color")
        self.assertGreater(score, 0.45)

        # Query 2: Negative test - unrelated request for umbrellas
        unrelated = self.user_store.retrieve(
            user_id,
            "I need a yellow folding umbrella for commuting",
            min_similarity=0.45,
        )
        self.assertEqual(len(unrelated), 0)

    # =========================================================================
    # 2. Time-Based Memory Decay
    # =========================================================================
    def test_memory_decay_weighting(self):
        now = datetime.now(UTC)
        cfg = DecayConfig(preference_half_life_days=60.0, fact_half_life_days=365.0)

        # Fresh preference (confirmed today)
        fresh_pref = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            last_confirmed_at=now.isoformat(),
        )
        decay_fresh = calculate_decay_factor(fresh_pref, now, cfg)
        self.assertAlmostEqual(decay_fresh, 1.0, places=2)

        # Old preference (confirmed 120 days ago = 2 half-lives)
        old_time = (now - timedelta(days=120)).isoformat()
        old_pref = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            last_confirmed_at=old_time,
        )
        decay_old = calculate_decay_factor(old_pref, now, cfg)
        self.assertLess(decay_old, 0.3)
        self.assertGreaterEqual(decay_old, cfg.min_decay_multiplier)

        # Stable fact (confirmed 120 days ago, half-life is 365 days)
        fact = MemoryRecord(
            category="fact",
            attribute="shoe_size",
            value="EU 42",
            last_confirmed_at=old_time,
        )
        decay_fact = calculate_decay_factor(fact, now, cfg)
        # Stable fact decays much slower than changeable preference
        self.assertGreater(decay_fact, decay_old)

    # =========================================================================
    # 3. End-of-Session Consolidation: ADD & Idempotency
    # =========================================================================
    def test_end_of_session_consolidation_add_and_idempotency(self):
        user_id = "bob"
        sid = self.session_store.create(user_id)
        with self.session_store.open(user_id, sid) as s:
            s.append("user_message", {"message": "I'm looking for gym wear. I usually wear black."})
            s.append("turn_completed", {"response": {"status": "ok"}})

        mock_policy = MockLLMPolicy({
            "reason": "Learned color preference for gym wear",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "gym wear",
                    "basis": "confirmed",
                    "quote": "I usually wear black.",
                    "confidence": 0.95,
                }
            ],
        })

        with self.session_store.open(user_id, sid) as s:
            res = consolidate_session(s, user_id, self.user_store, mock_policy)

        self.assertFalse(res.idempotent)
        self.assertEqual(res.revision, 1)
        self.assertEqual(len(res.operations_applied), 1)

        # Verify profile updated
        profile = self.user_store.read(user_id)
        self.assertEqual(profile.revision, 1)
        self.assertEqual(len(profile.records), 1)
        self.assertEqual(profile.records[0].value, "black")

        # Second consolidation on same session must be idempotent
        with self.session_store.open(user_id, sid) as s:
            res2 = consolidate_session(s, user_id, self.user_store, mock_policy)
        self.assertTrue(res2.idempotent)
        self.assertEqual(res2.revision, 1)

    # =========================================================================
    # 4. End-of-Session Consolidation: SUPERSEDE & Conflict Resolution
    # =========================================================================
    def test_consolidation_supersede_and_audit_trail(self):
        user_id = "charlie"
        # Seed initial preference: slim-fit
        rec = MemoryRecord(
            category="preference",
            attribute="fit",
            value="slim-fit",
            scope="workout shirts",
            quote="I prefer slim-fit shirts.",
            status="active",
        )
        with self.user_store._locked(user_id) as p:
            conn = self.user_store._init_db(p)
            prof = self.user_store.read(user_id)
            prof.records.append(rec)
            prof.revision = 1
            self.user_store.write_profile(prof, p, conn)
            conn.close()

        target_id = rec.id

        # New session: customer corrects preference
        sid = self.session_store.create(user_id)
        with self.session_store.open(user_id, sid) as s:
            s.append("user_message", {"message": "Actually, I no longer like slim-fit; I now prefer oversized shirts."})
            s.append("turn_completed", {"response": {"status": "ok"}})

        mock_policy = MockLLMPolicy({
            "reason": "Customer corrected fit preference from slim-fit to oversized",
            "operations": [
                {
                    "op": "SUPERSEDE",
                    "target_id": target_id,
                    "category": "preference",
                    "attribute": "fit",
                    "value": "oversized",
                    "scope": "workout shirts",
                    "quote": "Actually, I no longer like slim-fit; I now prefer oversized shirts.",
                }
            ],
        })

        with self.session_store.open(user_id, sid) as s:
            res = consolidate_session(s, user_id, self.user_store, mock_policy)

        self.assertEqual(res.revision, 2)
        prof_updated = self.user_store.read(user_id)

        # Exactly 1 active record with value "oversized"
        active = [r for r in prof_updated.records if r.status == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].value, "oversized")
        self.assertEqual(active[0].supersedes_id, target_id)

        # 1 superseded record retaining audit history
        superseded = [r for r in prof_updated.records if r.status == "superseded"]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].id, target_id)
        self.assertEqual(superseded[0].superseded_by_id, active[0].id)

    # =========================================================================
    # 5. Coexisting Non-Conflicting Scoped Preferences
    # =========================================================================
    def test_coexisting_scoped_preferences(self):
        user_id = "dana"
        # Preference 1: Black for workout clothing
        rec1 = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            scope="workout clothing",
            quote="I like black workout clothes.",
            status="active",
        )
        with self.user_store._locked(user_id) as p:
            conn = self.user_store._init_db(p)
            prof = self.user_store.read(user_id)
            prof.records.append(rec1)
            prof.revision = 1
            self.user_store.write_profile(prof, p, conn)
            conn.close()

        # Session 2: Customer specifies cream for formal clothing
        sid = self.session_store.create(user_id)
        with self.session_store.open(user_id, sid) as s:
            s.append("user_message", {"message": "For formal shirts, I generally prefer cream."})
            s.append("turn_completed", {"response": {"status": "ok"}})

        mock_policy = MockLLMPolicy({
            "reason": "New scoped preference for formal wear",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "cream",
                    "scope": "formal clothing",
                    "quote": "For formal shirts, I generally prefer cream.",
                }
            ],
        })

        with self.session_store.open(user_id, sid) as s:
            consolidate_session(s, user_id, self.user_store, mock_policy)

        prof_updated = self.user_store.read(user_id)
        active = [r for r in prof_updated.records if r.status == "active"]
        self.assertEqual(len(active), 2)
        scopes = {r.scope: r.value for r in active}
        self.assertEqual(scopes["workout clothing"], "black")
        self.assertEqual(scopes["formal clothing"], "cream")

    # =========================================================================
    # 6. Provenance Protection: Hallucinated Quote Rejection
    # =========================================================================
    def test_hallucinated_quote_rejection(self):
        user_id = "eve"
        sid = self.session_store.create(user_id)
        with self.session_store.open(user_id, sid) as s:
            s.append("user_message", {"message": "I want running shoes under $100."})
            s.append("turn_completed", {"response": {"status": "ok"}})

        # Policy invents a quote not spoken by the user
        mock_policy = MockLLMPolicy({
            "reason": "Invented preference",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "red",
                    "quote": "I always buy red shoes",  # NOT in user message
                }
            ],
        })

        with self.session_store.open(user_id, sid) as s:
            res = consolidate_session(s, user_id, self.user_store, mock_policy)

        self.assertEqual(len(res.operations_applied), 0)
        self.assertEqual(len(res.rejected_operations), 1)
        self.assertEqual(
            res.rejected_operations[0]["rejection_reason"],
            "quote_not_found_in_session_user_messages",
        )
        self.assertEqual(self.user_store.read(user_id).revision, 0)

    # =========================================================================
    # 7. Explicit Forgetting Immediate Withdrawal
    # =========================================================================
    def test_explicit_forgetting_immediate_withdrawal(self):
        user_id = "frank"
        # Seed preference
        rec = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            status="active",
        )
        with self.user_store._locked(user_id) as p:
            conn = self.user_store._init_db(p)
            prof = self.user_store.read(user_id)
            prof.records.append(rec)
            prof.revision = 1
            self.user_store.write_profile(prof, p, conn)
            conn.close()

        # Customer message with explicit forgetting instruction
        msg = "Please forget my color preference."
        withdrawn = self.user_store.check_and_apply_explicit_forgetting(user_id, msg)
        self.assertEqual(len(withdrawn), 1)
        self.assertEqual(withdrawn[0], rec.id)

        # Verify record is now deleted
        prof_after = self.user_store.read(user_id)
        self.assertEqual(prof_after.records[0].status, "deleted")

        # Context query does not retrieve it
        sid = self.session_store.create(user_id)
        with self.session_store.open(user_id, sid) as session:
            context = self.user_store.context(session, "workout clothes")
        self.assertEqual(len(context["records"]), 0)

    # =========================================================================
    # 8. Customer Isolation
    # =========================================================================
    def test_customer_isolation(self):
        user_alice = "alice_iso"
        user_bob = "bob_iso"

        # Alice has a preference
        rec_alice = MemoryRecord(
            category="preference",
            attribute="color",
            value="blue",
            status="active",
        )
        with self.user_store._locked(user_alice) as p:
            conn = self.user_store._init_db(p)
            prof = self.user_store.read(user_alice)
            prof.records.append(rec_alice)
            prof.revision = 1
            self.user_store.write_profile(prof, p, conn)
            conn.close()

        # Bob's query must not retrieve Alice's memory
        bob_results = self.user_store.retrieve(user_bob, "blue shirts")
        self.assertEqual(len(bob_results), 0)

    # =========================================================================
    # 9. Centralized Experience Distillation & Semantic Retrieval
    # =========================================================================
    def test_experience_distillation_and_semantic_retrieval(self):
        sid = self.session_store.create("anon-customer")
        with self.session_store.open("anon-customer", sid) as s:
            s.append("user_message", {"message": "I need red workout clothes."})
            s.append(
                "decision_validated",
                {
                    "action": {
                        "type": "CLARIFY",
                        "attribute": "style",
                        "question": "What style of workout clothing do you prefer?",
                    }
                },
            )
            s.append("user_message", {"message": "Sleeveless tops."})
            s.append(
                "decision_validated",
                {"action": {"type": "RECOMMEND", "product_ids": ["B001"]}},
            )

        mock_policy = MockLLMPolicy({
            "has_lesson": True,
            "situation": "Customer specifies clothing color but leaves style ambiguous",
            "strategy": "Clarify style before issuing recommendations",
            "rationale": "Narrowing style reduces irrelevant candidate pool",
            "directive": "Clarify style when color is specified but clothing style is ambiguous.",
            "expected_action": "CLARIFY",
            "trigger_type": "attribute_clarification",
            "trigger_condition": {"is_underspecified": True},
            "action_signature": {"attribute": "style"},
        })

        with self.session_store.open("anon-customer", sid) as s:
            distill_res = distill_session_experience(
                s,
                self.exp_store,
                mock_policy,
                outcome={"target_found": True},
            )

        self.assertTrue(distill_res.has_lesson)
        self.assertIn(distill_res.status, ("added", "reinforced"))
        lesson_id = distill_res.lesson.lesson_id

        # Verify lesson has no customer PII
        lesson = self.exp_store.get(lesson_id)
        self.assertNotIn("anon-customer", lesson.directive)
        self.assertNotIn("anon-customer", lesson.situation)

        # Semantic retrieval in a new, unseen session with a different customer
        new_query = "Looking for blue fitness apparel, what do you suggest?"
        matches = self.exp_store.retrieve_semantic(new_query, min_similarity=0.40)
        self.assertGreaterEqual(len(matches), 1)
        matched_lesson, score = matches[0]
        self.assertEqual(matched_lesson.expected_action, "CLARIFY")
        self.assertIn("style", matched_lesson.directive)

    # =========================================================================
    # 10. Target-Item Evaluation: Immediate Termination & Consolidation Lifecycle
    # =========================================================================
    def test_target_item_evaluation_lifecycle(self):
        user_id = "eval-target-user"
        rule = TargetRule("B001", k=5)

        # Scenario: Agent recommends B001 on Turn 1 -> Target found immediately!
        def search_shirts(ctx, updates=None):
            return decision(ctx, {"type": "SEARCH", "query": "shirt"}, updates)

        def scripted_turn(ctx):
            res = ctx["latest_search"]
            return decision(
                ctx,
                {
                    "type": "RECOMMEND",
                    "search_id": res["search_id"],
                    "product_ids": ["B001", "B002"],
                },
            )

        policy = MockLLMPolicy(
            # Turn 1 decision 1: search
            search_shirts,
            # Turn 1 decision 2: recommend target B001
            scripted_turn,
            # End-of-session memory consolidation response
            {
                "reason": "Consolidated evaluation session",
                "operations": [
                    {
                        "op": "ADD",
                        "category": "preference",
                        "attribute": "color",
                        "value": "black",
                        "quote": "I want black shirts.",
                    }
                ],
            },
        )

        agent = ShoppingAgent(
            self.session_store,
            self.search,
            policy,
            user_memory=self.user_store,
            auto_finalize=True,
        )

        class DummyProfile:
            opening_keys = []

            def fact(self, key):
                return None

        class DummyScenario:
            id = "scen-01"
            opening = "I want black shirts."
            max_user_turns = 6
            profile = DummyProfile()

        class DummySimulator:
            config = type("C", (), {"window_turns": 4})()

        runner = DialogueRunner(
            agent,
            self.session_store,
            DummySimulator(),
            run_id="test-run",
            user_id=user_id,
        )

        record = runner.run(
            DummyScenario(),
            condition="memory_on",
            transcript_path=self.root / "transcript.jsonl",
            target_rule=rule,
            turn_limit=6,
        )

        # 1. Immediate termination on target recommendation
        self.assertEqual(record.termination, "target_found")
        self.assertIsNotNone(record.target_hit)
        self.assertEqual(record.target_hit["turn"], 1)
        self.assertEqual(record.target_hit["rank"], 1)

        # 2. Consolidation triggered on session end
        profile = self.user_store.read(f"{user_id}-scen-01")
        self.assertEqual(profile.revision, 1)
        self.assertEqual(len(profile.records), 1)
        self.assertEqual(profile.records[0].value, "black")


if __name__ == "__main__":
    unittest.main()
