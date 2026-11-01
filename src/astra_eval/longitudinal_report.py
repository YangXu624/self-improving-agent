"""Transparent session/customer summaries and bounded, noncausal memory-use diagnostics."""

import json
from collections import Counter
from pathlib import Path

from .models import Fact
from .oracle import judge, norm, raw_facts
from .report import mean


def memory_audit(events, customer, task, oracle) -> dict:
    """Audit actual payloads and cards, not LLM explanations or hidden memory seeding."""
    _background, current = customer.state_at(task.visit.sequence)
    by_scope = {(p.category, p.fact.field, norm(p.scope)): p for p in current.values()}
    retrieved, injected, updates, rejected, flags, matches = [], [], [], [], [], []
    visible = {}
    for event in events:
        payload = event.payload
        if event.type == "user_memory_selection":
            retrieved.extend(payload["retrieved"])
        elif event.type == "user_memory_updated":
            updates.append(payload)
        elif event.type == "user_memory_update_rejected":
            rejected.append(payload)
        elif event.type == "model_request":
            try:
                from shopping_agent.memory_views import compact_user_memory

                sent = json.loads(payload["messages"][-1]["content"])
                records = sent.get("user_memory", {}).get("records", [])
                if sent.get("memory_format") == "compact":
                    canonical = payload.get("user_memory_records")
                    records = (
                        canonical["records"]
                        if canonical is not None
                        and compact_user_memory(canonical) == sent.get("user_memory")
                        else []
                    )
            except (ValueError, KeyError, TypeError):
                records = []
            visible = {}
            for record in records:
                injected.append(record["id"])
                preference = by_scope.get(
                    (record["category"], record["attribute"], norm(record["scope"]))
                )
                status = "unassessed"
                if task.visit.recipient == "gift" and preference is not None:
                    status = "recipient_inapplicable"
                elif preference is not None:
                    status = (
                        "outdated"
                        if norm(record["value"]) != norm(preference.fact.value)
                        else "relevant"
                        if preference.fact.key in task.visit.persistent_keys
                        else "irrelevant"
                    )
                visible[record["id"]] = (record, status, preference)
                if status in {"outdated", "recipient_inapplicable", "irrelevant"}:
                    flags.append(
                        {
                            "type": status + "_record_injected",
                            "memory_id": record["id"],
                            "request_id": event.turn_id,
                        }
                    )
        elif event.type == "recommendation":
            for product_id in payload.get("product_ids", []):
                row = oracle.row(product_id)
                if row is None:
                    continue
                values = raw_facts(row)
                for record, status, preference in visible.values():
                    if record["attribute"] not in {
                        "color",
                        "material",
                        "brand",
                        "department",
                        "size",
                    }:
                        continue
                    old = Fact(
                        key="memory-audit",
                        kind="soft",
                        field=record["attribute"],
                        op="not_contains" if record["category"] == "dislike" else "eq",
                        value=record["value"],
                        statement="Audit only",
                    )
                    if judge(values, [old], [])["hard"] != "pass":
                        continue
                    matches.append(
                        {
                            "memory_id": record["id"],
                            "product_id": product_id,
                            "request_id": event.turn_id,
                            "status": status,
                        }
                    )
                    if status in {"outdated", "recipient_inapplicable"}:
                        requirements = [
                            f
                            for f in task.scenario.profile.facts
                            if f.field == old.field
                        ]
                        if any(
                            judge(values, [f], [])["hard"] != "pass"
                            for f in requirements
                        ):
                            flags.append(
                                {
                                    "type": "potential_incorrect_reuse",
                                    "memory_id": record["id"],
                                    "product_id": product_id,
                                    "request_id": event.turn_id,
                                }
                            )
    unique_flags = list({json.dumps(f, sort_keys=True): f for f in flags}.values())
    return {
        "retrieved_ids": sorted(set(retrieved)),
        "injected_ids": sorted(set(injected)),
        "updates": updates,
        "rejected_updates": rejected,
        "recommendation_matches": matches,
        "flags": unique_flags,
        "interpretation": "Injection and catalogue associations are observable; they do not prove causal application. Unmapped attributes/scopes are unassessed, not verified correct.",
    }


