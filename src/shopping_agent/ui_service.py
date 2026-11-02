"""Thin UI boundary around the existing agent/store; no Streamlit dependency here."""

import json
import os
import re
from pathlib import Path
from typing import Any

from .agent import DecisionPolicy, ShoppingAgent
from .context import builder_for_profile
from .contracts import Event
from .memory_views import compact_state
from .purchases import PurchaseRecord, PurchaseStore
from .retrieval import LexicalSearch, file_hash
from .runtime_config import RuntimeConfig
from .sessions import MAX_EVENT_BYTES, SessionError, SessionStore
from .user_memory import UserMemoryStore

DEFAULT_MANUAL_USER_ID = "manual-user-001"
SAFE_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")


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
        purchases_db_path: Path | None = None,
        memory_format: str = "compact",
        default_user_id: str = DEFAULT_MANUAL_USER_ID,
        runtime_config: RuntimeConfig | None = None,
    ):
        self.index = index
        self.catalogue_hash = file_hash(catalogue)
        self.policy = policy
        self.memory_format = memory_format
        self.runtime_config = runtime_config or RuntimeConfig(
            memory_format=memory_format, user_memory_enabled=user_memory_enabled
        )
        self.context_builder = builder_for_profile(
            cards_profile, memory_format=memory_format
        )
        self.store = SessionStore(sessions, snapshot_format=memory_format)
        self.default_user_id = default_user_id
        self._user_memory_root = user_memory_root or sessions.parent / "user-memory"
        self._user_memory_store = UserMemoryStore(self._user_memory_root)
        self.user_memory_enabled = user_memory_enabled
        self.user_memory = self._user_memory_store if user_memory_enabled else None
        p_path = purchases_db_path or Path(
            os.environ.get(
                "ASTRA_PURCHASES_DB", sessions.parent / "purchases" / "purchases.sqlite"
            )
        )
        self.purchase_store = PurchaseStore(p_path)

        tool = self._search()
        tool.close()

    def set_runtime_config(self, config: RuntimeConfig) -> None:
        """Update active runtime config for subsequent actions."""
        self.runtime_config = config
        self.set_user_memory_enabled(config.user_memory_enabled)

    def get_runtime_config(self) -> RuntimeConfig:
        return self.runtime_config

    def set_user_memory_enabled(self, enabled: bool) -> None:
        """Toggle memory system on or off without re-instantiating storage."""
        self.user_memory_enabled = bool(enabled)
        self.user_memory = self._user_memory_store if self.user_memory_enabled else None

    def resolve_user_id(self, user_id: str | None = None) -> str:
        """Resolve customer identity server-side in local dev; prevent unauthorized access."""
        if not user_id or not str(user_id).strip():
            return self.default_user_id
        uid = str(user_id).strip()
        if not SAFE_USER_ID_RE.match(uid):
            raise SessionError(f"Invalid user identity format: {uid[:20]}")
        # In local manual development, isolate from synthetic evaluation spaces
        if (
            uid.startswith(("eval-", "synthetic-", "blueprint-"))
            and uid != self.default_user_id
        ):
            raise SessionError(
                "Direct impersonation of evaluation benchmark customers is not permitted"
            )
        return uid

    def _search(self) -> LexicalSearch:
        return LexicalSearch(self.index, expected_catalogue_hash=self.catalogue_hash)

    def create(
        self,
        user_id: str | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> str:
        uid = self.resolve_user_id(user_id)
        cfg = runtime_config or self.runtime_config
        sid = self.store.create(uid)
        with self.store.open(uid, sid) as session:
            session.append(
                "session_config_snapshot",
                {"runtime_config": cfg.to_dict()},
                turn_id=f"create-{sid}",
            )
        return sid

    def sessions(self, user_id: str | None = None) -> list[dict[str, str]]:
        """List only this local owner's valid UUID sessions, newest first.

        Read the bounded creation record for identity before opening full history. Corrupt
        or busy sessions are not mutated/repaired here; a direct resume still reports them.
        """
        uid = self.resolve_user_id(user_id)
        summaries = []
        for folder in self.store.root.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                with (folder / "events.jsonl").open("rb") as log:
                    line = log.readline(MAX_EVENT_BYTES + 1)
                first = Event.model_validate_json(line)
                if first.user_id != uid or first.type != "session_created":
                    continue
                with self.store.open(uid, folder.name) as session:
                    first_message = next(
                        (
                            e.payload["message"]
                            for e in session.events
                            if e.type == "user_message"
                        ),
                        "New chat",
                    )
                    finalized_ev = next(
                        (e for e in session.events if e.type == "session_finalized"),
                        None,
                    )
                    summaries.append(
                        {
                            "id": session.id,
                            "title": first_message[:45],
                            "created": first.timestamp,
                            "finalized": bool(finalized_ev),
                        }
                    )
            except (OSError, ValueError, PermissionError):
                continue
        return sorted(summaries, key=lambda s: (s["created"], s["id"]), reverse=True)

    def view(self, user_id: str | None, session_id: str) -> dict[str, Any]:
        uid = self.resolve_user_id(user_id)
        with self.store.open(uid, session_id) as session:
            messages = []
            finalized_event = None
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
                elif event.type == "session_finalized":
                    finalized_event = event.payload

            config_snapshot = next(
                (
                    e.payload.get("runtime_config")
                    for e in session.events
                    if e.type == "session_config_snapshot"
                ),
                None,
            )

            summary = self.get_purchase_summary(uid)
            purchases = self.get_purchases(uid, include_cancelled=True)
            return {
                "session_id": session.id,
                "user_id": uid,
                "state": session.state.model_dump(),
                "shopping_state": compact_state(session),
                "messages": messages,
                "events": [e.model_dump() for e in session.events],
                "finalized": finalized_event is not None,
                "finalization_details": finalized_event,
                "config_snapshot": config_snapshot or self.runtime_config.to_dict(),
                "purchase_summary": summary,
                "recent_purchases": purchases,
            }

    def send(
        self,
        user_id: str | None,
        session_id: str,
        message: str,
        request_id: str,
        runtime_config: RuntimeConfig | None = None,
    ) -> dict:
        uid = self.resolve_user_id(user_id)
        tool = self._search()
        try:
            cfg = runtime_config or self.runtime_config
            with self.store.open(uid, session_id) as session:
                snap = next(
                    (
                        e.payload.get("runtime_config")
                        for e in session.events
                        if e.type == "session_config_snapshot"
                    ),
                    None,
                )
                if snap and runtime_config is None:
                    try:
                        cfg = RuntimeConfig.from_dict(snap)
                    except Exception:
                        cfg = self.runtime_config

            return ShoppingAgent(
                self.store,
                tool,
                self.policy,
                context_builder=self.context_builder,
                user_memory=self.user_memory,
                memory_format=self.memory_format,
                runtime_config=cfg,
                purchase_store=self.purchase_store,
            ).turn(uid, session_id, message, request_id=request_id)
        finally:
            tool.close()

    def resume(self, user_id: str | None, session_id: str) -> str:
        uid = self.resolve_user_id(user_id)
        if not session_id or not session_id.strip():
            raise SessionError("Enter a session ID to resume")
        self.view(uid, session_id.strip())
        return session_id.strip()

    def finalize(self, user_id: str | None, session_id: str) -> dict:
        """Explicitly finish the session and run end-of-session memory consolidation once.

        Idempotent: safe to invoke repeatedly; only consolidates once per session.
        """
        uid = self.resolve_user_id(user_id)
        # Check if already finalized in session events
        with self.store.open(uid, session_id) as session:
            finalized_event = next(
                (e for e in session.events if e.type == "session_finalized"), None
            )
            if finalized_event:
                return {
                    "status": "idempotent",
                    "idempotent": True,
                    "revision": finalized_event.payload.get("revision", 0),
                    "operations_applied": finalized_event.payload.get(
                        "operations_applied", []
                    ),
                    "rejected_operations": finalized_event.payload.get(
                        "rejected_operations", []
                    ),
                    "reason": finalized_event.payload.get(
                        "reason", "session_already_finalized"
                    ),
                    "error": None,
                }

        if self.user_memory is None:
            # Memory is turned OFF: finalize session without mutating memories
            res_dict = {
                "status": "memory_disabled",
                "idempotent": False,
                "revision": 0,
                "operations_applied": [],
                "rejected_operations": [],
                "reason": "Memory system is OFF. Session finished without recording long-term memories.",
                "error": None,
            }
            with self.store.open(uid, session_id) as session:
                session.append(
                    "session_finalized", res_dict, turn_id=f"finalize-{session_id}"
                )
            return res_dict

        tool = self._search()
        try:
            agent = ShoppingAgent(
                self.store,
                tool,
                self.policy,
                context_builder=self.context_builder,
                user_memory=self.user_memory,
                memory_format=self.memory_format,
                purchase_store=self.purchase_store,
            )
            results = agent.finalize_session(uid, session_id)
        finally:
            tool.close()

        um_res = results.get("user_memory")
        if um_res is None:
            res_dict = {
                "status": "no_changes",
                "idempotent": False,
                "revision": 0,
                "operations_applied": [],
                "rejected_operations": [],
                "reason": "No durable customer preferences detected in this session.",
                "error": None,
            }
        elif "error" in um_res:
            res_dict = {
                "status": "error",
                "idempotent": False,
                "revision": 0,
                "operations_applied": [],
                "rejected_operations": [],
                "reason": "Consolidation failed.",
                "error": um_res.get("error"),
            }
        elif um_res.get("idempotent"):
            res_dict = {
                "status": "idempotent",
                "idempotent": True,
                "revision": um_res.get("revision", 0),
                "operations_applied": um_res.get("applied", []),
                "rejected_operations": um_res.get("rejected", []),
                "reason": um_res.get("reason", "Session already consolidated."),
                "error": None,
            }
        else:
            res_dict = {
                "status": "success",
                "idempotent": False,
                "revision": um_res.get("revision", 0),
                "operations_applied": um_res.get("applied", []),
                "rejected_operations": um_res.get("rejected", []),
                "reason": um_res.get("reason", "Consolidation applied successfully."),
                "error": None,
            }

        with self.store.open(uid, session_id) as session:
            session.append(
                "session_finalized", res_dict, turn_id=f"finalize-{session_id}"
            )
        return res_dict

    def record_purchase(
        self,
        user_id: str | None,
        session_id: str,
        turn_id: str,
        product_id: str,
        title: str,
        *,
        price: float | None = None,
        currency: str = "USD",
        quantity: int = 1,
        recipient_context: str = "self",
        attribute_snapshot: dict | None = None,
    ) -> dict:
        """Record a confirmed simulated purchase for the user, update session events."""
        uid = self.resolve_user_id(user_id)
        record = PurchaseRecord(
            customer_id=uid,
            session_id=session_id,
            turn_id=turn_id,
            product_id=product_id,
            title=title,
            attribute_snapshot=attribute_snapshot or {},
            price=price,
            currency=currency,
            quantity=quantity,
            recipient_context=recipient_context
            if recipient_context in {"self", "gift", "other"}
            else "self",
            status="simulated_completed",
            source="confirmed_user_interaction",
        )
        saved = self.purchase_store.record_purchase(record)
        saved_dict = saved.to_dict()

        # Audit events in active session
        try:
            with self.store.open(uid, session_id) as session:
                session.append(
                    "purchase_initiated",
                    {"product_id": product_id, "title": title, "price": price},
                    turn_id=f"purchase-init-{saved.purchase_id}",
                )
                session.append(
                    "purchase_confirmed",
                    {
                        "purchase_id": saved.purchase_id,
                        "product_id": product_id,
                        "quantity": quantity,
                    },
                    turn_id=f"purchase-conf-{saved.purchase_id}",
                )
                session.append(
                    "purchase_recorded",
                    saved_dict,
                    turn_id=f"purchase-rec-{saved.purchase_id}",
                )
        except Exception as exc:
            saved_dict["session_audit_error"] = str(exc)

        return saved_dict

    def cancel_purchase(
        self,
        user_id: str | None,
        purchase_id: str,
        session_id: str | None = None,
        reason: str = "Mistaken simulated purchase",
    ) -> dict | None:
        """Cancel a simulated purchase while preserving audit history."""
        uid = self.resolve_user_id(user_id)
        updated = self.purchase_store.cancel_purchase(uid, purchase_id, reason=reason)
        if not updated:
            return None
        res_dict = updated.to_dict()
        sid = session_id or updated.session_id
        if sid:
            try:
                with self.store.open(uid, sid) as session:
                    session.append(
                        "purchase_cancelled",
                        {
                            "purchase_id": purchase_id,
                            "reason": reason,
                            "cancelled_at": updated.cancelled_at,
                        },
                        turn_id=f"purchase-cancel-{purchase_id}",
                    )
            except Exception as exc:
                res_dict["session_audit_error"] = str(exc)
        return res_dict

    def get_purchases(
        self,
        user_id: str | None,
        *,
        include_cancelled: bool = True,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        uid = self.resolve_user_id(user_id)
        records = self.purchase_store.get_purchases(
            uid, include_cancelled=include_cancelled, session_id=session_id, limit=limit
        )
        return [r.to_dict() for r in records]

    def get_purchase_summary(self, user_id: str | None) -> dict:
        uid = self.resolve_user_id(user_id)
        return self.purchase_store.get_summary(uid)

    def inspect_memory(self, user_id: str | None = None) -> dict:
        """Inspect stored memories for the given user."""
        uid = self.resolve_user_id(user_id)
        profile = self._user_memory_store.read(uid)
        active = [r.model_dump() for r in profile.records if r.status == "active"]
        superseded = [
            r.model_dump()
            for r in profile.records
            if r.status in ("superseded", "deleted", "retracted")
        ]
        return {
            "user_id": uid,
            "memory_enabled": self.user_memory_enabled,
            "revision": profile.revision,
            "last_consolidated_session_id": profile.last_consolidated_session_id,
            "updated_at": profile.updated_at,
            "active": active,
            "superseded": superseded,
            "total_active": len(active),
            "total_superseded": len(superseded),
        }

    def clear_memory(self, user_id: str | None = None) -> bool:
        """Clear the caller's stored memories, resetting to an empty profile."""
        uid = self.resolve_user_id(user_id)
        self._user_memory_store.clear(uid)
        return True

    def export_memory(self, user_id: str | None = None) -> str:
        """Export user memory profile as formatted JSON string."""
        uid = self.resolve_user_id(user_id)
        profile = self._user_memory_store.read(uid)
        data = {
            "user_id": profile.user_id,
            "revision": profile.revision,
            "last_consolidated_session_id": profile.last_consolidated_session_id,
            "updated_at": profile.updated_at,
            "records": [r.model_dump() for r in profile.records],
        }
        return json.dumps(data, indent=2)

    def browse_catalogue(
        self,
        *,
        query: str = "",
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        price_known_only: bool = False,
        sort_by: str = "default",
        limit: int = 24,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query and paginate through catalogue products with search and attribute filters."""
        import sqlite3

        db = sqlite3.connect(self.index.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            params: list[Any] = []
            where_clauses: list[str] = []

            # 1. Text search via product_fts if query is non-empty
            terms = [t for t in re.findall(r"\w+", query) if len(t) > 0]
            if terms:
                match_str = " AND ".join(f'"{t}"' for t in terms)
                from_clause = (
                    "FROM product_fts JOIN products p ON p.rowid = product_fts.rowid"
                )
                where_clauses.append("product_fts MATCH ?")
                params.append(match_str)
            else:
                from_clause = "FROM products p"

            # 2. Category filtering
            if category and category.strip() and category != "All Categories":
                cat_clean = category.strip().replace('"', "")
                where_clauses.append("json_extract(p.record, '$.categories') LIKE ?")
                params.append(f'%"{cat_clean}"%')

            # 3. Price filtering
            if min_price is not None and min_price > 0:
                where_clauses.append("json_extract(p.record, '$.facts.price') >= ?")
                params.append(float(min_price))

            if max_price is not None and max_price > 0:
                where_clauses.append("json_extract(p.record, '$.facts.price') <= ?")
                params.append(float(max_price))

            if price_known_only:
                where_clauses.append(
                    "json_extract(p.record, '$.facts.price') IS NOT NULL"
                )

            where_str = (
                ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            )

            # 4. Count query
            count_sql = f"SELECT count(*) {from_clause} {where_str}"
            try:
                total_count = db.execute(count_sql, params).fetchone()[0]
            except sqlite3.OperationalError:
                total_count = 0

            if total_count == 0:
                return {
                    "total_count": 0,
                    "products": [],
                    "limit": limit,
                    "offset": offset,
                }

            # 5. Order By
            if sort_by == "price_asc":
                order_by = (
                    "ORDER BY CASE WHEN json_extract(p.record, '$.facts.price') IS NULL THEN 1 ELSE 0 END, "
                    "json_extract(p.record, '$.facts.price') ASC, p.id"
                )
            elif sort_by == "price_desc":
                order_by = "ORDER BY json_extract(p.record, '$.facts.price') DESC, p.id"
            elif sort_by == "rating_desc":
                order_by = (
                    "ORDER BY CASE WHEN json_extract(p.record, '$.facts.rating') IS NULL THEN 1 ELSE 0 END, "
                    "json_extract(p.record, '$.facts.rating') DESC, p.id"
                )
            else:
                if terms:
                    order_by = "ORDER BY bm25(product_fts, 5.0, 3.0, 2.0, 1.0), p.id"
                else:
                    order_by = "ORDER BY p.id"

            # 6. Page query
            query_sql = (
                f"SELECT p.record {from_clause} {where_str} {order_by} LIMIT ? OFFSET ?"
            )
            query_params = list(params) + [int(limit), int(offset)]
            records = []
            for (raw,) in db.execute(query_sql, query_params):
                try:
                    records.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass

            return {
                "total_count": total_count,
                "products": records,
                "limit": limit,
                "offset": offset,
            }
        finally:
            db.close()
