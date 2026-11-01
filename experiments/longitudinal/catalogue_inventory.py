"""Reproduce the development catalogue audit; never load credentials or call models."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from astra_eval.customers import load_customers
from astra_eval.oracle import CatalogueOracle, raw_facts
from shopping_agent.retrieval import LexicalSearch


def group(categories: list[str]) -> str:
    """Reporting buckets only, not a new product ontology or scoring rule."""
    if "Shoes" in categories:
        return "Footwear"
    if any(
        label in categories
        for label in ("Handbags & Wallets", "Backpacks", "Briefcases", "Duffels")
    ) and not any("Wallet" in label for label in categories[2:]):
        return "Bags"
    # Handbags & Wallets also contains bags; exclude only the wallet branch.
    if "Handbags & Wallets" in categories and not any(
        label == "Wallets" or "Card Cases" in label for label in categories[3:]
    ):
        return "Bags"
    if "Clothing" in categories or "Sport Specific Clothing" in categories:
        return "Clothing"
    return "Jewelry/accessories/other"


def inventory(catalogue: Path, index: Path, fixture: Path) -> str:
    """Audit exact leaves; count usable attributes only among usable-price rows."""
    data = load_customers(fixture)
    oracle = CatalogueOracle(catalogue)
    if oracle.sha256 != data.catalogue_sha256:
        raise ValueError("Catalogue differs from the original development fixture")
    tool = LexicalSearch(index, expected_catalogue_hash=oracle.sha256)
    indexed_count = tool.count
    tool.close()
    leaves = defaultdict(Counter)
    colors = defaultdict(Counter)
    materials = defaultdict(Counter)
    groups = defaultdict(set)
    totals = Counter()
    for row in oracle.rows():
        categories = row.get("categories", [])
        leaf = categories[-1] if categories else "(missing)"
        bucket = group(categories)
        groups[leaf].add(bucket)
        totals[bucket] += 1
        count = leaves[leaf]
        count["rows"] += 1
        facts = raw_facts(row)
        if facts["price"] is not None:
            count["priced"] += 1
            for field, counter in (("color", colors), ("material", materials)):
                if facts[field] is not None:
                    count[field] += 1
                    counter[leaf][facts[field]] += 1
    if sum(totals.values()) != 50_000 or indexed_count != 50_000:
        raise ValueError("Expected the approved 50k catalogue and index")

    def examples(counter: Counter) -> str:
        return "; ".join(f"{value} ({n})" for value, n in counter.most_common(3)).replace(
            "|", "\\|"
        ) or "—"

    lines = [
        "# Local TechJam catalogue inventory",
        "",
        f"Catalogue SHA-256: `{oracle.sha256}`. Read-only index source hash verified.",
        f"50,000 rows; {len(leaves)} exact leaf labels. Same labels across taxonomy paths are combined.",
        "",
        "Generated with `.venv/bin/python experiments/longitudinal/catalogue_inventory.py`.",
        "Counts describe parent products, not selectable variants or current availability.",
        "Usable price means the existing oracle's positive finite price. Color/material coverage",
        "counts only priced rows with structured detail fields accepted by `raw_facts`; titles",
        "and images are never used to infer attributes. Values shown are the three most frequent",
        "verbatim structured values, with counts. Missing fields stay unknown.",
        "",
        "Reporting buckets are heuristic taxonomy summaries only; they do not alter evaluation.",
        "The residual bucket includes jewelry, watches, accessories, luggage gear and unclassified",
        "leaves. Mixed-path leaf labels can appear in several buckets in the detailed table.",
        "",
        "| Reporting bucket | Rows |",
        "| --- | ---: |",
        *[f"| {name} | {count} |" for name, count in sorted(totals.items())],
        "",
        "| Exact leaf | Buckets | Rows | Priced | Color known | Material known | Color examples | Material examples |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for leaf, counts in sorted(leaves.items()):
        lines.append(
            f"| {leaf} | {', '.join(sorted(groups[leaf]))} | {counts['rows']} | "
            f"{counts['priced']} | {counts['color']} | {counts['material']} | "
            f"{examples(colors[leaf])} | {examples(materials[leaf])} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, default=Path("data/catalogue/catalog.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/index/catalogue.sqlite"))
    parser.add_argument(
        "--fixture", type=Path, default=Path("experiments/longitudinal/customers.dev.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/reviews/longitudinal-catalogue-inventory.md")
    )
    args = parser.parse_args()
    args.output.write_text(inventory(args.catalogue, args.index, args.fixture))
    print(f"Wrote {args.output}; no model calls.")
