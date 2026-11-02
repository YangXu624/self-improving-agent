"""Memory-sensitive target benchmark evaluation and group-partitioned scoring.

Evaluates ASTRA's user-memory benefits across three controlled scenario groups:
1. memory-helpful: task relates to remembered preference; prompt omits the preference.
2. memory-neutral: remembered preference is irrelevant to current task.
3. memory-conflicting: current request explicitly overrides preference or is a gift.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .customers import CustomerDataset, validate_dataset


@dataclass
class GroupMetrics:
    total_visits: int = 0
    successful_visits: int = 0
    target_success_at_6: float = 0.0
    turns_to_success: list[int] = field(default_factory=list)
    mean_turns_to_success: float = 0.0
    hard_violations: int = 0
    unknown_violations: int = 0
    model_calls: int = 0
    searches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class BenchmarkReport:
    dataset_id: str
    catalogue_sha256: str
    groups: dict[str, GroupMetrics]
    overall: GroupMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "catalogue_sha256": self.catalogue_sha256,
            "groups": {
                g: {
                    "total_visits": m.total_visits,
                    "successful_visits": m.successful_visits,
                    "target_success_at_6": round(m.target_success_at_6, 4),
                    "mean_turns_to_success": round(m.mean_turns_to_success, 2)
                    if m.mean_turns_to_success
                    else None,
                    "hard_violations": m.hard_violations,
                    "unknown_violations": m.unknown_violations,
                    "model_calls": m.model_calls,
                    "searches": m.searches,
                    "input_tokens": m.input_tokens,
                    "output_tokens": m.output_tokens,
                }
                for g, m in self.groups.items()
            },
            "overall": {
                "total_visits": self.overall.total_visits,
                "successful_visits": self.overall.successful_visits,
                "target_success_at_6": round(self.overall.target_success_at_6, 4),
                "mean_turns_to_success": round(self.overall.mean_turns_to_success, 2)
                if self.overall.mean_turns_to_success
                else None,
                "hard_violations": self.overall.hard_violations,
                "unknown_violations": self.overall.unknown_violations,
                "model_calls": self.overall.model_calls,
                "searches": self.overall.searches,
                "input_tokens": self.overall.input_tokens,
                "output_tokens": self.overall.output_tokens,
            },
        }


def score_memory_sensitive_results(
    dataset_path: str | Path, results: list[dict]
) -> BenchmarkReport:
    """Compute group-separated target-item evaluation metrics.

    SUCCESS: Target product recommended in turns <= 6.
    FAILURE: 6 completed turns without acceptable target recommendation, or stalled.
    """
    dataset = CustomerDataset.model_validate_json(Path(dataset_path).read_text())
    visit_group_map = {}
    for c in dataset.customers:
        for v in c.visits:
            group = v.scenario_group or "memory-helpful"
            visit_group_map[v.task_id] = group

    groups: dict[str, GroupMetrics] = {
        "memory-helpful": GroupMetrics(),
        "memory-neutral": GroupMetrics(),
        "memory-conflicting": GroupMetrics(),
    }
    overall = GroupMetrics()

    for row in results:
        task_id = row.get("task_id")
        group = visit_group_map.get(task_id, "memory-helpful")
        gm = groups.setdefault(group, GroupMetrics())

        gm.total_visits += 1
        overall.total_visits += 1

        hit = row.get("target_hit")
        term = row.get("termination")
        turn_hit = hit.get("turn") if hit else None

        if term == "target_found" and turn_hit is not None and turn_hit <= 6:
            gm.successful_visits += 1
            overall.successful_visits += 1
            gm.turns_to_success.append(turn_hit)
            overall.turns_to_success.append(turn_hit)

        # Violations
        viol = row.get("score", {}).get("violations", {})
        hard_fails = viol.get("hard_fail", 0)
        unk_fails = viol.get("unknown_required", 0)
        gm.hard_violations += hard_fails
        overall.hard_violations += hard_fails
        gm.unknown_violations += unk_fails
        overall.unknown_violations += unk_fails

        # Resource tracking
        res = row.get("score", {}).get("resources", {})
        calls = res.get("model_calls", 0)
        searches = res.get("searches", 0)
        tokens = res.get("tokens", {})
        inp_tok = tokens.get("input", 0)
        out_tok = tokens.get("output", 0)

        gm.model_calls += calls
        overall.model_calls += calls
        gm.searches += searches
        overall.searches += searches
        gm.input_tokens += inp_tok
        overall.input_tokens += inp_tok
        gm.output_tokens += out_tok
        overall.output_tokens += out_tok

    for m in list(groups.values()) + [overall]:
        if m.total_visits > 0:
            m.target_success_at_6 = m.successful_visits / m.total_visits
        if m.turns_to_success:
            m.mean_turns_to_success = sum(m.turns_to_success) / len(m.turns_to_success)

    return BenchmarkReport(
        dataset_id=dataset.dataset_id,
        catalogue_sha256=dataset.catalogue_sha256,
        groups=groups,
        overall=overall,
    )


def validate_benchmark_fixture(
    dataset_path: str
    | Path = "experiments/longitudinal/customers.memory-sensitive.json",
    catalogue_path: str | Path = "data/catalogue/catalog.jsonl",
) -> dict[str, Any]:
    """Strictly validate the memory-sensitive benchmark against frozen catalogue evidence."""
    dataset = CustomerDataset.model_validate_json(Path(dataset_path).read_text())
    compiled = validate_dataset(dataset, catalogue_path, require_evidence=True)

    group_counts = {}
    for c in dataset.customers:
        for v in c.visits:
            grp = v.scenario_group or "unspecified"
            group_counts[grp] = group_counts.get(grp, 0) + 1

    return {
        "status": "valid",
        "dataset_id": dataset.dataset_id,
        "catalogue_sha256": dataset.catalogue_sha256,
        "total_customers": len(dataset.customers),
        "total_visits": len(compiled),
        "group_distribution": group_counts,
        "verified_witness_count": len(compiled),
        "acceptable_target_candidates_present": all(
            bool(cv.target_truth.acceptable_target_ids or cv.target_truth.target_id)
            for cv in compiled
        ),
    }


if __name__ == "__main__":
    report = validate_benchmark_fixture()
    print(json.dumps(report, indent=2))
