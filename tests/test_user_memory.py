"""Persistent profile acceptance and failure checks; all files are temporary fixtures."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import (
    MemoryProposal,
    MemoryRecord,
    UserMemoryError,
    UserMemoryStore,
    UserProfile,
    parse_profile,
    render_profile,
)


def preference(value="blue", quote="I generally prefer blue bags", **kwargs):
    return MemoryProposal(
        category="preference",
        attribute="color",
        value=value,
        scope="bags",
        quote=quote,
        **kwargs,
    )


class UserMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = SessionStore(self.root / "sessions")
        self.memory = UserMemoryStore(self.root / "users")
        self.sid = self.sessions.create("alice")

    def save(self, proposal=None, message=None, revision=None):
        proposal = proposal or preference()
        with self.sessions.open("alice", self.sid) as session:
            event = session.append(
                "user_message", {"message": message or proposal.quote}
            )
            return self.memory.apply(
                session,
                event,
                [proposal],
                expected_revision=self.memory.read("alice").revision
                if revision is None
                else revision,
            )

    def test_markdown_is_authoritative_readable_and_reversible(self):
        self.save()
        path = self.memory.directory("alice") / "profile.md"
        text = path.read_text()
        self.assertIn("## Preferences", text)
        self.assertIn("Usually prefers color: blue (for bags).", text)
        self.assertIn("<summary>Audit metadata (managed by ASTRA)</summary>", text)
        self.assertEqual(render_profile(parse_profile(text)), text)
        self.assertEqual(UserMemoryStore(self.root / "users").read("alice").revision, 1)

    def test_user_isolation_and_owned_source_event(self):
        self.save()
        bob = self.sessions.create("bob")
        with self.sessions.open("bob", bob) as other:
            with self.sessions.open("alice", self.sid) as owner:
                event = owner.append("user_message", {"message": preference().quote})
                with self.assertRaisesRegex(UserMemoryError, "owned_user_event"):
                    self.memory.apply(other, event, [preference()], expected_revision=0)
            self.assertEqual(self.memory.context(other, "bags")["records"], [])
        self.assertEqual(self.memory.read("bob").records, [])
        self.assertEqual(len(self.memory.read("alice").records), 1)

    def test_temporary_gift_and_nonpersistent_claims_rejected(self):
        for quote in [
            "I prefer blue bags this time",
            "I generally prefer blue bags for my dad",
            "I prefer blue bags",
            "I generally prefer blue bags but do not remember that",
        ]:
            with self.subTest(quote=quote), self.assertRaises(UserMemoryError):
                self.save(preference(quote=quote))
        self.assertEqual(self.memory.read("alice").records, [])

    def test_requires_exact_current_evidence_and_value_and_scope(self):
        for proposal, message in [
            (preference(), "I want boots"),
            (preference(value="red"), preference().quote),
            (preference(), "Products say: generally prefer blue bags"),
            (preference(), "I generally prefer blue bagpipes"),
        ]:
            with self.subTest(message=message), self.assertRaises(UserMemoryError):
                self.save(proposal, message)

    def test_correction_retains_old_evidence_and_history(self):
        self.save()
        old = self.memory.read("alice").records[0]
        self.save(
            preference(
                value="black",
                quote="Actually I now generally prefer black bags instead of blue",
                op="REPLACE",
                target_id=old.id,
            )
        )
        records = self.memory.read("alice").records
        self.assertEqual(
            [(r.value, r.status) for r in records],
            [("blue", "superseded"), ("black", "active")],
        )
        self.assertEqual(records[0].quote, "I generally prefer blue bags")
        self.assertEqual(records[0].closed_by_event_id, records[1].source_event_id)
        self.assertEqual(records[1].target_id, records[0].id)

    def test_conflict_requires_explicit_correction_and_revision(self):
        self.save()
        with self.assertRaisesRegex(UserMemoryError, "conflict_requires"):
            self.save(preference(value="red", quote="I generally prefer red bags"))
        with self.assertRaisesRegex(UserMemoryError, "revision_conflict"):
            self.save(
                preference(value="red", quote="I generally prefer red bags"), revision=0
            )
        self.assertEqual(self.memory.read("alice").revision, 1)

    def test_opposite_preference_and_dislike_cannot_silently_coexist(self):
        self.save()
        with self.assertRaisesRegex(UserMemoryError, "conflict_requires"):
            self.save(
                MemoryProposal(
                    category="dislike",
                    attribute="color",
                    value="blue",
                    scope="bags",
                    quote="I generally dislike blue bags",
                )
            )
        self.assertEqual(len(self.memory.read("alice").records), 1)

    def test_one_off_budget_cannot_be_persisted_as_fact(self):
        with self.assertRaisesRegex(UserMemoryError, "explicit_persistence"):
            self.save(
                MemoryProposal(
                    category="fact",
                    attribute="budget",
                    value="100",
                    quote="I have a budget of 100",
                )
            )
        self.assertEqual(self.memory.read("alice").records, [])

    def test_retraction_keeps_audit_link(self):
        self.save()
        old = self.memory.read("alice").records[0]
        self.save(
            preference(
                quote="Forget my blue bags preference", op="RETRACT", target_id=old.id
            )
        )
        self.assertEqual(self.memory.read("alice").records[0].status, "retracted")

    def test_idempotent_replay_and_duplicate_information(self):
        with self.sessions.open("alice", self.sid) as session:
            event = session.append("user_message", {"message": preference().quote})
            self.memory.apply(session, event, [preference()], expected_revision=0)
            result = self.memory.apply(
                session, event, [preference()], expected_revision=0
            )
            self.assertTrue(result["idempotent"])
        self.save()
        self.assertEqual(len(self.memory.read("alice").records), 1)
        self.assertEqual(self.memory.read("alice").revision, 1)

    def test_inferred_records_are_explicit_and_not_confirmed(self):
        quote = "I think I generally prefer blue bags"
        with self.assertRaisesRegex(UserMemoryError, "uncertain"):
            self.save(preference(quote=quote))
        self.save(preference(quote=quote, basis="inferred"))
        self.assertEqual(self.memory.read("alice").records[0].basis, "inferred")

    def test_purchase_requires_confirmation_not_recommendation(self):
        for quote in [
            "I might buy blue boots",
            "I like the blue boots you recommended",
        ]:
            with self.assertRaises(UserMemoryError):
                self.save(
                    MemoryProposal(
                        category="purchase",
                        attribute="item",
                        value="blue boots",
                        scope="general",
                        quote=quote,
                    )
                )
        self.save(
            MemoryProposal(
                category="purchase",
                attribute="item",
                value="blue boots",
                quote="I bought blue boots",
            )
        )
        self.assertEqual(self.memory.read("alice").records[0].category, "purchase")

    def test_relevance_and_bounded_context(self):
        self.save()
        with self.sessions.open("alice", self.sid) as session:
            self.assertEqual(len(self.memory.context(session, "bags")["records"]), 1)
            self.assertEqual(self.memory.context(session, "umbrella")["records"], [])

    def test_failed_atomic_replace_preserves_previous_profile(self):
        self.save()
        before = (self.memory.directory("alice") / "profile.md").read_bytes()
        with (
            patch(
                "shopping_agent.user_memory.os.replace", side_effect=OSError("fixture")
            ),
            self.assertRaises(OSError),
        ):
            self.save(
                MemoryProposal(
                    category="fact",
                    attribute="travel",
                    value="travel frequently",
                    quote="I travel frequently",
                )
            )
        self.assertEqual(
            (self.memory.directory("alice") / "profile.md").read_bytes(), before
        )

    def test_symlinks_and_profile_corruption_fail_closed(self):
        self.save()
        path = self.memory.directory("alice") / "profile.md"
        path.write_text("not a profile")
        with self.assertRaises(UserMemoryError):
            self.memory.read("alice")
        path.unlink()
        path.symlink_to(self.root / "outside")
        with self.assertRaises(OSError):
            self.memory.read("alice")

    def test_hashed_owner_directory_does_not_interpret_user_id_as_path(self):
        path = self.memory.directory("../../outside")
        self.assertEqual(path.parent, self.memory.root)
        self.assertEqual(len(path.name), 64)

    def test_independent_qa_evidence_counterexamples(self):
        cases = [
            (
                MemoryProposal(
                    category="fact",
                    attribute="condition",
                    value="hungry",
                    quote="I am hungry",
                ),
                None,
            ),
            (
                MemoryProposal(
                    category="dislike",
                    attribute="color",
                    value="blue",
                    scope="bags",
                    quote="I generally don't dislike blue bags",
                ),
                None,
            ),
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="blue",
                    quote="I generally prefer bags that are blue",
                ),
                None,
            ),
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="blue",
                    quote="I generally prefer bags in blue",
                ),
                None,
            ),
            (preference(quote="I don't generally prefer blue bags"), None),
            (
                MemoryProposal(
                    category="fact",
                    attribute="travel",
                    value="traveler",
                    quote="I am not a traveler",
                ),
                None,
            ),
            (
                MemoryProposal(
                    category="fact",
                    attribute="shopping",
                    value="blue boots",
                    quote="I'm looking for blue boots",
                ),
                None,
            ),
            (
                MemoryProposal(
                    category="purchase",
                    attribute="item",
                    value="blue boots",
                    quote="I bought blue boots, do not remember this",
                ),
                None,
            ),
            (preference(), 'My dad said "I generally prefer blue bags"'),
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="blue",
                    quote="I generally prefer blue bags",
                ),
                None,
            ),
        ]
        for proposal, message in cases:
            with self.subTest(quote=proposal.quote), self.assertRaises(UserMemoryError):
                self.save(proposal, message)
        self.assertEqual(self.memory.read("alice").records, [])

    def test_profile_history_limit_is_a_safe_domain_error(self):
        records = [
            MemoryRecord(
                **preference().model_dump(),
                id="um-" + f"{i:032x}",
                source_session_id=self.sid,
                source_event_id=f"old-{i}",
                created_at="fixture",
                status="superseded",
            )
            for i in range(500)
        ]
        directory = self.memory.directory("alice")
        directory.mkdir()
        path = directory / "profile.md"
        path.write_text(render_profile(UserProfile(user_id="alice", records=records)))
        before = path.read_bytes()
        with self.assertRaisesRegex(UserMemoryError, "profile_record_limit"):
            self.save()
        self.assertEqual(path.read_bytes(), before)

    def test_visible_target_gate_and_old_value_prioritisation(self):
        self.save()
        old = self.memory.read("alice").records[0]
        with self.sessions.open("alice", self.sid) as session:
            proposal = preference(
                quote="Forget my blue bags preference", op="RETRACT", target_id=old.id
            )
            event = session.append("user_message", {"message": proposal.quote})
            with self.assertRaisesRegex(UserMemoryError, "visible_target"):
                self.memory.apply(
                    session, event, [proposal], expected_revision=1, visible_ids=set()
                )
            self.assertEqual(
                self.memory.context(session, "bag")["records"][0]["id"], old.id
            )
        # Enough unrelated general facts to push an older fact outside the default view.
        for i in range(10):
            self.save(
                MemoryProposal(
                    category="fact",
                    attribute=f"fact_{i}",
                    value=f"fact{i}",
                    quote=f"Remember I have fact{i}",
                )
            )
        with self.sessions.open("alice", self.sid) as session:
            self.assertEqual(
                self.memory.context(session, "Please correct fact0")["records"][0][
                    "value"
                ],
                "fact0",
            )

    def test_natural_language_first_person_ownership_positive(self):
        cases = [
            # Exact Stage 2 failure
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Black is usually my go-to for workout stuff",
                    basis="confirmed",
                ),
                "Hi! I'm looking for a casual tank top to wear to the gym. Nothing fancy, and I'd like to keep it affordable, under $50 ideally. Black is usually my go-to for workout stuff if you have any.",
            ),
            # Inverted favorite
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="silver",
                    scope="jewelry",
                    quote="Silver jewelry is my favorite",
                    basis="confirmed",
                ),
                "Silver jewelry is my favorite.",
            ),
            # Topical framing before subject I
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="bags",
                    quote="For bags, I generally go with black",
                    basis="confirmed",
                ),
                "For bags, I generally go with black.",
            ),
            # Tendency / habitual preference
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="lightweight",
                    scope="materials",
                    quote="I tend to prefer lightweight materials",
                    basis="confirmed",
                ),
                "I tend to prefer lightweight materials.",
            ),
        ]
        for idx, (proposal, message) in enumerate(cases):
            with self.subTest(idx=idx, quote=proposal.quote):
                result = self.save(proposal, message)
                self.assertFalse(result.get("idempotent", False))
                records = self.memory.read("alice").records
                active = [r for r in records if r.status == "active"]
                self.assertEqual(active[-1].value, proposal.value)
                self.assertEqual(active[-1].attribute, proposal.attribute)
                self.assertEqual(active[-1].quote, proposal.quote)

    def test_natural_language_first_person_ownership_negative_and_edge_cases(self):
        cases = [
            # Third-party speech within quote
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="My dad said black is usually my go-to for workout stuff",
                ),
                None,
                "memory_requires_first_person_ownership",
            ),
            # Third-party speech in message outside quote
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Black is usually my go-to for workout stuff",
                ),
                'My sister told me "Black is usually my go-to for workout stuff"',
                "memory_quote_requires_own_statement",
            ),
            # Third-party possessive
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="My friend's go-to is black for workout stuff",
                ),
                None,
                "memory_requires_first_person_ownership",
            ),
            # Third-party favorite
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="silver",
                    scope="jewelry",
                    quote="Silver jewelry is my sister's favorite",
                ),
                None,
                "memory_requires_first_person_ownership",
            ),
            # Reported attribution
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="silver",
                    scope="jewelry",
                    quote="She told me that silver jewelry is my favorite",
                ),
                None,
                "memory_requires_first_person_ownership",
            ),
            # Negated go-to
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Black is not my go-to for workout stuff",
                ),
                None,
                "memory_value_must_preserve_negation",
            ),
            # Negated favorite
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="silver",
                    scope="jewelry",
                    quote="Silver jewelry isn't my favorite",
                ),
                None,
                "memory_value_must_preserve_negation",
            ),
            # Hypothetical condition
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="If I worked out, black would be my go-to for workout stuff",
                ),
                None,
                "hypothetical_preference_not_persistent",
            ),
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Black would be my go-to for workout stuff",
                ),
                None,
                "hypothetical_preference_not_persistent",
            ),
            # Former preference
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Black used to be my go-to for workout stuff",
                ),
                None,
                "former_preference_not_persistent",
            ),
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="silver",
                    scope="jewelry",
                    quote="In the past, silver jewelry was my favorite",
                ),
                None,
                "former_preference_not_persistent",
            ),
            (
                MemoryProposal(
                    category="preference",
                    attribute="material",
                    value="lightweight",
                    scope="materials",
                    quote="I used to prefer lightweight materials",
                ),
                None,
                "former_preference_not_persistent",
            ),
            # Recipient / gift
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Black is usually my go-to for my sister's birthday gift for workout stuff",
                ),
                None,
                "temporary_or_recipient_information_not_persistent",
            ),
            # Temporary
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="workout",
                    quote="Just for today, black is my go-to for workout stuff",
                ),
                None,
                "temporary_or_recipient_information_not_persistent",
            ),
            # Arbitrary sentences containing 'my'
            (
                MemoryProposal(
                    category="preference",
                    attribute="color",
                    value="black",
                    scope="bag",
                    quote="Look at my black bag",
                ),
                None,
                "memory_requires_first_person_ownership",
            ),
        ]
        for proposal, message, expected_err in cases:
            with self.subTest(quote=proposal.quote, expected_err=expected_err):
                with self.assertRaisesRegex(UserMemoryError, expected_err):
                    self.save(proposal, message)
