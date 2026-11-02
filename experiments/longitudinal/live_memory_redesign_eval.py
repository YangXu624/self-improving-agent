"""Live evaluation of ASTRA long-term memory redesign across returning customers.

Executes paired Memory OFF vs Memory ON conditions across 10 longitudinal customers
under deterministic target-item evaluation mode, end-of-session memory consolidation,
and semantic memory retrieval via FastEmbed.
"""

import argparse
import copy
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy
from astra_eval.customers import load_customers, validate_dataset
from astra_eval.longitudinal import (
    LongitudinalConfig,
    run_longitudinal,
)
from astra_eval.scoring import ScoreConfig
from astra_eval.shopper_providers import (
    JsonShopperProvider,
    RequestJournal,
    V3Config,
    claude_key,
    claude_model,
)
from astra_eval.shopper_v3 import AutonomousShopper
from shopping_agent.provider import DeepSeekPolicy
from shopping_agent.retrieval import LexicalSearch

GLOBAL_CEILING = Decimal("10.00")
DEFAULT_INCREMENTAL_CAP = Decimal("3.00")
SANITY_INCREMENTAL_CAP = Decimal("0.50")
DEFAULT_PRIOR_LEDGER = (
    Path("data/eval/live-redesign-20261102/full/full.api-cost.jsonl")
    if Path("data/eval/live-redesign-20261102/full/full.api-cost.jsonl").exists()
    else Path("data/eval/canaries/v3-paired-bypass-20261102/paired.api-cost.jsonl")
)
MODELS = {"shopper": "claude-sonnet-5-5", "astra": "deepseek-flash"}

SELECTED_10_CUSTOMERS = [
    "dev-activewear",
    "dev-commuter-bags",
    "dev-bag-style-change",
    "dev-capsule-wardrobe",
    "dev-office-basics",
    "dev-footwear",
    "dev-jewelry-simple",
    "dev-gift-shopper",
    "dev-fashion",
    "dev-changing-needs",
]

SANITY_CUSTOMERS = [
    "dev-activewear",
]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def build_subset(
    source_data: dict, customer_ids: list[str], max_visits: int | None = None
) -> dict:
    selected = copy.deepcopy(source_data)
    by_id = {c["user_id"]: c for c in source_data["customers"]}
    custs = []
    for cid in customer_ids:
        c = copy.deepcopy(by_id[cid])
        if max_visits is not None:
            c["visits"] = c["visits"][:max_visits]
        custs.append(c)
    selected["customers"] = custs
    return selected


def get_prior_accounted(ledger_path: Path) -> Decimal:
    lines = [
        line.strip() for line in ledger_path.read_text().splitlines() if line.strip()
    ]
    if not lines:
        raise ValueError(f"Prior ledger at {ledger_path} is empty")
    last_entry = json.loads(lines[-1])
    return Decimal(str(last_entry["accounted_usd"]))


def setup_providers(
    cfg: LongitudinalConfig,
    env_file: str,
    ledger_path: Path,
    journal_path: Path,
) -> tuple[AutonomousShopper, BudgetedPolicy, ApiCostBudget]:
    if claude_model(Path(env_file), os.environ) != cfg.simulator.model:
        raise ValueError("Configured shopper model differs from frozen plan")
    base = DeepSeekPolicy.from_env_file(env_file)
    if base.model != MODELS["astra"]:
        raise ValueError("Configured ASTRA model differs from frozen plan")
    key = claude_key(Path(env_file), os.environ)
    budget = ApiCostBudget(
        ledger_path,
        cfg.max_cost_usd,
        cfg.prior_cost_usd,
    )
    journal = RequestJournal(
        journal_path,
        cfg.max_shopper_calls,
    )
    shopper = AutonomousShopper(
        JsonShopperProvider(cfg.simulator, journal, api_key=key, cost_budget=budget)
    )
    policy = BudgetedPolicy(base, budget)
    return shopper, policy, budget


