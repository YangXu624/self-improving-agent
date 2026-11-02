"""SQLite-backed persistent store for experiential lessons with provenance and snapshots."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..embeddings import (
    EmbeddingProvider,
    cosine_similarity,
    get_default_embedding_provider,
)
from .models import ExperienceSnapshot, Lesson, utc_now_iso
from .sanitizer import validate_lesson

SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    scope TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_condition TEXT NOT NULL,
    directive TEXT NOT NULL,
    expected_action TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    observed_outcome TEXT NOT NULL,
    hypothesized_cause TEXT NOT NULL,
    evidence TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK(status IN ('candidate', 'confirmed', 'active', 'superseded', 'rejected', 'retracted')),
    supersedes_id TEXT,
    superseded_by_id TEXT,
    review_notes TEXT,
    created_at TEXT NOT NULL,
    situation TEXT NOT NULL DEFAULT '',
    strategy TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.8,
    usage_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT '',
    embedding_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_lessons_lookup
ON lessons(status, trigger_type, scope);
"""


class ExperienceStore:
    """Manages lesson lifecycle, provenance, semantic retrieval, and immutable snapshot creation."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, autocommit=False)
        self.conn.row_factory = sqlite3.Row
        self.embedding_provider = embedding_provider or get_default_embedding_provider()
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
            # Automatic schema migration for existing sqlite dbs
            cur = self.conn.execute("PRAGMA table_info(lessons)")
            cols = {row["name"] for row in cur.fetchall()}
            new_columns = [
                ("situation", "TEXT NOT NULL DEFAULT ''"),
                ("strategy", "TEXT NOT NULL DEFAULT ''"),
                ("rationale", "TEXT NOT NULL DEFAULT ''"),
                ("confidence", "REAL NOT NULL DEFAULT 0.8"),
                ("usage_count", "INTEGER NOT NULL DEFAULT 0"),
                ("success_count", "INTEGER NOT NULL DEFAULT 0"),
                ("failure_count", "INTEGER NOT NULL DEFAULT 0"),
                ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                ("embedding_json", "TEXT"),
            ]
            for col_name, col_type in new_columns:
                if col_name not in cols:
                    try:
                        self.conn.execute(f"ALTER TABLE lessons ADD COLUMN {col_name} {col_type}")
                    except sqlite3.OperationalError:
                        pass

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ExperienceStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _row_to_lesson(self, row: sqlite3.Row) -> Lesson:
        emb = json.loads(row["embedding_json"]) if "embedding_json" in row.keys() and row["embedding_json"] else None
        return Lesson(
            lesson_id=row["lesson_id"],
            version=row["version"],
            scope=row["scope"],
            trigger_type=row["trigger_type"],
            trigger_condition=json.loads(row["trigger_condition"]),
            directive=row["directive"],
            expected_action=row["expected_action"],
            action_signature=json.loads(row["action_signature"]),
            observed_outcome=row["observed_outcome"],
            hypothesized_cause=row["hypothesized_cause"],
            evidence=json.loads(row["evidence"]),
            status=row["status"],
            supersedes_id=row["supersedes_id"],
            superseded_by_id=row["superseded_by_id"],
            review_notes=row["review_notes"],
            created_at=row["created_at"],
            situation=row["situation"] if "situation" in row.keys() else "",
            strategy=row["strategy"] if "strategy" in row.keys() else "",
            rationale=row["rationale"] if "rationale" in row.keys() else "",
            confidence=row["confidence"] if "confidence" in row.keys() else 0.8,
            usage_count=row["usage_count"] if "usage_count" in row.keys() else 0,
            success_count=row["success_count"] if "success_count" in row.keys() else 0,
            failure_count=row["failure_count"] if "failure_count" in row.keys() else 0,
            updated_at=row["updated_at"] if "updated_at" in row.keys() else row["created_at"],
            embedding=emb,
        )

    def add_candidate(
        self,
        lesson: Lesson,
        *,
        forbidden_titles: list[str] | None = None,
        allow_non_learning: bool = False,
    ) -> Lesson:
        """Validate and insert a candidate lesson. Replaces draft if same unconfirmed ID."""
        if lesson.status != "candidate":
            raise ValueError(
                "add_candidate accepts candidate status only; use explicit review transitions"
            )
        validate_lesson(
            lesson,
            forbidden_titles=forbidden_titles,
            allow_non_learning=allow_non_learning,
        )

        emb = lesson.embedding
        if emb is None:
            emb = self.embedding_provider.embed_query(lesson.semantic_text())
        emb_json = json.dumps(emb) if emb else None

        with self.conn:
            current = self.get(lesson.lesson_id)
            if current is not None:
                ignored = {"status", "created_at", "updated_at", "review_notes", "superseded_by_id", "embedding"}
                old = {k: v for k, v in current.to_dict().items() if k not in ignored}
                new = {k: v for k, v in lesson.to_dict().items() if k not in ignored}
                notes_unchanged = (
                    lesson.review_notes is None
                    or lesson.review_notes == current.review_notes
                )
                if old == new and notes_unchanged:
                    return current
                if current.status != "candidate":
                    raise ValueError(
                        "Reviewed lesson is immutable; use explicit revision/supersession"
                    )
            self.conn.execute(
                """
                INSERT OR REPLACE INTO lessons (
                    lesson_id, version, scope, trigger_type, trigger_condition,
                    directive, expected_action, action_signature, observed_outcome,
                    hypothesized_cause, evidence, status, supersedes_id,
                    superseded_by_id, review_notes, created_at, situation, strategy,
                    rationale, confidence, usage_count, success_count, failure_count,
                    updated_at, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson.lesson_id,
                    lesson.version,
                    lesson.scope,
                    lesson.trigger_type,
                    json.dumps(lesson.trigger_condition, sort_keys=True),
                    lesson.directive,
                    lesson.expected_action,
                    json.dumps(lesson.action_signature, sort_keys=True),
                    lesson.observed_outcome,
                    lesson.hypothesized_cause,
                    json.dumps(lesson.evidence, sort_keys=True),
                    lesson.status,
                    lesson.supersedes_id,
                    lesson.superseded_by_id,
                    lesson.review_notes,
                    lesson.created_at,
                    lesson.situation,
                    lesson.strategy,
                    lesson.rationale,
                    lesson.confidence,
                    lesson.usage_count,
                    lesson.success_count,
                    lesson.failure_count,
                    lesson.updated_at or lesson.created_at,
                    emb_json,
                ),
            )
        return self.get(lesson.lesson_id)  # type: ignore

    def get(self, lesson_id: str) -> Lesson | None:
        cur = self.conn.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,))
        row = cur.fetchone()
        return self._row_to_lesson(row) if row is not None else None

    def confirm(
        self,
        lesson_id: str,
        review_notes: str | None = None,
        *,
        activate: bool = True,
    ) -> Lesson:
        """Explicitly approve a candidate lesson, promoting it to active (or confirmed) status."""
        current = self.get(lesson_id)
        if not current:
            raise KeyError(f"Lesson not found: {lesson_id}")
        if current.status not in ("candidate", "confirmed", "active"):
            raise ValueError(f"Cannot confirm lesson in status: {current.status!r}")
        notes = (
            f"{current.review_notes}; {review_notes}"
            if current.review_notes and review_notes
            else review_notes or current.review_notes
        )
        new_status = "active" if activate else "confirmed"
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = ?, review_notes = ? WHERE lesson_id = ?",
                (new_status, notes, lesson_id),
            )
        return self.get(lesson_id)  # type: ignore

    confirm_candidate = confirm

    def reject(
        self,
        lesson_id: str,
        reason: str = "Rejected during review",
        review_notes: str | None = None,
    ) -> Lesson:
        """Reject a candidate lesson; retains historical record and provenance."""
        current = self.get(lesson_id)
        if not current:
            raise KeyError(f"Lesson not found: {lesson_id}")
        notes = review_notes or reason
        if current.review_notes and current.review_notes != notes:
            notes = f"{current.review_notes}; {notes}"
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'rejected', review_notes = ? WHERE lesson_id = ?",
                (notes, lesson_id),
            )
        return self.get(lesson_id)  # type: ignore

    def retract(
        self,
        lesson_id: str,
        reason: str = "Retracted during review",
        review_notes: str | None = None,
    ) -> Lesson:
        """Retract an active lesson; excluded from future retrieval while preserving provenance."""
        current = self.get(lesson_id)
        if not current:
            raise KeyError(f"Lesson not found: {lesson_id}")
        notes = review_notes or reason
        if current.review_notes and current.review_notes != notes:
            notes = f"{current.review_notes}; {notes}"
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'retracted', review_notes = ? WHERE lesson_id = ?",
                (notes, lesson_id),
            )
        return self.get(lesson_id)  # type: ignore

    def supersede(
        self,
        old_lesson_id: str,
        new_lesson: Lesson,
        *,
        reason: str = "Superseded by updated revision",
        forbidden_titles: list[str] | None = None,
        allow_non_learning: bool = False,
    ) -> tuple[Lesson, Lesson]:
        """Atomically supersede an existing lesson with a new version."""
        if (
            new_lesson.lesson_id == old_lesson_id
            or self.get(new_lesson.lesson_id) is not None
        ):
            raise ValueError("Supersession requires a new, unused lesson ID")
        old = self.get(old_lesson_id)
        if not old:
            raise KeyError(f"Lesson to supersede not found: {old_lesson_id}")
        if old.status in ("superseded", "retracted", "rejected"):
            raise ValueError(f"Cannot supersede lesson in status: {old.status!r}")

        emb = new_lesson.embedding
        if emb is None:
            emb = self.embedding_provider.embed_query(new_lesson.semantic_text())
        emb_json = json.dumps(emb) if emb else None

        replacement = Lesson(
            lesson_id=new_lesson.lesson_id,
            version=old.version + 1,
            scope=new_lesson.scope,
            trigger_type=new_lesson.trigger_type,
            trigger_condition=new_lesson.trigger_condition,
            directive=new_lesson.directive,
            expected_action=new_lesson.expected_action,
            action_signature=new_lesson.action_signature,
            observed_outcome=new_lesson.observed_outcome,
            hypothesized_cause=new_lesson.hypothesized_cause,
            evidence=new_lesson.evidence,
            status=new_lesson.status,
            supersedes_id=old_lesson_id,
            superseded_by_id=None,
            review_notes=new_lesson.review_notes,
            created_at=new_lesson.created_at,
            situation=new_lesson.situation,
            strategy=new_lesson.strategy,
            rationale=new_lesson.rationale,
            confidence=new_lesson.confidence,
            usage_count=new_lesson.usage_count,
            success_count=new_lesson.success_count,
            failure_count=new_lesson.failure_count,
            updated_at=new_lesson.updated_at,
            embedding=emb,
        )
        validate_lesson(
            replacement,
            forbidden_titles=forbidden_titles,
            allow_non_learning=allow_non_learning,
        )

        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'superseded', superseded_by_id = ?, review_notes = ? WHERE lesson_id = ?",
                (
                    replacement.lesson_id,
                    f"{old.review_notes}; {reason}" if old.review_notes else reason,
                    old_lesson_id,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO lessons (
                    lesson_id, version, scope, trigger_type, trigger_condition,
                    directive, expected_action, action_signature, observed_outcome,
                    hypothesized_cause, evidence, status, supersedes_id,
                    superseded_by_id, review_notes, created_at, situation, strategy,
                    rationale, confidence, usage_count, success_count, failure_count,
                    updated_at, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    replacement.lesson_id,
                    replacement.version,
                    replacement.scope,
                    replacement.trigger_type,
                    json.dumps(replacement.trigger_condition, sort_keys=True),
                    replacement.directive,
                    replacement.expected_action,
                    json.dumps(replacement.action_signature, sort_keys=True),
                    replacement.observed_outcome,
                    replacement.hypothesized_cause,
                    json.dumps(replacement.evidence, sort_keys=True),
                    replacement.status,
                    replacement.supersedes_id,
                    replacement.superseded_by_id,
                    replacement.review_notes,
                    replacement.created_at,
                    replacement.situation,
                    replacement.strategy,
                    replacement.rationale,
                    replacement.confidence,
                    replacement.usage_count,
                    replacement.success_count,
                    replacement.failure_count,
                    replacement.updated_at or replacement.created_at,
                    emb_json,
                ),
            )
        return self.get(old_lesson_id), self.get(replacement.lesson_id)  # type: ignore

    def activate(self, lesson_id: str) -> Lesson:
        current = self.get(lesson_id)
        if current is None:
            raise KeyError(f"Lesson not found: {lesson_id}")
        if current.status not in ("confirmed", "active"):
            raise ValueError(f"Can only activate confirmed lessons; status is {current.status}")
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'active' WHERE lesson_id = ?",
                (lesson_id,),
            )
        return self.get(lesson_id)  # type: ignore

    def list_lessons(
        self,
        status: str | None = None,
        scope: str | None = None,
        trigger_type: str | None = None,
    ) -> list[Lesson]:
        query = "SELECT * FROM lessons WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if scope is not None:
            query += " AND scope = ?"
            params.append(scope)
        if trigger_type is not None:
            query += " AND trigger_type = ?"
            params.append(trigger_type)
        query += " ORDER BY version DESC, created_at DESC"
        cur = self.conn.execute(query, params)
        return [self._row_to_lesson(r) for r in cur.fetchall()]

    def retrieve(
        self,
        trigger_type: str,
        scope: str = "*",
        context_cues: dict[str, Any] | None = None,
        max_lessons: int = 1,
    ) -> list[Lesson]:
        """Retrieve active lessons matching behavioral trigger and scope."""
        cur = self.conn.execute(
            """
            SELECT * FROM lessons
            WHERE status = 'active'
              AND trigger_type = ?
              AND scope IN (?, '*')
            ORDER BY CASE WHEN scope = ? THEN 0 ELSE 1 END, version DESC, created_at DESC
            """,
            (trigger_type, scope, scope),
        )
        candidates = [self._row_to_lesson(r) for r in cur.fetchall()]
        matched: list[Lesson] = []
        cues = context_cues or {}

        for lesson in candidates:
            cond = lesson.trigger_condition
            matches = True
            for k, expected in cond.items():
                actual = cues.get(k)
                if isinstance(expected, bool):
                    if bool(actual) != expected:
                        matches = False
                        break
                elif actual != expected:
                    matches = False
                    break
            if matches:
                matched.append(lesson)
                if len(matched) >= max_lessons:
                    break
        return matched

    def retrieve_semantic(
        self,
        situation_query: str,
        *,
        min_similarity: float = 0.50,
        limit: int = 2,
        scope: str = "*",
        context_cues: dict[str, Any] | None = None,
    ) -> list[tuple[Lesson, float]]:
        """Retrieve active procedural lessons using vector semantic similarity to the current shopping situation."""
        cur = self.conn.execute(
            """
            SELECT * FROM lessons
            WHERE status IN ('active', 'confirmed')
              AND scope IN (?, '*')
            """,
            (scope,),
        )
        candidates = [self._row_to_lesson(r) for r in cur.fetchall()]
        if not candidates:
            return []

        # Ensure embeddings exist
        missing_emb = [les for les in candidates if not les.embedding]
        if missing_emb:
            texts = [les.semantic_text() for les in missing_emb]
            embs = self.embedding_provider.embed(texts)
            with self.conn:
                for les, emb in zip(missing_emb, embs, strict=False):
                    self.conn.execute(
                        "UPDATE lessons SET embedding_json = ? WHERE lesson_id = ?",
                        (json.dumps(emb), les.lesson_id),
                    )
            # Re-fetch with embeddings
            candidates = [self.get(les.lesson_id) for les in candidates]  # type: ignore

        query_emb = self.embedding_provider.embed_query(situation_query)
        scored: list[tuple[Lesson, float]] = []

        for lesson in candidates:
            if not lesson.embedding:
                continue
            if context_cues and lesson.trigger_condition:
                cues_match = True
                for k, expected in lesson.trigger_condition.items():
                    actual = context_cues.get(k)
                    if isinstance(expected, bool):
                        if bool(actual) != expected:
                            cues_match = False
                            break
                    elif actual != expected:
                        cues_match = False
                        break
                if not cues_match:
                    continue
            sim = cosine_similarity(query_emb, lesson.embedding)
            score = sim * lesson.confidence
            if sim >= min_similarity:
                scored.append((lesson, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def reinforce_or_add_lesson(
        self,
        candidate: Lesson,
        *,
        min_similarity_for_reinforce: float = 0.82,
        allow_non_learning: bool = False,
    ) -> tuple[str, Lesson]:
        """Compare candidate lesson with existing lessons. Reinforce if similar; add if novel."""
        emb = candidate.embedding
        if emb is None:
            emb = self.embedding_provider.embed_query(candidate.semantic_text())

        existing_active = self.list_lessons(status="active")
        for existing in existing_active:
            if existing.scope == candidate.scope and existing.expected_action == candidate.expected_action:
                ex_emb = existing.embedding
                if ex_emb is None:
                    ex_emb = self.embedding_provider.embed_query(existing.semantic_text())
                sim = cosine_similarity(emb, ex_emb)
                if sim >= min_similarity_for_reinforce:
                    # Reinforce existing lesson
                    with self.conn:
                        new_usage = existing.usage_count + 1
                        new_success = existing.success_count + 1
                        new_conf = min(0.99, existing.confidence + 0.05)
                        now_str = utc_now_iso()
                        self.conn.execute(
                            """
                            UPDATE lessons
                            SET usage_count = ?, success_count = ?, confidence = ?, updated_at = ?
                            WHERE lesson_id = ?
                            """,
                            (new_usage, new_success, new_conf, now_str, existing.lesson_id),
                        )
                    return "reinforced", self.get(existing.lesson_id)  # type: ignore

        # Novel lesson: add as candidate and activate
        added = self.add_candidate(candidate, allow_non_learning=allow_non_learning)
        activated = self.confirm_candidate(added.lesson_id, activate=True)
        return "added", activated

    def create_snapshot(self, snapshot_id: str) -> ExperienceSnapshot:
        """Freeze all active lessons into an immutable ExperienceSnapshot."""
        active = self.list_lessons(status="active")
        return ExperienceSnapshot.from_lessons(snapshot_id, active)

    @staticmethod
    def save_snapshot(snapshot: ExperienceSnapshot, path: str | Path) -> Path:
        target = Path(path)
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "sha256": snapshot.sha256,
            "lessons": [item.to_dict() for item in snapshot.lessons],
        }
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return target

    @staticmethod
    def load_snapshot(path: str | Path) -> ExperienceSnapshot:
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        lessons = tuple(Lesson.from_dict(d) for d in payload.get("lessons", []))
        snapshot = ExperienceSnapshot.from_lessons(
            payload["snapshot_id"], list(lessons)
        )
        if snapshot.sha256 != payload["sha256"]:
            raise ValueError(
                f"Snapshot content digest mismatch: expected {payload['sha256']}, got {snapshot.sha256}"
            )
        return snapshot
