"""Deterministic checks that a simulated shopper stayed faithful to its hidden profile.

Lexical on purpose: cheap, explainable and independent of any LLM. Errors trigger one
re-ask with feedback and then invalidate the session (a simulator fault, not an agent
fault); warnings are only logged. These checks measure whether Llama is reliable enough;
they are not a proof of consistency.
"""

import re
import unicodedata
from dataclasses import dataclass

from .models import ShopperProfile, ShopperReply
from .oracle import norm, tokens

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
    "guy": "men",
    "guys": "men",
    "husband": "men",
    "dad": "men",
    "father": "men",
    "boyfriend": "men",
    "wife": "women",
    "mom": "women",
    "mother": "women",
    "girlfriend": "women",
    "son": "boys",
    "daughter": "girls",
}
ID_PATTERN = re.compile(r"\bB0[0-9A-Z]{8}\b|\b\d{9}[\dX]\b", re.I)
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
PRICE_PATTERN = re.compile(
    rf"\$\s?({NUMBER})|({NUMBER})\s?(?:usd|dollars|bucks)\b", re.I
)
NEGATIONS = {"not", "no", "never", "without", "non", "t"}  # "t" is the n't of "don't"
CANONICAL_COLORS = {
    "gray": "grey",
    "multicolored": "multicolor",
    "multicoloured": "multicolor",
}


@dataclass(frozen=True)
class Violation:
    code: str
    level: str  # "error" | "warning"
    detail: str = ""


@dataclass(frozen=True)
class ConsistencyConfig:
    max_reveals: int = 2
    check_vocabulary: bool = True


def canonical_words(words):
    return {CANONICAL_COLORS.get(w, w) for w in words}


def departments_in(words):
    return {DEPARTMENT_WORDS[w] for w in words if w in DEPARTMENT_WORDS}


def prices_in(text):
    found = []
    for a, b in PRICE_PATTERN.findall(text):
        found.append(float((a or b).replace(",", "")))
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


def numbers_in(text):
    return {
        float(n.replace(",", ""))
        for n in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", text)
    }


def check_reply(
    reply: ShopperReply,
    profile: ShopperProfile,
    *,
    shown_text="",
    shown_titles="",
    shown_prices=(),
    has_products=False,
    forbidden=(),
    config=ConsistencyConfig(),
):
    """Return a list of Violations for one structured reply.

    `shown_text` is ASTRA's message, `shown_titles` the product cards the shopper can see.
    Echoing a card is fine; adopting an attribute that only ASTRA suggested is a warning;
    contradicting a profile attribute is always an error, even if ASTRA mentioned it.
    """
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
    # A word right after "not"/"no"/"without"/"n't" is excluded, not requested ("not for men").
    ordered = re.findall(r"\w+", norm(reply.message))
    negated = {
        w
        for i, token in enumerate(ordered)
        if token in NEGATIONS
        for w in ordered[i + 1 : i + 4]
    }
    positive_words = message_words - negated
    allowed_prices = {round(p, 2) for p in [*profile_prices(profile), *shown_prices]}
    for price in prices_in(reply.message):
        if round(price, 2) not in allowed_prices:
            out.append(Violation("price_not_in_profile", "error", f"{price:g}"))
    if config.check_vocabulary:
        profile_w, title_w, assistant_w = (
            profile_words(profile),
            tokens(shown_titles),
            tokens(shown_text),
        )
        for name, vocabulary in (
            ("color", COLORS),
            ("material", MATERIALS),
            ("department", set(DEPARTMENT_WORDS)),
        ):
            if name == "department":
                mentioned, in_profile, in_titles, in_assistant = (
                    departments_in(positive_words),
                    departments_in(profile_w),
                    departments_in(title_w),
                    departments_in(assistant_w),
                )
            else:
                canon = canonical_words if name == "color" else (lambda w: w)
                mentioned, in_profile, in_titles, in_assistant = (
                    canon(positive_words) & vocabulary,
                    canon(profile_w) & vocabulary,
                    canon(title_w) & vocabulary,
                    canon(assistant_w) & vocabulary,
                )
            if any(f.field == name for f in profile.facts):
                bad = mentioned - in_profile - in_titles
                if bad:
                    out.append(
                        Violation(
                            "contradicts_profile", "error", f"{name}: {sorted(bad)}"
                        )
                    )
                continue
            bad = mentioned - in_titles
            if bad - in_assistant:
                out.append(
                    Violation(
                        "invented_attribute",
                        "error",
                        f"{name}: {sorted(bad - in_assistant)}",
                    )
                )
            if bad & in_assistant:
                out.append(
                    Violation(
                        "adopted_assistant_suggestion",
                        "warning",
                        f"{name}: {sorted(bad & in_assistant)}",
                    )
                )
    for key in reply.reveals:
        fact = profile.fact(key)
        if fact is None or key in unknown:
            continue
        if fact.field in {"color", "material", "brand", "size"}:
            stated = bool(fact_words(fact) & message_words)
        elif fact.field == "price":
            stated = any(
                abs(n - float(v)) < 0.01
                for n in numbers_in(reply.message)
                for v in (fact.value if isinstance(fact.value, list) else [fact.value])
            )
        elif fact.field == "department":
            stated = bool(
                departments_in(fact_words(fact)) & departments_in(message_words)
            )
        else:
            stated = True
        if not stated:
            out.append(Violation("claimed_reveal_missing", "warning", key))
    shown = (shown_text + " " + shown_titles).lower()
    leaked_titles = [
        s
        for s in forbidden
        if s and s.lower() in reply.message.lower() and s.lower() not in shown
    ]
    if ID_PATTERN.search(reply.message) or leaked_titles:
        out.append(
            Violation("target_leak", "error", "product identifier or title in message")
        )
    if reply.action == "accept" and not has_products:
        out.append(Violation("accepted_without_recommendation", "warning"))
    return out


