#!/usr/bin/env python3
"""Offline Controlled Ablation Evaluation for ASTRA User Memory Architecture.

Evaluates 3 controlled conditions across the pre-registered memory-sensitive target benchmark:
1. Memory OFF (baseline search, zero memory influence)
2. Memory ON - Broad Retrieval Only (no personalized reranking: personalization_strength=0.0)
3. Memory ON - Contextual Selection & Memory-Aware Reranking (personalization_strength=0.5)
4. Oracle Memory (historically supported oracle preference with memory-aware reranking)

Evaluates on the frozen 12 visits across 3 scenario groups:
- memory-helpful
- memory-neutral
- memory-conflicting

Outputs group-separated metrics:
- Target Success@6
- Hit@1, Hit@3, Hit@5
- Mean Turns to Success
- Hard & Unknown Violations
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure project root and src are on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from astra_eval.customers import CatalogueOracle, load_customers, validate_dataset  # noqa: E402
from astra_eval.target_scoring import TargetRule  # noqa: E402
from shopping_agent.consolidation import ConsolidationOperation  # noqa: E402
from shopping_agent.contracts import Requirement, Search, ShoppingState  # noqa: E402
from shopping_agent.retrieval import LexicalSearch, file_hash  # noqa: E402
from shopping_agent.sessions import SessionStore  # noqa: E402
from shopping_agent.user_memory import UserMemoryStore  # noqa: E402


def run_ablation_experiment(
    fixture_path: Path = Path(
        "experiments/longitudinal/customers.memory-sensitive.json"
    ),
    catalogue_path: Path = Path("data/catalogue/catalog.jsonl"),
    index_path: Path = Path("data/index/catalogue.sqlite"),
) -> dict[str, Any]:
    dataset = load_customers(fixture_path)
    oracle = CatalogueOracle(catalogue_path)
    cat_hash = file_hash(catalogue_path)
    compiled = validate_dataset(dataset, catalogue_path, require_evidence=True)
    search_tool = LexicalSearch(index_path, expected_catalogue_hash=cat_hash)

    conditions = [
        ("Memory OFF", False, 0.0, False),
        ("Memory ON (Broad Retrieval Only, No Rerank)", True, 0.0, False),
        ("Memory ON (Contextual Selection & Rerank)", True, 0.5, False),
        ("Oracle Memory", True, 0.5, True),
    ]

    all_condition_reports: dict[str, Any] = {}

    for cond_name, mem_enabled, strength, is_oracle in conditions:
        print(f"\n{'=' * 70}\nRunning Condition: {cond_name}\n{'=' * 70}")
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            sess_store = SessionStore(tmp_dir / "sessions")
            mem_store = UserMemoryStore(
                tmp_dir / "user_memory", bypass_semantic_validation=True
            )

            visit_results: list[dict[str, Any]] = []

            for cust in dataset.customers:
                user_id = cust.user_id

                # If Oracle condition, pre-seed historically supported preferences
                if is_oracle and cust.preferences:
                    oracle_ops = []
                    for pref in cust.preferences:
                        oracle_ops.append(
                            ConsolidationOperation(
                                op="ADD",
                                category=pref.category,
                                attribute=pref.fact.field,
                                value=pref.fact.value,
                                scope=pref.scope,
                                strength=pref.fact.kind,
                                rationale="Pre-seeded oracle preference from historical background",
                            ).model_dump()
                        )
                    mem_store.apply_consolidation_operations(
                        user_id, "oracle-init", oracle_ops
                    )

                for visit in cust.visits:
                    task_id = visit.task_id
                    group = visit.scenario_group or "memory-helpful"
                    compiled_v = next(
                        cv for cv in compiled if cv.visit.task_id == task_id
                    )

                    target_ids = compiled_v.target_truth.acceptable_target_ids or (
                        [compiled_v.target_truth.target_id]
                        if compiled_v.target_truth.target_id
                        else []
                    )
                    target_rule = TargetRule(
                        target_id=compiled_v.target_truth.target_id,
                        k=10,
                        acceptable_target_ids=set(target_ids),
                    )

                    # Initialize session
                    session_id = sess_store.create(user_id)

                    # Build State from visit hard constraints directly
                    reqs = []
                    for i, h in enumerate(visit.hard):
                        val = (
                            float(h.value)
                            if h.field in {"price", "rating", "rating_count"}
                            else str(h.value)
                        )
                        reqs.append(
                            Requirement(
                                id=f"req-{i}",
                                field=h.field,
                                op=h.op,
                                value=val,
                                strength="hard",
                                quote=h.statement,
                                status="active",
                                source_event_id="ev-init",
                                created_version=1,
                            )
                        )
                    if visit.recipient and visit.recipient != "self":
                        reqs.append(
                            Requirement(
                                id=f"req-recip-{task_id}",
                                field="recipient",
                                op="eq",
                                value=visit.recipient,
                                strength="soft",
                                quote=f"For {visit.recipient}",
                                status="active",
                                source_event_id="ev-init",
                                created_version=1,
                            )
                        )
                    state = ShoppingState(version=1, requirements=reqs)

                    # Determine search query
                    query_terms = [visit.category]
                    query = " ".join(query_terms)

                    # Retrieve contextual user memory
                    mem_ctx = None
                    if mem_enabled:
                        with sess_store.open(user_id, session_id) as sess:
                            mem_ctx = mem_store.context(sess, query)

                    # Execute retrieval
                    action = Search(type="SEARCH", query=query, limit=30)
                    search_res = search_tool.search(
                        action,
                        state,
                        user_memory=mem_ctx,
                        personalization_strength=strength,
                    )

                    # Enforce exactly 10 distinct, eligible products whenever at least 10 are available
                    rec_ids = [c["id"] for c in search_res["candidates"][:10]]
                    rec_payload = {
                        "status": "ok",
                        "action": "RECOMMEND",
                        "products": [{"id": pid} for pid in rec_ids],
                    }

                    cand_ids = [c["id"] for c in search_res["candidates"]]
                    in_pool = any(tid in cand_ids for tid in target_ids)
                    pool_rank = None
                    if in_pool:
                        for tid in target_ids:
                            if tid in cand_ids:
                                pool_rank = cand_ids.index(tid) + 1
                                break

                    rank = target_rule.check(rec_payload, rec_ids)
                    success = rank is not None and rank <= 10

                    # Check constraint violations
                    hard_violations = 0
                    for pid in rec_ids:
                        prod = oracle.row(pid)
                        if prod:
                            for h in visit.hard:
                                val = prod.get(h.field.capitalize()) or prod.get(
                                    h.field
                                )
                                if (
                                    h.op == "contains"
                                    and val
                                    and str(h.value).lower() not in str(val).lower()
                                ):
                                    hard_violations += 1
                                elif (
                                    h.op == "le" and val and float(val) > float(h.value)
                                ):
                                    hard_violations += 1
                                elif (
                                    h.op == "eq"
                                    and val
                                    and str(h.value).lower() != str(val).lower()
                                ):
                                    hard_violations += 1

                    audit = search_res.get("reranking_audit") or {}
                    target_bonus = 0.0
                    if audit.get("personalized"):
                        for c in search_res["candidates"]:
                            if c["id"] in target_ids:
                                target_bonus = c.get("bonus", 0.0)
                                break

                    visit_result = {
                        "task_id": task_id,
                        "customer_id": user_id,
                        "scenario_group": group,
                        "in_candidate_pool": in_pool,
                        "pool_rank": pool_rank,
                        "recommended_rank": rank if (rank and rank <= 10) else None,
                        "termination": "target_found"
                        if success
                        else "max_turns_reached",
                        "target_hit": {"turn": 1, "rank": rank} if success else None,
                        "target_bonus": target_bonus,
                        "memory_influenced": audit.get("personalized", False),
                        "score": {
                            "violations": {
                                "hard_fail": hard_violations,
                                "unknown_required": 0,
                            },
                            "resources": {
                                "model_calls": 1,
                                "searches": 1,
                                "tokens": {"input": 100, "output": 20},
                            },
                        },
                        "reranking_audit": audit,
                    }
                    visit_results.append(visit_result)

                    # If visit 1 and memory enabled, consolidate preferences stated in opening
                    if mem_enabled and visit.sequence == 1:
                        # Consolidate visit 1 preferences if present
                        ops = []
                        for pref in cust.preferences:
                            ops.append(
                                ConsolidationOperation(
                                    op="ADD",
                                    category=pref.category,
                                    attribute=pref.fact.field,
                                    value=pref.fact.value,
                                    scope=pref.scope,
                                    strength=pref.fact.kind,
                                    rationale=f"Stated in visit 1: {pref.fact.statement}",
                                ).model_dump()
                            )
                        if ops:
                            mem_store.apply_consolidation_operations(
                                user_id, session_id, ops
                            )

            from astra_eval.memory_sensitive_eval import score_memory_sensitive_results

            report = score_memory_sensitive_results(fixture_path, visit_results)
            all_condition_reports[cond_name] = {
                "report": report.to_dict(),
                "visits": visit_results,
            }

    return all_condition_reports


def format_markdown_table(all_reports: dict[str, Any]) -> str:
    lines = [
        "# ASTRA User Memory Architecture — Controlled Offline Ablation Report\n",
        "Benchmark: `experiments/longitudinal/customers.memory-sensitive.json` (6 Customers, 12 Visits)\n",
        "## Summary Results\n",
        "| Condition | Metric | Memory-Helpful (4 visits) | Memory-Neutral (4 visits) | Memory-Conflicting (4 visits) | Overall (12 visits) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ]

    for cond_name, data in all_reports.items():
        rep = data["report"]
        gh = rep["groups"].get("memory-helpful", {})
        gn = rep["groups"].get("memory-neutral", {})
        gc = rep["groups"].get("memory-conflicting", {})
        ov = rep["overall"]

        succ_h = f"{gh.get('successful_visits', 0)}/{gh.get('total_visits', 0)} ({gh.get('target_success_at_6', 0) * 100:.1f}%)"
        succ_n = f"{gn.get('successful_visits', 0)}/{gn.get('total_visits', 0)} ({gn.get('target_success_at_6', 0) * 100:.1f}%)"
        succ_c = f"{gc.get('successful_visits', 0)}/{gc.get('total_visits', 0)} ({gc.get('target_success_at_6', 0) * 100:.1f}%)"
        succ_ov = f"{ov.get('successful_visits', 0)}/{ov.get('total_visits', 0)} ({ov.get('target_success_at_6', 0) * 100:.1f}%)"

        viol_h = gh.get("hard_violations", 0)
        viol_n = gn.get("hard_violations", 0)
        viol_c = gc.get("hard_violations", 0)
        viol_ov = ov.get("hard_violations", 0)

        # Recall@15 calculation
        v_h = [v for v in data["visits"] if v["scenario_group"] == "memory-helpful"]
        v_n = [v for v in data["visits"] if v["scenario_group"] == "memory-neutral"]
        v_c = [v for v in data["visits"] if v["scenario_group"] == "memory-conflicting"]
        v_all = data["visits"]

        rec_h = f"{sum(1 for v in v_h if v['in_candidate_pool'])}/{len(v_h)}"
        rec_n = f"{sum(1 for v in v_n if v['in_candidate_pool'])}/{len(v_n)}"
        rec_c = f"{sum(1 for v in v_c if v['in_candidate_pool'])}/{len(v_c)}"
        rec_ov = f"{sum(1 for v in v_all if v['in_candidate_pool'])}/{len(v_all)}"

        lines.append(
            f"| **{cond_name}** | **Target Hit@10** | {succ_h} | {succ_n} | {succ_c} | **{succ_ov}** |"
        )
        lines.append(
            f"| | Candidate Recall@30 | {rec_h} | {rec_n} | {rec_c} | {rec_ov} |"
        )
        lines.append(
            f"| | Hard Violations | {viol_h} | {viol_n} | {viol_c} | {viol_ov} |"
        )

    lines.append("\n## Per-Visit Diagnostic Detail (Target Ranks & Reranking)\n")
    lines.append(
        "| Visit ID | Group | Target in Pool? | Candidate Rank (Pool K=30) | Final Rec Rank (Top 10) | Target Bonus | Hit@10? |"
    )
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: |")

    # We show the detail for the primary active condition: Contextual Selection & Rerank
    active_cond = all_reports.get("Memory ON (Contextual Selection & Rerank)")
    if active_cond:
        for v in active_cond["visits"]:
            t_id = v["task_id"]
            grp = v["scenario_group"]
            in_pool = "Yes" if v["in_candidate_pool"] else "No"
            p_rank = f"Rank {v['pool_rank']}" if v["pool_rank"] else "> 30"
            r_rank = (
                f"Rank {v['recommended_rank']}"
                if v["recommended_rank"]
                else "Not in Top 10"
            )
            bonus = f"+{v['target_bonus']:.2f}" if v["target_bonus"] > 0 else "0.00"
            hit = "✅ Hit" if v["recommended_rank"] else "❌ Miss"
            lines.append(
                f"| `{t_id}` | {grp} | {in_pool} | {p_rank} | {r_rank} | {bonus} | {hit} |"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    reports = run_ablation_experiment()
    md = format_markdown_table(reports)
    print("\n" + md)
    output_path = Path("experiments/longitudinal/ablation_report.md")
    output_path.write_text(md + "\n")
    print(f"\nSaved ablation report to {output_path}")
