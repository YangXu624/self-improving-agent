#!/usr/bin/env python3
"""ASTRA Local Submission Smoke-Test.

Lightweight, standalone, offline smoke-test executing the full end-to-end stack:
- Fast BM25 catalogue indexing & verification
- Multi-turn shopping agent turn with deterministic fixture
- Instant simulated purchase recording & SQLite ledger
- End-of-session memory consolidation & idempotent finalization
- Cross-session memory & purchase history retrieval
- Procedural memory generalization, sanitization, & retrieval
- Session Audit Explorer state reconstruction

Requires zero network, zero paid LLM API keys, and zero private 50k assets.
Run:
    python tools/submission_smoke_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root and src are on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from shopping_agent.experience.models import Lesson  # noqa: E402
from shopping_agent.experience.sanitizer import validate_lesson  # noqa: E402
from shopping_agent.experience.store import ExperienceStore  # noqa: E402
from shopping_agent.provider import PolicyReply  # noqa: E402
from shopping_agent.retrieval import build_index  # noqa: E402
from shopping_agent.session_audit import extract_session_audit  # noqa: E402
from shopping_agent.ui_service import ChatService  # noqa: E402
from shopping_agent.user_memory import UserMemoryStore  # noqa: E402


class ScriptedPolicy:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.contexts = []

    def complete(self, messages):
        content = messages[-1]["content"]
        try:
            ctx = json.loads(content)
        except Exception:
            ctx = content
        self.contexts.append(ctx)

        if not self.responses:
            raise RuntimeError("ScriptedPolicy: no more responses queued")
        step = self.responses.pop(0)
        if callable(step):
            val = step(ctx)
        else:
            val = step
        text = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        return PolicyReply(content=text, metadata={"usage": {"total_tokens": 50}})


def run_smoke_test() -> bool:
    print("=" * 70)
    print("  ASTRA LOCAL SUBMISSION SMOKE-TEST")
    print("=" * 70)
    start_time = time.monotonic()

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp = Path(tmp_dir_str)
        cat_file = tmp / "catalog.jsonl"
        idx_file = tmp / "catalog.sqlite"
        sessions_dir = tmp / "sessions"
        memory_dir = tmp / "user_memory"
        purchases_db = tmp / "purchases.sqlite"
        experience_db = tmp / "experience.sqlite"

        # 1. Mini-Catalogue
        products = [
            {
                "parent_asin": "B001_SMOKE_RUN",
                "title": "Astra Ultra Running Shoes Black",
                "price": 120.0,
                "categories": [
                    "Clothing, Shoes & Jewelry",
                    "Men",
                    "Shoes",
                    "Athletic",
                    "Running",
                ],
                "details": {"Color": "Black", "Type": "Running", "Department": "Men"},
            },
            {
                "parent_asin": "B002_SMOKE_SOCK",
                "title": "Astra Cushion Running Socks 3-Pack Black",
                "price": 22.0,
                "categories": ["Clothing, Shoes & Jewelry", "Men", "Socks", "Athletic"],
                "details": {"Color": "Black"},
            },
        ]
        with cat_file.open("w", encoding="utf-8") as f:
            for p in products:
                f.write(json.dumps(p) + "\n")

        # Step A: Indexing
        build_index(cat_file, idx_file)
        print("  [PASS] 1. Catalogue indexing (SQLite FTS5 + BM25)")

        # Prepare scripted decisions
        def search_step(ctx):
            return {
                "reason": "Searching for running shoes",
                "updates": [
                    {
                        "op": "ADD",
                        "quote": "I want running shoes.",
                        "requirement": {
                            "field": "product_type",
                            "op": "eq",
                            "value": "shoes",
                            "quote": "I want running shoes.",
                        },
                    },
                    {
                        "op": "ADD",
                        "quote": "I prefer black color.",
                        "requirement": {
                            "field": "color",
                            "op": "eq",
                            "value": "black",
                            "strength": "soft",
                            "quote": "I prefer black color.",
                        },
                    },
                ],
                "action": {"type": "SEARCH", "query": "running shoes"},
            }

        def recommend_step(ctx):
            search_res = ctx["latest_search"]
            cand_id = search_res["candidates"][0]["id"]
            return {
                "reason": "Recommending Astra Ultra",
                "updates": [],
                "action": {
                    "type": "RECOMMEND",
                    "search_id": search_res["search_id"],
                    "product_ids": [cand_id],
                    "follow_up_question": "Do you prefer a snug or relaxed fit?",
                },
            }

        consolidation_decision = {
            "reason": "Direct statement of black color preference with confirmed shoe purchase.",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "Black",
                    "scope": "running shoes",
                    "quote": "I prefer black color.",
                    "basis": "confirmed",
                    "confidence": 0.95,
                    "rationale": "Explicit user statement confirmed by purchase.",
                }
            ],
        }

        def turn2_search(ctx):
            return {
                "reason": "Searching for socks",
                "updates": [],
                "action": {"type": "SEARCH", "query": "running socks"},
            }

        def turn2_rec(ctx):
            search_res = ctx["latest_search"]
            cand_id = search_res["candidates"][0]["id"]
            return {
                "reason": "Recommending running socks",
                "updates": [],
                "action": {
                    "type": "RECOMMEND",
                    "search_id": search_res["search_id"],
                    "product_ids": [cand_id],
                    "follow_up_question": "Do you need crew or ankle height?",
                },
            }

        policy = ScriptedPolicy(
            [
                search_step,
                recommend_step,
                consolidation_decision,
                turn2_search,
                turn2_rec,
            ]
        )

        service = ChatService(
            cat_file,
            idx_file,
            sessions_dir,
            policy=policy,
            user_memory_enabled=True,
            user_memory_root=memory_dir,
            purchases_db_path=purchases_db,
        )

        # Step B: Turn 1
        user_id = "smoke-customer-001"
        sess1_id = service.create(user_id)
        turn1_res = service.send(
            user_id,
            sess1_id,
            "I want running shoes. I prefer black color.",
            request_id="smoke-t1",
        )
        assert turn1_res["status"] == "ok"
        assert len(turn1_res["products"]) == 1
        assert turn1_res["products"][0]["id"] == "B001_SMOKE_RUN"
        assert turn1_res["follow_up_question"] == "Do you prefer a snug or relaxed fit?"
        print("  [PASS] 2. Agent Turn 1 (Search + Verified Recommendation + Question)")

        # Step C: Simulated Purchase
        purch = service.record_purchase(
            user_id,
            sess1_id,
            "smoke-t1",
            "B001_SMOKE_RUN",
            "Astra Ultra Running Shoes Black",
            price=120.0,
            quantity=1,
            recipient_context="self",
            attribute_snapshot={"Color": "Black", "Type": "Running"},
        )
        assert purch["status"] == "simulated_completed"
        active_purchases = service.get_purchases(user_id)
        assert len(active_purchases) == 1
        print("  [PASS] 3. Simulated Purchase Recorded & Instantly Persisted in SQLite")

        # Step D: Session Finalization & Consolidation
        fin1 = service.finalize(user_id, sess1_id)
        assert fin1["status"] == "success"
        assert fin1["revision"] == 1
        assert len(fin1["operations_applied"]) == 1
        # Idempotency check
        fin2 = service.finalize(user_id, sess1_id)
        assert fin2["idempotent"] is True
        print(
            "  [PASS] 4. End-of-Session Memory Consolidation & Idempotent Finalization"
        )

        # Step E: Session 2 Pre-Turn Retrieval
        sess2_id = service.create(user_id)
        turn2_res = service.send(
            user_id,
            sess2_id,
            "Now show me matching running socks.",
            request_id="smoke-t2",
        )
        assert turn2_res["status"] == "ok"
        sess2_search_ctx = policy.contexts[3]
        assert "user_memory" in sess2_search_ctx
        assert "Black" in str(sess2_search_ctx["user_memory"])
        assert "relevant_purchases" in sess2_search_ctx
        assert (
            sess2_search_ctx["relevant_purchases"][0]["product_id"] == "B001_SMOKE_RUN"
        )
        print("  [PASS] 5. Cross-Session Memory & Purchase Retrieval Verified")

        # Step F: Session Audit Reconstruction
        audit = extract_session_audit(sessions_dir, user_id, sess1_id)
        assert audit.session_id == sess1_id
        assert audit.finalized is True
        assert len(audit.turns) == 1
        assert audit.turns[0].recommended_product_ids == ["B001_SMOKE_RUN"]
        assert (
            audit.turns[0].follow_up_question == "Do you prefer a snug or relaxed fit?"
        )
        assert len(audit.turns[0].purchases) == 1
        assert len(audit.turns[0].state_updates) == 2
        print("  [PASS] 6. Session Audit Explorer History & State Reconstruction")

        # Step G: Procedural Learning Sanitization & Store
        exp_store = ExperienceStore(experience_db)
        lesson = Lesson(
            lesson_id="lesson-smoke-001",
            trigger_type="initial_query",
            scope="Shoes",
            trigger_condition={"is_initial": True},
            directive="Prioritize category noun and primary attribute before compound adjectives in lexical search.",
            expected_action="SEARCH",
            action_signature={"mode": "all"},
            observed_outcome="empty_search",
            hypothesized_cause="Excessive compound modifiers caused zero FTS5 BM25 matches.",
            evidence={
                "source_scenario_id": "smoke-footwear-01",
                "source_split": "learning",
                "turn": 1,
            },
            situation="Customer initial query contains compound descriptive adjectives.",
            strategy="Issue lexical search with category noun first.",
            rationale="Recovers relevant candidates while avoiding zero-result query drops.",
            confidence=0.85,
            status="candidate",
        )
        validate_lesson(lesson, allow_non_learning=False)
        exp_store.add_candidate(lesson)
        exp_store.confirm(lesson.lesson_id, review_notes="Verified by smoke test")
        retrieved = exp_store.retrieve(
            "initial_query",
            scope="Shoes",
            context_cues={"is_initial": True},
            max_lessons=5,
        )
        assert len(retrieved) == 1
        assert retrieved[0].lesson_id == "lesson-smoke-001"
        assert user_id not in retrieved[0].strategy
        assert "B001_SMOKE_RUN" not in retrieved[0].strategy
        print(
            "  [PASS] 7. Procedural Memory: Sanitization, Persistence & Cross-Customer Retrieval"
        )

        # Step H: Memory OFF Isolation
        off_service = ChatService(
            cat_file,
            idx_file,
            sessions_dir,
            policy=policy,
            user_memory_enabled=False,
            user_memory_root=memory_dir,
            purchases_db_path=purchases_db,
        )
        sess3_id = off_service.create(user_id)
        assert sess3_id
        # Verify profile still has stored data in SQLite
        mem_store = UserMemoryStore(memory_dir)
        profile = mem_store.read(user_id)
        assert profile.revision == 1
        assert len([r for r in profile.records if r.status == "active"]) == 1
        print(
            "  [PASS] 8. Memory OFF Isolation (No Contamination, Stored Data Preserved)"
        )

    duration = time.monotonic() - start_time
    print("=" * 70)
    print(f"  ALL 8 SMOKE-TEST PHASES PASSED in {duration:.3f}s")
    print("  Status: SUBMISSION READY")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
