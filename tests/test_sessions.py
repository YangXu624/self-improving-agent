import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from shopping_agent.contracts import Decision, ShoppingState, StateUpdate
from shopping_agent.sessions import SessionError, SessionStore
from shopping_agent.state import StateError, apply_updates


def add(field="price", op="lt", value=100.0, quote="under 100", strength="hard"):
    return StateUpdate.model_validate(
        {
            "op": "ADD",
            "quote": quote,
            "requirement": {
                "field": field,
                "op": op,
                "value": value,
                "quote": quote,
                "strength": strength,
            },
        }
    )


class StateTests(unittest.TestCase):
    def test_closed_action_and_requirement_contracts(self):
        with self.assertRaises(ValidationError):
            Decision.model_validate(
                {
                    "based_on_state_version": 0,
                    "reason": "bad",
                    "action": {
                        "type": "SEARCH",
                        "query": "boots",
                        "sql": "DROP TABLE products",
                    },
                }
            )
        with self.assertRaises(ValidationError):
            add(value=True)
        with self.assertRaises(ValidationError):
            add(value=float("nan"))
        with self.assertRaises(ValidationError):
            add(field="recipient", op="eq", value="mother")

    def test_correction_preserves_history_and_retraction_not_positive(self):
        state = apply_updates(
            ShoppingState(),
            [add(), add("material", "neq", "leather", "no leather")],
            expected_version=0,
            user_message="boots under 100, no leather",
            source_event_id="u1",
        )
        prior = state.model_dump()
        replacement = StateUpdate(
            op="REPLACE",
            target_id=state.requirements[0].id,
            quote="under 60",
            requirement=add(value=60.0, quote="under 60").requirement,
        )
        state2 = apply_updates(
            state,
            [replacement],
            expected_version=1,
            user_message="Actually under 60",
            source_event_id="u2",
        )
        self.assertEqual(state.model_dump(), prior)
        self.assertEqual(state2.version, 2)
        self.assertEqual(state2.requirements[0].status, "superseded")
        state3 = apply_updates(
            state2,
            [
                StateUpdate(
                    op="RETRACT",
                    target_id=state2.requirements[1].id,
                    quote="leather is fine",
                )
            ],
            expected_version=2,
            user_message="leather is fine",
            source_event_id="u3",
        )
        self.assertFalse(
            any(
                r.field == "material" and r.status == "active"
                for r in state3.requirements
            )
        )

    def test_evidence_staleness_and_transactional_edits(self):
        state = ShoppingState()
        with self.assertRaises(StateError):
            apply_updates(
                state,
                [add()],
                expected_version=0,
                user_message="hello",
                source_event_id="u",
            )
        with self.assertRaises(StateError):
            apply_updates(
                state, [], expected_version=1, user_message="hello", source_event_id="u"
            )
        with self.assertRaises(StateError):
            apply_updates(
                state,
                [add(), StateUpdate(op="RETRACT", target_id="foreign", quote="100")],
                expected_version=0,
                user_message="under 100",
                source_event_id="u",
            )
        self.assertEqual(state.requirements, [])

    def test_conflicts_duplicate_and_new_goal(self):
        state = apply_updates(
            ShoppingState(),
            [add(), add(op="gte", value=120.0, quote="at least 120")],
            expected_version=0,
            user_message="under 100 and at least 120",
            source_event_id="u",
        )
        self.assertEqual(state.conflicts, ["price"])
        same = apply_updates(
            state,
            [add()],
            expected_version=1,
            user_message="under 100",
            source_event_id="u2",
        )
        self.assertEqual(same.version, 1)
        fresh = apply_updates(
            state,
            [StateUpdate(op="NEW_GOAL", quote="new gift")],
            expected_version=1,
            user_message="new gift",
            source_event_id="u3",
        )
        self.assertFalse(fresh.conflicts)
        self.assertEqual(fresh.goal_epoch, 1)
        self.assertTrue(all(r.status == "superseded" for r in fresh.requirements))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SessionStore(self.tmp.name)

    def test_owner_isolation_and_same_user_new_session_empty(self):
        one, two = self.store.create("alice"), self.store.create("alice")
        with self.store.open("alice", one) as s:
            event = s.append("user_message", {"message": "under 100"}, "turn")
            state = apply_updates(
                s.state,
                [add()],
                expected_version=0,
                user_message="under 100",
                source_event_id=event.event_id,
            )
            s.commit(state, [add().model_dump()], "turn")
        with self.store.open("alice", two) as s:
            self.assertEqual(s.state.version, 0)
        with self.assertRaises(PermissionError):
            with self.store.open("bob", one):
                pass
        with self.assertRaises(SessionError):
            with self.store.open("alice", "../../escape"):
                pass

    def test_restart_rebuilds_stale_snapshot_and_keeps_every_version(self):
        sid = self.store.create("alice")
        with self.store.open("alice", sid) as s:
            s.append("user_message", {"message": "under 100"}, "t1")
            state = apply_updates(
                s.state,
                [add()],
                expected_version=0,
                user_message="under 100",
                source_event_id=s.events[-1].event_id,
            )
            s.commit(state, [], "t1")
        path = Path(self.tmp.name) / sid
        original_log = (path / "events.jsonl").read_bytes()
        (path / "state.json").write_text("invalid snapshot")
        with SessionStore(self.tmp.name).open("alice", sid) as s:
            self.assertEqual(s.state.version, 1)
            self.assertEqual(len(s.events), 3)
        self.assertEqual((path / "events.jsonl").read_bytes(), original_log)
        self.assertEqual(
            json.loads((path / "state.json").read_text())["last_event_seq"], 3
        )

    def test_incomplete_tail_and_middle_corruption_fail_closed(self):
        sid = self.store.create("alice")
        path = Path(self.tmp.name) / sid / "events.jsonl"
        with path.open("ab") as f:
            f.write(b'{"incomplete":')
        original = path.read_bytes()
        with self.assertRaises(SessionError):
            with self.store.open("alice", sid):
                pass
        self.assertEqual(path.read_bytes(), original)

    def test_one_writer_per_session(self):
        sid = self.store.create("alice")
        with self.store.open("alice", sid):
            with self.assertRaisesRegex(SessionError, "busy"):
                with SessionStore(self.tmp.name).open("alice", sid):
                    pass

    def test_complete_corrupt_record_is_not_skipped(self):
        sid = self.store.create("alice")
        path = Path(self.tmp.name) / sid / "events.jsonl"
        with path.open("ab") as handle:
            handle.write(b'{"unexpected":"record"}\n')
        before = path.read_bytes()
        with self.assertRaisesRegex(SessionError, "corrupt_event_log"):
            with self.store.open("alice", sid):
                pass
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
