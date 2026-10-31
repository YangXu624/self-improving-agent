"""Initial source-rule evidence checks, independent of runtime matching.

This is not a general shopping-preference judge. The declared pilot intents are exact
source categories plus explicit metadata. Public task rules contain no product IDs;
generated ID judgments stay in ignored data, outside all model-context construction.
Exact taxonomy is only an annotation seed: final natural-intent relevance requires an
independent reviewed pool and source witnesses. It is not exhaustive semantic ground truth.
"""

import math
import re
from decimal import Decimal


def text(value):
    return " ".join(str(value).casefold().split())


def raw_fact(row, field):
    """Read the declared source contract without importing retrieval.project/assess."""
    if field == "price":
        value = row.get("price")
        if isinstance(value, str):
            if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value.strip()):
                return None, "price"
            value = float(value)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            return None, "price"
        return float(value), "price"
    names = {
        "department": ("Department",),
        "brand": ("Brand", "Brand Name"),
        "material": ("Material", "Material Type"),
        "color": ("Color", "Colour"),
        "size": ("Size",),
    }
    details = row.get("details") or {}
    for name in names[field]:
        value = details.get(name)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip(), "details." + name
    return None, "details." + names[field][0]


def hard_check(row, requirement):
    field, op, expected = (requirement[k] for k in ("field", "op", "value"))
    if field == "product_type":
        categories = row.get("categories") or []
        known = bool(categories)
        value = categories if known else None
        actual_words = set(re.findall(r"\w+", text(" ".join(categories))))
        wanted_words = set(re.findall(r"\w+", text(expected)))
        passed = wanted_words <= actual_words
        return {
            "field": field,
            "source": "categories",
            "value": value,
            "verdict": "unknown" if not known else "pass" if passed else "fail",
        }
    actual, source = raw_fact(row, field)
    if actual is None:
        return {"field": field, "source": source, "value": None, "verdict": "unknown"}
    if field == "price":
        a, b = Decimal(str(actual)), Decimal(str(expected))
        passed = {"lt": a < b, "lte": a <= b, "eq": a == b, "gte": a >= b, "gt": a > b}[
            op
        ]
    else:
        a, b = text(actual), text(expected)
        if field == "department":
            aliases = {
                "mens": "men",
                "men's": "men",
                "womens": "women",
                "women's": "women",
            }
            a, b = aliases.get(a, a), aliases.get(b, b)
        if op == "eq":
            passed = a == b
        elif op == "neq":
            passed = a != b
        elif op == "contains":
            passed = set(re.findall(r"\w+", b)) <= set(re.findall(r"\w+", a))
        else:
            raise ValueError("Unsupported pilot predicate")
    return {
        "field": field,
        "source": source,
        "value": actual,
        "verdict": "pass" if passed else "fail",
    }


def judge(row, task):
    category = task["relevance"]["category"]
    category_match = category in (row.get("categories") or [])
    checks = [
        hard_check(row, r)
        for r in task["requirements"]
        if r.get("strength", "hard") == "hard"
    ]
    unknown = any(c["verdict"] == "unknown" for c in checks)
    failed = any(c["verdict"] == "fail" for c in checks)
    return {
        "relevant": category_match and not unknown and not failed,
        "category_match": category_match,
        "hard_verdict": "fail" if failed else "unknown" if unknown else "pass",
        "category_evidence": {
            "source": "categories",
            "value": row.get("categories", []),
        },
        "hard_checks": checks,
    }
