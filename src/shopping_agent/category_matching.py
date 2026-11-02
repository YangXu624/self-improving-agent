"""Bounded English number inflection for category evidence, never semantic synonyms.

Only product-type category matching uses this. Prices, brands, colors and keywords retain
literal matching. Compound terms such as wristwatch are deliberately not inferred.
"""

import re


def forms(word: str) -> set[str]:
    w = word.casefold()
    result = {w}
    if w in ("clothes", "clothing", "clothe"):
        result.update({"clothes", "clothing", "clothe"})
    if w in ("workout", "activewear", "athletic", "active"):
        result.update({"workout", "activewear", "athletic", "active"})
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is", "ous")):
        result.add(w[:-1])
        if w.endswith(("ches", "shes", "sses", "xes", "zes")):
            result.add(w[:-2])
        if w.endswith("ies") and len(w) > 4:
            result.add(w[:-3] + "y")
    return result


def category_contains(value: str, expected: str) -> bool:
    available = [forms(w) for w in re.findall(r"\w+", value.casefold())]
    wanted = [forms(w) for w in re.findall(r"\w+", expected.casefold())]
    return bool(wanted) and all(any(q & actual for actual in available) for q in wanted)
