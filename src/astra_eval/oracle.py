"""Independent catalogue judge: raw rows and exact rules, not the agent's retrieval code.

Deliberately re-implements the small amount of matching logic the scenarios need so the
scorer does not share a bug with the shopping agent's hard gate. A test cross-checks the two
on fixtures. Missing attributes are unknown and can never satisfy a hard requirement.
"""

import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

DETAIL_NAMES = {
    "department": ("Department",),
    "brand": ("Brand", "Brand Name"),
    "color": ("Color", "Colour"),
    "material": ("Material", "Material Type"),
    "size": ("Size",),
}
DEPARTMENT_ALIASES = {
    "mens": "men",
    "men's": "men",
    "womens": "women",
    "women's": "women",
    "unisex-adult": "unisex",
    "unisex adult": "unisex",
}


def norm(text):
    # NFKC folds full-width and compatibility characters ("ｂｌａｃｋ" -> "black").
    return " ".join(unicodedata.normalize("NFKC", str(text)).casefold().split())


def tokens(text):
    return set(re.findall(r"\w+", norm(text)))


def positive_price(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value.strip()):
            return None
        value = float(value)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def raw_facts(row):
    """Structured facts straight from a catalogue row; None means unknown."""
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    facts = {"price": positive_price(row.get("price"))}
    for field, names in DETAIL_NAMES.items():
        value = next(
            (
                str(details[n]).strip()
                for n in names
                if isinstance(details.get(n), (str, int, float))
                and not isinstance(details.get(n), bool)
                and str(details[n]).strip()
            ),
            None,
        )
        if value is not None and field == "department":
            value = DEPARTMENT_ALIASES.get(norm(value), norm(value))
        facts[field] = value
    categories = [c for c in row.get("categories", []) if isinstance(c, str)]
    facts["product_type"] = " ".join(categories) if categories else None
    return facts


def _compare(value, op, expected, field):
    """True/False for a known value under one operator."""
    if field == "price":
        a, b = Decimal(str(value)), Decimal(str(expected))
        return {
            "eq": a == b,
            "neq": a != b,
            "lt": a < b,
            "lte": a <= b,
            "gt": a > b,
            "gte": a >= b,
        }[op]
    text = norm(value)
    wanted = expected if isinstance(expected, list) else [expected]
    wanted = [
        DEPARTMENT_ALIASES.get(norm(w), norm(w)) if field == "department" else norm(w)
        for w in wanted
    ]
    if field == "product_type" or op in {"contains", "not_contains"}:
        present = any(tokens(w) <= tokens(text) for w in wanted)
        return present if op in {"contains", "eq", "in"} else not present
    if op in {"eq", "in"}:
        return text in wanted
    if op in {"neq", "not_in"}:
        return text not in wanted
    raise ValueError("Unsupported operator for this field")


def verdict(facts, fact):
    """pass / fail / unknown for one Fact against a row's raw facts."""
    value = facts.get(fact.field)
    if value is None:
        return "unknown"
    return "pass" if _compare(value, fact.op, fact.value, fact.field) else "fail"


def judge(facts, hard, soft):
    """Grade 0-3 with verdicts. 0 = a hard fact fails or is unknown."""
    hard_verdicts = [verdict(facts, f) for f in hard]
    soft_verdicts = [verdict(facts, f) for f in soft]
    if "fail" in hard_verdicts:
        status = "fail"
    elif "unknown" in hard_verdicts:
        status = "unknown"
    else:
        status = "pass"
    if status != "pass":
        grade = 0
    elif not soft:
        grade = 3
    else:
        grade = 1 + round(2 * soft_verdicts.count("pass") / len(soft))
    return {
        "hard": status,
        "grade": grade,
        "hard_verdicts": hard_verdicts,
        "soft_verdicts": soft_verdicts,
    }


class CatalogueOracle:
    """Random access to raw rows by product ID without holding the catalogue in memory."""

    def __init__(self, path):
        self.path = Path(path)
        self.sha256 = file_sha256(self.path)
        self._offsets = None

    def _index(self):
        if self._offsets is None:
            offsets, position = {}, 0
            with self.path.open("rb") as handle:
                for line in handle:
                    if line.strip():
                        offsets[json.loads(line)["parent_asin"]] = position
                    position += len(line)
            self._offsets = offsets
        return self._offsets

    def row(self, product_id):
        offsets = self._index()
        if product_id not in offsets:
            return None
        with self.path.open("rb") as handle:
            handle.seek(offsets[product_id])
            return json.loads(handle.readline())

    def rows(self):
        """Stream every row; physical newlines only (U+2028 is valid inside strings)."""
        with self.path.open("rb") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
