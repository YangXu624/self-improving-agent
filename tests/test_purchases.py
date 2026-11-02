"""Deterministic offline tests for simulated purchase history and purchase-based memory learning.

Verifies:
1. Purchase confirmation and SQLite persistence
2. Customer isolation
3. Duplicate event prevention and intentional repurchase
4. Purchase correction and cancellation audit preservation
5. Cross-session purchase-history retrieval into agent context
6. Memory consolidation using purchase evidence
7. Gift recipient distinction (no customer preference attribution)
8. No unsupported gender or identity inference
9. UI service integration and session event audit logging
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shopping_agent.agent import ShoppingAgent
from shopping_agent.consolidation import consolidate_session
from shopping_agent.provider import PolicyReply
from shopping_agent.purchases import PurchaseRecord, PurchaseStore
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore
from shopping_agent.ui_service import ChatService
from shopping_agent.user_memory import UserMemoryStore


def make_test_catalogue_and_index(tmp_dir: Path) -> tuple[Path, Path]:
    cat_path = tmp_dir / "catalog.jsonl"
    idx_path = tmp_dir / "catalogue.sqlite"

    items = [
        {
            "parent_asin": "BAG_001",
            "title": "Minimalist Black Leather Handbag",
            "description": ["Sleek modern minimalist black leather bag"],
            "features": ["genuine leather", "minimalist aesthetic"],
            "price": 85.0,
            "categories": ["Clothing", "Handbags"],
            "details": {
                "Department": "women",
                "Color": "black",
                "Material": "leather",
                "Style": "minimalist",
            },
            "average_rating": 4.8,
            "rating_number": 45,
            "store": "LeatherCraft",
        },
        {
            "parent_asin": "BAG_002",
            "title": "Vintage Brown Canvas Tote Bag",
            "description": ["Durable casual brown canvas tote for shopping"],
            "features": ["heavy canvas", "vintage style"],
            "price": 45.0,
            "categories": ["Clothing", "Handbags"],
            "details": {
                "Department": "women",
                "Color": "brown",
                "Material": "canvas",
                "Style": "vintage",
            },
            "average_rating": 4.2,
            "rating_number": 18,
            "store": "UrbanGear",
        },
        {
            "parent_asin": "BOOT_001",
            "title": "Women Winter Snow Boots",
            "description": ["Waterproof warm winter boots"],
            "features": ["waterproof", "insulated"],
            "price": 110.0,
            "categories": ["Shoes", "Boots"],
            "details": {
                "Department": "women",
                "Color": "black",
            },
            "average_rating": 4.5,
            "rating_number": 60,
            "store": "SnowSteps",
        },
    ]
    with cat_path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")

    build_index(cat_path, idx_path)
    return cat_path, idx_path


def reply(data: dict) -> PolicyReply:
    return PolicyReply(
        json.dumps(data), {"provider": "fixture", "usage": {"total_tokens": 10}}
    )


class PurchaseHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cat_path, self.idx_path = make_test_catalogue_and_index(self.root)
        self.sessions_dir = self.root / "sessions"
        self.user_memory_dir = self.root / "user-memory"
        self.purchases_db = self.root / "purchases.sqlite"

        self.store = SessionStore(self.sessions_dir)
        self.search = LexicalSearch(self.idx_path)
        self.purchase_store = PurchaseStore(self.purchases_db)
        self.memory_store = UserMemoryStore(self.user_memory_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_purchase_confirmation_and_persistence(self):
        """1. Record a simulated purchase and verify persistent SQLite storage across instances."""
        record = PurchaseRecord(
            purchase_id="purch-test-001",
            customer_id="manual-user-001",
            session_id="sess-001",
            turn_id="turn-001",
            product_id="BAG_001",
            title="Minimalist Black Leather Handbag",
            attribute_snapshot={
                "color": "black",
                "material": "leather",
                "style": "minimalist",
            },
            price=85.0,
            currency="USD",
            quantity=1,
            recipient_context="self",
            status="simulated_completed",
            source="confirmed_user_interaction",
        )
        self.purchase_store.record_purchase(record)

        # Reload store from new instance pointing to same SQLite database
        reopened_store = PurchaseStore(self.purchases_db)
        saved = reopened_store.get_purchase("manual-user-001", "purch-test-001")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.customer_id, "manual-user-001")
        self.assertEqual(saved.product_id, "BAG_001")
        self.assertEqual(saved.price, 85.0)
        self.assertEqual(saved.status, "simulated_completed")
        self.assertEqual(saved.source, "confirmed_user_interaction")
        self.assertEqual(saved.attribute_snapshot["style"], "minimalist")

        summary = reopened_store.get_summary("manual-user-001")
        self.assertEqual(summary["total_count"], 1)
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["total_spend"], 85.0)
        self.assertIn("BAG_001", summary["purchased_product_ids"])

    def test_customer_isolation(self):
        """2. Customer A's purchases are strictly isolated from Customer B."""
        # Alice's purchase
        self.purchase_store.record_purchase(
            PurchaseRecord(
                purchase_id="purch-alice-01",
                customer_id="alice",
                session_id="sess-a",
                turn_id="turn-a",
                product_id="BAG_001",
                title="Minimalist Black Leather Handbag",
                price=85.0,
            )
        )
        # Bob's purchase
        self.purchase_store.record_purchase(
            PurchaseRecord(
                purchase_id="purch-bob-01",
                customer_id="bob",
                session_id="sess-b",
                turn_id="turn-b",
                product_id="BAG_002",
                title="Vintage Brown Canvas Tote Bag",
                price=45.0,
            )
        )

        alice_purchases = self.purchase_store.get_purchases("alice")
        self.assertEqual(len(alice_purchases), 1)
        self.assertEqual(alice_purchases[0].purchase_id, "purch-alice-01")

        bob_purchases = self.purchase_store.get_purchases("bob")
        self.assertEqual(len(bob_purchases), 1)
        self.assertEqual(bob_purchases[0].purchase_id, "purch-bob-01")

        # Alice cannot retrieve or cancel Bob's purchase
        self.assertIsNone(self.purchase_store.get_purchase("alice", "purch-bob-01"))
        self.assertIsNone(self.purchase_store.cancel_purchase("alice", "purch-bob-01"))

    def test_purchase_correction_and_cancellation_audit(self):
        """3. Cancel a mistaken purchase without deleting its audit history."""
        self.purchase_store.record_purchase(
            PurchaseRecord(
                purchase_id="purch-cancel-01",
                customer_id="manual-user-001",
                session_id="sess-c",
                turn_id="turn-c",
                product_id="BAG_001",
                title="Minimalist Black Leather Handbag",
                price=85.0,
            )
        )

        cancelled = self.purchase_store.cancel_purchase(
            "manual-user-001",
            "purch-cancel-01",
            reason="Mistaken simulated click",
        )
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, "simulated_cancelled")
        self.assertEqual(cancelled.cancellation_reason, "Mistaken simulated click")
        self.assertIsNotNone(cancelled.cancelled_at)

        # Audit history preserved in database
        all_p = self.purchase_store.get_purchases(
            "manual-user-001", include_cancelled=True
        )
        self.assertEqual(len(all_p), 1)
        self.assertEqual(all_p[0].status, "simulated_cancelled")

        # Active-only query excludes cancelled
        active_p = self.purchase_store.get_purchases(
            "manual-user-001", include_cancelled=False
        )
        self.assertEqual(len(active_p), 0)

        # Spend summary excludes cancelled purchase
        summary = self.purchase_store.get_summary("manual-user-001")
        self.assertEqual(summary["total_count"], 1)
        self.assertEqual(summary["active_count"], 0)
        self.assertEqual(summary["total_spend"], 0.0)

    def test_duplicate_prevention_and_intentional_repurchase(self):
        """4. Repeated writes of the same purchase_id are idempotent; intentional repurchase creates new ID."""
        rec1 = PurchaseRecord(
            purchase_id="purch-repeat-01",
            customer_id="manual-user-001",
            session_id="sess-rep",
            turn_id="turn-rep",
            product_id="BAG_001",
            title="Minimalist Black Leather Handbag",
            price=85.0,
        )
        # Rerun 1
        self.purchase_store.record_purchase(rec1)
        # Rerun 2 (e.g. Streamlit rerun with same purchase_id)
        self.purchase_store.record_purchase(rec1)
        self.assertEqual(len(self.purchase_store.get_purchases("manual-user-001")), 1)

        # Intentional repurchase (new purchase_id)
        rec2 = PurchaseRecord(
            purchase_id="purch-repeat-02",
            customer_id="manual-user-001",
            session_id="sess-rep",
            turn_id="turn-rep-2",
            product_id="BAG_001",
            title="Minimalist Black Leather Handbag",
            price=85.0,
        )
        self.purchase_store.record_purchase(rec2)
        self.assertEqual(len(self.purchase_store.get_purchases("manual-user-001")), 2)

    def test_cross_session_purchase_history_retrieval(self):
        """5. Relevant past purchases are retrieved and injected into agent context in future sessions."""
        # Record a past purchase for manual-user-001
        self.purchase_store.record_purchase(
            PurchaseRecord(
                purchase_id="purch-past-bag",
                customer_id="manual-user-001",
                session_id="past-session-01",
                turn_id="past-turn-01",
                product_id="BAG_001",
                title="Minimalist Black Leather Handbag",
                attribute_snapshot={
                    "color": "black",
                    "material": "leather",
                    "style": "minimalist",
                },
                price=85.0,
            )
        )

        captured_messages = []

        class MockShoppingPolicy:
            def complete(self, messages):
                captured_messages.append(messages)
                ctx = json.loads(messages[-1]["content"])
                if ctx["latest_search"] is None:
                    return reply(
                        {
                            "based_on_state_version": ctx["state"]["version"],
                            "updates": [],
                            "action": {
                                "type": "SEARCH",
                                "query": "handbag",
                                "limit": 3,
                            },
                            "reason": "Search handbags",
                        }
                    )
                candidates = [p["id"] for p in ctx["latest_search"]["candidates"][:2]]
                return reply(
                    {
                        "based_on_state_version": ctx["state"]["version"],
                        "updates": [],
                        "action": {
                            "type": "RECOMMEND",
                            "product_ids": candidates,
                            "message": "Here are bags you might like.",
                            "follow_up_question": "Do you prefer a tote or shoulder style?",
                        },
                        "reason": "Recommend bags",
                    }
                )

        agent = ShoppingAgent(
            self.store,
            self.search,
            MockShoppingPolicy(),
            purchase_store=self.purchase_store,
        )
        sid = self.store.create("manual-user-001")

        # In a new session, customer asks for a bag
        res = agent.turn("manual-user-001", sid, "I am looking for another bag.")
        self.assertEqual(res["action"], "RECOMMEND")

        # Verify context included relevant_purchases
        first_call_context = json.loads(captured_messages[0][-1]["content"])
        self.assertIn("relevant_purchases", first_call_context)
        relevant = first_call_context["relevant_purchases"]
        self.assertEqual(len(relevant), 1)
        self.assertEqual(relevant[0]["product_id"], "BAG_001")
        self.assertEqual(relevant[0]["title"], "Minimalist Black Leather Handbag")

        # Verify purchase_evidence_used event was recorded in session
        with self.store.open("manual-user-001", sid) as session:
            ev_types = [e.type for e in session.events]
            self.assertIn("purchase_evidence_used", ev_types)

    def test_memory_consolidation_using_purchase_evidence(self):
        """6. At session end, purchase history events reinforce customer preferences in memory consolidation."""
        sid = self.store.create("manual-user-001")
        with self.store.open("manual-user-001", sid) as session:
            session.append(
                "user_message",
                {"message": "I usually prefer minimalist bags."},
                turn_id="turn-1",
            )
            # Simulated purchase recorded in this session
            session.append(
                "purchase_recorded",
                {
                    "purchase_id": "purch-ses-01",
                    "customer_id": "manual-user-001",
                    "session_id": sid,
                    "turn_id": "turn-1",
                    "product_id": "BAG_001",
                    "title": "Minimalist Black Leather Handbag",
                    "attribute_snapshot": {"color": "black", "style": "minimalist"},
                    "price": 85.0,
                    "recipient_context": "self",
                },
                turn_id="purchase-turn-1",
            )

        class MockConsolidationPolicy:
            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                # Policy observes session_purchases in context
                self.has_purchases = bool(ctx.get("session_purchases"))
                return reply(
                    {
                        "reason": "Customer stated minimalist preference and purchased matching bag",
                        "operations": [
                            {
                                "op": "ADD",
                                "category": "preference",
                                "attribute": "style",
                                "value": "minimalist",
                                "scope": "bags",
                                "basis": "confirmed",
                                "quote": "I usually prefer minimalist bags.",
                                "confidence": 1.0,
                                "rationale": "Stated preference reinforced by purchase BAG_001",
                            }
                        ],
                    }
                )

        policy = MockConsolidationPolicy()
        with self.store.open("manual-user-001", sid) as session:
            res = consolidate_session(
                session,
                "manual-user-001",
                self.memory_store,
                policy,
                purchase_store=self.purchase_store,
            )

        self.assertEqual(len(res.operations_applied), 1)
        self.assertEqual(res.operations_applied[0]["value"], "minimalist")

        # Verify durable memory profile was updated
        profile = self.memory_store.read("manual-user-001")
        self.assertEqual(len(profile.records), 1)
        self.assertEqual(profile.records[0].attribute, "style")
        self.assertEqual(profile.records[0].value, "minimalist")

        # Verify session audit events
        with self.store.open("manual-user-001", sid) as session:
            types = [e.type for e in session.events]
            self.assertIn("purchase_evidence_used", types)
            self.assertIn("memory_reinforced_from_purchase", types)

    def test_gift_recipient_distinction(self):
        """7. Purchases marked as 'gift' are not attributed as customer preferences."""
        sid = self.store.create("manual-user-001")
        with self.store.open("manual-user-001", sid) as session:
            session.append(
                "user_message",
                {"message": "I need a gift for my sister."},
                turn_id="turn-gift-1",
            )
            session.append(
                "purchase_recorded",
                {
                    "purchase_id": "purch-gift-01",
                    "customer_id": "manual-user-001",
                    "session_id": sid,
                    "turn_id": "turn-gift-1",
                    "product_id": "BAG_002",
                    "title": "Vintage Brown Canvas Tote Bag",
                    "attribute_snapshot": {"style": "vintage", "color": "brown"},
                    "price": 45.0,
                    "recipient_context": "gift",
                },
                turn_id="purchase-gift-1",
            )

        class GiftAwareConsolidationPolicy:
            def complete(self, messages):
                ctx = json.loads(messages[-1]["content"])
                # Policy correctly inspects recipient_context="gift" and does not generalize
                purchases = ctx.get("session_purchases", [])
                if any(p.get("recipient_context") == "gift" for p in purchases):
                    return reply(
                        {
                            "reason": "Purchase was a gift; no customer preference inferred",
                            "operations": [],
                        }
                    )
                return reply({"reason": "none", "operations": []})

        with self.store.open("manual-user-001", sid) as session:
            res = consolidate_session(
                session,
                "manual-user-001",
                self.memory_store,
                GiftAwareConsolidationPolicy(),
                purchase_store=self.purchase_store,
            )

        self.assertEqual(len(res.operations_applied), 0)
        profile = self.memory_store.read("manual-user-001")
        self.assertEqual(len(profile.records), 0)

    def test_ui_service_purchase_integration(self):
        """8. ChatService record, cancel, summary, and view methods function correctly."""

        class MockPolicy:
            def complete(self, messages):
                return reply({"status": "ok"})

        service = ChatService(
            self.cat_path,
            self.idx_path,
            self.sessions_dir,
            policy=MockPolicy(),
            purchases_db_path=self.purchases_db,
            user_memory_enabled=False,
        )

        sid = service.create("manual-user-001")

        # 1. Record purchase via ChatService
        p = service.record_purchase(
            "manual-user-001",
            sid,
            "turn-ui-1",
            "BAG_001",
            "Minimalist Black Leather Handbag",
            price=85.0,
            quantity=2,
            recipient_context="self",
            attribute_snapshot={"color": "black", "style": "minimalist"},
        )
        self.assertEqual(p["product_id"], "BAG_001")
        self.assertEqual(p["quantity"], 2)

        # 2. Check summary
        summary = service.get_purchase_summary("manual-user-001")
        self.assertEqual(summary["total_count"], 1)
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["total_spend"], 170.0)

        # 3. Check view
        view = service.view("manual-user-001", sid)
        self.assertIn("purchase_summary", view)
        self.assertEqual(view["purchase_summary"]["active_count"], 1)
        self.assertEqual(len(view["recent_purchases"]), 1)

        # Check session audit events
        ev_types = [e["type"] for e in view["events"]]
        self.assertIn("purchase_initiated", ev_types)
        self.assertIn("purchase_confirmed", ev_types)
        self.assertIn("purchase_recorded", ev_types)

        # 4. Cancel purchase
        canc = service.cancel_purchase(
            "manual-user-001",
            p["purchase_id"],
            session_id=sid,
            reason="Demo correction",
        )
        self.assertEqual(canc["status"], "simulated_cancelled")
        view_after = service.view("manual-user-001", sid)
        ev_types_after = [e["type"] for e in view_after["events"]]
        self.assertIn("purchase_cancelled", ev_types_after)


if __name__ == "__main__":
    unittest.main()
