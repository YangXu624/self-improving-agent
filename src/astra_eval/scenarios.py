"""Reproducible, catalogue-grounded shopping scenarios with separate ground truth.

Every acceptable set is computed by the independent oracle over the whole catalogue, so a
scenario states what is verifiable, not what a model might guess. Missing attributes stay
unknown. Product families (leaf category) never cross splits.
"""

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import VERSION
from .models import Fact, GroundTruth, Scenario, ShopperProfile
from .oracle import CatalogueOracle, judge, norm, raw_facts, tokens

DEFAULT_SPLIT_WEIGHTS = {"learning": 0.4, "development": 0.2, "held_out": 0.4}
# Leaf categories that are brand-like or too generic to be a product type.
DEFAULT_EXCLUDED_TYPES = (
    "Westlake",
    "Casual",
    "Sets",
    "Clothing",
    "Shoes",
    "Women",
    "Men",
    "Boys",
    "Girls",
    "Baby",
    "Unisex",
    "Accessories",
    "Stud",
    "Bead",
    "Beads",
    "Bottoms",
    "Hoop",
    "Bands",
    "Pendants Only",
    "Novelty",
)
MIN_TYPE_PRICED = 40
MIN_TITLE_OVERLAP = 0.3
ACCEPTABLE_RANGE = (3, 400)
KINDS_CYCLE = (
    "feasible",
    "underspecified",
    "feasible",
    "no_valid_product",
    "underspecified",
    "feasible",
)
PERSONAS = (
    "Practical and brief; answers exactly what is asked.",
    "Friendly and chatty but never changes their requirements.",
    "Busy shopper who gives short answers.",
    "Careful shopper who double-checks details but stays consistent.",
)
EVIDENCE_CONTRACT = (
    "Acceptable means every hard requirement passes on explicit catalogue fields (exact "
    "positive price, explicit detail fields, category-word containment). Missing facts are "
    "unknown and never acceptable. Historical parent-product data does not establish "
    "variant stock or current price."
)


def stem(word):
    word = word.lower()
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]  # sunglasses -> sunglass
    if word.endswith("ss"):
        return word  # glass, dress: not plurals
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def nice_budget(value):
    """Round up to a human budget: 10/25/50 steps."""
    step = 10 if value < 60 else 25 if value < 200 else 50
    return float(math.ceil(value / step) * step)


def quantile(sorted_values, q):
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def load_entries(oracle):
    """One compact record per product; the rows themselves are not retained."""
    entries = []
    for row in oracle.rows():
        categories = [c for c in row.get("categories", []) if isinstance(c, str)]
        if not categories:
            continue
        entries.append(
            {
                "id": row["parent_asin"],
                "leaf": categories[-1],
                "title": str(row.get("title") or ""),
                "facts": raw_facts(row),
            }
        )
    return entries


def eligible_types(entries, excluded):
    leaves = defaultdict(list)
    for e in entries:
        leaves[e["leaf"]].append(e)
    types = []
    for leaf, items in leaves.items():
        if leaf in excluded:
            continue
        priced = [e for e in items if e["facts"]["price"] is not None]
        if len(priced) < MIN_TYPE_PRICED:
            continue
        words = {stem(w) for w in re.findall(r"[A-Za-z]+", leaf) if len(w) > 2}
        if not words:
            continue
        overlap = sum(any(w in norm(e["title"]) for w in words) for e in items) / len(
            items
        )
        if overlap >= MIN_TITLE_OVERLAP:
            types.append((leaf, len(priced)))
    return sorted(types, key=lambda t: (-t[1], t[0]))


GENERIC_WORDS = {
    "fashion",
    "women",
    "womens",
    "mens",
    "girls",
    "boys",
    "casual",
    "other",
    "sets",
}


def cluster_types(leaves):
    """Group leaves that share a product noun ("Necklaces" with "Pendant Necklaces").

    A scenario's scope is every product whose category words contain its type, so related
    leaves overlap in products; keeping each cluster in one split stops that leakage.
    """
    parent = {leaf: leaf for leaf in leaves}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for leaf in sorted(leaves):
        for word in re.findall(r"[A-Za-z]+", leaf):
            word = stem(word)
            if len(word) < 4 or word in GENERIC_WORDS:
                continue
            if word in owner:
                parent[find(leaf)] = find(owner[word])
            else:
                owner[word] = leaf
    clusters = defaultdict(list)
    for leaf in leaves:
        clusters[find(leaf)].append(leaf)
    return [sorted(v) for v in clusters.values()]


