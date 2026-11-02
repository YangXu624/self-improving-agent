"""Session-end reconciliation using original stores; checkpoints are not user memory."""

from shopping_agent.experience.extractor import extract_candidate_lesson
from shopping_agent.user_memory import MemoryProposal, UserMemoryError

from .engine import Turn


def consolidate_user(turn: Turn) -> None:
    if turn.user_memory is None:
        return
    completed = {
        e.payload["source_event_id"]
        for e in turn.session.events
        if e.type == "framework_memory_consolidated"
    }
    # Compare revision at each event, preserving intervening writes by other sessions.
    staged = [e for e in turn.session.events if e.type == "framework_memory_staged"]
    revision = None
    for event in staged:
        payload = event.payload
        if payload["source_event_id"] in completed:
            continue
        source = next(
            e for e in turn.session.events if e.event_id == payload["source_event_id"]
        )
        expected = payload["revision"] if revision is None else revision
        try:
            result = turn.user_memory.apply(
                turn.session,
                source,
                [MemoryProposal.model_validate(p) for p in payload["proposals"]],
                expected_revision=expected,
                visible_ids=set(payload["visible_ids"]),
            )
            revision = result["revision"]
            turn.audit(
                "framework_memory_consolidated",
                source_event_id=source.event_id,
                **result,
            )
            completed.add(source.event_id)
        except UserMemoryError as exc:
            turn.memory_rejections.append(str(exc))
            turn.audit(
                "user_memory_update_rejected",
                source_event_id=source.event_id,
                code=str(exc),
            )
            # A conflict is never silently rebased onto somebody else's profile edits.
            break


def consolidate_procedural(turn: Turn) -> None:
    if not turn.learn or turn.experience is None:
        return
    searches = [e.payload for e in turn.session.events if e.type == "search_result"]
    # Only aggregate deterministic tool facts enter centralized extraction. No shopper
    # identity, utterances, product IDs, private truth or evaluator outcomes are supplied.
    trace = {
        "scenario_id": "framework-observation",
        "turns": [
            {"turn": i + 1, "action": "SEARCH", "searches": 1, "counts": [r["counts"]]}
            for i, r in enumerate(searches)
        ],
    }
    lesson = extract_candidate_lesson(trace, {"termination": "application_session_end"})
    if lesson is None:
        turn.audit("framework_procedural_consolidated", candidate=None)
        return
    existing = turn.experience.get(lesson.lesson_id)
    # Never rewrite a reviewed lesson or even a pre-existing candidate from another run.
    if existing is None:
        turn.experience.add_candidate(lesson)
    turn.audit(
        "framework_procedural_consolidated",
        candidate=lesson.lesson_id,
        created=existing is None,
        activated=False,
    )
