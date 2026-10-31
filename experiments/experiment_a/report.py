"""Reproducible Experiment A report: prespecified strata and paired profile comparisons.

Reads a verified frozen directory plus an offline result and/or a completed live run;
never calls a provider and never re-scores with different rules. Output is deterministic
(sorted keys, fixed bootstrap seed), so identical inputs give a byte-identical report.
Every rate states its denominator; an empty denominator is None (N/A), not zero. With 24
held-out tasks and one live repeat the comparisons are exploratory, not evidence of
superiority, and the report says so.
"""

import argparse
import json
import math
import random
import statistics
from pathlib import Path

from shopping_agent.retrieval import file_hash
from shopping_agent.sessions import dumps

from .prepare import write_json
from .run import load_frozen, read_lines

PROFILE_ORDER = ("v3_k10", "v3_k5", "shared_k10", "shared_k5")
# (treatment, reference): count-only, format-only, and both together.
COMPARISONS = (
    ("v3_k5", "v3_k10"),
    ("shared_k10", "v3_k10"),
    ("shared_k5", "v3_k5"),
    ("shared_k5", "v3_k10"),
)
# (metric, stratum of tasks it applies to). Feasible = a certified positive witness exists.
LIVE_BINARY = (
    ("strict_success", "feasible"),
    ("any_verified_hit", "feasible"),
    ("structured_facts_sensitivity_success", "feasible"),
    ("false_feasible_abstention", "feasible"),
    ("safe_abstention", "no_witness"),
    ("failure", "all"),
)
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261031
CAVEAT = (
    "Exploratory: conditional one-turn recommendation success given fixed state and "
    "frozen BM25 results; 24 held-out tasks and one repeat per profile cannot establish "
    "small differences. Reviewed-pool labels are not an exhaustive relevance set."
)


def rate(values):
    """Mean of booleans with n; None entries are outside the denominator."""
    kept = [bool(v) for v in values if v is not None]
    return {
        "n": len(kept),
        "k": sum(kept),
        "rate": sum(kept) / len(kept) if kept else None,
    }


def mean(values):
    kept = [v for v in values if v is not None]
    return statistics.fmean(kept) if kept else None


def median(values):
    kept = [v for v in values if v is not None]
    return statistics.median(kept) if kept else None


def stratum_of(feasible, which):
    return which == "all" or (which == "feasible") == bool(feasible)


