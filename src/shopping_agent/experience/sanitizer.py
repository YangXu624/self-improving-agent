"""Anti-contamination validation and structural integrity checks for experiential lessons."""

import re

from .models import Lesson

ID_PATTERN = re.compile(r"\bB0[0-9A-Z]{8}\b|\b\d{9}[\dX]\b", re.I)
FORBIDDEN_DIRECTIVE_PATTERNS = [
    re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions\b", re.I),
    re.compile(r"\bbypass\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
]
VALID_TRIGGER_TYPES = {
    "initial_query",
    "unsuccessful_search",
    "attribute_clarification",
    "competing_requirements",
    "recommend_cutoff",
}
VALID_ACTIONS = {"SEARCH", "CLARIFY", "RECOMMEND", "RESPOND"}


class LessonValidationError(ValueError):
    """Raised when a candidate lesson fails structural validation or anti-contamination."""


def validate_lesson(
    lesson: Lesson,
    *,
    forbidden_titles: list[str] | None = None,
    allow_non_learning: bool = False,
) -> list[str]:
    """Validate lesson structure, source provenance, and anti-leakage constraints.

    Returns a list of warning/info violation strings, or raises LessonValidationError on hard errors.
    """
    errors: list[str] = []

    # 1. Provenance: must be from the learning split unless explicitly allowed in test fixtures
    split = lesson.evidence.get("source_split")
    if not allow_non_learning and split != "learning":
        raise LessonValidationError(
            f"Lesson source split must be 'learning', got: {split!r}"
        )

    # 2. Structural fields
    if not lesson.directive.strip():
        raise LessonValidationError("Lesson directive must not be empty")
    if len(lesson.directive) > 400:
        raise LessonValidationError(
            f"Lesson directive exceeds 400 characters ({len(lesson.directive)})"
        )
    if lesson.trigger_type not in VALID_TRIGGER_TYPES:
        raise LessonValidationError(
            f"Invalid trigger_type: {lesson.trigger_type!r}. Must be one of {sorted(VALID_TRIGGER_TYPES)}"
        )
    if lesson.expected_action not in VALID_ACTIONS:
        raise LessonValidationError(
            f"Invalid expected_action: {lesson.expected_action!r}. Must be one of {sorted(VALID_ACTIONS)}"
        )

    # 3. Anti-contamination / target leak checks
    combined_text = (
        f"{lesson.directive} {lesson.hypothesized_cause} {lesson.scope} "
        f"{lesson.observed_outcome}"
    )

    if ID_PATTERN.search(combined_text):
        raise LessonValidationError(
            "Target leak detected: product ASIN or catalogue identifier in lesson content"
        )

    for pat in FORBIDDEN_DIRECTIVE_PATTERNS:
        if pat.search(lesson.directive):
            raise LessonValidationError(
                f"Suspicious instruction override pattern in directive: {pat.pattern}"
            )

    if forbidden_titles:
        lower_text = combined_text.lower()
        for title in forbidden_titles:
            if title and len(title) >= 8 and title.lower() in lower_text:
                raise LessonValidationError(
                    f"Contamination leak detected: target title fragment in lesson: {title!r}"
                )

    return errors