def assign_types(types, seed, weights):
    """Deterministic split by family cluster: sort by seeded hash, then deal by weight."""
    clusters = sorted(
        cluster_types([t[0] for t in types]),
        key=lambda c: hashlib.sha256(f"{seed}:{c[0]}".encode()).hexdigest(),
    )
    splits = {name: [] for name in weights}
    total = sum(weights.values())
    cumulative, edges = 0.0, []
    for name, weight in weights.items():
        cumulative += weight / total
        edges.append((name, cumulative))
    for index, cluster in enumerate(clusters):
        position = (index + 0.5) / len(clusters)
        name = next(n for n, edge in edges if position <= edge)
        splits[name].extend(cluster)
    return splits


def grade_all(entries, hard, soft):
    """Grades for every product plus counts; returns (graded, acceptable, unknown)."""
    graded, unknown = [], 0
    for e in entries:
        result = judge(e["facts"], hard, soft)
        if result["hard"] == "unknown":
            unknown += 1
        if result["grade"] > 0:
            graded.append((result["grade"], e))
    graded.sort(key=lambda x: (-x[0], x[1]["id"]))
    return graded, unknown


def fact(key, kind, field, op, value, statement, keywords):
    return Fact(
        key=key,
        kind=kind,
        field=field,
        op=op,
        value=value,
        statement=statement,
        keywords=keywords,
    )


TYPE_KEYWORDS = ["kind", "type", "looking for"]
BUDGET_KEYWORDS = ["budget", "price", "spend", "cost", "afford", "how much"]
DEPT_KEYWORDS = [
    "who",
    "for whom",
    "gender",
    "department",
    "men",
    "women",
    "recipient",
    "wearing",
]
COLOR_KEYWORDS = ["color", "colour", "shade"]
MATERIAL_KEYWORDS = ["material", "fabric", "made of", "leather"]
BRAND_KEYWORDS = ["brand", "maker", "manufacturer"]


def type_fact(leaf):
    return fact(
        "type",
        "hard",
        "product_type",
        "contains",
        leaf.lower(),
        f"I'm looking for {leaf.lower()}.",
        TYPE_KEYWORDS,
    )


def budget_fact(amount):
    return fact(
        "budget",
        "hard",
        "price",
        "lt",
        amount,
        f"My budget is under ${amount:g}.",
        BUDGET_KEYWORDS,
    )


def department_fact(value):
    who = {
        "men": "a man",
        "women": "a woman",
        "boys": "a boy",
        "girls": "a girl",
        "unisex": "anyone, it should be unisex",
    }.get(value, value)
    return fact(
        "department",
        "hard",
        "department",
        "eq",
        value,
        f"It's for {who}.",
        DEPT_KEYWORDS,
    )


def color_fact(value, kind):
    wording = "I'd like it in {}." if kind == "soft" else "It has to be {}."
    return fact(
        "color",
        kind,
        "color",
        "eq",
        value.lower(),
        wording.format(value.lower()),
        COLOR_KEYWORDS,
    )


def material_fact(value, kind="soft"):
    return fact(
        "material",
        kind,
        "material",
        "contains",
        value.lower(),
        f"{value.capitalize()} would be ideal.",
        MATERIAL_KEYWORDS,
    )


def brand_fact(value):
    return fact(
        "brand",
        "hard",
        "brand",
        "eq",
        value.lower(),
        f"It has to be {value}.",
        BRAND_KEYWORDS,
    )


def common_values(pool, field, minimum=3):
    counts = Counter(norm(e["facts"][field]) for e in pool if e["facts"][field])
    return [
        v
        for v, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= minimum
    ]


