"""Data models for experiential memory, versioning, provenance, and frozen snapshots."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

LessonStatus = Literal[
    "candidate", "confirmed", "active", "superseded", "rejected", "retracted"
]


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def digest_lesson_content(
    scope: str, trigger_type: str, directive: str, version: int = 1
) -> str:
    payload = json.dumps(
        [scope, trigger_type, directive, version], sort_keys=True
    ).encode("utf-8")
    return f"exp-{hashlib.sha256(payload).hexdigest()[:12]}"


@dataclass(frozen=True)
class Lesson:
    """A scoped, provenanced procedural lesson with behavioral triggers and validation status."""

    lesson_id: str
    version: int = 1
    scope: str = "*"  # '*' for generalizable cross-category, or specific category name
    trigger_type: str = "initial_query"
    trigger_condition: dict[str, Any] = field(default_factory=dict)
    directive: str = ""
    expected_action: str = "SEARCH"  # SEARCH | CLARIFY | RECOMMEND | RESPOND
    action_signature: dict[str, Any] = field(default_factory=dict)
    observed_outcome: str = ""
    hypothesized_cause: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    status: LessonStatus = "candidate"
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    review_notes: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Lesson":
        return cls(
            lesson_id=data["lesson_id"],
            version=data.get("version", 1),
            scope=data.get("scope", "*"),
            trigger_type=data.get("trigger_type", "initial_query"),
            trigger_condition=dict(data.get("trigger_condition") or {}),
            directive=data.get("directive", ""),
            expected_action=data.get("expected_action", "SEARCH"),
            action_signature=dict(data.get("action_signature") or {}),
            observed_outcome=data.get("observed_outcome", ""),
            hypothesized_cause=data.get("hypothesized_cause", ""),
            evidence=dict(data.get("evidence") or {}),
            status=data.get("status", "candidate"),
            supersedes_id=data.get("supersedes_id"),
            superseded_by_id=data.get("superseded_by_id"),
            review_notes=data.get("review_notes"),
            created_at=data.get("created_at") or utc_now_iso(),
        )


@dataclass(frozen=True)
class ExperienceSnapshot:
    """An immutable, content-hashed collection of active lessons frozen for evaluation."""

    snapshot_id: str
    sha256: str
    lessons: tuple[Lesson, ...] = ()

    @classmethod
    def from_lessons(
        cls, snapshot_id: str, lessons: list[Lesson]
    ) -> "ExperienceSnapshot":
        sorted_lessons = tuple(sorted(lessons, key=lambda item: item.lesson_id))
        content = json.dumps(
            [item.to_dict() for item in sorted_lessons], sort_keys=True
        ).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        return cls(snapshot_id=snapshot_id, sha256=digest, lessons=sorted_lessons)