def summarize(rows: list[dict]) -> dict:
    """All-started and valid-only outcomes, grouped by mode rather than a weighted score."""
    mode_cells = {}
    for mode in sorted({r["evaluation_mode"] for r in rows}):
        group = [r for r in rows if r["evaluation_mode"] == mode]
        valid = [r for r in group if r["score"].get("valid")]
        hits = [r for r in group if r["score"].get("outcome") == "success"]

        def turns(r):
            return r["score"].get(
                "first_success_turn", r["score"].get("turns_to_first_success")
            )

        mode_cells[mode] = {
            "started": len(group),
            "valid": len(valid),
            "success_rate_all_started": len(hits) / len(group),
            "success_rate_valid_only": sum(
                r["score"].get("outcome") == "success" for r in valid
            )
            / len(valid)
            if valid
            else None,
            "mttc_successes_only": mean([turns(r) for r in hits]),
            "penalized_mttc": mean(
                [turns(r) if r in hits else r["turn_budget"] + 1 for r in group]
            ),
            "mean_searches_to_success": mean(
                [r["efficiency_to_first_success"]["searches"] for r in hits]
            ),
            "mean_clarifications_to_success": mean(
                [r["efficiency_to_first_success"]["clarifications"] for r in hits]
            ),
            "mean_first_hit_mrr_at_k": mean(
                [r["score"].get("first_hit_mrr_at_k", 0) for r in group]
            )
            if mode == "target_item"
            else None,
            "mean_suitability_ndcg_first": {
                k: mean(
                    [
                        (
                            r["suitability"]
                            .get("metrics", {})
                            .get("ndcg_first", {})
                            .get(k)
                            or 0
                        )
                        if r["score"].get("valid")
                        else 0
                        for r in group
                    ]
                )
                for k in sorted(
                    {
                        k
                        for r in group
                        for k in r["suitability"]
                        .get("metrics", {})
                        .get("ndcg_first", {})
                    }
                )
            },
            "cumulative_success_by_turn": {
                str(t): sum(turns(r) <= t for r in hits) / len(group)
                for t in range(1, max(r["turn_budget"] for r in group) + 1)
            },
        }
    resources = {
        key: sum(r["score"]["resources"].get(key, 0) for r in rows)
        for key in (
            "agent_turns",
            "model_calls",
            "searches",
            "clarifications",
            "simulator_calls",
        )
    }
    for side in ("agent_usage", "simulator_usage"):
        keys = {k for r in rows for k in r["score"]["resources"].get(side, {})}
        resources[side] = {
            k: sum(r["score"]["resources"].get(side, {}).get(k, 0) or 0 for r in rows)
            for k in keys
        }
        resources[side + "_sessions_missing"] = sum(
            not r["score"]["resources"].get(side) for r in rows
        )
    costs = [r["score"]["resources"].get("estimated_cost_usd") for r in rows]
    resources["reported_estimated_cost_usd"] = (
        sum(c for c in costs if c is not None)
        if any(c is not None for c in costs)
        else None
    )
    resources["cost_sessions_missing"] = sum(c is None for c in costs)
    resources["simulator_failure_accounting_incomplete_sessions"] = sum(
        r.get("token_accounting", {}).get(
            "simulator_failure_may_have_unreported_attempts", False
        )
        for r in rows
    )
    return {
        "sessions_started": len(rows),
        "by_mode": mode_cells,
        "resources": resources,
        "terminations": dict(Counter(r["termination"] for r in rows)),
        "disclosed_requirement_compliance": {
            key: sum(r["disclosed_requirement_compliance"].get(key, 0) for r in rows)
            for key in (
                "checked_occurrences",
                "passed",
                "violations",
                "unknown_required",
                "unknown_product_id",
                "missing_snapshot_occurrences",
            )
        },
        "memory_flags": dict(
            Counter(f["type"] for r in rows for f in r["user_memory"]["flags"])
        ),
        "memory_update_batches": sum(len(r["user_memory"]["updates"]) for r in rows),
        "memory_rejected_batches": sum(
            len(r["user_memory"]["rejected_updates"]) for r in rows
        ),
    }


