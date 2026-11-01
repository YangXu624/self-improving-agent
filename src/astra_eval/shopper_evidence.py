"""Conservative dialogue evidence, independent of the shopper model and scoring.

Recognized contradictions are errors. Unrecognized paraphrases remain explicitly
unverified; this bounded English checker is not a general semantic consistency proof.
"""

import re
from dataclasses import dataclass

from .consistency import (
    COLORS,
    DEPARTMENT_WORDS,
    MATERIALS,
    Violation,
    canonical_words,
    check_reply,
)
from .models import ShopperProfile, ShopperReply
from .oracle import norm, tokens

AUDITOR_VERSION = "dialogue-evidence-v3-1"
NUMBER_WORDS = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(20),
        strict=True,
    )
) | dict(
    zip(
        "twenty thirty forty fifty sixty seventy eighty ninety".split(),
        range(20, 100, 10),
        strict=True,
    )
)
NEGATIVE = re.compile(r"\b(?:no|not|without|avoid|dislike|hate|never)\b")
INTENT = re.compile(
    r"\b(?:want|need|prefer|rather|preference|looking for|find|show|keep|budget|cap|maximum|limit)\b"
)


@dataclass(frozen=True)
class DialogueEvidence:
    verified: tuple[str, ...]
    observations: list[dict]
    violations: list[Violation]


def value_words(value, field: str) -> set[str]:
    values = value if isinstance(value, list) else [value]
    words = set().union(*(tokens(v) for v in values))
    if field == "color":
        return canonical_words(words)
    if field == "department":
        return {DEPARTMENT_WORDS.get(w, w) for w in words}
    if field == "product_type":
        return {
            w[:-1] if w.endswith("s") and not w.endswith(("ss", "us", "is")) else w
            for w in words
        }
    return words


def negated_value(text: str, wanted: set[str], field: str) -> bool:
    """Attach nearby negation to the value, not to every attribute in the sentence."""
    words = re.findall(r"[\w']+", text)
    indexes = [i for i, word in enumerate(words) if value_words(word, field) & wanted]
    for index in indexes:
        prefix = words[max(0, index - 3) : index]
        for boundary in ("and", "but"):
            if boundary in prefix:
                prefix = prefix[len(prefix) - prefix[::-1].index(boundary) :]
        if NEGATIVE.search(" ".join(prefix)):
            return True
        if " ".join(words[index + 1 : index + 4]).startswith(("is not", "isn't")):
            return True
    return False


def amounts(text: str) -> list[float]:
    result = [
        float(n.replace(",", ""))
        for n in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", text)
    ]
    pattern = (
        r"\b("
        + "|".join(NUMBER_WORDS)
        + r")(?:[- ](one|two|three|four|five|six|seven|eight|nine))?\b"
    )
    for match in re.finditer(pattern, text):
        first = NUMBER_WORDS[match[1]]
        result.append(
            float(first + (NUMBER_WORDS[match[2]] if match[2] and first >= 20 else 0))
        )
    return result


