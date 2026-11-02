import tempfile
import unittest
from pathlib import Path

from shopping_agent.experience.models import Lesson
from shopping_agent.experience.store import ExperienceStore
from shopping_agent.inspect_memory import (
    inspect_experience_memory,
    inspect_user_memory,
)
from shopping_agent.user_memory import UserMemoryStore


class TestInspectMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_user_memory(self):
        mem_dir = self.root / "user-memory"
        store = UserMemoryStore(mem_dir)

        # Apply initial additions
        res = store.apply_consolidation_operations(
            "alice",
            "sess-01",
            [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "Black",
                    "scope": "general",
                    "quote": "I love black.",
                },
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "fit",
                    "value": "Slim",
                    "scope": "shirts",
                    "quote": "Slim shirts.",
                },
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "budget",
                    "value": "under 50",
                    "scope": "shoes",
                    "quote": "Shoes under 50.",
                },
            ],
        )
        rec1_id, rec2_id, rec3_id = res["ids"]

        # Replace rec2 and retract rec3 in a second session
        store.apply_consolidation_operations(
            "alice",
            "sess-02",
            [
                {
                    "op": "REPLACE",
                    "target_id": rec2_id,
                    "category": "preference",
                    "attribute": "fit",
                    "value": "Relaxed",
                    "scope": "shirts",
                    "quote": "Actually relaxed shirts now.",
                },
                {
                    "op": "RETRACT",
                    "target_id": rec3_id,
                    "category": "preference",
                    "attribute": "budget",
                    "value": "under 50",
                    "scope": "shoes",
                    "quote": "Nevermind the budget.",
                },
            ],
        )

        summary = inspect_user_memory("alice", root=mem_dir)
        self.assertEqual(summary["user_id"], "alice")
        self.assertEqual(summary["revision"], 2)
        self.assertEqual(summary["last_consolidated_session_id"], "sess-02")
        self.assertEqual(summary["active_count"], 2)  # rec1 and new relaxed fit
        self.assertEqual(summary["superseded_count"], 1)  # rec2
        self.assertEqual(summary["deleted_count"], 1)  # rec3

    def test_inspect_experience_memory(self):
        db_path = self.root / "experience.sqlite"
        store = ExperienceStore(db_path)
        lesson = Lesson(
            lesson_id="exp-test-01",
            scope="*",
            trigger_type="initial_query",
            trigger_condition={"is_initial": True},
            directive="Use primary category nouns in initial query.",
            expected_action="SEARCH",
            action_signature={"mode": "all"},
            observed_outcome="empty_search",
            hypothesized_cause="Query combined too many adjectives.",
            evidence={
                "source_scenario_id": "learn-001",
                "source_split": "learning",
                "turn": 1,
            },
            status="candidate",
        )
        store.add_candidate(lesson)
        store.confirm(lesson.lesson_id, review_notes="Tested in staging")
        store.activate(lesson.lesson_id)

        summary = inspect_experience_memory(db_path)
        self.assertEqual(summary["total_lessons"], 1)
        self.assertEqual(summary["active_lessons"], 1)
        self.assertEqual(summary["candidate_lessons"], 0)
        self.assertEqual(summary["lessons"][0]["lesson_id"], "exp-test-01")


if __name__ == "__main__":
    unittest.main()
