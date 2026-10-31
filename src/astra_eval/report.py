"""Aggregate session results into a deterministic report and view single transcripts.

Feasible scenarios (feasible + underspecified) and no-valid-product scenarios are always
reported separately. Invalid sessions (simulator/infrastructure faults) are counted and
excluded from agent-quality denominators; agent failures never are. Rates carry a Wilson
interval; with small samples these are descriptive, not significance claims.
"""

import json
import math
import statistics
from collections import Counter
from pathlib import Path

FEASIBLE_KINDS = {"feasible", "underspecified"}
SIMULATOR_WARNING_INVALID_RATE = 0.10


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def rate(k, n):
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson95": wilson(k, n)}


def mean(values):
    kept = [v for v in values if v is not None]
    return statistics.fmean(kept) if kept else None


def median(values):
    kept = [v for v in values if v is not None]
    return statistics.median(kept) if kept else None


def read_results(directory):
    path = Path(directory) / "results.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").split("\n")
        if line
    ]


def usage_sum(results, source, key):
    return sum(r["score"]["resources"][source].get(key, 0) for r in results)


def resource_summary(valid):
    n = len(valid)
    costs = [r["score"]["resources"]["estimated_cost_usd"] for r in valid]
    return {
        "mean_agent_turns": mean(
            [r["score"]["resources"]["agent_turns"] for r in valid]
        ),
        "mean_searches": mean([r["score"]["resources"]["searches"] for r in valid]),
        "mean_clarifications": mean(
            [r["score"]["resources"]["clarifications"] for r in valid]
        ),
        "mean_redundant_clarifications": mean(
            [r["score"]["resources"]["redundant_clarifications"] for r in valid]
        ),
        "mean_clarifications_about_nothing_in_profile": mean(
            [
                r["score"]["resources"]["clarifications_about_nothing_in_profile"]
                for r in valid
            ]
        ),
        "mean_model_calls": mean(
            [r["score"]["resources"]["model_calls"] for r in valid]
        ),
        "agent_prompt_tokens": usage_sum(valid, "agent_usage", "prompt_tokens"),
        "agent_completion_tokens": usage_sum(valid, "agent_usage", "completion_tokens"),
        "agent_cache_hit_tokens": usage_sum(
            valid, "agent_usage", "prompt_cache_hit_tokens"
        ),
        "sessions_with_incomplete_usage": sum(
            not r["score"]["resources"]["agent_usage"].get("prompt_tokens")
            for r in valid
        ),
        "median_agent_model_seconds": median(
            [r["score"]["resources"]["agent_model_seconds"] for r in valid]
        ),
        "median_agent_wall_ms": median(
            [r["score"]["resources"]["agent_wall_ms"] for r in valid]
        ),
        "estimated_cost_usd": None
        if not n or any(c is None for c in costs)
        else sum(costs),
        "simulator_prompt_tokens_not_charged": usage_sum(
            valid, "simulator_usage", "prompt_tokens"
        ),
        "simulator_completion_tokens_not_charged": usage_sum(
            valid, "simulator_usage", "completion_tokens"
        ),
    }


