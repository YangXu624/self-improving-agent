"""SQLite-backed persistent store for experiential lessons with provenance and snapshots."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import ExperienceSnapshot, Lesson
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
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lessons_lookup
ON lessons(status, trigger_type, scope);
"""


class ExperienceStore:
    """Manages lesson lifecycle, provenance, retrieval, and immutable snapshot creation."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, autocommit=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ExperienceStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _row_to_lesson(self, row: sqlite3.Row) -> Lesson:
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
        )

    def add_candidate(
        self,
        lesson: Lesson,
        *,
        forbidden_titles: list[str] | None = None,
        allow_non_learning: bool = False,
    ) -> Lesson:
        """Validate and insert a candidate lesson. Replaces draft if same unconfirmed ID."""
        validate_lesson(
            lesson,
            forbidden_titles=forbidden_titles,
            allow_non_learning=allow_non_learning,
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO lessons (
                    lesson_id, version, scope, trigger_type, trigger_condition,
                    directive, expected_action, action_signature, observed_outcome,
                    hypothesized_cause, evidence, status, supersedes_id,
                    superseded_by_id, review_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lesson_id) DO UPDATE SET
                    version=excluded.version,
                    directive=excluded.directive,
                    action_signature=excluded.action_signature,
                    observed_outcome=excluded.observed_outcome,
                    hypothesized_cause=excluded.hypothesized_cause,
                    evidence=excluded.evidence,
                    review_notes=excluded.review_notes
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
                ),
            )
        return lesson

    def get(self, lesson_id: str) -> Lesson | None:
        cur = self.conn.execute(
            "SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)
        )
        row = cur.fetchone()
        return self._row_to_lesson(row) if row else None

    def confirm(self, lesson_id: str, review_notes: str | None = None) -> Lesson:
        """Explicitly approve a candidate lesson, promoting it to active status."""
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
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'active', review_notes = ? WHERE lesson_id = ?",
                (notes, lesson_id),
            )
        return self.get(lesson_id)  # type: ignore

    def reject(self, lesson_id: str, reason: str) -> Lesson:
        """Reject a candidate lesson; retains historical record and provenance."""
        current = self.get(lesson_id)
        if not current:
            raise KeyError(f"Lesson not found: {lesson_id}")
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'rejected', review_notes = ? WHERE lesson_id = ?",
                (reason, lesson_id),
            )
        return self.get(lesson_id)  # type: ignore

    def retract(self, lesson_id: str, reason: str) -> Lesson:
        """Retract an active lesson; excluded from future retrieval while preserving provenance."""
        current = self.get(lesson_id)
        if not current:
            raise KeyError(f"Lesson not found: {lesson_id}")
        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'retracted', review_notes = ? WHERE lesson_id = ?",
                (reason, lesson_id),
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
        old = self.get(old_lesson_id)
        if not old:
            raise KeyError(f"Lesson to supersede not found: {old_lesson_id}")
        if old.status in ("superseded", "retracted", "rejected"):
            raise ValueError(f"Cannot supersede lesson in status: {old.status!r}")

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
        )
        validate_lesson(
            replacement,
            forbidden_titles=forbidden_titles,
            allow_non_learning=allow_non_learning,
        )

        with self.conn:
            self.conn.execute(
                "UPDATE lessons SET status = 'superseded', superseded_by_id = ?, review_notes = ? WHERE lesson_id = ?",
                (replacement.lesson_id, reason, old_lesson_id),
            )
            self.conn.execute(
                """
                INSERT INTO lessons (
                    lesson_id, version, scope, trigger_type, trigger_condition,
                    directive, expected_action, action_signature, observed_outcome,
                    hypothesized_cause, evidence, status, supersedes_id,
                    superseded_by_id, review_notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        return self.get(old_lesson_id), self.get(replacement.lesson_id)  # type: ignore

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
        """Retrieve active lessons matching behavioral trigger and scope.

        Specific scope takes precedence over cross-category ('*').
        Context predicates in trigger_condition must match context_cues if specified.
        """
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
            # Check condition predicates against context cues
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
