"""Independent compliance against confirmed hard state at each recommendation.

This is not an assertion that extraction captured every natural-language requirement.
Missing legacy snapshots are unknown, never zero violations.
"""

import math
from types import SimpleNamespace

from .oracle import _compare, norm, raw_facts, verdict


def compliance(record, oracle):
    counts = {
        "checked_occurrences": 0,
        "passed": 0,
        "violations": 0,
        "unknown_required": 0,
        "unknown_product_id": 0,
        "missing_snapshot_occurrences": 0,
    }
    for turn in record.turns:
        if not turn.presented_ids:
            continue
        requirements = turn.recommendation_requirements
        if requirements is None:
            counts["missing_snapshot_occurrences"] += len(turn.presented_ids)
            continue
        for ident in turn.presented_ids:
            counts["checked_occurrences"] += 1
            row = oracle.row(ident)
            if row is None:
                counts["unknown_product_id"] += 1
                continue
            facts = raw_facts(row)
            text = " ".join(
                [
                    str(row.get("title") or ""),
                    *[str(v) for v in row.get("categories", [])],
                    *[str(v) for v in row.get("features", [])],
                    *[str(v) for v in row.get("description", [])],
                ]
            )
            facts["keyword"] = norm(text)
            results = []
            for raw in requirements:
                try:
                    fact = SimpleNamespace(**raw)
                    if fact.field in {"rating", "rating_count"}:
                        key = (
                            "average_rating"
                            if fact.field == "rating"
                            else "rating_number"
                        )
                        value = row.get(key)
                        valid = (
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and math.isfinite(value)
                            and value >= 0
                            and (
                                value <= 5
                                if fact.field == "rating"
                                else float(value).is_integer()
                            )
                        )
                        results.append(
                            (
                                "pass"
                                if _compare(value, fact.op, fact.value, "price")
                                else "fail"
                            )
                            if valid
                            else "unknown"
                        )
                    else:
                        results.append(verdict(facts, fact))
                except (KeyError, AttributeError, TypeError, ValueError):
                    results.append("unknown")
            key = (
                "violations"
                if "fail" in results
                else "unknown_required"
                if "unknown" in results
                else "passed"
            )
            counts[key] += 1
    return {
        "basis": "confirmed_active_hard_state_at_recommendation; extraction_completeness_not_asserted",
        **counts,
    }