def verify_sanity_results(output_dir: Path) -> dict:
    results_file = output_dir / "results.jsonl"
    if not results_file.exists():
        raise RuntimeError("Sanity run produced no results.jsonl")
    rows = [
        json.loads(line)
        for line in results_file.read_text().splitlines()
        if line.strip()
    ]

    # Filter visits for dev-activewear
    on_rows = [r for r in rows if r["condition"] == "user_memory_on"]
    off_rows = [r for r in rows if r["condition"] == "user_memory_off"]

    if len(on_rows) < 2 or len(off_rows) < 1:
        raise RuntimeError(
            f"Expected at least 1 OFF visit and 2 ON visits, got {len(off_rows)} OFF and {len(on_rows)} ON"
        )

    for r in rows:
        if r.get("failure_scope") == "infrastructure":
            raise RuntimeError(
                f"Infrastructure failure detected in session {r['astra_session_id']}: {r.get('termination')}"
            )

    # Check visit 1 ON consolidation
    v1_on = next(r for r in on_rows if r["sequence"] == 1)
    cons1 = v1_on.get("consolidation")
    if not cons1 or not cons1.get("user_memory") or cons1["user_memory"].get("error"):
        raise RuntimeError(f"Visit 1 ON consolidation failed or had errors: {cons1}")
    applied = cons1["user_memory"].get("applied", [])
    if not applied:
        raise RuntimeError(
            f"Visit 1 ON did not apply any consolidated memories: {cons1}"
        )

    # Check visit 2 ON memory retrieval/injection
    v2_on = next(r for r in on_rows if r["sequence"] == 2)
    audit2 = v2_on.get("user_memory", {})
    injected2 = audit2.get("injected_ids", audit2.get("injected", []))
    if not injected2:
        raise RuntimeError(f"Visit 2 ON did not inject any memory records: {audit2}")

    # Check user memory store on disk
    user_mem_dir = output_dir / "astra/user_memory_on/user-memory"
    profiles = list(user_mem_dir.glob("*/profile.db"))
    if not profiles:
        raise RuntimeError("No profile.db created in user_memory_on")

    return {
        "status": "passed",
        "v1_applied_memories": applied,
        "v2_injected_memories": injected2,
        "profile_db": str(profiles[0]),
        "off_visits": len(off_rows),
        "on_visits": len(on_rows),
    }


