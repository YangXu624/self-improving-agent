"""Independent scoring against frozen ground truth and raw catalogue rows.

Nothing here asks the shopper whether it was satisfied, and nothing reuses the agent's
retrieval gate: products are judged by `oracle` from raw catalogue rows.

Handling of failures (fixed here, before any run):
  * Agent failures and exhausted budgets are FAILURES and stay in every denominator.
  * Simulator faults (malformed/inconsistent shopper) and infrastructure faults (provider
    errors, run budget) make a session INVALID: reported separately with their rate and
    excluded from agent-quality denominators, because they are not the agent's behaviour.
  * Turns-to-success is None for failures; aggregates report the median over successes and
    a penalised mean that counts a failure as budget+1 turns. Never silently dropped.
"""

import math
from dataclasses import dataclass

from .models import GroundTruth
from .oracle import judge, raw_facts, tokens

INVALID_TERMINATIONS = {"simulator_failure", "provider_error", "run_budget_exhausted"}
BUDGET_ERRORS = {
    "decision_budget_exhausted",
    "search_budget_exhausted",
    "search_requires_a_remaining_decision_call",
}
MAX_DIAGNOSTIC_IDS = 60


@dataclass(frozen=True)
class ScoreConfig:
    k_values: tuple = (1, 3, 5)
    headline_k: int = 3
    turn_budget: int | None = None  # None = the scenario's own max_user_turns
    price_input_per_million: float | None = None
    price_output_per_million: float | None = None


def dcg(grades):
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def ndcg(grades, ideal, k):
    best = dcg(sorted(ideal, reverse=True)[:k])
    return None if best == 0 else dcg(grades[:k]) / best


class Judge:
    """Cached per-product verdicts for one scenario."""

    def __init__(self, oracle, truth: GroundTruth):
        self.oracle, self.truth, self.cache = oracle, truth, {}

    def __call__(self, product_id):
        if product_id not in self.cache:
            row = self.oracle.row(product_id)
            if row is None:
                self.cache[product_id] = {"hard": "unknown_id", "grade": 0}
            else:
                self.cache[product_id] = judge(
                    raw_facts(row), self.truth.hard, self.truth.soft
                )
        return self.cache[product_id]


def estimated_cost(usage, config):
    if (
        config.price_input_per_million is None
        or config.price_output_per_million is None
    ):
        return None
    return (
        usage.get("prompt_tokens", 0) * config.price_input_per_million
        + usage.get("completion_tokens", 0) * config.price_output_per_million
    ) / 1_000_000


def resources(record, config):
    usage = {}
    for turn in record.turns:
        for key, value in turn.usage.items():
            usage[key] = usage.get(key, 0) + value
    sim = record.simulator or {}
    return {
        "agent_turns": len(record.turns),
        "model_calls": sum(t.model_calls for t in record.turns),
        "searches": sum(t.searches for t in record.turns),
        "clarifications": sum(t.action == "CLARIFY" for t in record.turns),
        "redundant_clarifications": record.repeated_questions,
        "clarifications_about_nothing_in_profile": record.unmatched_questions,
        "rejected_decisions": sum(t.rejected_decisions for t in record.turns),
        "agent_usage": usage,
        "agent_model_seconds": sum(t.model_seconds for t in record.turns),
        "agent_wall_ms": sum(t.wall_ms for t in record.turns),
        "estimated_cost_usd": estimated_cost(usage, config),
        "simulator_calls": sim.get("calls", 0),
        "simulator_usage": sim.get("usage", {}),
    }


def represented(fact, requirements):
    """Is a hidden hard fact captured by an active hard requirement of ASTRA's state?

    Field and value must agree (numbers equal; text equal or one containing the other).
    The operator is not compared: lt vs lte at the same value are the same intent here.
    """
    for r in requirements:
        if r["field"] != fact.field or r["strength"] != "hard":
            continue
        a, b = r["value"], fact.value
        if isinstance(b, (int, float)):
            if isinstance(a, (int, float)) and abs(float(a) - float(b)) < 1e-9:
                return True
            continue
        wanted = tokens(b)
        # Word sets, never substrings ("men" is a substring of "women").
        if any(
            wanted <= tokens(x) or tokens(x) <= wanted
            for x in (a if isinstance(a, list) else [a])
        ):
            return True
    return False


def failure_category(agent_codes, retrieval):
    if agent_codes & BUDGET_ERRORS:
        return "agent_budget_exhausted"
    if agent_codes:
        return "agent_error"
    if not retrieval["searched"]:
        return "no_search"
    # Acceptable products reached the agent but were not recommended (recommendation), or
    # ASTRA's stored requirements never matched the shopper's (state extraction), or
    # retrieval never surfaced an acceptable product: the distinction diagnostics exist for.
    if retrieval["acceptable_seen"]:
        return "recommendation_failure"
    if retrieval["hidden_hard_facts_not_in_state"]:
        return "state_extraction_failure"
    return "retrieval_failure"