def mcnemar_exact(only_treatment, only_reference):
    """Two-sided exact binomial p for discordant pairs; 1.0 with no discordant pairs."""
    n = only_treatment + only_reference
    if n == 0:
        return 1.0
    low = min(only_treatment, only_reference)
    tail = sum(math.comb(n, k) for k in range(low + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_interval(differences, seed=BOOTSTRAP_SEED, resamples=BOOTSTRAP_RESAMPLES):
    """Seeded percentile interval for the mean paired difference; None when n < 2."""
    if len(differences) < 2:
        return None
    rng = random.Random(seed)
    n = len(differences)
    means = sorted(
        statistics.fmean(rng.choices(differences, k=n)) for _ in range(resamples)
    )
    return [means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]]


def paired_binary(by_task, treatment, reference):
    """Per-task paired outcome of a boolean metric; unmatched/None tasks are excluded."""
    both = only_t = only_r = neither = 0
    differences = []
    for values in by_task.values():
        t, r = values.get(treatment), values.get(reference)
        if t is None or r is None:
            continue
        both += t and r
        only_t += t and not r
        only_r += r and not t
        neither += not t and not r
        differences.append(int(t) - int(r))
    n = len(differences)
    return {
        "n_pairs": n,
        "both": both,
        "only_treatment": only_t,
        "only_reference": only_r,
        "neither": neither,
        "mean_difference": statistics.fmean(differences) if n else None,
        "bootstrap_95": bootstrap_interval(differences),
        "mcnemar_exact_p": mcnemar_exact(only_t, only_r) if n else None,
        # Best case: every pair discordant in one direction. Shows what n can ever detect.
        "min_achievable_p": min(1.0, 2 * 0.5**n) if n else None,
    }


def holm_adjust(paired, metric):
    """Add Holm-adjusted p across the comparison family for one metric (in place).

    The adjusted value is descriptive: no comparison is designated primary yet.
    """
    items = [
        (label, metrics[metric])
        for label, metrics in paired.items()
        if metrics[metric]["mcnemar_exact_p"] is not None
    ]
    ordered = sorted(items, key=lambda item: item[1]["mcnemar_exact_p"])
    running = 0.0
    for rank, (_, cell) in enumerate(ordered):
        running = max(running, (len(ordered) - rank) * cell["mcnemar_exact_p"])
        cell["holm_adjusted_p"] = min(1.0, running)
    for metrics in paired.values():
        metrics[metric].setdefault("holm_adjusted_p", None)


def paired_numeric(by_task, treatment, reference):
    differences = [
        v[treatment] - v[reference]
        for v in by_task.values()
        if v.get(treatment) is not None and v.get(reference) is not None
    ]
    return {
        "n_pairs": len(differences),
        "median_difference": median(differences),
        "mean_difference": mean(differences),
        "bootstrap_95": bootstrap_interval(differences),
    }


def pivot(rows, key):
    """{task_id: {profile: value}} for one row key (None values retained as None)."""
    table = {}
    for row in rows:
        table.setdefault(row["task_id"], {})[row["profile"]] = key(row)
    return table


def summarize_offline(offline, tasks):
    """Shortlist quality and formatting cost per profile over all 36 tasks, by split."""
    rows = offline["rows"]
    out = {"profiles": {}, "paired": {}, "invariance": {}}
    for profile in PROFILE_ORDER:
        mine = [r for r in rows if r["profile"] == profile]
        cell = {}
        for split in ("all", "development", "held_out"):
            for which in ("all", "feasible", "no_witness"):
                chosen = [
                    r
                    for r in mine
                    if (split == "all" or r["split"] == split)
                    and stratum_of(r["feasible"], which)
                ]
                cell[f"{split}/{which}"] = {
                    "tasks": len(chosen),
                    "shortlist_hit_at_k": rate([r["shortlist"]["hit"] for r in chosen]),
                    "mean_precision_displayed": mean(
                        [r["shortlist"]["precision_displayed"] for r in chosen]
                    ),
                    "median_visible": median(
                        [r["shortlist"]["visible"] for r in chosen]
                    ),
                    "median_content_tokens": median(
                        [r["content_tokens"] for r in chosen]
                    ),
                    "median_result_tokens": median(
                        [r["result_tokens"] for r in chosen]
                    ),
                    "median_format_ms": median(
                        [r["formatting"]["median_ms"] for r in chosen]
                    ),
                }
        out["profiles"][profile] = cell
    held = {t["id"] for t in tasks if t["split"] == "held_out"}
    hit = {
        k: v
        for k, v in pivot(rows, lambda r: r["shortlist"]["hit"]).items()
        if k in held
    }
    tokens = {
        k: v for k, v in pivot(rows, lambda r: r["content_tokens"]).items() if k in held
    }
    results = {
        k: v for k, v in pivot(rows, lambda r: r["result_tokens"]).items() if k in held
    }
    for treatment, reference in COMPARISONS:
        label = f"{treatment}_vs_{reference}"
        out["paired"][label] = {
            "scope": "held_out (all 24 tasks, feasible and no-witness)",
            "shortlist_hit_at_k": paired_binary(hit, treatment, reference),
            "content_tokens": paired_numeric(tokens, treatment, reference),
            "result_tokens": paired_numeric(results, treatment, reference),
        }
    # Format-only profiles must show identical evidence at equal K (count-only retention
    # is the K5-vs-K10 pair above).
    semantic = pivot(rows, lambda r: r["semantic_sha256"])
    for shared, plain in (("shared_k10", "v3_k10"), ("shared_k5", "v3_k5")):
        compared = [v for v in semantic.values() if shared in v and plain in v]
        out["invariance"][f"{shared}_equals_{plain}"] = {
            "tasks": len(compared),
            "identical": sum(v[shared] == v[plain] for v in compared),
        }
    return out


def completed(records, tasks_by_id, qrels):
    """Annotate each live record with its task's stratum labels."""
    out = []
    for record in records:
        task = tasks_by_id[record["task_id"]]
        out.append(
            {
                **record,
                "feasible": qrels[record["task_id"]]["feasible"],
                "split": task["split"],
                "stratum": task["stratum"],
            }
        )
    return out


def usage_total(records, field):
    values = [
        (r["response"] or {}).get("metadata", {}).get("usage", {}).get(field)
        for r in records
    ]
    return {
        "reported": sum(v for v in values if isinstance(v, int)),
        "trials_missing": sum(not isinstance(v, int) for v in values),
    }


def summarize_live(records, requests, tasks, qrels):
    tasks_by_id = {t["id"]: t for t in tasks}
    records = completed(records, tasks_by_id, qrels)
    request_by_trial = {r["trial_id"]: r for r in requests}
    out = {"profiles": {}, "paired": {}, "by_stratum": {}}
    for profile in PROFILE_ORDER:
        mine = [r for r in records if r["profile"] == profile]
        summary = {"trials": len(mine)}
        for metric, which in LIVE_BINARY:
            summary[f"{metric}[{which}]"] = rate(
                [
                    r["metrics"].get(metric)
                    for r in mine
                    if stratum_of(r["feasible"], which)
                ]
            )
        feasible = [r for r in mine if r["feasible"]]
        summary.update(
            {
                "mean_selected_count": mean(
                    [r["metrics"]["selected_count"] for r in mine]
                ),
                "mean_selected_verified[feasible]": mean(
                    [r["metrics"]["selected_verified"] for r in feasible]
                ),
                "runtime_hard_gate_rejections": sum(
                    r["outcome"].get("runtime_hard_failures", 0) for r in mine
                ),
                "independent_known_hard_failures": sum(
                    r["metrics"]["independent_known_hard_failures"] for r in mine
                ),
                "independent_unknown_required": sum(
                    r["metrics"]["independent_unknown_required"] for r in mine
                ),
                "invalid_or_error_trials": sum(
                    r["outcome"]["status"] != "ok" for r in mine
                ),
                "trials_with_incomplete_usage": sum(
                    not r["usage_complete"] for r in mine
                ),
                "median_latency_ms": median([r["latency_ms"] for r in mine]),
                "prompt_tokens": usage_total(mine, "prompt_tokens"),
                "completion_tokens": usage_total(mine, "completion_tokens"),
                "prompt_cache_hit_tokens": usage_total(mine, "prompt_cache_hit_tokens"),
                "median_content_tokens": median(
                    [request_by_trial[r["trial_id"]]["content_tokens"] for r in mine]
                ),
                "median_result_tokens": median(
                    [request_by_trial[r["trial_id"]]["result_tokens"] for r in mine]
                ),
            }
        )
        out["profiles"][profile] = summary
        for stratum in sorted({t["stratum"] for t in tasks}):
            sub = [r for r in mine if r["stratum"] == stratum]
            out["by_stratum"].setdefault(stratum, {})[profile] = {
                "trials": len(sub),
                "strict_success[feasible]": rate(
                    [r["metrics"]["strict_success"] for r in sub if r["feasible"]]
                ),
                "safe_abstention[no_witness]": rate(
                    [r["metrics"]["safe_abstention"] for r in sub if not r["feasible"]]
                ),
            }
    for treatment, reference in COMPARISONS:
        label = f"{treatment}_vs_{reference}"
        out["paired"][label] = {}
        for metric, which in LIVE_BINARY:
            table = {}
            for r in records:
                if stratum_of(r["feasible"], which):
                    table.setdefault(r["task_id"], {})[r["profile"]] = r["metrics"].get(
                        metric
                    )
            out["paired"][label][f"{metric}[{which}]"] = paired_binary(
                table, treatment, reference
            )
        tokens = {}
        for r in records:
            tokens.setdefault(r["task_id"], {})[r["profile"]] = request_by_trial[
                r["trial_id"]
            ]["content_tokens"]
        out["paired"][label]["content_tokens"] = paired_numeric(
            tokens, treatment, reference
        )
    for metric, which in LIVE_BINARY:
        holm_adjust(out["paired"], f"{metric}[{which}]")
    return out


def build_report(frozen, run=None, offline=None, *, allow_partial=False):
    manifest, tasks, _baseline, qrels = load_frozen(frozen)
    report = {
        "caveat": CAVEAT,
        "frozen_manifest_sha256": file_hash(Path(frozen) / "manifest.json"),
        "protocol": manifest["protocol"],
        "tasks": {
            "total": len(tasks),
            "held_out": sum(t["split"] == "held_out" for t in tasks),
            "feasible": sum(qrels[t["id"]]["feasible"] for t in tasks),
            "no_witness": sum(not qrels[t["id"]]["feasible"] for t in tasks),
        },
        "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES},
    }
    if offline is not None:
        report["offline"] = summarize_offline(
            json.loads(Path(offline).read_text()), tasks
        )
    if run is not None:
        run = Path(run)
        records = list(map(json.loads, read_lines(run / "outcomes.jsonl")))
        requests = list(map(json.loads, read_lines(run / "requests.jsonl")))
        meta = json.loads((run / "run.json").read_text())
        if meta["manifest_sha256"] != file_hash(Path(frozen) / "manifest.json"):
            raise ValueError("Run was made against a different frozen manifest")
        if not (run / "completed.json").exists() and not allow_partial:
            raise ValueError("Run is not finished; pass allow_partial to report it")
        if (
            len(records) != len({r["trial_id"] for r in records})
            or len(records) > meta["trials"]
        ):
            raise ValueError("Run records are duplicated or exceed the schedule")
        report["live"] = {
            "run": {
                "git_commit": meta["git_commit"],
                "requested_model": meta["requested_model"],
                "seed": meta["seed"],
                "planned_trials": meta["trials"],
                "observed_trials": len(records),
                "finished": (run / "completed.json").exists(),
                "tokenizer_sha256": meta.get("tokenizer_sha256"),
                "verification_sha256": meta.get("verification_sha256"),
                "requirements_lock_sha256": meta.get("requirements_lock_sha256"),
            },
            **summarize_live(records, requests, tasks, qrels),
        }
    return report


def fmt(value):
    if value is None:
        return "N/A"
    if isinstance(value, dict) and "rate" in value:
        text = "N/A" if value["rate"] is None else f"{value['rate']:.3f}"
        return f"{text} ({value['k']}/{value['n']})"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(report):
    lines = ["# Experiment A report", "", f"> {report['caveat']}", ""]
    counts = report["tasks"]
    lines += [
        f"Tasks: {counts['total']} ({counts['held_out']} held out); "
        f"{counts['feasible']} feasible, {counts['no_witness']} without a certified witness.",
        "",
    ]
    if "offline" in report:
        lines += ["## Offline shortlist and cost (held-out, feasible tasks)", ""]
        lines += [
            "| Profile | Hit@K | Mean precision | Median content tokens | Median result tokens |"
        ]
        lines += ["| --- | --- | --- | --- | --- |"]
        for profile, cells in report["offline"]["profiles"].items():
            c = cells["held_out/feasible"]
            lines.append(
                f"| {profile} | {fmt(c['shortlist_hit_at_k'])} | "
                f"{fmt(c['mean_precision_displayed'])} | {fmt(c['median_content_tokens'])} | "
                f"{fmt(c['median_result_tokens'])} |"
            )
        lines += ["", "Format-only invariance (same evidence at equal K):"]
        for name, value in report["offline"]["invariance"].items():
            lines.append(f"- {name}: {value['identical']}/{value['tasks']} identical")
        lines.append("")
    if "live" in report:
        live = report["live"]
        info = live["run"]
        lines += [
            "## Live one-turn recommendation decision",
            "",
            f"Run `{info['git_commit'][:12]}`, model alias `{info['requested_model']}`, "
            f"{info['observed_trials']}/{info['planned_trials']} trials, "
            f"{'finished' if info['finished'] else 'NOT finished'}.",
            "",
            "| Profile | Strict success (feasible) | Any verified hit | Safe abstention (no witness) "
            "| False abstention | Invalid/error | Known hard failures |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for profile, s in live["profiles"].items():
            lines.append(
                f"| {profile} | {fmt(s['strict_success[feasible]'])} | "
                f"{fmt(s['any_verified_hit[feasible]'])} | "
                f"{fmt(s['safe_abstention[no_witness]'])} | "
                f"{fmt(s['false_feasible_abstention[feasible]'])} | "
                f"{s['invalid_or_error_trials']} | {s['independent_known_hard_failures']} |"
            )
        lines += ["", "### Paired differences (treatment - reference)", ""]
        lines += [
            "| Comparison | Metric | Pairs | Mean diff | 95% bootstrap | Discordant (T only / R only) | Exact p | Holm p | Best-case p |"
        ]
        lines += ["| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for label, metrics in live["paired"].items():
            for name in ("strict_success[feasible]", "safe_abstention[no_witness]"):
                m = metrics[name]
                interval = m["bootstrap_95"]
                lines.append(
                    f"| {label} | {name} | {m['n_pairs']} | {fmt(m['mean_difference'])} | "
                    f"{'N/A' if interval is None else f'[{interval[0]:.3f}, {interval[1]:.3f}]'} | "
                    f"{m['only_treatment']} / {m['only_reference']} | {fmt(m['mcnemar_exact_p'])} | "
                    f"{fmt(m['holm_adjusted_p'])} | {fmt(m['min_achievable_p'])} |"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def write_report(frozen, output, run=None, offline=None, *, allow_partial=False):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Report output exists; choose a new directory")
    if run is None and offline is None:
        raise ValueError("Provide --run and/or --offline")
    report = build_report(frozen, run, offline, allow_partial=allow_partial)
    output.mkdir(parents=True)
    write_json(output / "report.json", report)
    (output / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--run", type=Path, help="completed live run directory")
    parser.add_argument("--offline", type=Path, help="offline.json from run.py offline")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--allow-partial", action="store_true", help="report an unfinished live run"
    )
    args = parser.parse_args()
    write_report(
        args.frozen,
        args.output,
        args.run,
        args.offline,
        allow_partial=args.allow_partial,
    )
    print(dumps({"report": str(args.output / "report.json")}))


if __name__ == "__main__":
    main()