def derive_disclosures(
    message: str,
    profile: ShopperProfile,
    *,
    assistant_text: str = "",
    shown_titles: str = "",
    shown_prices=(),
    forbidden=(),
) -> DialogueEvidence:
    # Reuse identity/unsupported-price guards without accepting model-supplied labels.
    base = check_reply(
        ShopperReply(message=message),
        profile,
        shown_titles=shown_titles,
        shown_prices=shown_prices,
        forbidden=forbidden,
    )
    violations = [v for v in base if v.code in {"target_leak", "price_not_in_profile"}]
    verified, observations = [], []
    clauses = list(re.finditer(r".+?(?:[.!?;,](?:\s+|$)|\s+but\s+|$)", message, re.S))
    for fact in profile.facts:
        status, evidence = "unverified", None
        for match in clauses:
            raw = match.group()
            text = norm(raw).replace("don't", "do not").replace("don’t", "do not")
            # Explicit past preferences are not current requirements after a change.
            if re.search(r"\b(?:used to|previously|in the past)\b", text):
                continue
            # Questions about a product and quoted assistant statements are not preferences.
            short_answer = len(tokens(text)) <= 4 and not text.rstrip().endswith("?")
            assertive = bool(INTENT.search(text)) or short_answer
            if not assertive or re.search(
                r"\b(?:you said|does (?:it|that)|is (?:it|that)|(?:they|these|those|it|that) (?:are|is|look|seem))\b",
                text,
            ):
                continue
            negative = bool(NEGATIVE.search(text))
            if fact.field == "price":
                values = amounts(text)
                relation = (
                    "lte"
                    if re.search(r"\b(?:at most|up to|no more than)\b", text)
                    else "gte"
                    if re.search(r"\b(?:at least|no less than)\b", text)
                    else "lt"
                    if re.search(r"\b(?:under|below|less than)\b", text)
                    else "gt"
                    if re.search(r"\b(?:over|above|more than)\b", text)
                    else "eq"
                    if "exactly" in tokens(text)
                    else None
                )
                budget_context = (
                    bool(re.search(r"\b(?:budget|cap|maximum|limit|spend)\b", text))
                    or relation is not None
                )
                if not values or not budget_context:
                    continue
                if (
                    float(fact.value) not in values
                    or (relation in {"gt", "gte"} and fact.op in {"lt", "lte"})
                    or (relation in {"lt", "lte"} and fact.op in {"gt", "gte"})
                ):
                    status = "contradicted"
                elif relation == fact.op:
                    status = "verified"
                else:
                    continue  # Boundary/intent ambiguity is not silently equated.
            else:
                wanted = value_words(fact.value, fact.field)
                mentioned = value_words(text, fact.field)
                if wanted and wanted <= mentioned:
                    expects_negative = fact.op in {"neq", "not_contains", "not_in"}
                    status = (
                        "verified"
                        if negated_value(text, wanted, fact.field) == expects_negative
                        else "contradicted"
                    )
                else:
                    vocabulary = (
                        COLORS
                        if fact.field == "color"
                        else MATERIALS
                        if fact.field == "material"
                        else set(DEPARTMENT_WORDS)
                        if fact.field == "department"
                        else set()
                    )
                    alternatives = value_words(text, fact.field) & value_words(
                        list(vocabulary), fact.field
                    )
                    if (
                        alternatives - wanted
                        and (
                            short_answer
                            or re.search(r"\b(?:want|need|prefer|rather)\b", text)
                        )
                        and not negative
                    ):
                        status = "contradicted"
                    elif re.search(
                        r"\b(?:no (?:strong )?preference|do not have (?:a )?(?:strong )?preference)\b",
                        text,
                    ) and re.search(
                        r"\b(?:color|colour)\b"
                        if fact.field == "color"
                        else rf"\b{fact.field}\b",
                        assistant_text,
                        re.I,
                    ):
                        status = "contradicted"
                    else:
                        continue
            evidence = {"start": match.start(), "end": match.end(), "text": raw}
            if status == "contradicted":
                break
        observations.append(
            {
                "key": fact.key,
                "field": fact.field,
                "status": status,
                "evidence": evidence,
            }
        )
        if status == "verified":
            verified.append(fact.key)
        elif status == "contradicted":
            violations.append(Violation("contradicts_profile", "error", fact.key))
    # Explicit new color/material requirements absent from the frozen facts are unsupported.
    for match in clauses:
        text = norm(match.group())
        if not re.search(r"\b(?:want|need|prefer|rather)\b", text):
            continue
        for field, vocabulary in (("color", COLORS), ("material", MATERIALS)):
            if (
                not any(f.field == field for f in profile.facts)
                and tokens(text) & vocabulary
            ):
                violations.append(Violation("unsupported_requirement", "error", field))
    unique = {(v.code, v.detail): v for v in violations}
    return DialogueEvidence(tuple(verified), observations, list(unique.values()))
