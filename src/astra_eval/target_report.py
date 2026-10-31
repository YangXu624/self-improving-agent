"""Target discovery and abstention reports, deliberately separate from preference quality."""

import json
from collections import Counter
from pathlib import Path

from .report import fmt, mcnemar_exact, mean, rate, read_results, resource_summary


def cell(rows):
    scores = [r["score"] for r in rows]
    hits = [s for s in scores if s["hit_at_k"]]
    failures = [r for r in rows if not r["score"]["hit_at_k"]]
    horizon = max((s["turn_budget"] for s in scores), default=0)
    disclosed = [s.get("disclosed_requirement_compliance") for s in scores]
    fields = (
        "checked_occurrences",
        "passed",
        "violations",
        "unknown_required",
        "unknown_product_id",
        "missing_snapshot_occurrences",
    )
    confirmed = {
        key: sum(d.get(key, 0) for d in disclosed if d is not None) for key in fields
    }
    confirmed["sessions_without_compliance_data"] = sum(d is None for d in disclosed)
    return {
        "disclosed_requirement_compliance": confirmed,
        "started": len(rows),
        "valid": sum(s["valid"] for s in scores),
        "hit_at_k_all_started": rate(len(hits), len(rows)),
        "hit_at_k_valid_only": rate(
            sum(s["hit_at_k"] for s in scores if s["valid"]),
            sum(s["valid"] for s in scores),
        ),
        "first_hit_mrr_at_k": mean([s["first_hit_mrr_at_k"] for s in scores]),
        "mttc_successes_only": mean([s["first_success_turn"] for s in hits]),
        "penalized_mttc": mean([s["penalized_turns"] for s in scores]),
        "unsuccessful_sessions": len(failures),
        "cumulative_success_by_turn": {
            str(t): rate(
                sum(s["hit_at_k"] and s["first_success_turn"] <= t for s in scores),
                len(rows),
            )
            for t in range(1, horizon + 1)
        },
        "mean_searches_to_success": mean([s["searches_to_success"] for s in hits]),
        "mean_clarifications_to_success": mean(
            [s["clarifications_to_success"] for s in hits]
        ),
        "success_resources": resource_summary(
            [r for r in rows if r["score"]["hit_at_k"]]
        ),
        "failure_resources": resource_summary(failures),
        "terminations": dict(Counter(s["termination"] for s in scores)),
        "violations": {
            key: sum(s["violations"][key] for s in scores)
            for key in ("items", "hard_fail", "unknown_required", "unknown_product_id")
        },
    }


def build_target_report(directory):
    rows = read_results(directory)
    run = json.loads((Path(directory) / "run.json").read_text())
    cells, negatives = {}, {}
    for condition in sorted({r["condition"] for r in rows}):
        for split in ["all", *sorted({r["scenario"]["split"] for r in rows})]:
            group = [
                r
                for r in rows
                if r["condition"] == condition
                and split in {"all", r["scenario"]["split"]}
            ]
            targets = [r for r in group if r["score"]["ambiguity"] != "no_target"]
            for ambiguity in ("all", "distinguishable", "ambiguous"):
                selected = [
                    r for r in targets if ambiguity in {"all", r["score"]["ambiguity"]}
                ]
                if selected:
                    cells[f"{condition}/{split}/{ambiguity}"] = cell(selected)
            absent = [r for r in group if r["score"]["ambiguity"] == "no_target"]
            if absent:
                negatives[f"{condition}/{split}"] = {
                    "started": len(absent),
                    "grounded_abstention": rate(
                        sum(r["score"]["grounded_abstention"] for r in absent),
                        len(absent),
                    ),
                    "false_recommendations": sum(
                        r["score"]["false_recommendation"] for r in absent
                    ),
                    "terminations": dict(
                        Counter(r["score"]["termination"] for r in absent)
                    ),
                    "resources": resource_summary(absent),
                }
    paired = None
    conditions = sorted({r["condition"] for r in rows})
    if len(conditions) == 2:
        reference = "memory_off" if "memory_off" in conditions else conditions[0]
        treatment = next(c for c in conditions if c != reference)
        table = {}
        for r in rows:
            if r["score"]["ambiguity"] != "no_target":
                table.setdefault(r["scenario"]["id"], {})[r["condition"]] = r["score"][
                    "hit_at_k"
                ]
        pairs = [v for v in table.values() if reference in v and treatment in v]
        win = sum(v[treatment] and not v[reference] for v in pairs)
        loss = sum(v[reference] and not v[treatment] for v in pairs)
        paired = {
            "reference": reference,
            "treatment": treatment,
            "complete_pairs": len(pairs),
            "incomplete_pairs": len(table) - len(pairs),
            "only_treatment_hits": win,
            "only_reference_hits": loss,
            "mcnemar_exact_p": mcnemar_exact(win, loss) if pairs else None,
        }
    return {
        "evaluation_mode": "target_item",
        "primary_k": run["shared_config"]["score"]["headline_k"],
        "run": run,
        "cells": cells,
        "no_target": negatives,
        "paired_all_started": paired,
        "definition": "First qualifying presented list within primary K; failures have reciprocal rank zero and turn penalty budget+1. Exact-target discovery is not broader recommendation quality. Secondary cutoffs are censored by the primary stopping rule.",
    }


def render_target_report(report):
    lines = [
        "# Target-item evaluation",
        "",
        report["definition"],
        "",
        f"Primary K: {report['primary_k']}. Rates include all started target sessions; invalid sessions remain visible.",
        "",
        "| Group | Started | Hit@K | First-hit MRR@K | MTTC successes | Penalized MTTC |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, c in report["cells"].items():
        lines.append(
            f"| {name} | {c['started']} | {fmt(c['hit_at_k_all_started'])} | {fmt(c['first_hit_mrr_at_k'])} | {fmt(c['mttc_successes_only'])} | {fmt(c['penalized_mttc'])} |"
        )
        lines.extend(
            [
                "",
                f"Cumulative success: {c['cumulative_success_by_turn']}",
                f"Terminations: {c['terminations']}; hidden-target-profile mismatches (distinct products): {c['violations']}",
                f"Disclosed-requirement compliance (per presentation; committed hard state, extraction completeness not asserted): {c['disclosed_requirement_compliance']}",
                f"Success searches / CLARIFY actions: {c['mean_searches_to_success']} / {c['mean_clarifications_to_success']}",
                f"Failure resources: {c['failure_resources']}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            f"No-target grounded abstention (separate): {report['no_target']}",
            f"Paired comparison: {report['paired_all_started']}",
            "",
            "Small pilots are descriptive; ambiguous targets include chance and catalogue limitations.",
        ]
    )
    return "\n".join(lines) + "\n"
