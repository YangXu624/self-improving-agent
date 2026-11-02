"""Unit tests for Phase 2: Memory Retrieval and Selection."""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shopping_agent.consolidation import ConsolidationOperation
from shopping_agent.contracts import Requirement
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore


class TestMemoryRetrieval(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = UserMemoryStore(root=self.root / "users")
        self.sessions = SessionStore(self.root / "sessions")
        self.user_id = "test-retrieval-user"
        self.sid = self.sessions.create(self.user_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_active_embedding_provider_reported(self):
        """Active embedding provider name is exposed and not silently hidden."""
        provider_name = self.store.embedding_provider_name
        self.assertTrue(bool(provider_name))
        self.assertIn(
            provider_name, ["deterministic-local", "fastembed (BAAI/bge-small-en-v1.5)"]
        )

    def test_semantic_retrieval_workout_to_gym_shirt(self):
        """Workout clothing preference is semantically relevant to a gym shirt request."""
        op = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="black",
            scope="workout clothing",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I usually buy black workout clothing.",
        )
        self.store.apply_consolidation_operations(self.user_id, "s1", [op.model_dump()])

        with self.sessions.open(self.user_id, self.sid) as session:
            ctx = self.store.context(session, "Find an affordable gym shirt under $45.")

        self.assertEqual(len(ctx["candidates"]), 1)
        self.assertEqual(len(ctx["records"]), 1)
        self.assertEqual(ctx["records"][0]["value"], "black")
        self.assertEqual(ctx["records"][0]["scope"], "workout clothing")
        self.assertEqual(len(ctx["ignored"]), 0)

    def test_irrelevant_memory_retrieved_in_stage_a_but_ignored_in_stage_b(self):
        """Prefers black workout clothing is retrieved for broad candidate pool, but ignored when shopping for a formal suit."""
        op = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="black",
            scope="workout clothing",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I usually buy black workout clothing.",
        )
        self.store.apply_consolidation_operations(self.user_id, "s1", [op.model_dump()])

        with self.sessions.open(self.user_id, self.sid) as session:
            ctx = self.store.context(session, "Recommend a formal suit for a gala.")

        # Stage A retrieved it (small profile retention or broad semantic match)
        self.assertEqual(len(ctx["candidates"]), 1)
        # Stage B explicitly filtered it out!
        self.assertEqual(len(ctx["records"]), 0)
        self.assertEqual(len(ctx["ignored"]), 1)
        ignored = ctx["ignored"][0]
        self.assertEqual(ignored["id"], op.attribute and ctx["candidates"][0]["id"])
        self.assertIn("formal", ignored["ignore_reason"].lower())

    def test_gift_recipient_conflict_overrides_personal_preference(self):
        """User prefers black bags, but is shopping for a red bag for sister: personal preference is ignored/conflicting."""
        op = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="black",
            scope="bags",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I usually prefer black bags.",
        )
        self.store.apply_consolidation_operations(self.user_id, "s1", [op.model_dump()])

        with self.sessions.open(self.user_id, self.sid) as session:
            ctx = self.store.context(session, "Find a red bag for my sister.")

        self.assertEqual(len(ctx["candidates"]), 1)
        # Not applied to current recommendation context
        self.assertEqual(len(ctx["records"]), 0)
        self.assertEqual(len(ctx["ignored"]), 1)
        self.assertIn("sister", ctx["ignored"][0]["ignore_reason"].lower())

    def test_direct_conflict_with_current_requirement_ignored(self):
        """Current request explicitly asks for blue shirt, overriding historical black preference."""
        op = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="black",
            scope="clothing",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I usually prefer black clothing.",
        )
        self.store.apply_consolidation_operations(self.user_id, "s1", [op.model_dump()])

        with self.sessions.open(self.user_id, self.sid) as session:
            # Add active state requirement: color == "blue"
            session.state.requirements.append(
                Requirement(
                    id="req-1",
                    field="color",
                    op="eq",
                    value="blue",
                    strength="hard",
                    quote="I need a blue shirt",
                    status="active",
                    source_event_id="ev-1",
                    created_version=1,
                )
            )
            ctx = self.store.context(session, "Find a blue dress shirt.")

        self.assertEqual(len(ctx["candidates"]), 1)
        self.assertEqual(len(ctx["records"]), 0)
        self.assertEqual(len(ctx["ignored"]), 1)
        self.assertIn("blue", ctx["ignored"][0]["ignore_reason"].lower())

    def test_old_memory_with_decay_remains_usable(self):
        """Older memory decays in prioritization score, but remains usable if still relevant."""
        now = datetime.now(UTC)
        past_60_days = (now - timedelta(days=60)).isoformat()

        op = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="navy",
            scope="jackets",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I like navy jackets.",
        )
        self.store.apply_consolidation_operations(
            self.user_id, "s-old", [op.model_dump()]
        )

        profile = self.store.read(self.user_id)
        profile.records[0].created_at = past_60_days
        profile.records[0].last_confirmed_at = past_60_days
        user_dir = self.store.directory(self.user_id)
        conn = self.store._init_db(user_dir)
        try:
            self.store.write_profile(profile, user_dir, conn)
        finally:
            conn.close()

        with self.sessions.open(self.user_id, self.sid) as session:
            ctx = self.store.context(session, "Looking for a warm winter jacket.")

        self.assertEqual(len(ctx["records"]), 1)
        self.assertEqual(ctx["records"][0]["value"], "navy")
        self.assertGreater(ctx["records"][0]["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