def feasible_cell(rows, k_values, headline):
    valid = [r for r in rows if r["score"]["valid"]]
    n = len(valid)
    scores = [r["score"] for r in valid]
    successes = [s for s in scores if s["outcome"] == "success"]
    turns = [s["turns_to_first_success"] for s in successes]
    penalised = [
        s["turns_to_first_success"]
        if s["outcome"] == "success"
        else s["turn_budget"] + 1
        for s in scores
    ]
    items = sum(s["violations"]["items"] for s in scores)
    fails = sum(s["violations"]["hard_fail"] for s in scores)
    with_recs = [s for s in scores if s["violations"]["items"]]
    cell = {
        "sessions": len(rows),
        "valid": n,
        "invalid": len(rows) - n,
        "success_headline_k": {"headline_k": headline, **rate(len(successes), n)},
        "success_at_k_within_budget": {
            str(k): rate(
                sum(s["metrics"]["success_at_k_within_budget"][str(k)] for s in scores),
                n,
            )
            for k in k_values
        },
        "first_recommendation_hit_at_k": {
            str(k): rate(sum(bool(s["metrics"]["hit_at_k"][str(k)]) for s in scores), n)
            for k in k_values
        },
        "ndcg_first_recommendation_no_rec_as_zero": {
            str(k): mean([s["metrics"]["ndcg_first"][str(k)] or 0.0 for s in scores])
            if n
            else None
            for k in k_values
        },
        "strict_success_at_k_within_budget": {
            str(k): rate(
                sum(
                    s["metrics"]["strict_success_at_k_within_budget"][str(k)]
                    for s in scores
                ),
                n,
            )
            for k in k_values
        },
        "precision_first_recommendation_given_a_recommendation": {
            str(k): mean([s["metrics"]["precision_first_at_k"][str(k)] for s in scores])
            for k in k_values
        },
        "ndcg_final_recommendation_no_rec_as_zero": {
            str(k): mean([s["metrics"]["ndcg_final"][str(k)] or 0.0 for s in scores])
            if n
            else None
            for k in k_values
        },
        "terminations": dict(Counter(r["score"]["termination"] for r in rows)),
        "invalid_by_reason": dict(
            Counter(
                r["score"]["failure_category"] for r in rows if not r["score"]["valid"]
            )
        ),
        "success_headline_k_if_invalid_counted_as_failure": rate(
            sum(r["score"]["outcome"] == "success" for r in rows), len(rows)
        ),
        "ndcg_first_recommendation_given_a_recommendation": {
            str(k): mean([s["metrics"]["ndcg_first"][str(k)] for s in scores])
            for k in k_values
        },
        "ndcg_final_recommendation_given_a_recommendation": {
            str(k): mean([s["metrics"]["ndcg_final"][str(k)] for s in scores])
            for k in k_values
        },
        "hard_violations": {
            "recommended_items": items,
            "items_failing_a_hidden_hard_requirement": fails,
            "item_violation_rate": fails / items if items else None,
            "sessions_with_a_recommendation": len(with_recs),
            "sessions_with_any_violation": sum(
                s["violations"]["any_hard_fail"] for s in with_recs
            ),
            "items_with_unknown_required_attribute": sum(
                s["violations"]["unknown_required"] for s in scores
            ),
            "items_with_unknown_product_id": sum(
                s["violations"]["unknown_product_id"] for s in scores
            ),
        },
        "turns_to_first_success": {
            "median_over_successes": median(turns),
            "mean_over_successes": mean(turns),
            "penalised_mean_failure_as_budget_plus_one": mean(penalised),
            "successes": len(successes),
        },
        "failure_categories": dict(
            Counter(s["failure_category"] for s in scores if s["outcome"] == "failure")
        ),
        "retrieval_diagnostics": {
            "acceptable_product_ever_returned_to_agent": rate(
                sum(s["retrieval"]["acceptable_seen"] for s in scores), n
            ),
            "mean_hard_pass_rate_of_candidates": mean(
                [s["retrieval"]["hard_pass_rate_of_candidates"] for s in scores]
            ),
            "sessions_missing_a_hidden_hard_field_in_state": sum(
                bool(s["retrieval"]["hidden_hard_fields_missing_from_state"])
                for s in scores
            ),
            "state_extraction_failures": sum(
                s["failure_category"] == "state_extraction_failure" for s in scores
            ),
            "retrieval_failures": sum(
                s["failure_category"] == "retrieval_failure" for s in scores
            ),
            "recommendation_failures": sum(
                s["failure_category"] == "recommendation_failure" for s in scores
            ),
        },
        "resources": resource_summary(valid),
    }
    return cell


def no_valid_cell(rows):
    valid = [r for r in rows if r["score"]["valid"]]
    scores = [r["score"] for r in valid]
    n = len(valid)
    return {
        "sessions": len(rows),
        "valid": n,
        "invalid": len(rows) - n,
        "correct_abstention": rate(sum(s["abstained_correctly"] for s in scores), n),
        "false_recommendation": rate(sum(s["false_recommendation"] for s in scores), n),
        "failure_categories": dict(
            Counter(s["failure_category"] for s in scores if s["outcome"] == "failure")
        ),
        "resources": resource_summary(valid),
    }


def simulator_reliability(results):
    scores = [r["score"] for r in results]
    calls = sum(s["resources"]["simulator_calls"] for s in scores)
    violations = Counter()
    for s in scores:
        violations.update(s["simulator_audit"]["violations"])
    invalid = Counter(s["failure_category"] for s in scores if not s["valid"])
    sim_invalid = sum(v for k, v in invalid.items() if k == "simulator_failure")
    rate_invalid = sim_invalid / len(scores) if scores else None
    return {
        "sessions": len(scores),
        "shopper_calls": calls,
        "malformed_reply_retries": sum(
            s["simulator_audit"]["malformed_retries"] for s in scores
        ),
        "consistency_retries": sum(
            s["simulator_audit"]["consistency_retries"] for s in scores
        ),
        "violations_by_code": dict(sorted(violations.items())),
        "violations_per_shopper_call": (sum(violations.values()) / calls)
        if calls
        else None,
        "context_entries_dropped_for_budget": sum(
            s["simulator_audit"]["context_entries_dropped"] for s in scores
        ),
        "invalid_sessions_by_reason": dict(invalid),
        "simulator_failure_rate": rate_invalid,
        "warning": (
            "Simulator invalid-session rate above 10%: this simulator may be too unreliable "
            "to trust these results."
            if rate_invalid is not None
            and rate_invalid > SIMULATOR_WARNING_INVALID_RATE
            else None
        ),
    }


