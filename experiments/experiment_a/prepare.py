"""Freeze source-backed pilot qrels and raw BM25 top10; no provider is constructed."""

import argparse
import json
from pathlib import Path

from shopping_agent.contracts import Requirement, Search, ShoppingState
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.sessions import dumps

from .source_judgments import judge

ROOT = Path(__file__).resolve().parents[2]
TASKS = Path(__file__).with_name("tasks.json")


def state_for(task):
    return ShoppingState(
        version=1,
        requirements=[
            Requirement(
                **r,
                id=task["id"] + f":r{i}",
                source_event_id=task["id"] + ":user",
                created_version=1,
            )
            for i, r in enumerate(task["requirements"])
        ],
    )


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )


def prepare(catalogue, index, destination, tasks_path=TASKS):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(
            "Use a fresh output directory; frozen evidence is never overwritten"
        )
    task_doc = json.loads(Path(tasks_path).read_text())
    tasks = task_doc["tasks"]
    source_hash = file_hash(catalogue)
    if source_hash != task_doc["catalogue_sha256"]:
        raise ValueError("Pilot catalogue hash mismatch")
    groups = {}
    for task in tasks:
        if task["family"] in groups and groups[task["family"]] != task["split"]:
            raise ValueError("Related task family crosses split")
        groups[task["family"]] = task["split"]
        for r in task["requirements"]:
            if not r["quote"].strip() or r["quote"] not in task["request"]:
                raise ValueError("Invalid fixed-state quote")
    # JSONL uses physical newlines; str.splitlines also splits valid Unicode text.
    with Path(catalogue).open(encoding="utf-8") as source:
        rows = {r["parent_asin"]: r for r in map(json.loads, source)}
    qrels, baseline = {}, {}
    tool = LexicalSearch(index, expected_catalogue_hash=source_hash)
    try:
        for task in tasks:
            state = state_for(task)
            result = tool.search(
                Search(type="SEARCH", query=task["query"], mode=task["mode"], limit=10),
                state,
            )
            positive_ids = sorted(
                ident for ident, row in rows.items() if judge(row, task)["relevant"]
            )
            judgments = {
                p["id"]: judge(rows[p["id"]], task) for p in result["candidates"]
            }
            qrels[task["id"]] = {
                "positive_ids": positive_ids,
                "positive_count": len(positive_ids),
                "candidate_judgments": judgments,
            }
            baseline[task["id"]] = {
                "state": state.model_dump(),
                "search_result": result,
            }
    finally:
        tool.close()
    if file_hash(catalogue) != source_hash:
        raise ValueError("Source changed")
    destination.mkdir(parents=True)
    write_json(destination / "tasks.json", task_doc)
    write_json(destination / "qrels.json", qrels)
    write_json(destination / "baseline.json", baseline)
    write_json(
        destination / "judgments_for_review.json",
        {
            task_id: sorted(value["candidate_judgments"])
            for task_id, value in qrels.items()
        },
    )
    manifest = {
        "protocol": "experiment-a-pilot-v1",
        "catalogue_sha256": source_hash,
        "tasks_sha256": file_hash(destination / "tasks.json"),
        "qrels_sha256": file_hash(destination / "qrels.json"),
        "baseline_sha256": file_hash(destination / "baseline.json"),
        "retrieval_source_sha256": file_hash(ROOT / "src/shopping_agent/retrieval.py"),
        "judgment_source_sha256": file_hash(
            Path(__file__).with_name("source_judgments.py")
        ),
        "task_count": len(tasks),
        "independent_verification": "pending",
    }
    write_json(destination / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue", default="data/catalogue/catalog.jsonl", type=Path
    )
    parser.add_argument("--index", default="data/index/catalogue.sqlite", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(dumps(prepare(args.catalogue, args.index, args.output)))


if __name__ == "__main__":
    main()
