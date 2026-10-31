"""Seeded anonymous target tasks; target identity stays exclusively in ground truth.

Evidence contract: existing explicit detail fields, category tokens and historical USD
prices. Budget is the next strictly greater $10 boundary, never an identifying exact price.
No inferred uses, title fragments, feature extractions or child-variant availability claims.
"""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .models import Fact, Scenario, ShopperProfile, TargetGroundTruth
from .oracle import DETAIL_NAMES, CatalogueOracle, norm, tokens
from .scenarios import (
    assign_types,
    budget_fact,
    load_entries,
    read_lines,
    sha256_text,
    type_fact,
)

TARGET_VERSION = "target-v1"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def anonymous_value(value, title):
    return bool(
        value
        and len(str(value)) <= 60
        and norm(value) != norm(title)
        and not re.search(r"\bB0[A-Z0-9]{8}\b|https?://|\b\d{10,}\b", str(value), re.I)
    )


def documented_profile(entry):
    """A fixed, maximal allowed profile; only price is coarsened by a declared rule."""
    f = entry["facts"]
    if (
        f["price"] is None
        or not anonymous_value(entry["leaf"], entry["title"])
        or not entry["title"]
    ):
        return None
    cap = (math.floor(f["price"] / 10) + 1) * 10.0
    facts = [type_fact(entry["leaf"]), budget_fact(cap)]
    for field in ("department", "brand", "color", "material", "size"):
        value = f.get(field)
        if anonymous_value(value, entry["title"]):
            facts.append(
                Fact(
                    key=field,
                    kind="hard",
                    field=field,
                    op="eq",
                    value=norm(value),
                    statement=f"The {field} must be {norm(value)}.",
                    keywords=[field, "colour"] if field == "color" else [field],
                )
            )
    return facts


class TargetPool:
    """Inverted exact-facet/category index for offline eligibility, not agent retrieval."""

    def __init__(self, catalogue):
        self.oracle = CatalogueOracle(catalogue)
        self.entries = load_entries(self.oracle)
        self.by_id = {e["id"]: e for e in self.entries}
        self.words, self.facets = defaultdict(set), defaultdict(set)
        for e in self.entries:
            for word in tokens(e["facts"]["product_type"] or ""):
                self.words[word].add(e["id"])
            for field in DETAIL_NAMES:
                if e["facts"].get(field) is not None:
                    self.facets[(field, norm(e["facts"][field]))].add(e["id"])
        self.profiles, self.matches, self.groups = {}, {}, {}
        for e in self.entries:
            facts = documented_profile(e)
            if facts is None:
                self.groups[e["id"]] = "insufficient_evidence"
                continue
            found = self.compatible(facts)
            if e["id"] not in found:
                raise ValueError("Target evidence does not satisfy its profile")
            self.profiles[e["id"]] = facts
            self.matches[e["id"]] = found
            self.groups[e["id"]] = "distinguishable" if len(found) == 1 else "ambiguous"

    def compatible(self, facts):
        pools, budget = [], None
        for f in facts:
            if f.field == "product_type":
                pools.extend(self.words[w] for w in tokens(f.value))
            elif f.field == "price":
                budget = float(f.value)
            else:
                pools.append(self.facets[(f.field, norm(f.value))])
        if not pools:
            return set()
        found = set(min(pools, key=len))
        for pool in pools:
            found.intersection_update(pool)
        return {
            i
            for i in found
            if self.by_id[i]["facts"]["price"] is not None
            and (budget is None or self.by_id[i]["facts"]["price"] < budget)
        }

    def audit(self):
        total = sum(1 for _ in self.oracle.rows())
        groups = Counter(self.groups.values())
        groups["insufficient_evidence"] += total - len(self.entries)
        return {
            "catalogue_sha256": self.oracle.sha256,
            "catalogue_products": total,
            "counts": dict(groups),
            "policy": "explicit-detail-v1; next-strictly-greater-10-USD-budget",
            "known_attribute_counts": dict(
                Counter(len(v) - 2 for v in self.profiles.values())
            ),
            "by_family": {
                leaf: dict(
                    Counter(
                        self.groups[e["id"]] for e in self.entries if e["leaf"] == leaf
                    )
                )
                for leaf in sorted({e["leaf"] for e in self.entries})
            },
        }


