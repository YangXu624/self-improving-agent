"""Show that two frozen directories differ only in opaque identifiers (read-only evidence).

Used to justify a versioned replacement of a verified benchmark: tasks, qrels, reviewed
labels, candidate IDs/order/counts and card evidence must be identical; only requirement
and source-event IDs (replaced by opaque hashes), per-run random search IDs and last-digit
BM25 float noise may differ. This prints evidence; it does not create a certificate, which
still requires an independent review of the replacement.
"""

import argparse
import json
import math
from pathlib import Path

from shopping_agent.sessions import dumps

SAME_FILES = ("tasks.json", "qrels.json", "reviewed_labels.json")


def rename(value, mapping):
    if isinstance(value, dict):
        return {k: rename(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, mapping) for v in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def without(result):
    """Search result minus the per-run random ID and BM25 floats (compared separately)."""
    value = {k: v for k, v in result.items() if k != "search_id"}
    value["candidates"] = [
        {k: v for k, v in c.items() if k != "bm25"} for c in result["candidates"]
    ]
    return value


def strip(state):
    return [
        {k: v for k, v in r.items() if k not in {"id", "source_event_id"}}
        for r in state["requirements"]
    ]


def compare(old, new):
    """Return {check: bool, ...}; True means the two directories agree on that check."""
    old, new = Path(old), Path(new)
    checks = {
        name: (old / name).read_bytes() == (new / name).read_bytes()
        for name in SAME_FILES
    }
    a = json.loads((old / "baseline.json").read_text())
    b = json.loads((new / "baseline.json").read_text())
    checks["same_task_set"] = set(a) == set(b)
    ids = order = counts = facts = states = mapped = True
    for key in set(a) & set(b):
        sa, sb = a[key]["state"], b[key]["state"]
        # Opaque IDs must map one-to-one by position; the same mapping then has to
        # explain every ID reference inside the search result (matched/applied filters).
        mapping = {
            o["id"]: n["id"] for o, n in zip(sa["requirements"], sb["requirements"])
        } | {
            o["source_event_id"]: n["source_event_id"]
            for o, n in zip(sa["requirements"], sb["requirements"])
        }
        mapped &= len(mapping) == len(set(mapping.values()))
        ra = rename(a[key]["search_result"], mapping)
        rb = b[key]["search_result"]
        counts &= ra["counts"] == rb["counts"]
        ids &= {c["id"] for c in ra["candidates"]} == {
            c["id"] for c in rb["candidates"]
        }
        order &= [c["id"] for c in ra["candidates"]] == [
            c["id"] for c in rb["candidates"]
        ]
        for x, y in zip(ra["candidates"], rb["candidates"]):
            facts &= math.isclose(x["bm25"], y["bm25"], rel_tol=1e-9)
        facts &= dumps(without(ra)) == dumps(without(rb))
        states &= strip(sa) == strip(sb) and sa["version"] == sb["version"]
    checks.update(
        candidate_ids_equal=ids,
        candidate_order_equal=order,
        counts_equal=counts,
        card_evidence_equal_after_id_mapping=facts,
        requirement_ids_map_one_to_one=mapped,
        requirement_content_equal_except_ids=states,
    )
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    args = parser.parse_args()
    result = compare(args.old, args.new)
    print(dumps(result))
    raise SystemExit(0 if all(result.values()) else 1)


if __name__ == "__main__":
    main()