def impossible_variant(
    pool, all_entries, base_facts, soft, rng
):  # all_entries = type scope
    """A verifiably empty variation of a satisfiable task, plus the changed facts.

    Either a budget below the cheapest known price, or a colour/brand pair that never
    co-occurs although each occurs alone. Returns (facts, unknown_count) or None.
    """
    hard = [f for f in base_facts if f.kind == "hard"]
    priced = sorted(
        e["facts"]["price"] for e in pool if e["facts"]["price"] is not None
    )
    colors = common_values(pool, "color", minimum=3)
    brands = common_values(pool, "brand", minimum=3)
    options = ["budget"] + (["pair"] if colors and brands else [])
    rng.shuffle(options)
    for option in options:
        if option == "budget":
            if priced[0] < 5:  # "under $1" is absurd; use the pair variant instead
                continue
            amount = float(max(2, math.floor(priced[0] * 0.6)))
            changed = [f for f in base_facts if f.key != "budget"] + [
                budget_fact(amount)
            ]
        else:
            changed = None
            for color in colors:
                for brand in brands:
                    kept = [f for f in base_facts if f.key not in {"color", "brand"}]
                    trial = kept + [color_fact(color, "hard"), brand_fact(brand)]
                    only_color, _ = grade_all(
                        all_entries, hard + [color_fact(color, "hard")], []
                    )
                    only_brand, _ = grade_all(
                        all_entries, hard + [brand_fact(brand)], []
                    )
                    both, unknown = grade_all(
                        all_entries,
                        [f for f in trial if f.kind == "hard"],
                        [f for f in trial if f.kind == "soft"],
                    )
                    if not both and len(only_color) >= 3 and len(only_brand) >= 3:
                        changed = trial
                        break
                if changed:
                    break
            if not changed:
                continue
        hard_changed = [f for f in changed if f.kind == "hard"]
        soft = [f for f in changed if f.kind == "soft"]
        empty, unknown = grade_all(all_entries, hard_changed, soft)
        relaxed = [
            f
            for f in hard_changed
            if f.key not in {"color", "brand"} and f.key != "budget"
        ]
        near_miss, _ = grade_all(all_entries, relaxed or hard_changed[:1], soft)
        if not empty and len(near_miss) >= ACCEPTABLE_RANGE[0]:
            return changed, unknown
    return None


def build_scenario(entries_by_leaf, scopes, leaf, kind, rng, serial):
    """Try a few random constraint sets; return (facts, graded, unknown) or None.

    `scopes[leaf]` holds every product whose category words contain the type: a hard
    product-type requirement fails everywhere else, so grading only the scope is exact.
    `unknown` counts in-scope products with an unknown required attribute.
    """
    pool = entries_by_leaf[leaf]
    all_entries = scopes[leaf]
    priced = sorted(
        e["facts"]["price"] for e in pool if e["facts"]["price"] is not None
    )
    departments = [
        d
        for d in common_values(pool, "department")
        if d in {"men", "women", "boys", "girls", "unisex"}
    ]
    colors = common_values(pool, "color", minimum=2)
    materials = common_values(pool, "material", minimum=2)
    brands = common_values(pool, "brand", minimum=3)
    for _ in range(25):
        budget = nice_budget(quantile(priced, rng.uniform(0.35, 0.8)))
        facts = [type_fact(leaf), budget_fact(budget)]
        if departments and rng.random() < 0.7:
            facts.append(department_fact(rng.choice(departments)))
        if colors and rng.random() < 0.8:
            facts.append(color_fact(rng.choice(colors), "soft"))
        if materials and rng.random() < 0.5:
            facts.append(material_fact(rng.choice(materials)))
        if brands and rng.random() < 0.2:
            facts.append(brand_fact(rng.choice(brands)))
        hard = [f for f in facts if f.kind == "hard"]
        soft = [f for f in facts if f.kind == "soft"]
        graded, unknown = grade_all(all_entries, hard, soft)
        if not ACCEPTABLE_RANGE[0] <= len(graded) <= ACCEPTABLE_RANGE[1]:
            continue
        if kind != "no_valid_product":
            return facts, graded, unknown
        variant = impossible_variant(pool, all_entries, facts, soft, rng)
        if variant:
            changed, unknown = variant
            return changed, [], unknown
    return None


def opening_text(kind, facts, rng):
    by_key = {f.key: f for f in facts}
    leaf = by_key["type"].value
    greetings = ("Hi,", "Hello,", "Hey there,", "Good day,")
    hello = rng.choice(greetings)
    if kind == "underspecified":
        keys = ["type"]
        return f"{hello} I need some {leaf}.", keys
    keys = ["type", "budget"]
    return f"{hello} I'm shopping for {leaf} under ${by_key['budget'].value:g}.", keys


def scenario_id(seed, split, serial, facts):
    digest = hashlib.sha256(
        json.dumps(
            [seed, split, serial, [f.model_dump() for f in facts]], sort_keys=True
        ).encode()
    ).hexdigest()
    return f"{split[:3]}-{serial:03d}-{digest[:8]}"


