"""Unit and regression tests for Developer Console, RuntimeConfig, and Execution Trace."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from test_retrieval import product

from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import build_index
from shopping_agent.runtime_config import (
    DEMO_PRESET,
    EVALUATION_PRESET,
    ConfigurationError,
    RuntimeConfig,
)
from shopping_agent.trace import TraceExtractor, diagnose_turn_failure
from shopping_agent.ui_service import DEFAULT_MANUAL_USER_ID, ChatService
from shopping_agent.user_memory import MemoryRecord, UserProfile


class DeveloperConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.catalogue = self.root / "catalog.jsonl"
        self.index = self.root / "index.sqlite"
        self.sessions = self.root / "sessions"
        self.user_memory_root = self.root / "user-memory"

        rows = [
            product("boot-black-01", 85, Color="Black", ProductType="Boots"),
            product("boot-brown-01", 95, Color="Brown", ProductType="Boots"),
            product("boot-red-01", 120, Color="Red", ProductType="Boots"),
        ]
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.catalogue, self.index)

        self.mock_policy = MagicMock()
        self.service = ChatService(
            self.catalogue,
            self.index,
            self.sessions,
            policy=self.mock_policy,
            user_memory_enabled=True,
            user_memory_root=self.user_memory_root,
        )

    def test_runtime_config_bounds_and_presets(self):
        """RuntimeConfig validates parameter limits and exports/loads JSON presets."""
        cfg = RuntimeConfig()
        self.assertEqual(cfg.agent_max_calls, 3)
        self.assertEqual(cfg.agent_max_searches, 2)
        self.assertEqual(cfg.timeout, 25.0)

        # Invalid bounds raise ConfigurationError
        with self.assertRaises(ConfigurationError):
            RuntimeConfig(agent_max_calls=0)
        with self.assertRaises(ConfigurationError):
            RuntimeConfig(agent_max_calls=7)
        with self.assertRaises(ConfigurationError):
            RuntimeConfig(agent_max_searches=4)
        with self.assertRaises(ConfigurationError):
            RuntimeConfig(user_memory_similarity_threshold=0.95)
        with self.assertRaises(ConfigurationError):
            RuntimeConfig(session_api_cost_ceiling_usd=0.05)

        # Presets are valid
        DEMO_PRESET.validate()
        EVALUATION_PRESET.validate()

        # Serialization roundtrip
        serialized = cfg.to_json()
        loaded = RuntimeConfig.from_json(serialized)
        self.assertEqual(loaded.agent_max_calls, cfg.agent_max_calls)
        self.assertEqual(loaded.timeout, cfg.timeout)

    def test_backend_respects_configured_search_limit(self):
        """ShoppingAgent respects configured agent_max_searches."""
        custom_cfg = RuntimeConfig(agent_max_searches=1, agent_max_calls=3)
        user_id = DEFAULT_MANUAL_USER_ID
        sid = self.service.create(user_id, runtime_config=custom_cfg)

        # Mock policy to issue search on attempt 1, and search on attempt 2
        search_reply = json.dumps(
            {
                "updates": [],
                "action": {
                    "type": "SEARCH",
                    "query": "boots",
                    "mode": "all",
                    "limit": 5,
                },
                "reason": "first search",
            }
        )
        self.mock_policy.complete.return_value = PolicyReply(search_reply, {})

        # Turn 1
        res = self.service.send(
            user_id, sid, "I need boots", "req-1", runtime_config=custom_cfg
        )
        # Second search should be blocked because max_searches = 1
        budget = res.get("budget_used", {})
        self.assertEqual(budget.get("searches"), 1)

    def test_backend_respects_configured_call_limit(self):
        """ShoppingAgent respects configured agent_max_calls."""
        custom_cfg = RuntimeConfig(agent_max_calls=2, agent_max_searches=2)
        user_id = DEFAULT_MANUAL_USER_ID
        sid = self.service.create(user_id, runtime_config=custom_cfg)

        # Mock policy to continuously return empty updates without terminal action
        invalid_reply = json.dumps(
            {
                "updates": [],
                "action": {
                    "type": "SEARCH",
                    "query": "boots",
                    "mode": "all",
                    "limit": 5,
                },
                "reason": "search boots",
            }
        )
        self.mock_policy.complete.return_value = PolicyReply(invalid_reply, {})

        res = self.service.send(
            user_id, sid, "I need boots", "req-calls", runtime_config=custom_cfg
        )
        budget = res.get("budget_used", {})
        self.assertEqual(budget.get("model_calls"), 2)

    def test_memory_similarity_threshold_changes_retrieval(self):
        """Higher memory similarity threshold filters out borderline memories."""
        user_id = DEFAULT_MANUAL_USER_ID

        # Seed memory store with a memory record
        rec = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            scope="boots",
            basis="confirmed",
            quote="I like black boots.",
            status="active",
        )
        with self.service._user_memory_store._locked(user_id) as p:
            conn = self.service._user_memory_store._init_db(p)
            try:
                prof = UserProfile(user_id=user_id, revision=1, records=[rec])
                self.service._user_memory_store.write_profile(prof, p, conn)
            finally:
                conn.close()

        # With generous threshold (0.20), memory is retrieved
        low_thresh_cfg = RuntimeConfig(user_memory_similarity_threshold=0.20)
        sid1 = self.service.create(user_id, runtime_config=low_thresh_cfg)
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {"type": "RESPOND", "message": "Hi"},
                    "reason": "hi",
                }
            ),
            {},
        )
        res1 = self.service.send(
            user_id, sid1, "I need boots", "req-low", runtime_config=low_thresh_cfg
        )
        injected1 = res1.get("user_memory", {}).get("injected", [])
        self.assertIn(rec.id, injected1)

        # With very strict threshold (0.90), borderline memory is skipped
        high_thresh_cfg = RuntimeConfig(user_memory_similarity_threshold=0.90)
        sid2 = self.service.create(user_id, runtime_config=high_thresh_cfg)
        res2 = self.service.send(
            user_id, sid2, "I need footwear", "req-high", runtime_config=high_thresh_cfg
        )
        injected2 = res2.get("user_memory", {}).get("injected", [])
        self.assertEqual(len(injected2), 0)

    def test_trace_extractor_stages_and_failure_diagnosis(self):
        """TraceExtractor extracts 13 stages and diagnoses specific failure causes."""
        user_id = DEFAULT_MANUAL_USER_ID
        sid = self.service.create(user_id)

        # Cause search budget exhausted by exceeding searches
        cfg = RuntimeConfig(agent_max_searches=1, agent_max_calls=3)
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {
                        "type": "SEARCH",
                        "query": "boots",
                        "mode": "all",
                        "limit": 5,
                    },
                    "reason": "search boots",
                }
            ),
            {},
        )
        res = self.service.send(
            user_id, sid, "Boots please", "req-trace", runtime_config=cfg
        )

        view = self.service.view(user_id, sid)
        stages = TraceExtractor.extract_turn_trace(
            view["events"], request_id="req-trace", turn_result=res
        )
        self.assertEqual(len(stages), 13)

        # Check stage names
        stage_ids = [s.stage_id for s in stages]
        self.assertIn("receive_message", stage_ids)
        self.assertIn("call_llm", stage_ids)
        self.assertIn("execute_search", stage_ids)
        self.assertIn("filter_hard_constraints", stage_ids)
        self.assertIn("consolidate_user_memory", stage_ids)

        # Diagnosis
        diag = diagnose_turn_failure(view["events"], res)
        self.assertIsNotNone(diag)

    def test_session_config_snapshot_reproducibility(self):
        """Creating a session records session_config_snapshot, preserving reproducibility across turns."""
        user_id = DEFAULT_MANUAL_USER_ID
        cfg = RuntimeConfig(agent_max_calls=4, agent_max_searches=1)
        sid = self.service.create(user_id, runtime_config=cfg)

        view = self.service.view(user_id, sid)
        snapshot = view.get("config_snapshot")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.get("agent_max_calls"), 4)
        self.assertEqual(snapshot.get("agent_max_searches"), 1)

        # Subsequent send without explicit config override uses session snapshot
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {"type": "RESPOND", "message": "Hi"},
                    "reason": "hi",
                }
            ),
            {},
        )
        res = self.service.send(user_id, sid, "Hello", "req-snap")
        self.assertEqual(res["status"], "ok")


if __name__ == "__main__":
    unittest.main()
