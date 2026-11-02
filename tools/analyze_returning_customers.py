#!/usr/bin/env python3
"""Reproducible offline analysis script for ASTRA returning-customer evaluation.

Analyzes the 22 paired returning-customer visits (sequence >= 2) from the live
run at `data/eval/hit10-live-20261102/full/`, computes all evaluation metrics,
and generates presentation-ready PNG and SVG visualization charts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def load_returning_data(results_path: Path) -> tuple[list[dict], list[dict], dict]:
    rows = [
        json.loads(line)
        for line in results_path.read_text().splitlines()
        if line.strip()
    ]
    returning = [r for r in rows if r["sequence"] >= 2]
    off_rows = [r for r in returning if r["condition"] == "user_memory_off"]
    on_rows = [r for r in returning if r["condition"] == "user_memory_on"]

    pairs = {}
    for r in returning:
        key = (r["customer_id"], r["task_id"], r["sequence"])
        pairs.setdefault(key, {})[r["condition"]] = r

    return off_rows, on_rows, pairs


def compute_arm_metrics(arm_rows: list[dict]) -> dict[str, Any]:
    n = len(arm_rows)
    if n == 0:
        return {}

    # Target Scoring
    succ = [r for r in arm_rows if r["score"].get("outcome") == "success"]
    n_succ = len(succ)
    succ_rate = n_succ / n

    ranks = [
        r["score"]["target_rank"]
        for r in arm_rows
        if r["score"].get("target_rank") is not None
    ]
    hit1 = sum(1 for r in ranks if r <= 1) / n
    hit3 = sum(1 for r in ranks if r <= 3) / n
    hit5 = sum(1 for r in ranks if r <= 5) / n
    hit10 = sum(1 for r in ranks if r <= 10) / n
    mrr = sum(1.0 / r for r in ranks) / n

    first_turn_succ = (
        sum(1 for r in succ if r["score"].get("first_success_turn") == 1) / n
    )

    turns_succ = [
        r["score"]["first_success_turn"]
        for r in succ
        if r["score"].get("first_success_turn") is not None
    ]
    mttc = sum(turns_succ) / len(turns_succ) if turns_succ else None

    penalized_turns = [r["score"]["penalized_turns"] for r in arm_rows]
    pmttc = sum(penalized_turns) / n

    searches_succ = [
        r["score"]["searches_to_success"]
        for r in succ
        if r["score"].get("searches_to_success") is not None
    ]
    m_searches = sum(searches_succ) / len(searches_succ) if searches_succ else None

    clarif_succ = [
        r["score"]["clarifications_to_success"]
        for r in succ
        if r["score"].get("clarifications_to_success") is not None
    ]
    m_clarif = sum(clarif_succ) / len(clarif_succ) if clarif_succ else 0.0

    # Suitability Scoring
    suit_succ = sum(
        1 for r in arm_rows if r.get("suitability", {}).get("outcome") == "success"
    )
    suit_rate = suit_succ / n

    ndcg1 = (
        sum(
            (
                r.get("suitability", {})
                .get("metrics", {})
                .get("ndcg_first", {})
                .get("1")
                or 0.0
            )
            for r in arm_rows
        )
        / n
    )
    ndcg3 = (
        sum(
            (
                r.get("suitability", {})
                .get("metrics", {})
                .get("ndcg_first", {})
                .get("3")
                or 0.0
            )
            for r in arm_rows
        )
        / n
    )
    ndcg5 = (
        sum(
            (
                r.get("suitability", {})
                .get("metrics", {})
                .get("ndcg_first", {})
                .get("5")
                or 0.0
            )
            for r in arm_rows
        )
        / n
    )

    # Terminations
    terms = {}
    for r in arm_rows:
        t = r["termination"]
        terms[t] = terms.get(t, 0) + 1

    # Resources
    res_list = [r["score"]["resources"] for r in arm_rows]
    agent_turns = sum(res["agent_turns"] for res in res_list) / n
    model_calls = sum(res["model_calls"] for res in res_list) / n
    searches = sum(res["searches"] for res in res_list) / n
    sim_calls = sum(res["simulator_calls"] for res in res_list) / n

    prompt_tokens = sum(res["agent_usage"]["prompt_tokens"] for res in res_list) / n
    cache_hit_tokens = (
        sum(res["agent_usage"]["prompt_cache_hit_tokens"] for res in res_list) / n
    )
    cache_miss_tokens = (
        sum(res["agent_usage"]["prompt_cache_miss_tokens"] for res in res_list) / n
    )
    completion_tokens = (
        sum(res["agent_usage"]["completion_tokens"] for res in res_list) / n
    )
    total_tokens = sum(res["agent_usage"]["total_tokens"] for res in res_list) / n

    sim_prompt_tokens = (
        sum(res["simulator_usage"]["prompt_tokens"] for res in res_list) / n
    )
    sim_comp_tokens = (
        sum(res["simulator_usage"]["completion_tokens"] for res in res_list) / n
    )

    # Compliance
    checked_occ = sum(
        r["disclosed_requirement_compliance"].get("checked_occurrences", 0)
        for r in arm_rows
    )
    passed_occ = sum(
        r["disclosed_requirement_compliance"].get("passed", 0) for r in arm_rows
    )
    violation_occ = sum(
        r["disclosed_requirement_compliance"].get("violations", 0) for r in arm_rows
    )
    unk_occ = sum(
        r["disclosed_requirement_compliance"].get("unknown_required", 0)
        for r in arm_rows
    )
    hard_fails = sum(r["score"]["violations"].get("hard_fail", 0) for r in arm_rows)

    return {
        "n": n,
        "n_succ": n_succ,
        "succ_rate": succ_rate,
        "hit1": hit1,
        "hit3": hit3,
        "hit5": hit5,
        "hit10": hit10,
        "mrr": mrr,
        "first_turn_succ": first_turn_succ,
        "mttc": mttc,
        "pmttc": pmttc,
        "m_searches": m_searches,
        "m_clarif": m_clarif,
        "suit_succ": suit_succ,
        "suit_rate": suit_rate,
        "ndcg1": ndcg1,
        "ndcg3": ndcg3,
        "ndcg5": ndcg5,
        "terms": terms,
        "agent_turns": agent_turns,
        "model_calls": model_calls,
        "searches": searches,
        "sim_calls": sim_calls,
        "prompt_tokens": prompt_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "sim_prompt_tokens": sim_prompt_tokens,
        "sim_comp_tokens": sim_comp_tokens,
        "checked_occ": checked_occ,
        "passed_occ": passed_occ,
        "violation_occ": violation_occ,
        "unk_occ": unk_occ,
        "hard_fails": hard_fails,
    }


def analyze_transitions(pairs: dict) -> dict[str, list]:
    gains = []
    regressions = []
    both_success = []
    both_failure = []

    for key, pair in sorted(pairs.items()):
        off_r = pair["user_memory_off"]
        on_r = pair["user_memory_on"]

        off_succ = off_r["score"].get("outcome") == "success"
        on_succ = on_r["score"].get("outcome") == "success"

        item = {
            "key": key,
            "customer_id": key[0],
            "task_id": key[1],
            "sequence": key[2],
            "off_rank": off_r["score"].get("target_rank"),
            "on_rank": on_r["score"].get("target_rank"),
            "off_turn": off_r["score"].get("first_success_turn"),
            "on_turn": on_r["score"].get("first_success_turn"),
            "injected": on_r["user_memory"].get("injected_ids", []),
        }

        if not off_succ and on_succ:
            gains.append(item)
        elif off_succ and not on_succ:
            regressions.append(item)
        elif off_succ and on_succ:
            both_success.append(item)
        else:
            both_failure.append(item)

    return {
        "gains": gains,
        "regressions": regressions,
        "both_success": both_success,
        "both_failure": both_failure,
    }


def plot_charts(off_m: dict, on_m: dict, trans: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use(
        "seaborn-v0_8-whitegrid"
        if "seaborn-v0_8-whitegrid" in plt.style.available
        else "default"
    )
    plt.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "DejaVu Sans"]
    plt.rcParams["axes.edgecolor"] = "#cccccc"
    plt.rcParams["axes.linewidth"] = 0.8

    color_off = "#64748b"  # Slate Gray
    color_on = "#2563eb"  # Vibrant Royal Blue
    color_gain = "#16a34a"  # Emerald Green
    color_loss = "#dc2626"  # Crimson Red

    # 1. Hit@K Grouped Bar Chart
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
    ks = ["Hit@1", "Hit@3", "Hit@5", "Hit@10"]
    x = [0, 1, 2, 3]
    w = 0.32

    off_vals = [
        off_m["hit1"] * 100,
        off_m["hit3"] * 100,
        off_m["hit5"] * 100,
        off_m["hit10"] * 100,
    ]
    on_vals = [
        on_m["hit1"] * 100,
        on_m["hit3"] * 100,
        on_m["hit5"] * 100,
        on_m["hit10"] * 100,
    ]

    r1 = ax.bar(
        [i - w / 2 for i in x],
        off_vals,
        width=w,
        label="Memory OFF",
        color=color_off,
        alpha=0.9,
        edgecolor="none",
    )
    r2 = ax.bar(
        [i + w / 2 for i in x],
        on_vals,
        width=w,
        label="Memory ON",
        color=color_on,
        alpha=0.95,
        edgecolor="none",
    )

    ax.set_ylabel(
        "Recommendation Success Rate (%)", fontsize=11, fontweight="bold", labelpad=8
    )
    ax.set_title(
        "ASTRA Returning-Customer Recommendation Accuracy (N=22 Pairs)",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(ks, fontsize=11, fontweight="bold")
    ax.set_ylim(0, 75)
    ax.legend(frameon=True, facecolor="white", edgecolor="#e2e8f0", fontsize=10)

    # Bar labels
    for bar in r1:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 1.2,
            f"{yval:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#475569",
        )
    for bar in r2:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 1.2,
            f"{yval:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color=color_on,
        )

    plt.tight_layout()
    fig.savefig(output_dir / "hit_at_k_comparison.png", dpi=300)
    fig.savefig(output_dir / "hit_at_k_comparison.svg")
    plt.close(fig)

    # 2. Ranking Quality (MRR and NDCG)
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
    metrics = ["MRR", "NDCG@1", "NDCG@3", "NDCG@5"]
    x = [0, 1, 2, 3]

    off_ranks = [off_m["mrr"], off_m["ndcg1"], off_m["ndcg3"], off_m["ndcg5"]]
    on_ranks = [on_m["mrr"], on_m["ndcg1"], on_m["ndcg3"], on_m["ndcg5"]]

    r1 = ax.bar(
        [i - w / 2 for i in x],
        off_ranks,
        width=w,
        label="Memory OFF",
        color=color_off,
        alpha=0.9,
    )
    r2 = ax.bar(
        [i + w / 2 for i in x],
        on_ranks,
        width=w,
        label="Memory ON",
        color=color_on,
        alpha=0.95,
    )

    ax.set_ylabel("Score (0.0 – 1.0)", fontsize=11, fontweight="bold", labelpad=8)
    ax.set_title(
        "Target Ranking Quality & Suitability NDCG (Returning Visits)",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=11, fontweight="bold")
    ax.set_ylim(0, 0.75)
    ax.legend(frameon=True, facecolor="white", edgecolor="#e2e8f0", fontsize=10)

    for bar in r1:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 0.015,
            f"{yval:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#475569",
        )
    for bar in r2:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 0.015,
            f"{yval:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color=color_on,
        )

    plt.tight_layout()
    fig.savefig(output_dir / "ranking_quality_comparison.png", dpi=300)
    fig.savefig(output_dir / "ranking_quality_comparison.svg")
    plt.close(fig)

    # 3. Task Efficiency Comparison
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 4.0), dpi=300)

    # Subplot 1: First-Turn Success Rate (%)
    ax1.bar(
        [0 - w / 2],
        [off_m["first_turn_succ"] * 100],
        width=w,
        color=color_off,
        label="Memory OFF",
    )
    ax1.bar(
        [0 + w / 2],
        [on_m["first_turn_succ"] * 100],
        width=w,
        color=color_on,
        label="Memory ON",
    )
    ax1.set_title("First-Turn Success Rate", fontsize=11, fontweight="bold", pad=8)
    ax1.set_ylabel("Percentage (%)", fontsize=10, fontweight="bold")
    ax1.set_xticks([0])
    ax1.set_xticklabels(["Turn 1 Success"], fontsize=10)
    ax1.set_ylim(0, 75)
    ax1.text(
        -w / 2,
        off_m["first_turn_succ"] * 100 + 1.5,
        f"{off_m['first_turn_succ'] * 100:.1f}%",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    ax1.text(
        w / 2,
        on_m["first_turn_succ"] * 100 + 1.5,
        f"{on_m['first_turn_succ'] * 100:.1f}%",
        ha="center",
        fontsize=9,
        fontweight="bold",
        color=color_on,
    )
    ax1.legend(
        loc="upper left",
        frameon=True,
        facecolor="white",
        edgecolor="#e2e8f0",
        fontsize=9,
    )

    # Subplot 2: Penalized MTTC (lower is better)
    ax2.bar([0 - w / 2], [off_m["pmttc"]], width=w, color=color_off)
    ax2.bar([0 + w / 2], [on_m["pmttc"]], width=w, color=color_on)
    ax2.set_title(
        "Penalized MTTC (Lower is Better)", fontsize=11, fontweight="bold", pad=8
    )
    ax2.set_ylabel("Turns to Success (Failure = 7)", fontsize=10, fontweight="bold")
    ax2.set_xticks([0])
    ax2.set_xticklabels(["Penalized MTTC"], fontsize=10)
    ax2.set_ylim(0, 5.5)
    ax2.text(
        -w / 2,
        off_m["pmttc"] + 0.1,
        f"{off_m['pmttc']:.2f}",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    ax2.text(
        w / 2,
        on_m["pmttc"] + 0.1,
        f"{on_m['pmttc']:.2f}",
        ha="center",
        fontsize=9,
        fontweight="bold",
        color=color_on,
    )

    plt.suptitle(
        "ASTRA Task Efficiency (Returning Customers, N=22 Pairs)",
        fontsize=12,
        fontweight="bold",
        y=1.02,
    )
    plt.tight_layout()
    fig.savefig(output_dir / "task_efficiency_comparison.png", dpi=300)
    fig.savefig(output_dir / "task_efficiency_comparison.svg")
    plt.close(fig)

    # 4. Paired Transition Breakdown
    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=300)
    categories = [
        "Memory Gains\n(Fail -> Success)",
        "Both Succeeded\n(Maintained)",
        "Both Failed\n(Unresolved)",
        "Memory Regressions\n(Success -> Fail)",
    ]
    counts = [
        len(trans["gains"]),
        len(trans["both_success"]),
        len(trans["both_failure"]),
        len(trans["regressions"]),
    ]
    colors = [color_gain, "#3b82f6", "#94a3b8", color_loss]

    y_pos = range(len(categories))
    bars = ax.barh(y_pos, counts, color=colors, height=0.55, edgecolor="none")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories, fontsize=10, fontweight="bold")
    ax.invert_yaxis()  # Top-down
    ax.set_xlabel(
        "Number of Paired Returning Visits (Total = 22)",
        fontsize=10,
        fontweight="bold",
        labelpad=8,
    )
    ax.set_title(
        "Paired Outcome Transitions (OFF -> ON)", fontsize=12, fontweight="bold", pad=12
    )
    ax.set_xlim(0, 13)

    for bar in bars:
        w_val = bar.get_width()
        pct = (w_val / 22) * 100
        ax.text(
            w_val + 0.3,
            bar.get_y() + bar.get_height() / 2,
            f"{w_val} ({pct:.1f}%)",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="#1e293b",
        )

    plt.tight_layout()
    fig.savefig(output_dir / "paired_transition_breakdown.png", dpi=300)
    fig.savefig(output_dir / "paired_transition_breakdown.svg")
    plt.close(fig)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Reproduce returning-customer evaluation metrics and charts from live evaluation artifacts."
    )
    root = Path(__file__).resolve().parent.parent
    default_results = root / "data/eval/hit10-live-20261102/full/results.jsonl"
    default_charts = root / "docs/reports/charts"

    parser.add_argument(
        "--results",
        type=Path,
        default=default_results,
        help=f"Path to results.jsonl (default: {default_results})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_charts,
        help=f"Output directory for charts (default: {default_charts})",
    )
    args = parser.parse_args()

    if not args.results.exists():
        print(f"Error: Evaluation results file not found at: {args.results}")
        print(
            "Note: The evaluation run artifacts reside in the local experimental directory"
        )
        print(
            "`data/eval/hit10-live-20261102/full/results.jsonl`. If you have stored the run results"
        )
        print("at another path, pass --results <path/to/results.jsonl>.")
        sys.exit(1)

    off_rows, on_rows, pairs = load_returning_data(args.results)
    off_m = compute_arm_metrics(off_rows)
    on_m = compute_arm_metrics(on_rows)
    trans = analyze_transitions(pairs)

    plot_charts(off_m, on_m, trans, args.output_dir)

    print("Offline Analysis Complete!")
    print(
        f"Returning visits analyzed: {len(off_rows)} OFF, {len(on_rows)} ON ({len(pairs)} matched pairs)"
    )
    print(
        f"Hit@1:  {off_m['hit1'] * 100:.1f}% OFF -> {on_m['hit1'] * 100:.1f}% ON (+{(on_m['hit1'] - off_m['hit1']) * 100:.1f} pp)"
    )
    print(
        f"Hit@10: {off_m['hit10'] * 100:.1f}% OFF -> {on_m['hit10'] * 100:.1f}% ON (+{(on_m['hit10'] - off_m['hit10']) * 100:.1f} pp)"
    )
    print(
        f"MRR:    {off_m['mrr']:.4f} OFF -> {on_m['mrr']:.4f} ON (+{on_m['mrr'] - off_m['mrr']:.4f})"
    )
    print(f"Charts written to: {args.output_dir}")


if __name__ == "__main__":
    main()
