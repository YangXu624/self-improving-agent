"""Extraction of candidate procedural lessons from learning-session traces and verified feedback."""

from typing import Any

from .models import Lesson, digest_lesson_content


def extract_candidate_lesson(
    trace: dict[str, Any],
    outcome: dict[str, Any],
    *,
    source_split: str = "learning",
) -> Lesson | None:
    """Select a predefined procedural template from a learning trace, not infer causality.

    Evaluator-only secrets (target IDs, titles, ground-truth hashes) are strictly excluded.
    The returned lesson is ALWAYS in 'candidate' status and requires explicit confirmation.
    Returns None if no actionable pattern is recognized.
    """
    if source_split != "learning":
        return None

    if not isinstance(trace, dict) or not isinstance(outcome, dict):
        return None

    scenario_id = trace.get("scenario_id")
    if not scenario_id:
        return None

    turns = trace.get("turns")
    if not isinstance(turns, list) or not turns:
        return None

    for t in turns:
        if not isinstance(t, dict):
            return None

    # Pattern 1: Empty search on initial turns due to query formulation
    for idx, turn in enumerate(turns):
        counts = turn.get("counts")
        searches = turn.get("searches", 0)
        action = turn.get("action", "")
        # Real traces must supply authoritative counts from search results
        if (searches > 0 or action == "SEARCH") and isinstance(counts, list) and counts:
            if any(
                isinstance(c, dict) and c.get("verified_eligible") == 0 for c in counts
            ):
                observed = "empty_search_zero_eligible"
                cause = (
                    "Search query formulation in initial turns was overly restrictive "
                    "or combined raw adjectives, returning zero verified products."
                )
                directive = (
                    "When searching for a product category, formulate queries using primary "
                    "category nouns and let confirmed attributes filter results outside the query."
                )
                lesson_id = digest_lesson_content("*", "initial_query", directive)
                return Lesson(
                    lesson_id=lesson_id,
                    version=1,
                    scope="*",
                    trigger_type="initial_query",
                    trigger_condition={"is_initial": True},
                    directive=directive,
                    expected_action="SEARCH",
                    action_signature={"mode": "all"},
                    observed_outcome=observed,
                    hypothesized_cause=cause,
                    evidence={
                        "source_scenario_id": scenario_id,
                        "source_split": source_split,
                        "turn": turn.get("turn", idx + 1),
                        "action": action,
                        "termination": outcome.get("termination", "unknown"),
                    },
                    status="candidate",
                )

    # Pattern 2: Search executed when qualifying candidates were already available
    for idx, turn in enumerate(turns[:-1]):
        counts = turn.get("counts")
        if isinstance(counts, list) and counts:
            if any(
                isinstance(c, dict) and c.get("verified_eligible", 0) >= 2
                for c in counts
            ):
                next_turn = turns[idx + 1]
                if (
                    next_turn.get("searches", 0) > 0
                    or next_turn.get("action") == "SEARCH"
                ):
                    observed = "redundant_search_with_eligible_candidates"
                    cause = (
                        "Agent executed an additional exploratory search despite already "
                        "having eligible candidates meeting all stated constraints."
                    )
                    directive = (
                        "When current search returns verified candidates satisfying all hard constraints, "
                        "recommend the qualifying items immediately rather than executing exploratory searches."
                    )
                    lesson_id = digest_lesson_content(
                        "*", "recommend_cutoff", directive
                    )
                    return Lesson(
                        lesson_id=lesson_id,
                        version=1,
                        scope="*",
                        trigger_type="recommend_cutoff",
                        trigger_condition={"has_candidates": True},
                        directive=directive,
                        expected_action="RECOMMEND",
                        action_signature={"min_products": 1},
                        observed_outcome=observed,
                        hypothesized_cause=cause,
                        evidence={
                            "source_scenario_id": scenario_id,
                            "source_split": source_split,
                            "turn": turn.get("turn", idx + 1),
                            "termination": outcome.get("termination", "unknown"),
                        },
                        status="candidate",
                    )

    # Pattern 3: Underspecified category search without clarification
    first_turn = turns[0]
    if (
        first_turn.get("searches", 0) > 0 or first_turn.get("action") == "SEARCH"
    ) and outcome.get("outcome") == "failure":
        observed = "unclarified_broad_search_failure"
        cause = (
            "Hypothesis: early clarification might reveal useful constraints before search. "
            "A failed task after an initial search does not establish this cause; shopper "
            "disclosure and retrieval coverage may also limit target discovery."
        )
        directive = (
            "When the opening request contains only an underspecified category, "
            "clarify key constraints (such as budget or department) before searching."
        )
        lesson_id = digest_lesson_content("*", "attribute_clarification", directive)
        return Lesson(
            lesson_id=lesson_id,
            version=1,
            scope="*",
            trigger_type="attribute_clarification",
            trigger_condition={"is_initial": True, "is_underspecified": True},
            directive=directive,
            expected_action="CLARIFY",
            action_signature={
                "attribute_in": ["budget", "department", "product_subtype", "price"]
            },
            observed_outcome=observed,
            hypothesized_cause=cause,
            evidence={
                "source_scenario_id": scenario_id,
                "source_split": source_split,
                "turn": 1,
                "termination": outcome.get("termination", "unknown"),
            },
            status="candidate",
        )

    return None