def mcnemar_exact(only_a, only_b):
    n = only_a + only_b
    if n == 0:
        return 1.0
    low = min(only_a, only_b)
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(low + 1)) / 2**n)


def paired(results, a, b):
    """Per-scenario paired SUCCESS for two conditions on feasible scenarios (no nDCG pairing).

    Pairs with an invalid session in either arm are dropped from the main comparison, and the
    drop is reported with reasons because it can be non-random. The sensitivity row counts an
    invalid session as a failure instead.
    """
    table = {}
    for r in results:
        if r["scenario"]["kind"] in FEASIBLE_KINDS:
            table.setdefault(r["scenario"]["id"], {})[r["condition"]] = r["score"]
    both = [(v[a], v[b]) for v in table.values() if a in v and b in v]
    pairs = [(x, y) for x, y in both if x["valid"] and y["valid"]]
    dropped = Counter()
    for x, y in both:
        for name, score in ((a, x), (b, y)):
            if not score["valid"]:
                dropped[f"{name}:{score['failure_category']}"] += 1

    def wins(rows):
        only_a = sum(
            x["outcome"] == "success" and y["outcome"] != "success" for x, y in rows
        )
        only_b = sum(
            y["outcome"] == "success" and x["outcome"] != "success" for x, y in rows
        )
        diff = (
            (
                sum(x["outcome"] == "success" for x, _ in rows)
                - sum(y["outcome"] == "success" for _, y in rows)
            )
            / len(rows)
            if rows
            else None
        )
        return only_a, only_b, diff

    only_a, only_b, diff = wins(pairs)
    s_a, s_b, s_diff = wins(both)  # invalid sessions are not successes
    return {
        "treatment": a,
        "reference": b,
        "pairs": len(pairs),
        "dropped_pairs": len(both) - len(pairs),
        "dropped_reasons": dict(dropped),
        "only_treatment_succeeds": only_a,
        "only_reference_succeeds": only_b,
        "success_rate_difference": diff,
        "mcnemar_exact_p": mcnemar_exact(only_a, only_b) if pairs else None,
        "sensitivity_invalid_counted_as_failure": {
            "pairs": len(both),
            "only_treatment_succeeds": s_a,
            "only_reference_succeeds": s_b,
            "success_rate_difference": s_diff,
        },
    }


def build_report(directory, k_values=None, headline=None):
    results = read_results(directory)
    run = json.loads((Path(directory) / "run.json").read_text(encoding="utf-8"))
    if run["shared_config"].get("evaluation_mode") == "target_item":
        from .target_report import build_target_report

        return build_target_report(directory)
    # The report must use the K values the run was scored with, not its own defaults.
    scored = run["shared_config"]["score"]
    k_values = tuple(k_values or scored["k_values"])
    headline = headline or scored["headline_k"]
    if headline not in k_values:
        raise ValueError("headline K must be one of the scored K values")
    conditions = sorted({r["condition"] for r in results})
    report = {
        "run": {
            "shared_config_sha256": run["shared_config_sha256"],
            "git": run["git"],
            "conditions": conditions,
            "sessions": len(results),
            "caveat": "Descriptive. Simulated shopper, fixed scenarios; small samples do not "
            "establish differences. No-valid-product scenarios are separate.",
        },
        "cells": {},
        "simulator_reliability": simulator_reliability(results),
    }
    splits = sorted({r["scenario"]["split"] for r in results})
    for condition in conditions:
        for split in [*splits, "all"]:
            rows = [
                r
                for r in results
                if r["condition"] == condition
                and split in ("all", r["scenario"]["split"])
            ]
            feasible = [r for r in rows if r["scenario"]["kind"] in FEASIBLE_KINDS]
            none = [r for r in rows if r["scenario"]["kind"] == "no_valid_product"]
            key = f"{condition}/{split}"
            report["cells"][key] = {
                "feasible": feasible_cell(feasible, k_values, headline)
                if feasible
                else None,
                "no_valid_product": no_valid_cell(none) if none else None,
            }
        for kind in ("feasible", "underspecified"):
            rows = [
                r
                for r in results
                if r["condition"] == condition and r["scenario"]["kind"] == kind
            ]
            if rows:
                report["cells"][f"{condition}/kind={kind}"] = {
                    "feasible": feasible_cell(rows, k_values, headline),
                    "no_valid_product": None,
                }
    if len(conditions) == 2:
        # Memory OFF is the reference when present; otherwise the first name alphabetically.
        reference = "memory_off" if "memory_off" in conditions else conditions[0]
        treatment = next(c for c in conditions if c != reference)
        report["paired_comparison"] = paired(results, treatment, reference)
    return report


