"""Freeze independently reviewed pooled relevance; never modify draft or reviewer data."""

import argparse
import json
import shutil
from pathlib import Path

from shopping_agent.retrieval import file_hash
from shopping_agent.sessions import dumps

from .prepare import write_json


def finalize(draft, review, destination):
    draft, review, destination = Path(draft), Path(review), Path(destination)
    if destination.exists():
        raise FileExistsError("Frozen evidence must not be overwritten")
    original = json.loads((draft / "manifest.json").read_text(encoding="utf-8"))
    for filename, key in [
        ("tasks.json", "tasks_sha256"),
        ("qrels.json", "qrels_sha256"),
        ("baseline.json", "baseline_sha256"),
    ]:
        if file_hash(draft / filename) != original[key]:
            raise ValueError("Draft evidence hash mismatch")
    task_doc = json.loads((draft / "tasks.json").read_text(encoding="utf-8"))
    baseline = json.loads((draft / "baseline.json").read_text(encoding="utf-8"))
    seed = json.loads((draft / "qrels.json").read_text(encoding="utf-8"))
    reviewed = json.loads(review.read_text(encoding="utf-8"))
    labels, witnesses = reviewed["labels"], reviewed["witnesses"]
    qrels = {}
    for task in task_doc["tasks"]:
        ident = task["id"]
        expected_ids = {p["id"] for p in baseline[ident]["search_result"]["candidates"]}
        actual = labels.get(ident, {})
        if set(actual) != expected_ids:
            raise ValueError(
                "Independent review does not cover the exact candidate pool"
            )
        for judgment in actual.values():
            if (
                type(judgment["relevant"]) is not bool
                or judgment["hard_verdict"] not in {"pass", "fail", "unknown"}
                or not judgment.get("support")
            ):
                raise ValueError("Invalid source-supported judgment")
        witness = witnesses.get(ident)
        if seed[ident]["positive_count"] and not witness:
            raise ValueError(
                "Feasible task lacks independently verified positive witness"
            )
        if witness and not witness.get("support"):
            raise ValueError("Witness lacks source support")
        qrels[ident] = {
            "judgments": actual,
            "witness": witness,
            "feasible": witness is not None,
            "scope": "independently_reviewed_top10_pool_not_exhaustive_corpus",
        }
    destination.mkdir(parents=True)
    shutil.copyfile(draft / "tasks.json", destination / "tasks.json")
    shutil.copyfile(draft / "baseline.json", destination / "baseline.json")
    shutil.copyfile(review, destination / "reviewed_labels.json")
    write_json(destination / "qrels.json", qrels)
    manifest = {
        **original,
        "protocol": "experiment-a-pilot-v1-reviewed-pool",
        "qrels_sha256": file_hash(destination / "qrels.json"),
        "review_sha256": file_hash(destination / "reviewed_labels.json"),
        "draft_manifest_sha256": file_hash(draft / "manifest.json"),
        "annotation_scope": "reviewed_top10_pool_and_independent_positive_witnesses",
        "independent_verification": "requires_matching_verification_certificate",
    }
    write_json(destination / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(dumps(finalize(args.draft, args.review, args.destination)))


if __name__ == "__main__":
    main()
