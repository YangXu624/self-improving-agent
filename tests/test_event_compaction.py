"""Lossless event sharing/deltas preserve public responses, replay and failure safety."""

import base64
import hashlib
import json
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from test_agent import ScriptedPolicy, recommend, search
from test_retrieval import product
from test_sessions import add

from shopping_agent.agent import ShoppingAgent
from shopping_agent.contracts import Event, ShoppingState
from shopping_agent.event_codec import decode_event, encode_event
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import MAX_EVENT_BYTES, SessionError, SessionStore, dumps
from shopping_agent.state import apply_updates


class EventCompactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SessionStore(self.root / "sessions")
        self.sid = self.store.create("shopper")
        self.log = self.store.root / self.sid / "events.jsonl"
        source, index = self.root / "catalogue.jsonl", self.root / "index.sqlite"
        source.write_text(
            "".join(
                json.dumps(product(i, price)) + "\n"
                for i, price in [("one", 20), ("two", 50)]
            )
        )
        build_index(source, index)
        self.search = LexicalSearch(index)
        self.addCleanup(self.search.close)

    def run_turn(self, message="boots", *steps, request_id="first"):
        policy = ScriptedPolicy(*(steps or (search, recommend)))
        response = ShoppingAgent(self.store, self.search, policy).turn(
            "shopper", self.sid, message, request_id=request_id
        )
        return response

    def canonical_events(self):
        with self.store.open("shopper", self.sid) as session:
            return [e.model_dump() for e in session.events]

    def test_roundtrip_keeps_prompt_hashes_cards_and_completed_request_replay(self):
        original_response = self.run_turn(
            "boots", search, lambda c: recommend(c, ["two", "one"])
        )
        original_events = self.canonical_events()
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        assistant = next(r for r in records if r["type"] == "assistant_response")
        complete = next(r for r in records if r["type"] == "turn_completed")
        self.assertNotIn("products", assistant["payload"])
        self.assertEqual(assistant["payload"]["products_ref"]["ids"], ["two", "one"])
        self.assertEqual(set(complete["payload"]), {"response_event"})
        self.assertTrue(
            any(
                "message_ref" in m
                for r in records
                if r["type"] == "model_request"
                for m in r["payload"]["messages"]
            )
        )
        self.store = SessionStore(self.store.root)
        self.assertEqual(self.canonical_events(), original_events)
        for event in original_events:
            if event["type"] == "model_request":
                p = event["payload"]
                self.assertEqual(
                    hashlib.sha256(dumps(p["messages"]).encode()).hexdigest(),
                    p["context_sha256"],
                )
        with patch(
            "shopping_agent.provider.urlopen",
            side_effect=AssertionError("Network forbidden"),
        ) as network:
            replay = ShoppingAgent(self.store, self.search, ScriptedPolicy()).turn(
                "shopper", self.sid, "boots", request_id="first"
            )
        network.assert_not_called()
        self.assertEqual(replay, original_response)
        self.assertEqual(self.canonical_events(), original_events)
        verbose_bytes = sum(len((dumps(e) + "\n").encode()) for e in original_events)
        self.assertLess(self.log.stat().st_size, verbose_bytes * 0.75)

    def test_state_deltas_preserve_correction_retraction_new_goal_and_snapshots(self):
        actions = [
            ("under 100", [add()]),
            ("under 30", None),
            ("withdraw budget", None),
            ("new gift", None),
        ]
        original_states = []
        for index, (message, changes) in enumerate(actions):
            with self.store.open("shopper", self.sid) as session:
                event = session.append("user_message", {"message": message}, str(index))
                if index == 1:
                    update = add(value=30.0, quote=message).model_dump()
                    update.update(
                        op="REPLACE", target_id=session.state.requirements[0].id
                    )
                    changes = [update]
                elif index == 2:
                    changes = [
                        {
                            "op": "RETRACT",
                            "target_id": session.state.requirements[-1].id,
                            "quote": message,
                        }
                    ]
                elif index == 3:
                    changes = [{"op": "NEW_GOAL", "quote": message}]
                after = apply_updates(
                    session.state,
                    changes,
                    expected_version=session.state.version,
                    user_message=message,
                    source_event_id=event.event_id,
                )
                session.commit(after, [], str(index))
                original_states.append(after.model_dump())
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        commits = [r for r in records if r["type"] == "state_committed"]
        self.assertTrue(
            all(
                "state_delta" in r["payload"] and "state" not in r["payload"]
                for r in commits
            )
        )
        # NEW_GOAL changes no already-retired requirements; no old ledger is repeated.
        self.assertEqual(commits[-1]["payload"]["state_delta"]["requirements"], [])
        path = self.store.root / self.sid / "state.json"
        snapshot = json.loads(path.read_text())
        self.assertEqual(
            ShoppingState.model_validate(snapshot["state"]).model_dump(),
            original_states[-1],
        )
        self.assertNotIn("replaces_id", snapshot["state"]["requirements"][0])
        path.write_text("corrupt cache")
        with self.store.open("shopper", self.sid) as session:
            self.assertEqual(
                [
                    e.payload["state"]
                    for e in session.events
                    if e.type == "state_committed"
                ],
                original_states,
            )
            self.assertEqual(session.state.goal_epoch, 1)
            self.assertEqual(session.state.requirements[-1].status, "retracted")

    def test_legacy_prefix_is_unchanged_when_compact_turns_are_appended(self):
        self.run_turn()
        legacy = "".join(dumps(e) + "\n" for e in self.canonical_events()).encode()
        self.log.write_bytes(legacy)  # Only this synthetic fixture, not user data.
        self.run_turn(
            "under 100",
            lambda c: search(c, [add().model_dump()]),
            recommend,
            request_id="second",
        )
        self.assertTrue(self.log.read_bytes().startswith(legacy))
        self.assertEqual(
            len(
                [
                    e
                    for e in self.canonical_events()
                    if e["type"] == "assistant_response"
                ]
            ),
            2,
        )
        self.assertTrue(
            any(
                json.loads(line).get("storage_version") == 2
                for line in self.log.read_bytes()[len(legacy) :].splitlines()
            )
        )

    def test_corrupt_references_fail_closed_without_rewriting_log(self):
        self.run_turn()
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        variants = []
        for reference in (-1, True, 1, 99999):
            variants.append(
                (
                    "turn_completed",
                    lambda r, value=reference: r["payload"].update(
                        response_event=value
                    ),
                )
            )
        variants.extend(
            [
                ("turn_completed", lambda r: r.update(storage_version=99)),
                ("turn_completed", lambda r: r.update(turn_id="another-turn")),
                ("turn_completed", lambda r: r.update(turn_id=None)),
                (
                    "assistant_response",
                    lambda r: r["payload"]["products_ref"].update(ids=["unseen"]),
                ),
                (
                    "assistant_response",
                    lambda r: r["payload"].update(search_id="another-search"),
                ),
            ]
        )
        for kind, mutate in variants:
            with self.subTest(kind=kind, mutate=mutate):
                changed = json.loads(json.dumps(records))
                mutate(next(r for r in changed if r["type"] == kind))
                raw = "".join(dumps(r) + "\n" for r in changed).encode()
                self.log.write_bytes(raw)
                with self.assertRaises(SessionError):
                    self.canonical_events()
                self.assertEqual(self.log.read_bytes(), raw)

    def test_message_reference_rejects_invalid_index(self):
        self.run_turn()
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        reference = next(
            m
            for r in records
            if r["type"] == "model_request"
            for m in r["payload"]["messages"]
            if "message_ref" in m
        )
        reference["message_ref"][1] = -1
        self.log.write_text("".join(dumps(r) + "\n" for r in records))
        with self.assertRaises(SessionError):
            self.canonical_events()

    def test_compressed_prompt_roundtrip_is_exact_for_unicode_and_whitespace(self):
        text = "  商品\nWaterproof boots 🥾  " * 200
        with self.store.open("shopper", self.sid) as session:
            event = session.append(
                "model_request",
                {"messages": [{"role": "user", "content": text}]},
                "unicode",
            )
        raw = json.loads(self.log.read_text().splitlines()[-1])
        self.assertIn("content_zlib", raw["payload"]["messages"][0])
        self.assertEqual(self.canonical_events()[-1], event.model_dump())

    def test_compressed_prompt_rejects_invalid_truncated_and_oversized_streams(self):
        self.run_turn()
        original = [json.loads(line) for line in self.log.read_text().splitlines()]
        for content in (
            "not base64!",
            base64.b64encode(b"not-zlib").decode(),
            base64.b64encode(zlib.compress(b"x" * (MAX_EVENT_BYTES + 1))).decode(),
            base64.b64encode(zlib.compress(b"valid")[:-1]).decode(),
        ):
            with self.subTest(content=content[:20]):
                records = json.loads(json.dumps(original))
                message = next(
                    m
                    for r in records
                    if r["type"] == "model_request"
                    for m in r["payload"]["messages"]
                    if "content_zlib" in m
                )
                message["content_zlib"] = content
                self.log.write_text("".join(dumps(r) + "\n" for r in records))
                before = self.log.read_bytes()
                with self.assertRaises(SessionError):
                    self.canonical_events()
                self.assertEqual(self.log.read_bytes(), before)

    def test_delta_duplicate_rows_and_invalid_versions_are_rejected(self):
        self.run_turn("under 100", lambda c: search(c, [add().model_dump()]), recommend)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        for mutation in ("duplicate", "version"):
            changed = json.loads(json.dumps(records))
            delta = next(
                r["payload"]["state_delta"]
                for r in changed
                if r["type"] == "state_committed"
            )
            if mutation == "duplicate":
                delta["requirements"].append(delta["requirements"][0])
            else:
                delta["version"] += 1
            self.log.write_text("".join(dumps(r) + "\n" for r in changed))
            with self.assertRaises(SessionError):
                self.canonical_events()

    def test_reordered_external_commit_uses_lossless_full_state_fallback(self):
        state = apply_updates(
            ShoppingState(),
            [add(), add("color", "eq", "red", "red")],
            expected_version=0,
            user_message="under 100 red",
            source_event_id="source",
        )
        reordered = state.model_copy(deep=True)
        reordered.version = 2
        reordered.requirements.reverse()
        event = Event(
            event_id="event",
            seq=1,
            session_id="session",
            user_id="owner",
            timestamp="date",
            turn_id="turn",
            type="state_committed",
            state_version=2,
            payload={
                "before_version": 1,
                "state": reordered.model_dump(),
                "updates": [],
            },
        )
        encoded = encode_event(event, [], state)
        self.assertIn("state", encoded["payload"])
        self.assertEqual(decode_event(encoded, [], state), event)

    def test_compaction_does_not_bypass_canonical_event_size_limit(self):
        with self.store.open("shopper", self.sid) as session:
            before = self.log.read_bytes()
            with self.assertRaisesRegex(SessionError, "event_size_limit"):
                session.append(
                    "user_message", {"message": "x" * MAX_EVENT_BYTES}, "large"
                )
            self.assertEqual(self.log.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
