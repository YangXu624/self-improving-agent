"""Prespecified reviewed-pool measures; never called during context construction."""


def verified(label):
    return label["relevant"] and label["hard_verdict"] == "pass"


def shortlist_metrics(ids, qrel):
    labels = qrel["judgments"]
    if any(ident not in labels for ident in ids):
        raise ValueError("Unjudged candidate; do not silently score it as irrelevant")
    hits = sum(verified(labels[ident]) for ident in ids)
    return {
        "visible": len(ids),
        "verified_matches": hits,
        "hit": hits > 0,
        "precision_displayed": hits / len(ids) if ids else None,
    }


def outcome_metrics(outcome, qrel):
    feasible = qrel["feasible"]
    ids = outcome["accepted_ids"]
    labels = [qrel["judgments"][ident] for ident in ids]
    valid_recommendation = (
        outcome["status"] == "ok"
        and outcome["action"] == "RECOMMEND"
        and 1 <= len(ids) <= 3
    )
    any_hit = valid_recommendation and any(verified(label) for label in labels)
    strict = valid_recommendation and all(verified(label) for label in labels)
    # Prespecified sensitivity: recognized structured facts remain authoritative,
    # ignoring only the two reviewed parent-metadata ambiguities, not known failures.
    structured = valid_recommendation and all(
        label["relevant"] and label["hard_verdict"] != "fail" for label in labels
    )
    abstention = (
        outcome["status"] == "ok"
        and outcome["action"] in {"CLARIFY", "RESPOND"}
        and not ids
    )
    return {
        "feasible": feasible,
        "strict_success": strict if feasible else None,
        "any_verified_hit": any_hit if feasible else None,
        "structured_facts_sensitivity_success": structured if feasible else None,
        "safe_abstention": abstention if not feasible else None,
        "false_feasible_abstention": feasible and abstention,
        "selected_count": len(ids),
        "selected_verified": sum(verified(label) for label in labels),
        "independent_known_hard_failures": sum(
            label["hard_verdict"] == "fail" for label in labels
        ),
        "independent_unknown_required": sum(
            label["hard_verdict"] == "unknown" for label in labels
        ),
        "failure": outcome["status"] != "ok",
    }