def fmt(value):
    if value is None:
        return "N/A"
    if isinstance(value, dict) and "rate" in value:
        text = "N/A" if value["rate"] is None else f"{value['rate']:.3f}"
        interval = value.get("wilson95")
        suffix = f" [{interval[0]:.2f}-{interval[1]:.2f}]" if interval else ""
        return f"{text} ({value['k']}/{value['n']}){suffix}"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(report):
    if report.get("evaluation_mode") == "target_item":
        from .target_report import render_target_report

        return render_target_report(report)
    lines = [
        "# Simulated-shopper evaluation report",
        "",
        f"> {report['run']['caveat']}",
        "",
    ]
    lines += [
        f"Config `{report['run']['shared_config_sha256'][:12]}`, commit `{(report['run']['git'].get('commit') or 'unknown')[:12]}`"
        f"{' (dirty tree)' if report['run']['git'].get('dirty') else ''}, {report['run']['sessions']} sessions.",
        "",
    ]
    rel = report["simulator_reliability"]
    lines += [
        "## Simulator reliability",
        "",
        f"- Shopper calls: {rel['shopper_calls']}; malformed-reply retries: {rel['malformed_reply_retries']}; "
        f"consistency retries: {rel['consistency_retries']}; dialogue entries dropped for budget: {rel['context_entries_dropped_for_budget']}",
        f"- Violations by code: {rel['violations_by_code'] or 'none'}",
        f"- Invalid sessions by reason: {rel['invalid_sessions_by_reason'] or 'none'}; simulator failure rate: {fmt(rel['simulator_failure_rate'])}",
    ]
    if rel["warning"]:
        lines.append(f"- **WARNING:** {rel['warning']}")
    lines.append("")
    for key, cell in report["cells"].items():
        feasible, none = cell["feasible"], cell["no_valid_product"]
        if feasible:
            lines += [
                f"## {key}: feasible scenarios",
                "",
                f"Sessions {feasible['sessions']} (valid {feasible['valid']}, invalid {feasible['invalid']}, excluded from rates below).",
                "",
                "| Measure | Value |",
                "| --- | --- |",
                f"| Headline Success@{feasible['success_headline_k']['headline_k']} (verified, within turn budget) | {fmt(feasible['success_headline_k'])} |",
            ]
            for k, v in feasible["success_at_k_within_budget"].items():
                lines.append(f"| Success@{k} (within turn budget) | {fmt(v)} |")
            for k, v in feasible["strict_success_at_k_within_budget"].items():
                lines.append(
                    f"| Strict success@{k} (every item in top {k} verified) | {fmt(v)} |"
                )
            lines.append(
                f"| Success@headline if invalid sessions counted as failures | "
                f"{fmt(feasible['success_headline_k_if_invalid_counted_as_failure'])} |"
            )
            lines.append(f"| Terminations | {feasible['terminations']} |")
            for k, v in feasible["first_recommendation_hit_at_k"].items():
                lines.append(f"| First-recommendation Hit@{k} | {fmt(v)} |")
            for k, v in feasible["ndcg_first_recommendation_no_rec_as_zero"].items():
                lines.append(f"| nDCG@{k} first rec (no rec = 0) | {fmt(v)} |")
            hv, tt, rd = (
                feasible["hard_violations"],
                feasible["turns_to_first_success"],
                feasible["retrieval_diagnostics"],
            )
            lines += [
                f"| Hard-violation item rate | {fmt(hv['item_violation_rate'])} ({hv['items_failing_a_hidden_hard_requirement']}/{hv['recommended_items']} items) |",
                f"| Items with unknown required attribute | {hv['items_with_unknown_required_attribute']} |",
                f"| Turns to first success (median / penalised mean) | {fmt(tt['median_over_successes'])} / {fmt(tt['penalised_mean_failure_as_budget_plus_one'])} |",
                f"| Failure categories | {feasible['failure_categories'] or 'none'} |",
                f"| Acceptable product ever returned to agent | {fmt(rd['acceptable_product_ever_returned_to_agent'])} |",
                f"| State-extraction / retrieval / recommendation failures | {rd['state_extraction_failures']} / {rd['retrieval_failures']} / {rd['recommendation_failures']} |",
            ]
            res = feasible["resources"]
            lines += [
                f"| Searches / clarifications / redundant clarifications (mean) | {fmt(res['mean_searches'])} / {fmt(res['mean_clarifications'])} / {fmt(res['mean_redundant_clarifications'])} |",
                f"| Agent tokens (prompt / completion / cache-hit) | {res['agent_prompt_tokens']} / {res['agent_completion_tokens']} / {res['agent_cache_hit_tokens']} |",
                f"| Median agent model seconds / wall ms | {fmt(res['median_agent_model_seconds'])} / {fmt(res['median_agent_wall_ms'])} |",
                f"| Estimated cost (USD) | {fmt(res['estimated_cost_usd'])} |",
                "",
            ]
        if none:
            lines += [
                f"## {key}: no-valid-product scenarios",
                "",
                f"Sessions {none['sessions']} (valid {none['valid']}, invalid {none['invalid']}).",
                f"- Correct abstention: {fmt(none['correct_abstention'])}",
                f"- False recommendation: {fmt(none['false_recommendation'])}",
                f"- Failure categories: {none['failure_categories'] or 'none'}",
                "",
            ]
    if "paired_comparison" in report:
        p = report["paired_comparison"]
        lines += [
            "## Paired comparison (feasible, both sessions valid)",
            "",
            f"{p['treatment']} vs {p['reference']}: {p['pairs']} pairs; only treatment succeeds {p['only_treatment_succeeds']}, "
            f"only reference {p['only_reference_succeeds']}; difference {fmt(p['success_rate_difference'])}; exact McNemar p {fmt(p['mcnemar_exact_p'])}",
            "",
        ]
    return "\n".join(lines) + "\n"