def score_session(record, truth, oracle, config=ScoreConfig(), *, max_turns):
    """Return a JSON-able result dict for one finished session."""
    sim = record.simulator or {}
    out = {
        "scenario_id": record.scenario_id,
        "condition": record.condition,
        "kind": truth.kind,
        "termination": record.termination,
        "error": record.error,
        "resources": resources(record, config),
        "simulator_audit": {
            "violations": sim.get("violations", {}),
            "consistency_retries": sim.get("consistency_retries", 0),
            "malformed_retries": max(0, sim.get("attempts", 0) - sim.get("calls", 0)),
            "context_entries_dropped": sim.get("context_entries_dropped", 0),
        },
    }
    if record.termination in INVALID_TERMINATIONS:
        return {
            **out,
            "valid": False,
            "outcome": "invalid",
            "failure_category": record.termination,
        }
    budget = config.turn_budget or max_turns
    judged = Judge(oracle, truth)
    recs = [(t.turn, t.recommended_ids) for t in record.turns if t.recommended_ids]
    all_ids = list(dict.fromkeys(i for _, ids in recs for i in ids))
    verdicts = {i: judged(i) for i in all_ids}
    fails = [i for i in all_ids if verdicts[i]["hard"] == "fail"]
    out["violations"] = {
        "items": len(all_ids),
        "hard_fail": len(fails),
        "unknown_required": sum(verdicts[i]["hard"] == "unknown" for i in all_ids),
        "unknown_product_id": sum(verdicts[i]["hard"] == "unknown_id" for i in all_ids),
        "hard_fail_rate": len(fails) / len(all_ids) if all_ids else None,
        "any_hard_fail": bool(fails),
    }
    seen = list(
        dict.fromkeys(
            i for t in record.turns for batch in t.candidates_seen for i in batch
        )
    )
    seen_judged = [judged(i) for i in seen[:MAX_DIAGNOSTIC_IDS]]
    wanted = {f.field for f in truth.hard}
    captured = {
        r["field"] for r in record.final_requirements if r["strength"] == "hard"
    }
    retrieval = {
        "searched": any(t.searches for t in record.turns),
        "candidates_seen": len(seen),
        "acceptable_seen": any(j["grade"] > 0 for j in seen_judged),
        "best_grade_seen": max((j["grade"] for j in seen_judged), default=0),
        "hard_pass_rate_of_candidates": (
            sum(j["grade"] > 0 for j in seen_judged) / len(seen_judged)
            if seen_judged
            else None
        ),
        "hidden_hard_fields_missing_from_state": sorted(wanted - captured),
        "hidden_hard_facts_not_in_state": [
            f.key for f in truth.hard if not represented(f, record.final_requirements)
        ],
        "acceptable_exists": truth.acceptable_count > 0,
    }
    # A safe closure is a status-ok turn, but it means ASTRA ran out of budget: not an answer.
    agent_codes = {c for t in record.turns for c in (t.error, t.closure) if c}
    out.update(valid=True, retrieval=retrieval)
    if truth.kind == "no_valid_product":
        errored = bool(agent_codes) or record.termination == "agent_error"
        correct = not all_ids and not errored
        category = (
            None
            if correct
            else "false_recommendation"
            if all_ids
            else failure_category(agent_codes, retrieval)
        )
        return {
            **out,
            "outcome": "success" if correct else "failure",
            "failure_category": category,
            "abstained_correctly": correct,
            "false_recommendation": bool(all_ids),
        }
    grades_by_rec = [(turn, [verdicts[i]["grade"] for i in ids]) for turn, ids in recs]
    metrics = {
        "hit_at_k": {},
        "success_at_k_within_budget": {},
        # Strict: every item in the top K (as many as were recommended) is verified.
        "strict_success_at_k_within_budget": {},
        "precision_first_at_k": {},
        "ndcg_first": {},
        "ndcg_final": {},
    }
    for k in config.k_values:
        first = grades_by_rec[0][1][:k] if grades_by_rec else None
        metrics["hit_at_k"][str(k)] = (
            None if first is None else any(g > 0 for g in first)
        )
        metrics["success_at_k_within_budget"][str(k)] = any(
            turn <= budget and any(g > 0 for g in grades[:k])
            for turn, grades in grades_by_rec
        )
        metrics["strict_success_at_k_within_budget"][str(k)] = any(
            turn <= budget and grades[:k] and all(g > 0 for g in grades[:k])
            for turn, grades in grades_by_rec
        )
        metrics["precision_first_at_k"][str(k)] = (
            sum(g > 0 for g in grades_by_rec[0][1][:k]) / len(grades_by_rec[0][1][:k])
            if grades_by_rec
            else None
        )
        metrics["ndcg_first"][str(k)] = (
            ndcg(grades_by_rec[0][1], truth.ideal_grades, k) if grades_by_rec else None
        )
        metrics["ndcg_final"][str(k)] = (
            ndcg(grades_by_rec[-1][1], truth.ideal_grades, k) if grades_by_rec else None
        )
    headline = config.headline_k
    first_success = next(
        (
            turn
            for turn, grades in grades_by_rec
            if turn <= budget and any(g > 0 for g in grades[:headline])
        ),
        None,
    )
    success = first_success is not None
    return {
        **out,
        "outcome": "success" if success else "failure",
        "failure_category": None
        if success
        else failure_category(agent_codes, retrieval),
        "metrics": metrics,
        "turns_to_first_success": first_success,
        "turn_budget": budget,
        "first_recommendation_turn": grades_by_rec[0][0] if grades_by_rec else None,
    }
