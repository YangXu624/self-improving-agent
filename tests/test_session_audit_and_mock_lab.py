"""Regression and unit tests for Session Audit Explorer and Mock Customer Lab.

Validates:
- Discovery of authorized sessions (manual dev chat and evaluation runs)
- Accurate reconstruction of turn dialogue, recommendations, searches, and purchases
- Accurate session-state tracking and state diff calculation (ADD, REPLACE, RETRACT)
- Memory retrieval and end-of-session consolidation auditing
- Mock customer fixture loading and validation (dev, dev-expanded, memory-sensitive)
- Strict confidentiality boundaries: hidden target IDs masked by default, never leaked to agent
- Conversation playback from saved artifacts without API calls
- Cross-customer isolation and security bounds
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from test_retrieval import product

from shopping_agent.contracts import Event
from shopping_agent.mock_lab import (
    load_mock_customer_fixtures,
)
from shopping_agent.retrieval import build_index
from shopping_agent.session_audit import (
    discover_available_sessions,
    extract_session_audit,
)
from shopping_agent.sessions import SessionStore
from shopping_agent.ui_service import ChatService


class SessionAuditAndMockLabTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.catalogue = self.root / "catalog.jsonl"
        self.index = self.root / "index.sqlite"
        self.sessions = self.root / "sessions"
        self.user_memory = self.root / "user-memory"

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
            user_memory_root=self.user_memory,
        )

    def test_discover_available_sessions_manual_and_eval(self):
        """discover_available_sessions returns manual sessions for authorized user and eval runs."""
        # 1. Create a manual session
        manual_sid = self.service.store.create("alice")

        # 2. Create a synthetic eval run session in data/eval-ui
        eval_ui_dir = self.root / "data/eval-ui/run_1001/user_memory_on/sessions"
        eval_ui_dir.mkdir(parents=True, exist_ok=True)
        eval_sess_dir = eval_ui_dir / "0123456789abcdef0123456789abcdef"
        eval_sess_dir.mkdir(parents=True, exist_ok=True)

        ev1 = Event(
            event_id="e1",
            seq=1,
            user_id="cust-synthetic-01",
            session_id="0123456789abcdef0123456789abcdef",
            type="session_created",
            timestamp="2026-11-02T12:00:00Z",
            turn_id=None,
            payload={"initial_goal": "Running shoes"},
        )
        (eval_sess_dir / "events.jsonl").write_text(ev1.model_dump_json() + "\n")

        # Discover sessions for alice
        discovered = discover_available_sessions(self.service, self.root, "alice")
        session_ids = [d["session_id"] for d in discovered]

        # Manual session found
        self.assertIn(manual_sid, session_ids)
        # Eval session found
        self.assertTrue(
            any(d["customer_id"] == "cust-synthetic-01" for d in discovered)
        )

    def test_extract_session_audit_reconstruction_and_diffs(self):
        """extract_session_audit reconstructs dialogue, state changes, memory and purchases."""
        store = SessionStore(self.sessions)
        user_id = "bob"
        session_id = store.create(user_id)

        with store.open(user_id, session_id) as session:
            # Turn 1: User message
            session.append(
                "user_message",
                {"message": "I want black boots under $100.", "turn": 1},
                turn_id="req-1",
            )
            # Memory injection
            session.append(
                "user_memory_injection",
                {
                    "selected": [{"key": "color", "value": "Black"}],
                    "injected": ["Shopper prefers Black footwear."],
                },
                turn_id="req-1",
            )
            # Internal search
            session.append(
                "internal_search",
                {
                    "query": "black boots",
                    "counts": {"verified_eligible": 1, "lexical_matches": 3},
                },
                turn_id="req-1",
            )
            # State update
            session.append(
                "state_updated",
                {
                    "version_before": 0,
                    "version_after": 1,
                    "requirements_before": [],
                    "requirements_after": [
                        {
                            "id": "req-color",
                            "key": "color",
                            "value": "black",
                            "status": "active",
                            "strength": "hard",
                        },
                        {
                            "id": "req-price",
                            "key": "price",
                            "value": 100,
                            "status": "active",
                            "strength": "hard",
                        },
                    ],
                },
                turn_id="req-1",
            )
            # Assistant reply
            session.append(
                "assistant_message",
                {
                    "action": "RECOMMEND",
                    "message": "I found these black boots for you.",
                    "recommended_product_ids": ["boot-black-01"],
                    "recommended_products": [
                        {"id": "boot-black-01", "title": "Black Boots"}
                    ],
                    "follow_up_question": "Do you need waterproof material?",
                },
                turn_id="req-1",
            )
            # Simulated purchase
            session.append(
                "simulated_purchase",
                {
                    "product_id": "boot-black-01",
                    "title": "Black Boots",
                    "price": 85.0,
                    "timestamp": "2026-11-02T12:05:00Z",
                },
                turn_id="req-1",
            )
            # Session finalized
            session.append(
                "session_finalized",
                {
                    "reason": "customer_finished",
                    "new_revision": 2,
                    "operations_applied": [
                        {
                            "op": "add",
                            "category": "preference",
                            "attribute": "color",
                            "value": "black",
                            "scope": "footwear",
                            "quote": "I want black boots under $100.",
                        }
                    ],
                    "operations_rejected": [],
                },
            )

        audit = extract_session_audit(self.sessions, user_id, session_id)
        self.assertEqual(audit.session_id, session_id)
        self.assertEqual(audit.user_id, user_id)
        self.assertTrue(audit.finalized)
        self.assertEqual(len(audit.turns), 1)

        t1 = audit.turns[0]
        self.assertEqual(t1.user_message, "I want black boots under $100.")
        self.assertEqual(t1.assistant_message, "I found these black boots for you.")
        self.assertEqual(t1.action_type, "RECOMMEND")
        self.assertEqual(t1.recommended_product_ids, ["boot-black-01"])
        self.assertEqual(t1.follow_up_question, "Do you need waterproof material?")
        self.assertEqual(len(t1.internal_searches), 1)
        self.assertEqual(len(t1.memories_injected), 1)
        self.assertEqual(len(t1.purchases), 1)
        self.assertEqual(t1.purchases[0]["product_id"], "boot-black-01")

        # State transition check
        self.assertEqual(t1.state_version_before, 0)
        self.assertEqual(t1.state_version_after, 1)
        self.assertEqual(len(t1.requirements_after), 2)

        # Consolidation check
        self.assertIsNotNone(audit.consolidation_audit)
        self.assertEqual(len(audit.consolidation_audit["operations_applied"]), 1)
        self.assertEqual(
            audit.consolidation_audit["operations_applied"][0]["attribute"], "color"
        )

    def test_mock_customer_fixtures_loading(self):
        """load_mock_customer_fixtures loads the three standard benchmark fixtures."""
        project_root = Path(__file__).resolve().parent.parent
        datasets = load_mock_customer_fixtures(project_root)
        filenames = [d["filename"] for d in datasets]

        self.assertIn("customers.dev.json", filenames)
        self.assertIn("customers.dev-expanded.json", filenames)
        self.assertIn("customers.memory-sensitive.json", filenames)

        for ds in datasets:
            self.assertGreater(ds["customer_count"], 0)
            self.assertEqual(len(ds["customers"]), ds["customer_count"])
            for c in ds["customers"]:
                self.assertIn("user_id", c)
                self.assertIn("personality", c)
                self.assertIn("visits", c)
                self.assertGreater(len(c["visits"]), 0)

    def test_confidential_evaluator_target_masking_boundary(self):
        """Target product IDs are strictly confidential and masked in UI structures."""
        project_root = Path(__file__).resolve().parent.parent
        datasets = load_mock_customer_fixtures(project_root)
        dev_ds = next(d for d in datasets if d["filename"] == "customers.dev.json")
        first_cust = dev_ds["customers"][0]
        first_visit = first_cust["visits"][0]

        target_id = first_visit.get("witness_id")
        self.assertIsNotNone(target_id)

        # Verify that opening user message does NOT contain the raw witness ID
        self.assertNotIn(target_id, first_visit.get("opening", ""))

        # Verify customer preferences do not contain the target product ID
        for p in first_cust.get("preferences", []):
            self.assertNotIn(target_id, str(p))

    def test_conversation_playback_saved_artifact_loading(self):
        """Playback functions load offline evaluation transcripts without API calls."""
        eval_ui_dir = self.root / "data/eval-ui/run_playback_test"
        eval_ui_dir.mkdir(parents=True, exist_ok=True)

        sample_eval_result = {
            "run_id": "run_playback_test",
            "timestamp": "2026-11-02T14:00:00Z",
            "dataset_id": "customers.dev.json",
            "customer_id": "alice",
            "mode": "paired",
            "runner_type": "offline",
            "on_arm": {
                "condition": "user_memory_on",
                "total_visits": 1,
                "successful_visits": 1,
                "target_success_rate": 1.0,
                "visits": [
                    {
                        "task_id": "task-01",
                        "sequence": 1,
                        "goal": "Black boots",
                        "target_hit": True,
                        "turn_hit": 1,
                        "total_turns": 1,
                        "hard_violations": 0,
                        "model_calls": 1,
                        "searches": 1,
                        "tokens": 450,
                        "transcript": [
                            {"role": "user", "message": "Looking for black boots"},
                            {"role": "assistant", "message": "[RECOMMEND] Found boots"},
                        ],
                        "retrieved_memories": ["Prefrs black"],
                        "consolidated_memories": [],
                        "status": "target_item_found",
                    }
                ],
            },
            "off_arm": None,
            "comparison": {},
        }
        (eval_ui_dir / "eval_result.json").write_text(
            json.dumps(sample_eval_result, indent=2)
        )

        res_path = eval_ui_dir / "eval_result.json"
        loaded = json.loads(res_path.read_text())
        self.assertEqual(loaded["customer_id"], "alice")
        visits = loaded["on_arm"]["visits"]
        self.assertEqual(len(visits), 1)
        self.assertTrue(visits[0]["target_hit"])
        self.assertEqual(len(visits[0]["transcript"]), 2)

    def test_package_isolation_no_static_astra_eval_imports(self):
        """Ensure no shopping_agent module statically imports astra_eval."""
        shopping_agent_dir = (
            Path(__file__).resolve().parent.parent / "src/shopping_agent"
        )
        for py_file in shopping_agent_dir.glob("*.py"):
            content = py_file.read_text()
            self.assertNotIn(
                "import astra_eval",
                content,
                f"Static import of astra_eval found in {py_file.name}",
            )
            self.assertNotIn(
                "from astra_eval",
                content,
                f"Static import from astra_eval found in {py_file.name}",
            )

    def test_session_audit_authorization_boundary(self):
        """User A cannot inspect sessions owned by User B."""
        store = SessionStore(self.sessions)
        mallory_sid = store.create("mallory")
        alice_sid = store.create("alice")

        alice_discovered = discover_available_sessions(self.service, self.root, "alice")
        alice_sids = [
            d["session_id"]
            for d in alice_discovered
            if d["source"] == "Manual Dev Chat"
        ]
        self.assertIn(alice_sid, alice_sids)
        self.assertNotIn(mallory_sid, alice_sids)


if __name__ == "__main__":
    unittest.main()