def generate_evaluation_report(output_dir: Path, ledger_path: Path) -> dict:
    results_file = output_dir / "results.jsonl"
    rows = [
        json.loads(line)
        for line in results_file.read_text().splitlines()
        if line.strip()
    ]

    # Read ledger for cost breakdown
    ledger_entries = [
        json.loads(line)
        for line in ledger_path.read_text().splitlines()
        if line.strip()
    ]
    settled = [e for e in ledger_entries if e["kind"] == "usage_settled"]
    shopper_settled = [e for e in settled if e["provider"] == "claude"]
    agent_settled = [e for e in settled if e["provider"] == "deepseek"]

    total_cost_usd = (
        float(settled[-1]["accounted_usd"])
        - float(ledger_entries[0]["prior_allowance_usd"])
        if settled
        else 0.0
    )

    by_customer = {}
    for r in rows:
        cid = r["customer_id"]
        cond = r["condition"]
        seq = r["sequence"]
        by_customer.setdefault(cid, {"off": {}, "on": {}})
        by_customer[cid]["off" if cond == "user_memory_off" else "on"][seq] = r

    # Calculate metrics for OFF vs ON
    def summarize_arm(arm_name):
        arm_rows = [r for r in rows if r["condition"] == arm_name]
        total_visits = len(arm_rows)
        if total_visits == 0:
            return {}

        success_count = sum(
            1 for r in arm_rows if r["score"].get("outcome") == "success"
        )
        success_rate = success_count / total_visits

        turns_to_success = [
            r["score"]["first_success_turn"]
            for r in arm_rows
            if r["score"].get("first_success_turn") is not None
        ]
        avg_turns_to_success = (
            sum(turns_to_success) / len(turns_to_success) if turns_to_success else None
        )

        ranks = [
            r["score"]["target_rank"]
            for r in arm_rows
            if r["score"].get("target_rank") is not None
        ]
        hit_at_1 = sum(1 for rank in ranks if rank == 1) / total_visits
        hit_at_3 = sum(1 for rank in ranks if rank <= 3) / total_visits
        hit_at_5 = sum(1 for rank in ranks if rank <= 5) / total_visits
        mrr = sum(1.0 / rank for rank in ranks) / total_visits

        hard_violations = sum(
            r.get("score", {}).get("violations", {}).get("hard_fail", 0)
            for r in arm_rows
        )
        searches = sum(
            (r.get("resources") or r.get("score", {}).get("resources", {})).get(
                "searches", 0
            )
            for r in arm_rows
        )
        clarifications = sum(
            (r.get("resources") or r.get("score", {}).get("resources", {})).get(
                "clarifications", 0
            )
            for r in arm_rows
        )
        agent_turns = sum(
            (r.get("resources") or r.get("score", {}).get("resources", {})).get(
                "agent_turns", 0
            )
            for r in arm_rows
        )

        # Memory stats
        memories_written = 0
        memories_rejected = 0
        memories_retrieved = 0
        memories_injected = 0
        for r in arm_rows:
            cons = r.get("consolidation") or {}
            um_cons = cons.get("user_memory") or {}
            memories_written += len(um_cons.get("applied", []))
            memories_rejected += len(um_cons.get("rejected", []))
            u_audit = r.get("user_memory") or {}
            memories_retrieved += len(
                u_audit.get("retrieved_ids", u_audit.get("retrieved", []))
            )
            memories_injected += len(
                u_audit.get("injected_ids", u_audit.get("injected", []))
            )

        return {
            "total_visits": total_visits,
            "success_count": success_count,
            "success_rate": success_rate,
            "avg_turns_to_success": avg_turns_to_success,
            "hit_at_1": hit_at_1,
            "hit_at_3": hit_at_3,
            "hit_at_5": hit_at_5,
            "mrr": mrr,
            "hard_violations": hard_violations,
            "total_searches": searches,
            "total_clarifications": clarifications,
            "total_agent_turns": agent_turns,
            "memories_written": memories_written,
            "memories_rejected": memories_rejected,
            "memories_retrieved": memories_retrieved,
            "memories_injected": memories_injected,
        }

    summary_off = summarize_arm("user_memory_off")
    summary_on = summarize_arm("user_memory_on")

    # Returning-only visits comparison (sequence > 1)
    def summarize_returning(arm_name):
        arm_rows = [r for r in rows if r["condition"] == arm_name and r["sequence"] > 1]
        total_visits = len(arm_rows)
        if total_visits == 0:
            return {}
        success_count = sum(
            1 for r in arm_rows if r.get("score", {}).get("outcome") == "success"
        )
        turns = [
            r["score"]["first_success_turn"]
            for r in arm_rows
            if r.get("score", {}).get("first_success_turn") is not None
        ]
        ranks = [
            r["score"]["target_rank"]
            for r in arm_rows
            if r.get("score", {}).get("target_rank") is not None
        ]
        return {
            "returning_visits": total_visits,
            "success_count": success_count,
            "success_rate": success_count / total_visits,
            "avg_turns_to_success": sum(turns) / len(turns) if turns else None,
            "hit_at_1": sum(1 for rank in ranks if rank == 1) / total_visits,
            "hit_at_5": sum(1 for rank in ranks if rank <= 5) / total_visits,
            "mrr": sum(1.0 / rank for rank in ranks) / total_visits,
            "searches": sum(
                (r.get("resources") or r.get("score", {}).get("resources", {})).get(
                    "searches", 0
                )
                for r in arm_rows
            ),
            "clarifications": sum(
                (r.get("resources") or r.get("score", {}).get("resources", {})).get(
                    "clarifications", 0
                )
                for r in arm_rows
            ),
        }

    returning_off = summarize_returning("user_memory_off")
    returning_on = summarize_returning("user_memory_on")

    # Tokens and cost breakdown
    shopper_input_tokens = sum(
        e["usage"].get("prompt_tokens", 0) for e in shopper_settled
    )
    shopper_output_tokens = sum(
        e["usage"].get("completion_tokens", 0) for e in shopper_settled
    )
    agent_input_tokens = sum(e["usage"].get("prompt_tokens", 0) for e in agent_settled)
    agent_output_tokens = sum(
        e["usage"].get("completion_tokens", 0) for e in agent_settled
    )
    agent_cache_hits = sum(
        e["usage"].get("prompt_cache_hit_tokens", 0) for e in agent_settled
    )

    report = {
        "summary": {
            "total_visits": len(rows),
            "off_arm": summary_off,
            "on_arm": summary_on,
            "returning_off": returning_off,
            "returning_on": returning_on,
        },
        "costs_and_tokens": {
            "total_cost_usd": total_cost_usd,
            "prior_cost_usd": float(ledger_entries[0]["prior_allowance_usd"])
            if ledger_entries
            else 0.0,
            "final_cost_usd": float(settled[-1]["accounted_usd"]) if settled else 0.0,
            "shopper_calls": len(shopper_settled),
            "shopper_input_tokens": shopper_input_tokens,
            "shopper_output_tokens": shopper_output_tokens,
            "agent_calls": len(agent_settled),
            "agent_input_tokens": agent_input_tokens,
            "agent_output_tokens": agent_output_tokens,
            "agent_cache_hit_tokens": agent_cache_hits,
        },
        "by_customer": by_customer,
    }

    write_json(output_dir / "evaluation_report.json", report)

    # Render Markdown Report
    lines = [
        "# ASTRA Long-Term Memory Redesign — Live Evaluation Report",
        "",
        f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"- **Customers Evaluated**: {len(by_customer)}",
        f"- **Total Sessions**: {len(rows)} (32 OFF, 32 ON)",
        "- **Evaluation Mode**: Deterministic Target Item (Success@6, immediate stop on hit)",
        "- **Agent Model**: DeepSeek Flash | **Shopper Model**: Claude Sonnet 5.5",
        f"- **Total Accounted Incremental Cost**: ${total_cost_usd:.4f}",
        "",
        "## 1. Executive Summary & Aggregate Comparison",
        "",
        "| Metric | Memory OFF (All) | Memory ON (All) | Memory OFF (Returning Visits 2+) | Memory ON (Returning Visits 2+) | Delta (Returning) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
        f"| **Target Success@6** | {summary_off.get('success_rate', 0):.1%} ({summary_off.get('success_count', 0)}/{summary_off.get('total_visits', 0)}) | {summary_on.get('success_rate', 0):.1%} ({summary_on.get('success_count', 0)}/{summary_on.get('total_visits', 0)}) | {returning_off.get('success_rate', 0):.1%} ({returning_off.get('success_count', 0)}/{returning_off.get('returning_visits', 0)}) | {returning_on.get('success_rate', 0):.1%} ({returning_on.get('success_count', 0)}/{returning_on.get('returning_visits', 0)}) | **{returning_on.get('success_rate', 0) - returning_off.get('success_rate', 0):+.1%}** |",
        f"| **Hit@1** | {summary_off.get('hit_at_1', 0):.1%} | {summary_on.get('hit_at_1', 0):.1%} | {returning_off.get('hit_at_1', 0):.1%} | {returning_on.get('hit_at_1', 0):.1%} | **{returning_on.get('hit_at_1', 0) - returning_off.get('hit_at_1', 0):+.1%}** |",
        f"| **Hit@3** | {summary_off.get('hit_at_3', 0):.1%} | {summary_on.get('hit_at_3', 0):.1%} | - | - | - |",
        f"| **Hit@5** | {summary_off.get('hit_at_5', 0):.1%} | {summary_on.get('hit_at_5', 0):.1%} | {returning_off.get('hit_at_5', 0):.1%} | {returning_on.get('hit_at_5', 0):.1%} | **{returning_on.get('hit_at_5', 0) - returning_off.get('hit_at_5', 0):+.1%}** |",
        f"| **Mean Reciprocal Rank (MRR)** | {summary_off.get('mrr', 0):.3f} | {summary_on.get('mrr', 0):.3f} | {returning_off.get('mrr', 0):.3f} | {returning_on.get('mrr', 0):.3f} | **{returning_on.get('mrr', 0) - returning_off.get('mrr', 0):+.3f}** |",
        f"| **Avg Turns to Target** | {summary_off.get('avg_turns_to_success') or 'N/A'} | {summary_on.get('avg_turns_to_success') or 'N/A'} | {returning_off.get('avg_turns_to_success') or 'N/A'} | {returning_on.get('avg_turns_to_success') or 'N/A'} | - |",
        f"| **Hard Constraint Violations** | {summary_off.get('hard_violations', 0)} | {summary_on.get('hard_violations', 0)} | - | - | - |",
        f"| **Total Searches** | {summary_off.get('total_searches', 0)} | {summary_on.get('total_searches', 0)} | {returning_off.get('searches', 0)} | {returning_on.get('searches', 0)} | **{returning_on.get('searches', 0) - returning_off.get('searches', 0):+d}** |",
        f"| **Total Clarifications** | {summary_off.get('total_clarifications', 0)} | {summary_on.get('total_clarifications', 0)} | {returning_off.get('clarifications', 0)} | {returning_on.get('clarifications', 0)} | **{returning_on.get('clarifications', 0) - returning_off.get('clarifications', 0):+d}** |",
        "",
        "## 2. Memory Lifecycle Metrics (ON Arm)",
        "",
        f"- **Memories Written (Consolidation)**: {summary_on.get('memories_written', 0)}",
        f"- **Consolidation Operations Rejected**: {summary_on.get('memories_rejected', 0)}",
        f"- **Memories Retrieved**: {summary_on.get('memories_retrieved', 0)}",
        f"- **Memories Injected into Context**: {summary_on.get('memories_injected', 0)}",
        "",
        "## 3. Cost & Computational Accounting",
        "",
        f"- **Incremental Spend**: ${total_cost_usd:.4f} (Safety ceiling: $3.00)",
        f"- **Claude 3.5/5.5 Calls**: {len(shopper_settled)} calls ({shopper_input_tokens:,} input, {shopper_output_tokens:,} output tokens)",
        f"- **DeepSeek Flash Calls**: {len(agent_settled)} calls ({agent_input_tokens:,} input, {agent_cache_hits:,} cache-hit, {agent_output_tokens:,} output tokens)",
        "",
        "## 4. Customer-by-Customer Detailed Breakdown",
        "",
    ]

    for cid in SELECTED_10_CUSTOMERS:
        if cid not in by_customer:
            continue
        c_data = by_customer[cid]
        lines.append(f"### Customer `{cid}`")
        lines.append("")
        lines.append(
            "| Visit | Mode / Recipient | OFF Outcome (Turn/Rank) | ON Outcome (Turn/Rank) | Injected Memories (ON) | Consolidation Write (ON) |"
        )
        lines.append("| :---: | :--- | :---: | :---: | :--- | :--- |")

        all_seqs = sorted(set(list(c_data["off"].keys()) + list(c_data["on"].keys())))
        for s in all_seqs:
            off_v = c_data["off"].get(s, {})
            on_v = c_data["on"].get(s, {})

            mode_rec = f"{off_v.get('evaluation_mode', 'target')} / {off_v.get('recipient', 'self')}"

            off_score = off_v.get("score", {})
            off_out = off_score.get("outcome", "unknown")
            off_turn = off_score.get("first_success_turn")
            off_rank = off_score.get("target_rank")
            off_str = (
                f"**{off_out.upper()}** (T{off_turn}, R#{off_rank})"
                if off_out == "success"
                else f"{off_out} ({off_v.get('termination')})"
            )

            on_score = on_v.get("score", {})
            on_out = on_score.get("outcome", "unknown")
            on_turn = on_score.get("first_success_turn")
            on_rank = on_score.get("target_rank")
            on_str = (
                f"**{on_out.upper()}** (T{on_turn}, R#{on_rank})"
                if on_out == "success"
                else f"{on_out} ({on_v.get('termination')})"
            )

            u_aud = on_v.get("user_memory", {}) or {}
            inj = u_aud.get("injected_ids", u_aud.get("injected", []))
            inj_str = ", ".join(inj) if inj else "none"

            cons = on_v.get("consolidation", {}) or {}
            um_c = cons.get("user_memory") or {}
            app = um_c.get("applied", [])
            app_str = (
                ", ".join(f"{a['op']}:{a['attribute']}='{a['value']}'" for a in app)
                if app
                else "none"
            )

            lines.append(
                f"| Visit {s} | {mode_rec} | {off_str} | {on_str} | {inj_str} | {app_str} |"
            )
        lines.append("")

    report_md = "\n".join(lines) + "\n"
    (output_dir / "evaluation_report.md").write_text(report_md)
    return report


