"""Thin UI boundary around the existing agent/store; no Streamlit dependency here."""

from pathlib import Path
from typing import Any

from .agent import DecisionPolicy, ShoppingAgent
from .context import builder_for_profile
from .contracts import Event
from .memory_views import compact_state
from .retrieval import LexicalSearch, file_hash
from .sessions import MAX_EVENT_BYTES, SessionError, SessionStore
from .user_memory import UserMemoryStore


class ChatService:
    """Owned session operations; open SQLite per request, never across UI rerun threads.

    The composition root must supply an explicit policy. Production uses DeepSeekPolicy;
    tests inject fixtures or mock HTTP. No implicit scripted/default policy is available.
    """

    def __init__(
        self,
        catalogue: Path,
        index: Path,
        sessions: Path,
        *,
        policy: DecisionPolicy,
        cards_profile: str = "baseline",
        user_memory_enabled: bool = False,
        user_memory_root: Path | None = None,
        memory_format: str = "compact",
    ):
        self.index = index
        self.catalogue_hash = file_hash(catalogue)
        self.policy = policy
        self.memory_format = memory_format
        self.context_builder = builder_for_profile(
            cards_profile, memory_format=memory_format
        )
        self.store = SessionStore(sessions, snapshot_format=memory_format)
        self.user_memory = (
            UserMemoryStore(user_memory_root or sessions.parent / "user-memory")
            if user_memory_enabled
            else None
        )
        tool = self._search()
        tool.close()

    def _search(self) -> LexicalSearch:
        return LexicalSearch(self.index, expected_catalogue_hash=self.catalogue_hash)

    def create(self, user_id: str) -> str:
        return self.store.create(user_id)

    def sessions(self, user_id: str) -> list[dict[str, str]]:
        """List only this local owner's valid UUID sessions, newest first.

        Read the bounded creation record for identity before opening full history. Corrupt
        or busy sessions are not mutated/repaired here; a direct resume still reports them.
        """
        summaries = []
        for folder in self.store.root.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                with (folder / "events.jsonl").open("rb") as log:
                    line = log.readline(MAX_EVENT_BYTES + 1)
                first = Event.model_validate_json(line)
                if first.user_id != user_id or first.type != "session_created":
                    continue
                with self.store.open(user_id, folder.name) as session:
                    first_message = next(
                        (
                            e.payload["message"]
                            for e in session.events
                            if e.type == "user_message"
                        ),
                        "New chat",
                    )
                    summaries.append(
                        {
                            "id": session.id,
                            "title": first_message[:45],
                            "created": first.timestamp,
                        }
                    )
            except (OSError, ValueError, PermissionError):
                continue
        return sorted(summaries, key=lambda s: (s["created"], s["id"]), reverse=True)

    def view(self, user_id: str, session_id: str) -> dict[str, Any]:
        with self.store.open(user_id, session_id) as session:
            messages = []
            for event in session.events:
                if event.type == "user_message":
                    messages.append(
                        {
                            "role": "user",
                            "message": event.payload["message"],
                            "turn_id": event.turn_id,
                        }
                    )
                elif event.type == "assistant_response":
                    messages.append({"role": "assistant", **event.payload})
            return {
                "session_id": session.id,
                "state": session.state.model_dump(),
                "shopping_state": compact_state(session),
                "messages": messages,
                "events": [e.model_dump() for e in session.events],
            }

    def send(
        self, user_id: str, session_id: str, message: str, request_id: str
    ) -> dict:
        tool = self._search()
        try:
            return ShoppingAgent(
                self.store,
                tool,
                self.policy,
                context_builder=self.context_builder,
                user_memory=self.user_memory,
                memory_format=self.memory_format,
            ).turn(user_id, session_id, message, request_id=request_id)
        finally:
            tool.close()

    def resume(self, user_id: str, session_id: str) -> str:
        if not session_id.strip():
            raise SessionError("Enter a session ID to resume")
        self.view(user_id, session_id.strip())
        return session_id.strip()
