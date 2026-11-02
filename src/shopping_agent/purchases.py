"""Structured SQLite purchase ledger and episodic customer decision store.

Maintains durable, auditable records of simulated customer purchases.
Ensures customer isolation, transaction safety, idempotency against
Streamlit reruns, and relevance-based retrieval for future shopping turns.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from .contracts import Strict


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class PurchaseRecord(Strict):
    """A verified, auditable simulated customer purchase event."""

    purchase_id: str = Field(default_factory=lambda: "purch-" + uuid4().hex)
    customer_id: str
    session_id: str
    turn_id: str
    product_id: str
    title: str
    attribute_snapshot: dict[str, Any] = Field(default_factory=dict)
    price: float | None = None
    currency: str = "USD"
    quantity: int = 1
    timestamp: str = Field(default_factory=utc_now_iso)
    recipient_context: Literal["self", "gift", "other"] = "self"
    status: Literal["simulated_completed", "simulated_cancelled"] = (
        "simulated_completed"
    )
    source: str = "confirmed_user_interaction"
    cancellation_reason: str | None = None
    cancelled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class PurchaseStore:
    """Persistent SQLite-backed purchase ledger with strict customer isolation."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS purchases (
                    purchase_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    attribute_snapshot TEXT NOT NULL,
                    price REAL,
                    currency TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    timestamp TEXT NOT NULL,
                    recipient_context TEXT NOT NULL DEFAULT 'self',
                    status TEXT NOT NULL DEFAULT 'simulated_completed',
                    source TEXT NOT NULL DEFAULT 'confirmed_user_interaction',
                    cancellation_reason TEXT,
                    cancelled_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_purchases_customer ON purchases(customer_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_purchases_session ON purchases(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_purchases_product ON purchases(product_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_purchases_timestamp ON purchases(timestamp)"
            )

    def record_purchase(self, record: PurchaseRecord) -> PurchaseRecord:
        """Atomically record a confirmed simulated purchase."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO purchases (
                    purchase_id, customer_id, session_id, turn_id, product_id,
                    title, attribute_snapshot, price, currency, quantity,
                    timestamp, recipient_context, status, source,
                    cancellation_reason, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.purchase_id,
                    record.customer_id,
                    record.session_id,
                    record.turn_id,
                    record.product_id,
                    record.title,
                    json.dumps(record.attribute_snapshot),
                    record.price,
                    record.currency,
                    record.quantity,
                    record.timestamp,
                    record.recipient_context,
                    record.status,
                    record.source,
                    record.cancellation_reason,
                    record.cancelled_at,
                ),
            )
        return record

    def get_purchase(self, customer_id: str, purchase_id: str) -> PurchaseRecord | None:
        """Retrieve a specific purchase record, enforcing customer isolation."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM purchases WHERE customer_id = ? AND purchase_id = ?",
                (customer_id, purchase_id),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def get_purchases(
        self,
        customer_id: str,
        *,
        include_cancelled: bool = True,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PurchaseRecord]:
        """List purchases for a customer, newest first, strictly isolated."""
        query = "SELECT * FROM purchases WHERE customer_id = ?"
        params: list[Any] = [customer_id]

        if not include_cancelled:
            query += " AND status != 'simulated_cancelled'"

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY timestamp DESC"

        if limit:
            query += f" LIMIT {int(limit)}"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_record(row) for row in rows]

    def cancel_purchase(
        self,
        customer_id: str,
        purchase_id: str,
        reason: str = "Mistaken simulated purchase",
    ) -> PurchaseRecord | None:
        """Cancel a simulated purchase without deleting its audit history."""
        now = utc_now_iso()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE purchases
                SET status = 'simulated_cancelled',
                    cancellation_reason = ?,
                    cancelled_at = ?
                WHERE customer_id = ? AND purchase_id = ?
                """,
                (reason, now, customer_id, purchase_id),
            )
            if cursor.rowcount == 0:
                return None

            row = conn.execute(
                "SELECT * FROM purchases WHERE customer_id = ? AND purchase_id = ?",
                (customer_id, purchase_id),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def get_summary(self, customer_id: str) -> dict[str, Any]:
        """Calculate spend and purchase counts for a customer."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as total_count,
                    SUM(CASE WHEN status != 'simulated_cancelled' THEN 1 ELSE 0 END) as active_count,
                    SUM(CASE WHEN status != 'simulated_cancelled' THEN COALESCE(price * quantity, 0.0) ELSE 0.0 END) as total_spend
                FROM purchases
                WHERE customer_id = ?
                """,
                (customer_id,),
            ).fetchone()

            total_count = int(row["total_count"] or 0)
            active_count = int(row["active_count"] or 0)
            total_spend = float(row["total_spend"] or 0.0)

            # Get distinct product IDs
            id_rows = conn.execute(
                """
                SELECT DISTINCT product_id
                FROM purchases
                WHERE customer_id = ? AND status != 'simulated_cancelled'
                """,
                (customer_id,),
            ).fetchall()
            product_ids = [r["product_id"] for r in id_rows]

            return {
                "customer_id": customer_id,
                "total_count": total_count,
                "active_count": active_count,
                "total_spend": round(total_spend, 2),
                "currency": "USD",
                "purchased_product_ids": product_ids,
            }

    def find_relevant_purchases(
        self,
        customer_id: str,
        query: str,
        *,
        limit: int = 3,
        include_cancelled: bool = False,
    ) -> list[PurchaseRecord]:
        """Find past customer purchases relevant to a query using token matching.

        Checks product titles, attributes (e.g. category, color, material, style),
        and recency. Returns newest/most relevant first.
        """
        all_purchases = self.get_purchases(
            customer_id, include_cancelled=include_cancelled
        )
        if not all_purchases:
            return []

        # Extract tokens from query (length >= 3, lowercase)
        import re

        tokens = [t.lower() for t in re.findall(r"\b[a-zA-Z0-9]{3,}\b", query.lower())]
        if not tokens:
            # Fallback to recent purchases if query has no tokens
            return all_purchases[:limit]

        scored: list[tuple[int, PurchaseRecord]] = []
        for p in all_purchases:
            searchable_text = f"{p.title} {p.product_id}".lower()
            attrs = p.attribute_snapshot
            if isinstance(attrs, dict):
                for k, v in attrs.items():
                    searchable_text += f" {k} {v}".lower()

            score = sum(1 for tok in tokens if tok in searchable_text)
            if score > 0:
                scored.append((score, p))

        # Sort by match score descending, then by purchase timestamp descending
        scored.sort(key=lambda x: (x[0], x[1].timestamp), reverse=True)
        return [item[1] for item in scored[:limit]]

    def _row_to_record(self, row: sqlite3.Row) -> PurchaseRecord:
        try:
            snapshot = json.loads(row["attribute_snapshot"])
        except Exception:
            snapshot = {}

        return PurchaseRecord(
            purchase_id=row["purchase_id"],
            customer_id=row["customer_id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            product_id=row["product_id"],
            title=row["title"],
            attribute_snapshot=snapshot,
            price=row["price"],
            currency=row["currency"],
            quantity=row["quantity"],
            timestamp=row["timestamp"],
            recipient_context=row["recipient_context"],
            status=row["status"],
            source=row["source"],
            cancellation_reason=row["cancellation_reason"],
            cancelled_at=row["cancelled_at"],
        )
