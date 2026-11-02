"""Tests for Part A — Interactive User Memory Demo & Session Lifecycle."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from test_retrieval import product

from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import build_index
from shopping_agent.sessions import SessionError
from shopping_agent.ui_service import DEFAULT_MANUAL_USER_ID, ChatService
from shopping_agent.user_memory import MemoryRecord, UserProfile


class ManualUserMemoryUITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue = self.root / "catalog.jsonl"
        self.index = self.root / "index.sqlite"
        self.sessions = self.root / "sessions"
        self.memory_root = self.root / "user-memory"

        rows = [
            product(
                "shirt-black-01",
                35,
                Color="Black",
                Style="Minimalist",
                ProductType="Workout Shirt",
            ),
            product(
                "shirt-red-01",
                30,
                Color="Red",
                Style="Graphic",
                ProductType="Workout Shirt",
            ),
            product(
                "casual-black-01",
                45,
                Color="Black",
                Style="Minimalist",
                ProductType="Casual Pants",
            ),
            product(
                "casual-blue-01",
                50,
                Color="Blue",
                Style="Classic",
                ProductType="Casual Pants",
            ),
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
            user_memory_root=self.memory_root,
            default_user_id=DEFAULT_MANUAL_USER_ID,
        )

    def test_persistent_manual_user_identity_resolution(self):
        """manual-user-001 is resolved server-side; arbitrary benchmark customer impersonation blocked."""
        self.assertEqual(self.service.resolve_user_id(None), "manual-user-001")
        self.assertEqual(self.service.resolve_user_id(""), "manual-user-001")
        self.assertEqual(self.service.resolve_user_id("   "), "manual-user-001")
        self.assertEqual(
            self.service.resolve_user_id("manual-user-001"), "manual-user-001"
        )
        self.assertEqual(
            self.service.resolve_user_id("local-tester-2"), "local-tester-2"
        )

        # Impersonating benchmark eval customers is forbidden
        with self.assertRaises(SessionError):
            self.service.resolve_user_id("eval-customer-1")
        with self.assertRaises(SessionError):
            self.service.resolve_user_id("synthetic-shopper-007")
        with self.assertRaises(SessionError):
            self.service.resolve_user_id("blueprint-shopper")
        with self.assertRaises(SessionError):
            self.service.resolve_user_id("../path-traversal")

    def test_session_lifecycle_and_idempotent_finalization(self):
        """Sessions can be created, chatted in, and finalized idempotently with memory consolidation."""
        user_id = DEFAULT_MANUAL_USER_ID
        sid = self.service.create(user_id)
        self.assertIsInstance(sid, str)

        # Agent turn response mock
        agent_reply = {
            "updates": [],
            "action": {
                "type": "RESPOND",
                "message": "I can help you find workout clothes.",
            },
            "reason": "acknowledge request",
        }
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(agent_reply), {}
        )

        # Send turn 1
        res = self.service.send(
            user_id,
            sid,
            "I'm looking for workout clothes. I generally prefer black clothing and minimalist designs.",
            "req-1",
        )
        self.assertEqual(res["action"], "RESPOND")

        # Verify consolidation did NOT run on regular turn
        view = self.service.view(user_id, sid)
        self.assertFalse(view["finalized"])
        profile = self.service._user_memory_store.read(user_id)
        self.assertEqual(profile.revision, 0)
        self.assertEqual(len(profile.records), 0)

        # Mock consolidation policy return
        consolidation_reply = {
            "reason": "Customer expressed enduring preference for black color and minimalist design in workout clothing.",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothing",
                    "basis": "confirmed",
                    "quote": "I generally prefer black clothing and minimalist designs.",
                    "confidence": 1.0,
                    "rationale": "Explicitly stated color preference.",
                },
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "style",
                    "value": "minimalist",
                    "scope": "workout clothing",
                    "basis": "confirmed",
                    "quote": "I generally prefer black clothing and minimalist designs.",
                    "confidence": 1.0,
                    "rationale": "Explicitly stated style preference.",
                },
            ],
        }
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(consolidation_reply), {}
        )

        # Call finalize
        fin = self.service.finalize(user_id, sid)
        self.assertEqual(fin["status"], "success")
        self.assertFalse(fin["idempotent"])
        self.assertEqual(len(fin["operations_applied"]), 2)
        self.assertEqual(fin["revision"], 1)

        # Verify memory is saved
        profile = self.service._user_memory_store.read(user_id)
        self.assertEqual(profile.revision, 1)
        self.assertEqual(len(profile.records), 2)
        self.assertEqual({r.attribute for r in profile.records}, {"color", "style"})

        # Call finalize a SECOND time (idempotency test)
        fin2 = self.service.finalize(user_id, sid)
        self.assertEqual(fin2["status"], "idempotent")
        self.assertTrue(fin2["idempotent"])
        profile2 = self.service._user_memory_store.read(user_id)
        self.assertEqual(profile2.revision, 1)
        self.assertEqual(len(profile2.records), 2)

    def test_cross_session_memory_retrieval_and_injection(self):
        """Memories consolidated in Session 1 are retrieved and injected into Session 2 for the same user."""
        user_id = DEFAULT_MANUAL_USER_ID

        # Seed memory store directly to test retrieval cleanly
        now = "2026-11-02T12:00:00.000000Z"
        rec1 = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            scope="workout clothing",
            basis="confirmed",
            quote="I prefer black clothing.",
            status="active",
            created_at=now,
            last_confirmed_at=now,
            source_session_id="session-001",
        )
        with self.service._user_memory_store._locked(user_id) as p:
            conn = self.service._user_memory_store._init_db(p)
            try:
                prof = UserProfile(
                    user_id=user_id,
                    revision=1,
                    records=[rec1],
                    last_consolidated_session_id="session-001",
                )
                self.service._user_memory_store.write_profile(prof, p, conn)
            finally:
                conn.close()

        # Start fresh Session 2
        sid2 = self.service.create(user_id)

        # Mock agent response
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {
                        "type": "SEARCH",
                        "query": "workout clothes black",
                        "mode": "all",
                        "limit": 5,
                    },
                    "reason": "search with customer preference",
                }
            ),
            {},
        )

        turn_res = self.service.send(
            user_id, sid2, "I'm looking for workout clothes.", "req-visit2"
        )
        self.assertTrue(turn_res.get("user_memory", {}).get("enabled"))
        injected = turn_res.get("user_memory", {}).get("injected", [])
        self.assertIn(rec1.id, injected)

        view = self.service.view(user_id, sid2)
        injection_events = [
            e for e in view["events"] if e["type"] == "user_memory_injection"
        ]
        self.assertTrue(len(injection_events) >= 1)
        self.assertIn(rec1.id, injection_events[0]["payload"]["injected"])

    def test_memory_off_isolation(self):
        """Memory OFF mode: no retrieval, no injection, no consolidation, stored records preserved."""
        user_id = DEFAULT_MANUAL_USER_ID

        # Seed an existing memory
        rec = MemoryRecord(
            category="preference",
            attribute="color",
            value="black",
            scope="general",
            basis="confirmed",
            quote="I prefer black.",
            status="active",
        )
        with self.service._user_memory_store._locked(user_id) as p:
            conn = self.service._user_memory_store._init_db(p)
            try:
                prof = UserProfile(user_id=user_id, revision=1, records=[rec])
                self.service._user_memory_store.write_profile(prof, p, conn)
            finally:
                conn.close()

        # Switch to Memory OFF
        self.service.set_user_memory_enabled(False)
        self.assertIsNone(self.service.user_memory)

        sid = self.service.create(user_id)
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {"type": "RESPOND", "message": "Here to help."},
                    "reason": "respond without memory",
                }
            ),
            {},
        )

        turn_res = self.service.send(user_id, sid, "I need shoes.", "req-off-1")
        self.assertNotIn("user_memory", turn_res)

        # Finalize in Memory OFF mode
        fin = self.service.finalize(user_id, sid)
        self.assertEqual(fin["status"], "memory_disabled")

        # Stored records MUST remain untouched
        after_prof = self.service._user_memory_store.read(user_id)
        self.assertEqual(after_prof.revision, 1)
        self.assertEqual(len(after_prof.records), 1)
        self.assertEqual(after_prof.records[0].id, rec.id)

    def test_memory_inspector_and_clear_export(self):
        """Memory inspector returns structured data; export produces JSON; clear resets profile."""
        user_id = DEFAULT_MANUAL_USER_ID

        # 1. Empty inspector
        info = self.service.inspect_memory(user_id)
        self.assertEqual(info["user_id"], user_id)
        self.assertEqual(info["total_active"], 0)

        # 2. Add an active and a superseded record
        rec_active = MemoryRecord(
            category="preference",
            attribute="size",
            value="M",
            scope="shirts",
            basis="confirmed",
            quote="I wear size M.",
            status="active",
        )
        rec_old = MemoryRecord(
            category="preference",
            attribute="size",
            value="S",
            scope="shirts",
            basis="confirmed",
            quote="I used to wear S.",
            status="superseded",
        )
        with self.service._user_memory_store._locked(user_id) as p:
            conn = self.service._user_memory_store._init_db(p)
            try:
                prof = UserProfile(
                    user_id=user_id, revision=2, records=[rec_active, rec_old]
                )
                self.service._user_memory_store.write_profile(prof, p, conn)
            finally:
                conn.close()

        info = self.service.inspect_memory(user_id)
        self.assertEqual(info["total_active"], 1)
        self.assertEqual(info["total_superseded"], 1)
        self.assertEqual(info["active"][0]["value"], "M")
        self.assertEqual(info["superseded"][0]["value"], "S")

        # 3. Export memory
        exported = self.service.export_memory(user_id)
        data = json.loads(exported)
        self.assertEqual(data["user_id"], user_id)
        self.assertEqual(len(data["records"]), 2)

        # 4. Clear memory
        cleared = self.service.clear_memory(user_id)
        self.assertTrue(cleared)
        info_after = self.service.inspect_memory(user_id)
        self.assertEqual(info_after["total_active"], 0)
        self.assertEqual(info_after["total_superseded"], 0)
        self.assertEqual(info_after["revision"], 0)

    def test_workout_clothes_turn_and_session_consolidation_regression(self):
        """Regression test for the exact manual message:

        - Message: 'I'm looking for workout clothes. I generally prefer black clothing and minimalist designs.'
        - Turn 1: No legacy semantic-validation warning, no long-term memory write before finalization.
        - Broad request produces useful assistance (e.g. CLARIFY or RECOMMEND) without exhausting turn budget.
        - Session finalization successfully persists black and minimalist preferences.
        - Session finalization is idempotent.
        - Session 2 ('I'm looking for casual clothes.') retrieves consolidated memories.
        """
        user_id = DEFAULT_MANUAL_USER_ID
        sid = self.service.create(user_id)
        user_msg = "I'm looking for workout clothes. I generally prefer black clothing and minimalist designs."

        # Mock the policy to clarify on the broad request
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [
                        {
                            "op": "ADD",
                            "quote": "I'm looking for workout clothes",
                            "requirement": {
                                "field": "product_type",
                                "op": "eq",
                                "value": "workout clothes",
                                "quote": "workout clothes",
                                "strength": "hard",
                            },
                        },
                        {
                            "op": "ADD",
                            "quote": "I generally prefer black clothing",
                            "requirement": {
                                "field": "color",
                                "op": "eq",
                                "value": "black",
                                "quote": "I generally prefer black clothing",
                                "strength": "soft",
                            },
                        },
                    ],
                    "action": {
                        "type": "CLARIFY",
                        "attribute": "product_subtype",
                        "question": "What type of workout clothes are you looking for, such as tops, shorts, or pants?",
                    },
                    "reason": "Clarify broad workout clothes request",
                }
            ),
            {},
        )

        res = self.service.send(user_id, sid, user_msg, "req-turn1")
        # 1. Useful response produced rather than budget exhaustion
        self.assertEqual(res["action"], "CLARIFY")
        self.assertIn("What type of workout clothes", res["message"])

        # 2. No legacy semantic-validation warnings or rejections
        self.assertEqual(res.get("user_memory", {}).get("rejected", []), [])

        # 3. No long-term memory writing before session finalization
        profile_before = self.service._user_memory_store.read(user_id)
        self.assertEqual(len(profile_before.records), 0)
        self.assertEqual(profile_before.revision, 0)

        # 4. End-of-session consolidation
        consolidation_payload = {
            "reason": "Customer disclosed enduring preferences for black color and minimalist design.",
            "operations": [
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "color",
                    "value": "black",
                    "scope": "workout clothes",
                    "basis": "confirmed",
                    "quote": "I generally prefer black clothing and minimalist designs.",
                    "confidence": 1.0,
                    "rationale": "Stated general preference for black clothing.",
                },
                {
                    "op": "ADD",
                    "category": "preference",
                    "attribute": "style",
                    "value": "minimalist",
                    "scope": "workout clothes",
                    "basis": "confirmed",
                    "quote": "I generally prefer black clothing and minimalist designs.",
                    "confidence": 1.0,
                    "rationale": "Stated general preference for minimalist designs.",
                },
            ],
        }
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(consolidation_payload), {}
        )

        fin1 = self.service.finalize(user_id, sid)
        self.assertEqual(fin1["status"], "success")
        self.assertFalse(fin1["idempotent"])
        self.assertEqual(len(fin1["operations_applied"]), 2)
        self.assertEqual(fin1["revision"], 1)

        # 5. Verify saved preferences
        profile_after = self.service._user_memory_store.read(user_id)
        self.assertEqual(profile_after.revision, 1)
        self.assertEqual(len(profile_after.records), 2)
        attrs = {r.attribute: r.value for r in profile_after.records}
        self.assertEqual(attrs.get("color"), "black")
        self.assertEqual(attrs.get("style"), "minimalist")

        # 6. Idempotent finalization
        fin2 = self.service.finalize(user_id, sid)
        self.assertEqual(fin2["status"], "idempotent")
        self.assertTrue(fin2["idempotent"])
        self.assertEqual(self.service._user_memory_store.read(user_id).revision, 1)

        # 7. Memory retrieval in a new session (Session 2)
        sid2 = self.service.create(user_id)
        self.mock_policy.complete.return_value = PolicyReply(
            json.dumps(
                {
                    "updates": [],
                    "action": {
                        "type": "RESPOND",
                        "message": "Here are casual options tailored to your black and minimalist style.",
                    },
                    "reason": "Acknowledge casual request using recalled preferences",
                }
            ),
            {},
        )
        res2 = self.service.send(
            user_id, sid2, "I'm looking for casual clothes.", "req-turn2"
        )
        self.assertEqual(res2["status"], "ok")
        injected_records = res2.get("user_memory", {}).get("injected_records", [])
        self.assertTrue(len(injected_records) >= 1)
        injected_values = {r["value"] for r in injected_records}
        self.assertTrue("black" in injected_values or "minimalist" in injected_values)


if __name__ == "__main__":
    unittest.main()