def write_report(directory):
    report = build_report(directory)
    directory = Path(directory)
    (directory / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def show_transcript(directory, scenario_id, condition=None, scenarios_dir=None):
    """Readable transcript plus the audit result. Hidden profile/truth only on request."""
    directory = Path(directory)
    matches = sorted((directory / "sessions").glob(f"{scenario_id}__*"))
    if condition:
        matches = [m for m in matches if m.name.endswith(f"__{condition}")]
    if not matches:
        raise FileNotFoundError("No such session")
    out = []
    for session in matches:
        result = json.loads((session / "result.json").read_text(encoding="utf-8"))
        s = result["score"]
        out += [
            f"=== {session.name}: outcome={s['outcome']} termination={s['termination']} "
            f"category={s.get('failure_category')} error={s.get('error')}"
        ]
        for line in (
            (session / "transcript.jsonl").read_text(encoding="utf-8").split("\n")
        ):
            if not line:
                continue
            e = json.loads(line)
            if e["role"] == "shopper":
                flags = f" flags={e['flags']}" if e.get("flags") else ""
                out.append(
                    f"[turn {e['turn']}] SHOPPER ({e.get('action')}): {e['text']}{flags}"
                )
            elif e["role"] == "assistant":
                out.append(f"[turn {e['turn']}] ASTRA {e.get('action')}: {e['text']}")
                for p in e.get("products", []):
                    out.append(
                        f"      - {p.get('title', '')[:90]} (${p.get('price')}) [{p.get('id')}]"
                    )
            else:
                out.append(f"[audit] {json.dumps(e, ensure_ascii=False)}")
        out.append(
            f"simulator audit: {json.dumps(s['simulator_audit'], sort_keys=True)}"
        )
        if scenarios_dir:
            from .scenarios import load_ground_truth, load_scenarios

            scenarios, _ = load_scenarios(scenarios_dir)
            scenario = next((x for x in scenarios if x.id == scenario_id), None)
            truth = load_ground_truth(scenarios_dir).get(scenario_id)
            out.append(
                "--- DEBUG ONLY (never shown to ASTRA or the shopper's audit) ---"
            )
            if scenario:
                out.append(
                    "hidden profile: "
                    + json.dumps(
                        [f.model_dump() for f in scenario.profile.facts],
                        ensure_ascii=False,
                    )
                )
            if truth:
                out.append(
                    f"ground truth: acceptable={truth.acceptable_count} ideal={truth.ideal_grades[:5]} sample={[a['id'] for a in truth.acceptable_sample[:5]]}"
                )
    return "\n".join(out)
