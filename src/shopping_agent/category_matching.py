"""Bounded English number inflection for category evidence, never semantic synonyms.

Only product-type category matching uses this. Prices, brands, colors and keywords retain
literal matching. Compound terms such as wristwatch are deliberately not inferred.
"""

import re


def forms(word: str) -> set[str]:
    result = {word}
    if (
        len(word) > 3
        and word.endswith("s")
        and not word.endswith(("ss", "us", "is", "ous"))
    ):
        result.add(word[:-1])
        if word.endswith(("ches", "shes", "sses", "xes", "zes")):
            result.add(word[:-2])
        if word.endswith("ies") and len(word) > 4:
            result.add(word[:-3] + "y")
    return result


def category_contains(value: str, expected: str) -> bool:
    available = [forms(w) for w in re.findall(r"\w+", value.casefold())]
    wanted = [forms(w) for w in re.findall(r"\w+", expected.casefold())]
    return bool(wanted) and all(any(q & actual for actual in available) for q in wanted)
