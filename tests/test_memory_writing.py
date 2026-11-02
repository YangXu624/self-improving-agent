"""Unit tests for Phase 1: Memory Writing and Updating."""

import tempfile
import unittest

from shopping_agent.consolidation import (
    CONSOLIDATION_SYSTEM_PROMPT,
    ConsolidationOperation,
)
from shopping_agent.user_memory import (
    UserMemoryStore,
)


class TestMemoryWriting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = UserMemoryStore(root=self.temp_dir.name)
        self.user_id = "test-customer-001"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_consolidation_prompt_contains_contextual_and_bag_guidelines(self):
        """Prompt instructs model on contextual history, bags for personal use without gender inference."""
        self.assertIn("contextual", CONSOLIDATION_SYSTEM_PROMPT)
        self.assertIn("women's bags", CONSOLIDATION_SYSTEM_PROMPT.lower())
        self.assertIn("personal use", CONSOLIDATION_SYSTEM_PROMPT.lower())
        self.assertIn(
            "Do NOT infer that the customer is a woman", CONSOLIDATION_SYSTEM_PROMPT
        )

    def test_womens_bag_for_myself_contextual_memory_record(self):
        """'I'm looking for a women's bag for myself' is stored as contextual history without gender inference."""
        op = ConsolidationOperation(
            op="ADD",
            category="contextual",
            attribute="shopping_history",
            value="previously shopped for women's bags for personal use",
            scope="bags",
            strength="soft",
            evidence_type="explicit",
            confidence=0.95,
            quote="I'm looking for a women's bag for myself",
            rationale="Customer shopped for women's bags for personal use; contextual observation.",
        )
        res = self.store.apply_consolidation_operations(
            self.user_id,
            "session-001",
            [op.model_dump()],
        )
        self.assertEqual(len(res["ids"]), 1)

        profile = self.store.read(self.user_id)
        active = [r for r in profile.records if r.status == "active"]
        self.assertEqual(len(active), 1)
        rec = active[0]
        self.assertEqual(rec.category, "contextual")
        self.assertEqual(rec.attribute, "shopping_history")
        self.assertEqual(
            rec.value, "previously shopped for women's bags for personal use"
        )
        self.assertEqual(rec.scope, "bags")
        self.assertEqual(rec.strength, "soft")
        self.assertEqual(rec.evidence_type, "explicit")
        self.assertGreaterEqual(rec.confidence, 0.9)
        self.assertNotIn("gender", rec.attribute)
        self.assertNotIn("woman", rec.value)

    def test_durable_explicit_vs_inferred_strengths(self):
        """Distinguish hard/soft explicit preferences from inferred tendencies."""
        ops = [
            ConsolidationOperation(
                op="ADD",
                category="preference",
                attribute="color",
                value="black",
                scope="workout clothing",
                strength="hard",
                evidence_type="explicit",
                confidence=1.0,
                quote="I always buy black workout clothing.",
                rationale="Durable explicit requirement stated by user.",
            ),
            ConsolidationOperation(
                op="ADD",
                category="preference",
                attribute="material",
                value="organic cotton",
                scope="general",
                strength="inferred",
                evidence_type="inferred",
                confidence=0.6,
                quote="Repeated purchases of organic cotton shirts.",
                rationale="Inferred from repeated shopping behavior.",
            ),
        ]
        self.store.apply_consolidation_operations(
            self.user_id,
            "session-002",
            [o.model_dump() for o in ops],
        )

        profile = self.store.read(self.user_id)
        records_by_attr = {
            r.attribute: r for r in profile.records if r.status == "active"
        }

        black_rec = records_by_attr["color"]
        self.assertEqual(black_rec.strength, "hard")
        self.assertEqual(black_rec.evidence_type, "explicit")
        self.assertEqual(black_rec.confidence, 1.0)
        self.assertEqual(black_rec.scope, "workout clothing")

        cotton_rec = records_by_attr["material"]
        self.assertEqual(cotton_rec.strength, "inferred")
        self.assertEqual(cotton_rec.evidence_type, "inferred")
        self.assertEqual(cotton_rec.confidence, 0.6)

    def test_scoped_preference_correction_and_supersede(self):
        """Specific scoped preference (formalwear cream) coexists with general preference (black clothing)."""
        # Initially prefers black clothing
        op1 = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="black",
            scope="clothing",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I usually prefer black clothing.",
            rationale="General clothing color preference.",
        )
        self.store.apply_consolidation_operations(
            self.user_id, "s1", [op1.model_dump()]
        )

        # Later states: For formal events, prefers cream
        op2 = ConsolidationOperation(
            op="ADD",
            category="preference",
            attribute="color",
            value="cream",
            scope="formalwear",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="For formal events, I prefer cream instead.",
            rationale="Specific scoped preference for formalwear does not erase general clothing preference.",
        )
        self.store.apply_consolidation_operations(
            self.user_id, "s2", [op2.model_dump()]
        )

        profile = self.store.read(self.user_id)
        active = [r for r in profile.records if r.status == "active"]
        self.assertEqual(len(active), 2)
        scopes = {r.scope: r.value for r in active}
        self.assertEqual(scopes["clothing"], "black")
        self.assertEqual(scopes["formalwear"], "cream")

        # Now customer explicitly corrects general clothing preference: "I no longer wear black clothing, I wear navy"
        general_black = next(r for r in active if r.scope == "clothing")
        op3 = ConsolidationOperation(
            op="SUPERSEDE",
            target_id=general_black.id,
            category="preference",
            attribute="color",
            value="navy",
            scope="clothing",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="I no longer wear black clothing, I wear navy.",
            rationale="Explicit correction supersedes general black clothing.",
        )
        self.store.apply_consolidation_operations(
            self.user_id, "s3", [op3.model_dump()]
        )

        profile2 = self.store.read(self.user_id)
        active2 = [r for r in profile2.records if r.status == "active"]
        self.assertEqual(len(active2), 2)
        scopes2 = {r.scope: r.value for r in active2}
        self.assertEqual(scopes2["clothing"], "navy")
        self.assertEqual(scopes2["formalwear"], "cream")

        superseded = [r for r in profile2.records if r.status == "superseded"]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].id, general_black.id)

    def test_gift_purchase_contextual_isolation(self):
        """Gift purchase is recorded as contextual or gift history, not assigned to user's personal preference."""
        op = ConsolidationOperation(
            op="ADD",
            category="contextual",
            attribute="gift_history",
            value="bought Lego set for 8-year-old nephew",
            scope="toys",
            strength="soft",
            evidence_type="explicit",
            confidence=1.0,
            quote="Looking for a gift for my 8-year-old nephew.",
            rationale="Gift purchase for someone else; context only.",
        )
        self.store.apply_consolidation_operations(
            self.user_id, "s-gift", [op.model_dump()]
        )

        profile = self.store.read(self.user_id)
        active = [r for r in profile.records if r.status == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].category, "contextual")
        self.assertEqual(active[0].attribute, "gift_history")

    def test_sqlite_and_markdown_synchronization_with_new_fields(self):
        """Verify persistence across SQLite and Markdown projection preserves strength, evidence_type, and confidence."""
        op = ConsolidationOperation(
            op="ADD",
            category="contextual",
            attribute="shopping_history",
            value="previously shopped for women's bags for personal use",
            scope="bags",
            strength="soft",
            evidence_type="explicit",
            confidence=0.95,
        )
        self.store.apply_consolidation_operations(
            self.user_id, "s-sync", [op.model_dump()]
        )

        # Re-read through fresh UserMemoryStore instance pointing to same dir
        fresh_store = UserMemoryStore(root=self.temp_dir.name)
        profile = fresh_store.read(self.user_id)
        self.assertEqual(len(profile.records), 1)
        r = profile.records[0]
        self.assertEqual(r.strength, "soft")
        self.assertEqual(r.evidence_type, "explicit")
        self.assertAlmostEqual(r.confidence, 0.95)

        # Markdown file inspection
        user_dir = self.store.directory(self.user_id)
        md_text = (user_dir / "profile.md").read_text(encoding="utf-8")
        self.assertIn("Shopping History & Context", md_text)
        self.assertIn("previously shopped for women's bags for personal use", md_text)


if __name__ == "__main__":
    unittest.main()
