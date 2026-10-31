"""Deterministic checks that a simulated shopper stayed faithful to its hidden profile.

Lexical on purpose: cheap, explainable and independent of any LLM. Errors trigger one
re-ask with feedback and then invalidate the session (a simulator fault, not an agent
fault); warnings are only logged. These checks measure whether Llama is reliable enough;
they are not a proof of consistency.
"""

import re
from dataclasses import dataclass

from .models import ShopperProfile, ShopperReply
from .oracle import tokens

COLORS = {
    "black",
    "white",
    "red",
    "blue",
    "green",
    "yellow",
    "pink",
    "purple",
    "orange",
    "brown",
    "grey",
    "gray",
    "silver",
    "gold",
    "navy",
    "beige",
    "tan",
    "multicolor",
    "multicolored",
    "multicoloured",
    "ivory",
    "burgundy",
    "teal",
    "turquoise",
}
MATERIALS = {
    "cotton",
    "leather",
    "polyester",
    "wool",
    "silk",
    "denim",
    "nylon",
    "linen",
    "suede",
    "rubber",
    "canvas",
    "plastic",
    "metal",
    "steel",
    "silicone",
    "velvet",
    "satin",
}
# Words a shopper uses for a department, mapped to one canonical value so "a woman" agrees
# with a profile value of "women" but contradicts "men".
DEPARTMENT_WORDS = {
    "man": "men",
    "men": "men",
    "mens": "men",
    "male": "men",
    "gentleman": "men",
    "woman": "women",
    "women": "women",
    "womens": "women",
    "female": "women",
    "ladies": "women",
    "lady": "women",
    "boy": "boys",
    "boys": "boys",
    "girl": "girls",
    "girls": "girls",
    "unisex": "unisex",
}
ID_PATTERN = re.compile(r"\bB0[0-9A-Z]{8}\b|\b\d{9}[\dX]\b")
PRICE_PATTERN = re.compile(
    r"\$\s?(\d+(?:[.,]\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s?(?:usd|dollars|bucks)\b", re.I
)


@dataclass(frozen=True)
class Violation:
    code: str
    level: str  # "error" | "warning"
    detail: str = ""


@dataclass(frozen=True)
class ConsistencyConfig:
    max_reveals: int = 2
    check_vocabulary: bool = True


def departments_in(words):
    return {DEPARTMENT_WORDS[w] for w in words if w in DEPARTMENT_WORDS}


def prices_in(text):
    found = []
    for a, b in PRICE_PATTERN.findall(text):
        found.append(float((a or b).replace(",", ".")))
    return found


def profile_prices(profile):
    values = []
    for f in profile.facts:
        if f.field == "price":
            values.extend(
                float(v) for v in (f.value if isinstance(f.value, list) else [f.value])
            )
    return values


def fact_words(fact):
    words = set()
    for v in fact.value if isinstance(fact.value, list) else [fact.value]:
        words |= tokens(v)
    return words


def profile_words(profile):
    words = set()
    for f in profile.facts:
        words |= fact_words(f)
    return words


def check_reply(
    reply: ShopperReply,
    profile: ShopperProfile,
    *,
    shown_text="",
    shown_prices=(),
    has_products=False,
    forbidden=(),
    config=ConsistencyConfig(),
):
    """Return a list of Violations for one structured reply."""
    out = []
    keys = {f.key for f in profile.facts}
    unknown = [k for k in reply.reveals if k not in keys]
    if unknown:
        out.append(Violation("reveals_unknown_key", "error", ",".join(unknown)))
    if len(set(reply.reveals)) > config.max_reveals:
        out.append(
            Violation("over_reveal", "error", f"{len(set(reply.reveals))} facts")
        )
    message_words = tokens(reply.message)
    allowed_prices = {round(p, 2) for p in [*profile_prices(profile), *shown_prices]}
    for price in prices_in(reply.message):
        if round(price, 2) not in allowed_prices:
            out.append(Violation("price_not_in_profile", "error", f"{price:g}"))
    if config.check_vocabulary:
        allowed = profile_words(profile) | tokens(shown_text)
        for name, vocabulary in (
            ("color", COLORS),
            ("material", MATERIALS),
            ("department", set(DEPARTMENT_WORDS)),
        ):
            if name == "department":
                mentioned = departments_in(message_words) - departments_in(allowed)
            else:
                mentioned = (message_words & vocabulary) - allowed
            if mentioned:
                have = [f for f in profile.facts if f.field == name]
                code = "contradicts_profile" if have else "invented_attribute"
                out.append(Violation(code, "error", f"{name}: {sorted(mentioned)}"))
    for key in reply.reveals:
        fact = profile.fact(key)
        if fact is not None and fact.field in {"color", "material", "brand", "size"}:
            wanted = fact_words(fact)
            if wanted and not (wanted & message_words) and not prices_in(reply.message):
                out.append(Violation("claimed_reveal_missing", "warning", key))
    if ID_PATTERN.search(reply.message) or any(
        s and s.lower() in reply.message.lower() for s in forbidden
    ):
        out.append(
            Violation("target_leak", "error", "product identifier or title in message")
        )
    if reply.action == "accept" and not has_products:
        out.append(Violation("accepted_without_recommendation", "warning"))
    return out


def errors(violations):
    return [v for v in violations if v.level == "error"]
