"""Single-writer local sessions: authoritative JSONL and a rebuildable snapshot."""

import fcntl
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .contracts import Event, ShoppingState

MAX_EVENT_BYTES = 512_000


def dumps(value, *, compact=False):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        **({"separators": (",", ":")} if compact else {}),
    )


class SessionError(ValueError):
    pass


class Session:
    def __init__(self, directory, user_id, session_id):
        self.directory, self.user_id, self.id = directory, user_id, session_id
        self.events, self.state = [], ShoppingState()
        seen_ids = set()
        path = directory / "events.jsonl"
        if path.exists():
            with path.open("rb") as handle:
                for line in handle:
                    if not line.endswith(b"\n") or len(line) > MAX_EVENT_BYTES:
                        raise SessionError(
                            "incomplete_or_oversized_event_log; preserve file for repair"
                        )
                    try:
                        event = Event.model_validate_json(line)
                    except ValueError as exc:
                        raise SessionError("corrupt_event_log") from exc
                    if event.session_id != session_id or event.user_id != user_id:
                        raise PermissionError("Session owner mismatch")
                    if event.seq != len(self.events) + 1:
                        raise SessionError("noncontiguous_event_sequence")
                    if not self.events and event.type != "session_created":
                        raise SessionError("missing_session_creation")
                    if event.type == "state_committed":
                        try:
                            after = ShoppingState.model_validate(event.payload["state"])
                        except (KeyError, ValueError) as exc:
                            raise SessionError("corrupt_state_commit") from exc
                        if after.version != self.state.version + 1:
                            raise SessionError("invalid_state_version_history")
                        if event.payload.get("before_version") != self.state.version:
                            raise SessionError("invalid_commit_before_version")
                        self.state = after
                    if event.state_version != self.state.version:
                        raise SessionError("event_state_version_mismatch")
                    if event.event_id in seen_ids:
                        raise SessionError("duplicate_event_id")
                    seen_ids.add(event.event_id)
                    self.events.append(event)
        if not self.events:
            raise SessionError("missing_session")
        self.snapshot()  # Event log wins over a stale/missing/corrupt cache.

    def append(self, type, payload, turn_id=None):
        event = Event(
            event_id=uuid4().hex,
            seq=len(self.events) + 1,
            state_version=(
                payload["state"]["version"]
                if type == "state_committed"
                else self.state.version
            ),
            session_id=self.id,
            user_id=self.user_id,
            timestamp=datetime.now(UTC).isoformat(),
            turn_id=turn_id,
            type=type,
            payload=payload,
        )
        encoded = (dumps(event.model_dump()) + "\n").encode()
        if len(encoded) > MAX_EVENT_BYTES:
            raise SessionError("event_size_limit")
        with (self.directory / "events.jsonl").open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        return event

    def commit(self, state, updates, turn_id):
        if state.version != self.state.version + 1:
            raise SessionError("state_version_mismatch")
        self.append(
            "state_committed",
            {
                "before_version": self.state.version,
                "state": state.model_dump(),
                "updates": updates,
            },
            turn_id,
        )
        self.state = state.model_copy(deep=True)
        self.snapshot()

    def snapshot(self):
        value = {
            "schema_version": 1,
            "session_id": self.id,
            "user_id": self.user_id,
            "last_event_seq": len(self.events),
            "state": self.state.model_dump(),
        }
        fd, temp = tempfile.mkstemp(dir=self.directory, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(dumps(value) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.directory / "state.json")
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


class SessionStore:
    _locks: ClassVar[dict] = {}
    _guard = threading.Lock()

    def __init__(self, root="data/sessions"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, user_id):
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
            raise SessionError("invalid_user_id")
        session_id = uuid4().hex
        directory = self.root / session_id
        directory.mkdir(mode=0o700)
        event = Event(
            event_id=uuid4().hex,
            seq=1,
            session_id=session_id,
            user_id=user_id,
            timestamp=datetime.now(UTC).isoformat(),
            turn_id=None,
            type="session_created",
            payload={"state": ShoppingState().model_dump()},
        )
        with (directory / "events.jsonl").open("xb") as handle:
            handle.write((dumps(event.model_dump()) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        with self.open(user_id, session_id):
            pass
        return session_id

    @contextmanager
    def open(self, user_id, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", session_id
        ):
            raise SessionError("invalid_session_id")
        directory = self.root / session_id
        if not directory.is_dir() or directory.is_symlink():
            raise SessionError("unknown_session")
        with self._guard:
            lock = self._locks.setdefault(str(directory), threading.Lock())
        if not lock.acquire(blocking=False):
            raise SessionError("session_busy")
        try:
            with (directory / ".lock").open("ab") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise SessionError("session_busy") from exc
                try:
                    session = Session(directory, user_id, session_id)
                    yield session
                    session.snapshot()
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock.release()