def generate(
    catalogue,
    seed,
    per_split,
    *,
    weights=None,
    excluded=DEFAULT_EXCLUDED_TYPES,
    max_user_turns=6,
):
    """Return (scenarios, ground_truths, manifest). Deterministic for fixed inputs."""
    oracle = CatalogueOracle(catalogue)
    entries = load_entries(oracle)
    weights = weights or DEFAULT_SPLIT_WEIGHTS
    types = eligible_types(entries, set(excluded))
    if not types:
        raise ValueError("Catalogue has no eligible product types")
    assignment = assign_types(types, seed, weights)
    by_leaf = defaultdict(list)
    for e in entries:
        by_leaf[e["leaf"]].append(e)
    scopes = {}
    for leaf in {leaf for names in assignment.values() for leaf in names}:
        wanted = tokens(leaf)
        scopes[leaf] = [
            e for e in entries if wanted <= tokens(e["facts"]["product_type"])
        ]
    scenarios, truths = [], []
    for split, count in per_split.items():
        leaves = assignment.get(split) or []
        if count and not leaves:
            raise ValueError(f"No product families available for split {split!r}")
        rng = random.Random(f"{seed}:{split}")
        produced, attempts, seen = 0, 0, set()
        while produced < count and attempts < count * 20:
            attempts += 1
            leaf = leaves[(produced + attempts) % len(leaves)]
            kind = KINDS_CYCLE[produced % len(KINDS_CYCLE)]
            built = build_scenario(by_leaf, scopes, leaf, kind, rng, produced)
            if built is None:
                continue
            facts, graded, unknown = built
            signature = (
                leaf,
                json.dumps([f.model_dump() for f in facts], sort_keys=True),
            )
            if (
                signature in seen
            ):  # identical tasks would inflate N with dependent samples
                continue
            seen.add(signature)
            ident = scenario_id(seed, split, produced, facts)
            opening, opening_keys = opening_text(kind, facts, rng)
            profile = ShopperProfile(
                scenario_id=ident,
                persona=rng.choice(PERSONAS),
                facts=tuple(facts),
                opening_keys=tuple(opening_keys),
            )
            scenarios.append(
                Scenario(
                    id=ident,
                    split=split,
                    kind=kind,
                    family=leaf,
                    opening=opening,
                    max_user_turns=max_user_turns,
                    profile=profile,
                )
            )
            truths.append(
                GroundTruth(
                    scenario_id=ident,
                    kind=kind,
                    hard=[f for f in facts if f.kind == "hard"],
                    soft=[f for f in facts if f.kind == "soft"],
                    acceptable_count=len(graded),
                    unknown_required_count=unknown,
                    ideal_grades=[g for g, _ in graded[:20]],
                    acceptable_sample=[
                        {"id": e["id"], "title": e["title"][:120], "grade": g}
                        for g, e in graded[:20]
                    ],
                    catalogue_sha256=oracle.sha256,
                    evidence_contract=EVIDENCE_CONTRACT,
                )
            )
            produced += 1
        if produced < count:
            raise ValueError(
                f"Could only build {produced}/{count} scenarios for {split}"
            )
    manifest = {
        "generator_version": VERSION,
        "seed": seed,
        "catalogue_sha256": oracle.sha256,
        "per_split": per_split,
        "split_weights": weights,
        "split_families": {k: sorted(v) for k, v in assignment.items()},
        "counts": {
            f"{split}/{kind}": n
            for (split, kind), n in sorted(
                Counter((s.split, s.kind) for s in scenarios).items()
            )
        },
    }
    return scenarios, truths, manifest


def dump_lines(models):
    return "".join(
        json.dumps(m.model_dump(), ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
        for m in models
    )


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save(directory, scenarios, truths, manifest):
    """Write three files into a NEW directory; frozen sets are never overwritten."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError("Scenario set exists; choose a new directory")
    directory.mkdir(parents=True)
    scenario_text, truth_text = dump_lines(scenarios), dump_lines(truths)
    (directory / "scenarios.jsonl").write_text(scenario_text, encoding="utf-8")
    (directory / "ground_truth.jsonl").write_text(truth_text, encoding="utf-8")
    manifest = {
        **manifest,
        "scenarios_sha256": sha256_text(scenario_text),
        "ground_truth_sha256": sha256_text(truth_text),
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def read_lines(path):
    return [line for line in Path(path).read_text(encoding="utf-8").split("\n") if line]


def load_scenarios(directory, split=None):
    """Scenarios only: the loader the runner uses never touches ground truth."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    text = (directory / "scenarios.jsonl").read_text(encoding="utf-8")
    if sha256_text(text) != manifest["scenarios_sha256"]:
        raise ValueError("Scenario file does not match its manifest")
    scenarios = [
        Scenario.model_validate_json(line) for line in text.split("\n") if line
    ]
    return [s for s in scenarios if split in (None, s.split)], manifest


def load_ground_truth(directory):
    """Scorer-side loader; verifies the frozen hash."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    text = (directory / "ground_truth.jsonl").read_text(encoding="utf-8")
    if sha256_text(text) != manifest["ground_truth_sha256"]:
        raise ValueError("Ground truth does not match its manifest")
    return {
        t.scenario_id: t
        for t in (
            GroundTruth.model_validate_json(line) for line in text.split("\n") if line
        )
    }