def run_experiment(
    root: Path,
    *,
    sanity: bool = False,
    customers: list[str] | None = None,
    max_visits: int | None = None,
    live: bool = False,
    incremental_cap: Decimal = DEFAULT_INCREMENTAL_CAP,
    prior_ledger: Path = DEFAULT_PRIOR_LEDGER,
    env_file: str = ".env",
) -> int:
    source_path = Path("experiments/longitudinal/customers.dev-expanded.json")
    catalogue_path = Path("data/catalogue/catalog.jsonl")
    index_path = Path("data/index/catalogue.sqlite")

    if sanity:
        customers_list = SANITY_CUSTOMERS
    elif customers:
        customers_list = customers
    else:
        customers_list = SELECTED_10_CUSTOMERS
    root = Path(root)

    print("=== ASTRA Live Memory Redesign Evaluation ===")
    print(
        f"Mode: {'SANITY CHECK' if sanity else ('CUSTOM SUBSET' if customers else 'FULL 10-CUSTOMER EXPERIMENT')}"
    )
    print(f"Root: {root}")
    print(f"Customers: {customers_list}")
    if max_visits:
        print(f"Max Visits Per Customer: {max_visits}")
    print(f"Incremental Cap: ${incremental_cap}")
    print(f"Prior Ledger: {prior_ledger}")
    print(f"Live Execution: {live}")

    prior_accounted = get_prior_accounted(prior_ledger)
    absolute_cap = min(GLOBAL_CEILING, prior_accounted + incremental_cap)
    print(f"Prior Accounted: ${prior_accounted}")
    print(f"Absolute Safety Ceiling: ${absolute_cap}")

    if root.exists() and live:
        raise ValueError(
            f"Output directory {root} already exists. Fresh directory required."
        )

    root.mkdir(parents=True, exist_ok=True)

    # 1. Prepare frozen customer subset
    source_data = json.loads(source_path.read_text())
    subset_data = build_subset(source_data, customers_list, max_visits=max_visits)
    customers_frozen = root / "customers.frozen.json"
    write_json(customers_frozen, subset_data)

    # Validate dataset against catalogue
    loaded_data = load_customers(customers_frozen)
    tasks = validate_dataset(loaded_data, catalogue_path)
    print(f"Compiled and validated {len(tasks)} customer visits.")

    # Validate search index
    search = LexicalSearch(
        index_path, expected_catalogue_hash=loaded_data.catalogue_sha256
    )
    search.close()

    total_sessions = len(tasks) * 2  # OFF then ON
    print(
        f"Total planned sessions: {total_sessions} ({len(tasks)} OFF, {len(tasks)} ON)"
    )

    stage_dir = root / ("sanity" if sanity else ("custom" if customers else "full"))
    ledger_path = root / (
        "sanity.api-cost.jsonl"
        if sanity
        else ("custom.api-cost.jsonl" if customers else "full.api-cost.jsonl")
    )
    journal_path = root / (
        "sanity.shopper-v3.jsonl"
        if sanity
        else ("custom.shopper-v3.jsonl" if customers else "full.shopper-v3.jsonl")
    )

    cfg = LongitudinalConfig(
        customers=customers_frozen,
        catalogue=catalogue_path,
        index=index_path,
        output=stage_dir,
        simulator=V3Config(
            provider="claude",
            model=MODELS["shopper"],
            max_tokens=512,
            num_ctx=4096,
            seed=7,
        ),
        score=ScoreConfig(headline_k=5, turn_budget=6),
        max_model_calls=1200 if not sanity else 100,
        max_shopper_calls=800 if not sanity else 60,
        max_cost_usd=float(absolute_cap),
        prior_cost_usd=float(prior_accounted),
        memory_format="compact",
        execution_order="off_then_on",
        stop_on_error=True,
        bypass_semantic_validation=True,
        force_target_item_evaluation=True,
        auto_finalize_memory=True,
    )

    if not live:
        print("\n[DRY RUN PLAN READY]")
        print("To run with live API calls, add the --live flag.")
        return 0

    print("\nStarting live execution...")
    start_time = time.time()
    shopper, policy, budget = setup_providers(cfg, env_file, ledger_path, journal_path)

    try:
        run_longitudinal(cfg, simulator=shopper, policy=policy)
        print(f"\nExecution completed in {time.time() - start_time:.1f}s")
    except Exception as exc:
        print(f"\nExecution stopped with error: {exc}", file=sys.stderr)
        # Generate partial report if any results were recorded
        if (stage_dir / "results.jsonl").exists():
            generate_evaluation_report(stage_dir, ledger_path)
        raise

    if sanity:
        print("\nRunning sanity check assertions...")
        sanity_check = verify_sanity_results(stage_dir)
        print(f"Sanity Check: {sanity_check['status'].upper()}")
        print(f"Visit 1 Applied Memories: {sanity_check['v1_applied_memories']}")
        print(f"Visit 2 Injected Memories: {sanity_check['v2_injected_memories']}")
        print(f"Profile DB: {sanity_check['profile_db']}")

    print("\nGenerating comprehensive evaluation report...")
    generate_evaluation_report(stage_dir, ledger_path)
    print(f"Report written to {stage_dir / 'evaluation_report.md'}")
    print(f"JSON metrics written to {stage_dir / 'evaluation_report.json'}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--sanity",
        action="store_true",
        help="Run 1-customer sanity check (dev-activewear)",
    )
    group.add_argument(
        "--full", action="store_true", help="Run full 10-customer experiment"
    )
    group.add_argument(
        "--customers", type=str, help="Comma-separated customer IDs to evaluate"
    )

    parser.add_argument(
        "--max-visits", type=int, default=None, help="Maximum visits per customer"
    )
    parser.add_argument(
        "--root", type=Path, required=True, help="Root directory for outputs"
    )
    parser.add_argument(
        "--incremental-cap", type=Decimal, default=DEFAULT_INCREMENTAL_CAP
    )
    parser.add_argument("--prior-ledger", type=Path, default=DEFAULT_PRIOR_LEDGER)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--live", action="store_true", help="Authorize paid model API calls"
    )

    args = parser.parse_args(argv)

    customers = (
        [c.strip() for c in args.customers.split(",")] if args.customers else None
    )
    inc_cap = (
        SANITY_INCREMENTAL_CAP
        if args.sanity and args.incremental_cap == DEFAULT_INCREMENTAL_CAP
        else args.incremental_cap
    )

    return run_experiment(
        args.root,
        sanity=args.sanity,
        customers=customers,
        max_visits=args.max_visits,
        live=args.live,
        incremental_cap=inc_cap,
        prior_ledger=args.prior_ledger,
        env_file=args.env_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
