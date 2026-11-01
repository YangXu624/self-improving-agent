"""Representation changes retain predicate meaning, edit safety and historical loading."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from shopping_agent.contracts import Requirement, ShoppingState
from shopping_agent.memory_views import (
    compact_state,
    compact_user_memory,
    expand_decision,
)
from shopping_agent.user_memory import (
    MemoryRecord,
    UserProfile,
    _render_legacy_profile,
    parse_profile,
    render_profile,
)


def state_fixture():
    rows = [
        ("price", "gte", 40.0, "hard"),
        ("price", "lt", 80.0, "hard"),
        ("color", "not_contains", "black", "hard"),
        ("brand", "in", ["Nike", "Adidas"], "soft"),
    ]
    return ShoppingState(
        version=3,
        goal_epoch=1,
        requirements=[
            Requirement(
                id=f"internal-{i}",
                field=f,
                op=op,
                value=value,
                strength=strength,
                quote="source quote",
                source_event_id="internal-source",
                created_version=1,
            )
            for i, (f, op, value, strength) in enumerate(rows)
        ],
    )


def profile_fixture():
    record = MemoryRecord(
        category="preference",
        attribute="color",
        value="Blue",
        scope="bags",
        quote="I generally prefer Blue bags",
        id="um-" + "1" * 32,
        source_session_id="a" * 32,
        source_event_id="source-event",
        created_at="2026-11-01T00:00:00Z",
    )
    return UserProfile(user_id="alice", revision=1, records=[record])


class MemoryViewTests(unittest.TestCase):
    def test_actual_serialized_prompt_is_smaller_on_fixed_fixture(self):
        from shopping_agent.context import build_context

        profile = profile_fixture()
        view = {
            "revision": 1,
            "records": [
                {
                    key: getattr(r, key)
                    for key in (
                        "id",
                        "category",
                        "attribute",
                        "value",
                        "scope",
                        "basis",
                    )
                }
                for r in profile.records
            ],
        }
        counts = {}
        for format_name in ("legacy", "compact"):
            messages = build_context(
                SimpleNamespace(state=state_fixture(), events=[]),
                "I need bags",
                None,
                [],
                {"model_calls": 3, "searches": 2},
                True,
                user_memory=view,
                memory_format=format_name,
            )
            counts[format_name] = sum(len(m["content"]) for m in messages)
        self.assertLess(counts["compact"], counts["legacy"])

    def test_compact_state_keeps_ranges_exclusions_alternatives_without_audit(self):
        state = state_fixture()
        view = compact_state(SimpleNamespace(state=state, events=[]))
        self.assertEqual(view["hard"]["price"], [{"gte": 40.0}, {"lt": 80.0}])
        self.assertEqual(view["hard"]["color"], [{"not_contains": "black"}])
        self.assertEqual(view["preferences"]["brand"], [{"in": ["Nike", "Adidas"]}])
        text = json.dumps(view)
        self.assertTrue(
            all(
                k not in text
                for k in (
                    "internal-",
                    "source_event_id",
                    "created_version",
                    "goal_epoch",
                    "version",
                )
            )
        )

    def test_decision_resolves_current_field_reference_and_server_revision(self):
        raw = {
            "updates": [
                {
                    "op": "RETRACT",
                    "target_id": "hard.price.1",
                    "quote": "remove my upper budget",
                }
            ],
            "action": {"type": "RESPOND", "message": "Okay"},
            "reason": "Withdraw upper bound",
        }
        result = expand_decision(json.dumps(raw), state_fixture())
        self.assertEqual(result.based_on_state_version, 3)
        self.assertEqual(result.updates[0].target_id, "internal-1")
        raw["updates"][0]["target_id"] = "hard.price.99"
        with self.assertRaisesRegex(ValueError, "current_state_reference"):
            expand_decision(json.dumps(raw), state_fixture())

    def test_user_memory_is_text_with_short_current_references(self):
        profile = profile_fixture()
        view = {"revision": 1, "records": [profile.records[0].model_dump()]}
        compact = compact_user_memory(view)
        self.assertEqual(
            compact,
            {
                "records": [
                    {
                        "ref": "memory.0",
                        "text": "Usually prefers color: Blue (for bags).",
                    }
                ]
            },
        )
        self.assertNotIn("source-event", json.dumps(compact))
        raw = {
            "updates": [],
            "action": {"type": "RESPOND", "message": "Okay"},
            "reason": "Correct preference",
            "user_memory_updates": [
                {
                    "op": "REPLACE",
                    "category": "preference",
                    "attribute": "color",
                    "value": "Black",
                    "scope": "bags",
                    "quote": "Actually I now generally prefer Black bags",
                    "target_id": "memory.0",
                }
            ],
        }
        decision = expand_decision(json.dumps(raw), ShoppingState(), view)
        self.assertEqual(
            decision.user_memory_updates[0].target_id, profile.records[0].id
        )
        raw["user_memory_updates"][0]["target_id"] = "memory.9"
        with self.assertRaisesRegex(ValueError, "current_memory_reference"):
            expand_decision(json.dumps(raw), ShoppingState(), view)

    def test_readable_markdown_and_legacy_profile_are_lossless(self):
        profile = profile_fixture()
        self.assertEqual(parse_profile(_render_legacy_profile(profile)), profile)
        text = render_profile(profile)
        self.assertEqual(parse_profile(text), profile)
        body = text.split("<details>")[0]
        self.assertIn("Usually prefers color: Blue", body)
        self.assertNotIn("source_event_id", body)
        self.assertNotIn("created_at", body)
        with self.assertRaises(ValueError):
            parse_profile(text.replace("Usually prefers", "Never prefers", 1))

    def test_history_and_uncertainty_are_preserved_without_stale_prose(self):
        profile = profile_fixture()
        profile.records[0].status = "superseded"
        current = profile.records[0].model_copy(
            update={
                "id": "um-" + "2" * 32,
                "value": "Black",
                "basis": "inferred",
                "status": "active",
            }
        )
        profile.records.append(current)
        text = render_profile(profile)
        body = text.split("<details>")[0]
        self.assertNotIn("Blue", body)
        self.assertIn("Black", body)
        self.assertIn("unconfirmed inference", body)
        self.assertEqual(parse_profile(text), profile)

    def test_profile_markup_cannot_escape_into_active_sections(self):
        profile = profile_fixture()
        profile.records[0].value = "<script>bad</script>\n## Fake"
        text = render_profile(profile)
        self.assertNotIn("<script>", text)
        self.assertEqual(parse_profile(text), profile)

    def test_reading_legacy_profile_does_not_rewrite_file(self):
        from shopping_agent.user_memory import UserMemoryStore

        with tempfile.TemporaryDirectory() as temp:
            store = UserMemoryStore(Path(temp))
            directory = store.directory("alice")
            directory.mkdir()
            path = directory / "profile.md"
            original = _render_legacy_profile(profile_fixture())
            path.write_text(original)
            self.assertEqual(store.read("alice"), profile_fixture())
            self.assertEqual(path.read_text(), original)