def write_longitudinal_report(directory: Path) -> dict:
    directory = Path(directory)
    path = directory / "results.jsonl"
    rows = (
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if path.exists()
        else []
    )
    run = json.loads((directory / "run.json").read_text())
    plan = run["shared_config"]["plan"]
    conditions = [c["name"] for c in plan["conditions"]]
    customers = plan["customer_order"]
    cells = {
        condition: summarize([r for r in rows if r["condition"] == condition])
        for condition in conditions
    }
    per_customer = {
        customer: {
            condition: summarize(
                [
                    r
                    for r in rows
                    if r["customer_id"] == customer and r["condition"] == condition
                ]
            )
            for condition in conditions
        }
        for customer in customers
    }
    for condition, cell in cells.items():
        cell["planned_sessions"] = len(plan["tasks"])
        cell["not_started_sessions"] = len(plan["tasks"]) - cell["sessions_started"]
    for customer, arms in per_customer.items():
        planned = sum(t["customer_id"] == customer for t in plan["tasks"])
        for cell in arms.values():
            cell["planned_sessions"] = planned
            cell["not_started_sessions"] = planned - cell["sessions_started"]
    paired = []
    for task in plan["tasks"]:
        matches = {r["condition"]: r for r in rows if r["task_id"] == task["task_id"]}
        paired.append(
            {
                "customer_id": task["customer_id"],
                "task_id": task["task_id"],
                "complete": len(matches) == 2,
                "valid_pair": len(matches) == 2
                and all(r["score"].get("valid") for r in matches.values()),
                "outcomes": {c: r["score"]["outcome"] for c, r in matches.items()},
            }
        )
    report = {
        "evaluation_mode": "longitudinal_user_memory",
        "development_only": True,
        "primary_k": run["shared_config"]["score"]["headline_k"],
        "planned_sessions": plan["sessions"],
        "started_sessions": len(rows),
        "conditions": cells,
        "customers": per_customer,
        "pairs": paired,
        "definition": "Separate exact-target and suitability outcomes; all started errors remain visible. Failed turns penalty is budget+1. Secondary suitability in target sessions observes only the primary-stopped prefix. Memory flags are private-profile associations, not causal proof or disclosed-requirement violations. Old exposure can be necessary for correction. ON includes schema/instruction changes and naturally diverging histories.",
        "token_accounting": "Available reported usage only; inherited shopper failures can omit transport attempts/tokens. Missing usage is not zero cost. Estimates require explicit rates and are not billing records.",
    }
    (directory / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    lines = [
        "# Returning-customer development evaluation",
        "",
        report["definition"],
        report["token_accounting"],
        "",
        f"Sessions started/planned: {len(rows)}/{plan['sessions']}; primary K={report['primary_k']}",
        "",
        "| Customer | Condition | Mode | Started | Success | MTTC | Penalized MTTC |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for customer, arms in per_customer.items():
        for condition, result in arms.items():
            for mode, cell in result["by_mode"].items():
                lines.append(
                    f"| {customer} | {condition} | {mode} | {cell['started']} | {cell['success_rate_all_started']} | {cell['mttc_successes_only']} | {cell['penalized_mttc']} |"
                )
    lines.extend(
        [
            "",
            "## Resources, compliance and memory diagnostics",
            "",
            "```json",
            json.dumps(cells, indent=2, sort_keys=True),
            "```",
            "",
            "Small development fixtures and scripted/mocked runs do not establish real memory benefit.",
        ]
    )
    (directory / "report.md").write_text("\n".join(lines) + "\n")
    return report