def errors(violations):
    return [v for v in violations if v.level == "error"]


def target_disclosures(reply, memory):
    """Conservative literal disclosure evidence for the target protocol, not an LLM judge.

    Declared keys alone never establish a disclosure. Repeating known facts is harmless;
    the bound concerns genuinely new information. Paraphrases may remain unverified.
    """
    supported, flags = [], []
    norm_msg = unicodedata.normalize("NFKC", reply.message)
    words = tokens(norm_msg)
    ordered = re.findall(r"\w+", norm(norm_msg))
    negated = {
        w
        for i, token in enumerate(ordered)
        if token in NEGATIONS
        for w in ordered[i + 1 : i + 4]
    }
    positive_words = words - negated
    for fact in memory.profile.facts:
        f_words = (
            canonical_words(fact_words(fact))
            if fact.field == "color"
            else fact_words(fact)
        )
        pos_words = (
            canonical_words(positive_words) if fact.field == "color" else positive_words
        )
        if fact.field == "price":
            stated = any(
                abs(float(fact.value) - n) < 0.01 for n in numbers_in(norm_msg)
            )
            val = float(fact.value)
            val_str = f"{val:g}"
            val_pattern = re.escape(val_str)
            if val.is_integer() and val >= 1000:
                thousands = f"{int(val):,}"
                val_pattern = rf"(?:{re.escape(val_str)}|{re.escape(thousands)})"
            opposite = re.search(
                r"\b(over|above|at least|more than)\s*\$?\s*" + val_pattern + r"\b",
                norm_msg,
                re.I,
            )
            below = re.search(
                r"\b(under|below|at most|less than)\s*\$?\s*" + val_pattern + r"\b",
                norm_msg,
                re.I,
            )
            if opposite and fact.op in {"lt", "lte"}:
                flags.append(
                    Violation("contradicts_budget_operator", "error", fact.key)
                )
                stated = False
            elif below and fact.op in {"gt", "gte"}:
                flags.append(
                    Violation("contradicts_budget_operator", "error", fact.key)
                )
                stated = False
        elif fact.field == "department":
            stated = bool(
                departments_in(fact_words(fact)) & departments_in(positive_words)
            )
        else:
            stated = bool(f_words) and f_words <= pos_words
        if stated:
            supported.append(fact.key)
        elif fact.key in reply.reveals:
            flags.append(Violation("claimed_reveal_missing", "warning", fact.key))
    new = set(supported) - set(memory.revealed)
    if len(new) > 2:
        flags.append(
            Violation("over_reveal", "error", "More than two new facts in message")
        )
    if set(supported) - set(reply.reveals):
        flags.append(
            Violation(
                "unclaimed_disclosure",
                "warning",
                "Message states more than its declared keys",
            )
        )
    return supported, flags
