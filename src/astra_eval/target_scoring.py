"""Exact-target discovery: first qualifying presented list, not best rank over time."""

import re
from dataclasses import dataclass

from .disclosed_compliance import compliance
from .scoring import Judge, ScoreConfig, resources


@dataclass(frozen=True)
class TargetRule:
    target_id: str | None
    k: int = 5

    def __post_init__(self):
        if not 1 <= self.k <= 5:
            raise ValueError(
                "Target K must be within current recommendation limit 1..5"
            )

    def check(self, response, event_ids):
        """Validate actual rendered RECOMMEND order, then return its one-based hit rank."""
        if response.get("status") != "ok" or response.get("action") != "RECOMMEND":
            if event_ids:
                raise ValueError("recommendation_response_event_mismatch")
            return None
        cards = response.get("products", [])
        ids = [p.get("id") for p in cards]
        if (
            not 1 <= len(ids) <= 5
            or any(not isinstance(i, str) or not i for i in ids)
            or len(set(ids)) != len(ids)
            or ids != event_ids
        ):
            raise ValueError("recommendation_response_event_mismatch")
        return (
            ids.index(self.target_id) + 1 if self.target_id in ids[: self.k] else None
        )


def target_score(record, truth, oracle, config=ScoreConfig(headline_k=5), *, max_turns):
    """Recompute hit proof from the runner's presented lists; failures never improve MRR."""
    k = config.headline_k
    rule = TargetRule(truth.target_id, k)
    hit, integrity_error = None, record.termination == "harness_error"
    if not integrity_error:
        try:
            for t in record.turns:
                response = {
                    "status": t.status,
                    "action": t.action,
                    "products": [{"id": i} for i in t.presented_ids],
                }
                rank = rule.check(response, t.recommended_ids)
                if rank is not None:
                    hit = {"turn": t.turn, "rank": rank, "request_id": t.request_id}
                    break
            integrity_error = hit != record.target_hit or bool(hit) != (
                record.termination == "target_found"
            )
        except (ValueError, KeyError, TypeError):
            integrity_error = True
    if integrity_error:
        hit = None
    judge = Judge(oracle, truth)
    presented = list(dict.fromkeys(i for t in record.turns for i in t.presented_ids))
    verdicts = [judge(i) for i in presented]
    base = {
        "scenario_id": record.scenario_id,
        "condition": record.condition,
        "mode": "target_item",
        "ambiguity": truth.ambiguity,
        "compatible_count": truth.compatible_count,
        "termination": record.termination,
        "error": record.error,
        "valid": record.termination
        not in {
            "simulator_error",
            "provider_error",
            "harness_error",
            "run_budget_exhausted",
        },
        "resources": resources(record, config),
        "simulator_audit": {"violations": record.simulator.get("violations", {})},
        "violations": {
            "items": len(presented),
            "hard_fail": sum(v["hard"] == "fail" for v in verdicts),
            "unknown_required": sum(v["hard"] == "unknown" for v in verdicts),
            "unknown_product_id": sum(v["hard"] == "unknown_id" for v in verdicts),
        },
    }
    # Keep the historical key/value meaning for readers of existing scores.
    base["hidden_target_profile_mismatches"] = dict(base["violations"])
    base["disclosed_requirement_compliance"] = compliance(record, oracle)
    if integrity_error:
        base.update(
            termination="harness_error",
            error="invalid_target_recommendation_proof",
            valid=False,
        )
    if truth.target_id is None:
        # Conservative, auditable response templates plus independently proved empty truth.
        no_match = re.compile(
            r"^(?:There are no verified matches|No verified matches|I (?:could not|couldn't) find (?:any )?(?:verified|suitable|matching) (?:products|items|options))\b",
            re.I,
        )

        def signature(f):
            return (f["field"], f["op"], str(f["value"]).casefold())

        captured = {
            signature(f) for f in record.final_requirements if f["strength"] == "hard"
        }
        required = {signature(f.model_dump()) for f in truth.hard}
        searched_empty = any(
            c.get("verified_eligible") == 0 for t in record.turns for c in t.counts
        )
        response = any(
            t.status == "ok"
            and t.action == "RESPOND"
            and not t.closure
            and no_match.search(t.message)
            for t in record.turns
        )
        grounded = (
            not integrity_error
            and base["valid"]
            and not presented
            and not truth.compatible_count
            and required <= captured
            and searched_empty
            and response
            and record.termination in {"max_turns", "shopper_ended"}
        )
        return {
            **base,
            "outcome": "success" if grounded else "failure",
            "grounded_abstention": bool(grounded),
            "false_recommendation": bool(presented),
        }
    r = base["resources"]
    return {
        **base,
        "outcome": "success" if hit else "failure",
        "primary_k": k,
        "hit_at_k": bool(hit),
        "first_hit_mrr_at_k": 1 / hit["rank"] if hit else 0.0,
        "first_success_turn": hit["turn"] if hit else None,
        "target_rank": hit["rank"] if hit else None,
        "turn_budget": max_turns,
        "penalized_turns": hit["turn"] if hit else max_turns + 1,
        "searches_to_success": r["searches"] if hit else None,
        "clarifications_to_success": r["clarifications"] if hit else None,
    }