def generate_targets(
    catalogue,
    seed,
    per_split,
    *,
    max_user_turns=6,
    group="distinguishable",
    no_target_per_split=0,
):
    if group not in {"distinguishable", "ambiguous", "all"}:
        raise ValueError("Unknown target group")
    if (
        max_user_turns < 1
        or any(v < 0 for v in per_split.values())
        or no_target_per_split < 0
    ):
        raise ValueError("Counts/turn budget must be nonnegative/positive")
    pool = TargetPool(catalogue)
    types = Counter(e["leaf"] for e in pool.entries if e["id"] in pool.profiles)
    assignment = assign_types(
        list(types.items()), seed, {k: max(1, v) for k, v in per_split.items()}
    )
    scenarios, truths, occupied, used_ids = [], [], {}, set()
    used_profiles, occupied_titles = set(), {}
    for split, count in per_split.items():
        choices = [
            e
            for e in pool.entries
            if e["leaf"] in assignment[split]
            and e["id"] in pool.profiles
            and (group == "all" or pool.groups[e["id"]] == group)
        ]
        choices.sort(key=lambda e: digest([seed, split, e["id"]]))
        produced = 0
        for e in choices:
            if produced >= count:
                break
            matching = pool.matches[e["id"]]
            if e["id"] in used_ids or any(
                occupied.get(i, split) != split for i in matching
            ):
                continue
            facts = pool.profiles[e["id"]]
            signature = digest([f.model_dump() for f in facts])
            titles = {norm(pool.by_id[i]["title"]) for i in matching}
            if signature in used_profiles or any(
                occupied_titles.get(t, split) != split for t in titles
            ):
                continue
            used_profiles.add(signature)
            occupied_titles.update({t: split for t in titles})
            ident = digest([seed, split, e["id"]])[:16]
            scenario_id = f"{split[:3]}-{ident}"
            profile = ShopperProfile(
                scenario_id=scenario_id,
                persona="A shopper seeking an item with the fixed documented requirements below. Answer questions honestly and progressively.",
                facts=tuple(facts),
                opening_keys=("type",),
            )
            scenarios.append(
                Scenario(
                    id=scenario_id,
                    split=split,
                    family=e["leaf"],
                    kind="underspecified",
                    opening=f"I'm looking for {e['leaf'].lower()}.",
                    max_user_turns=max_user_turns,
                    profile=profile,
                )
            )
            row = pool.oracle.row(e["id"])
            evidence = {
                "type": "categories",
                "budget": "price (next greater $10 boundary; historical USD)",
            }
            for f in facts[2:]:
                evidence[f.key] = "details." + next(
                    n
                    for n in DETAIL_NAMES[f.field]
                    if isinstance(row.get("details", {}).get(n), (str, int, float))
                    and not isinstance(row["details"][n], bool)
                    and str(row["details"][n]).strip()
                )
            truths.append(
                TargetGroundTruth(
                    scenario_id=scenario_id,
                    target_id=e["id"],
                    target_title=e["title"],
                    catalogue_sha256=pool.oracle.sha256,
                    profile_sha256=digest(profile.model_dump()),
                    hard=facts,
                    ambiguity=pool.groups[e["id"]],
                    compatible_count=len(matching),
                    compatible_ids_sha256=digest(sorted(matching)),
                    evidence=evidence,
                )
            )
            used_ids.add(e["id"])
            occupied.update({i: split for i in matching})
            produced += 1
        if produced != count:
            raise ValueError(
                f"Only {produced}/{count} eligible {group} targets for {split}; do not invent identifying hints"
            )
        for n in range(no_target_per_split):
            # Proved impossible over documented positive historical prices; not live-stock absence.
            e = choices[n % len(choices)] if choices else None
            if e is None:
                raise ValueError("No family available for no-target scenario")
            base = [type_fact(e["leaf"])]
            scope = set.intersection(*(pool.words[w] for w in tokens(e["leaf"])))
            prices = [
                pool.by_id[i]["facts"]["price"]
                for i in scope
                if pool.by_id[i]["facts"]["price"] is not None
            ]
            cap = min(prices) / 2
            facts = base + [budget_fact(cap)]
            if pool.compatible(facts):
                raise ValueError("No-target proof failed")
            sid = f"{split[:3]}-none-{digest([seed, split, e['leaf'], n])[:12]}"
            profile = ShopperProfile(
                scenario_id=sid,
                persona="Answer the fixed requirements honestly.",
                facts=tuple(facts),
                opening_keys=("type", "budget"),
            )
            scenarios.append(
                Scenario(
                    id=sid,
                    split=split,
                    family=e["leaf"],
                    kind="no_valid_product",
                    opening=f"I need {e['leaf'].lower()} under ${cap:g}.",
                    max_user_turns=max_user_turns,
                    profile=profile,
                )
            )
            truths.append(
                TargetGroundTruth(
                    scenario_id=sid,
                    catalogue_sha256=pool.oracle.sha256,
                    profile_sha256=digest(profile.model_dump()),
                    hard=facts,
                    ambiguity="no_target",
                    compatible_count=0,
                    compatible_ids_sha256=digest([]),
                    evidence={
                        "budget": "below minimum known category price; missing prices remain unknown"
                    },
                )
            )
    return (
        scenarios,
        truths,
        {
            "evaluation_mode": "target_item",
            "generator_version": TARGET_VERSION,
            "seed": seed,
            "catalogue_sha256": pool.oracle.sha256,
            "per_split": per_split,
            "target_group": group,
            "no_target_per_split": no_target_per_split,
            "eligibility": pool.audit(),
        },
    )


def load_target_truth(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    text = (directory / "ground_truth.jsonl").read_text()
    if sha256_text(text) != manifest["ground_truth_sha256"]:
        raise ValueError("Target ground truth hash mismatch")
    records = [
        TargetGroundTruth.model_validate_json(line)
        for line in read_lines(directory / "ground_truth.jsonl")
    ]
    if len({t.scenario_id for t in records}) != len(records):
        raise ValueError("Duplicate target scenario IDs")
    return {t.scenario_id: t for t in records}
