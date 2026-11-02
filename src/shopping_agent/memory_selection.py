"""Two-stage memory selection: Broad semantic candidate retrieval followed by

contextual applicability assessment.

Explicitly separates:
1. Candidate memories retrieved (Stage A)
2. Memories selected as applicable (Stage B)
3. Memories actually applied in recommendations
4. Memories deliberately ignored, with reasons
"""

import re
from typing import Literal

from pydantic import Field

from .contracts import ShoppingState, Strict
from .state import normalized


class MemoryApplicability(Strict):
    """Structured assessment of a candidate memory's relevance to the current shopping goal."""

    memory_id: str
    applicability: Literal["relevant", "irrelevant", "conflicting"] = "relevant"
    use_policy: Literal["soft_preference", "ignore", "do_not_use"] = "soft_preference"
    reason: str = Field(default="", max_length=500)
    conflict_with_current_request: bool = False


CATEGORY_SYNONYMS = {
    "clothing": {
        "clothing",
        "apparel",
        "wear",
        "shirt",
        "pants",
        "suit",
        "jacket",
        "activewear",
    },
    "workout clothing": {
        "workout",
        "gym",
        "athletic",
        "running",
        "fitness",
        "activewear",
        "training",
        "exercise",
        "shirt",
        "top",
        "shorts",
        "leggings",
    },
    "bags": {
        "bag",
        "bags",
        "backpack",
        "tote",
        "duffel",
        "purse",
        "handbag",
        "luggage",
    },
    "shoes": {"shoes", "shoe", "sneakers", "boots", "footwear", "runners", "sandals"},
    "formalwear": {
        "formal",
        "suit",
        "tuxedo",
        "blazer",
        "dress shirt",
        "gown",
        "evening",
    },
}


def _detect_gift_or_other_recipient(
    message: str, state: ShoppingState | None
) -> tuple[bool, str]:
    """Determine if current shopping request is for someone else."""
    if state and hasattr(state, "requirements"):
        for req in state.requirements:
            if req.status == "active" and req.field == "recipient":
                val = str(req.value or "").strip().lower()
                if val and val not in {"self", "me"}:
                    return True, f"shopping for {val}"

    gift_patterns = [
        (
            r"\b(?:for\s+my\s+(sister|brother|mom|dad|mother|father|niece|nephew|friend|daughter|son|wife|husband))\b",
            "someone else",
        ),
        (r"\b(?:gift\s+for|present\s+for|buying\s+for)\s+([a-z]+)\b", "gift recipient"),
    ]
    for pattern, label in gift_patterns:
        m = re.search(pattern, message, re.I)
        if m:
            recipient = m.group(1).lower()
            if recipient not in {"myself", "me", "self"}:
                return True, f"shopping for {recipient}"

    return False, ""


def assess_memory_applicability(
    candidates: list[dict],
    message: str,
    state: ShoppingState | None = None,
    *,
    policy: object | None = None,
) -> list[MemoryApplicability]:
    """Assess whether retrieved candidate memories apply to the current shopping request.

    Evaluates:
    - Target domain/product category applicability
    - Recipient context (personal preference vs gift for someone else)
    - Direct conflicts with customer's current explicit instructions
    - Degree of persistence (explicit preference vs weak inference vs contextual history)
    """
    if not candidates:
        return []

    is_other_recipient, recipient_desc = _detect_gift_or_other_recipient(message, state)

    # Active hard requirements and explicit constraints from current state
    state_reqs = {}
    if state and hasattr(state, "requirements"):
        for r in state.requirements:
            if getattr(r, "status", None) == "active":
                state_reqs.setdefault(r.field, []).append(r)

    query_text = normalized(message)
    active_product_types = [
        normalized(str(r.value)) for r in state_reqs.get("product_type", [])
    ]
    combined_query = query_text + " " + " ".join(active_product_types)
    query_words = set(re.findall(r"\w+", combined_query.casefold()))

    assessments: list[MemoryApplicability] = []

    for cand in candidates:
        mem_id = cand.get("id", "")
        cat = cand.get("category", "preference")
        attr = cand.get("attribute", "")
        val = normalized(str(cand.get("value", "")))
        scope = normalized(str(cand.get("scope", "general")))
        strength = cand.get("strength", "soft")
        evidence_type = cand.get("evidence_type", "explicit")

        # 1. Recipient check: If customer is shopping for someone else, personal preferences do not apply
        if is_other_recipient and cat in {"preference", "dislike", "fact"}:
            assessments.append(
                MemoryApplicability(
                    memory_id=mem_id,
                    applicability="conflicting",
                    use_policy="do_not_use",
                    reason=f"Current request is a gift ({recipient_desc}); customer's personal preferences do not apply.",
                    conflict_with_current_request=True,
                )
            )
            continue

        # 2. Direct contradiction check with current explicit request
        has_direct_conflict = False
        conflict_reason = ""
        if attr in state_reqs:
            for req in state_reqs[attr]:
                req_val = normalized(str(req.value or ""))
                # If current state explicitly negates this memory value
                if req.op in {"neq", "not_contains", "not_in"} and (
                    val in req_val or req_val in val
                ):
                    has_direct_conflict = True
                    conflict_reason = (
                        f"Current requirement explicitly excludes '{val}'."
                    )
                    break
                # If current state explicitly requires a different value
                if req.op in {"eq", "contains", "in"}:
                    if val != req_val and val not in req_val and req_val not in val:
                        has_direct_conflict = True
                        conflict_reason = f"Current requirement specifies '{req_val}', overriding historical '{val}'."
                        break

        # Also check message text for direct negation or explicit choice of a different attribute value
        if not has_direct_conflict and attr == "color":
            # If user explicitly asks for "red" or "blue" in message, but memory is "black"
            color_matches = [
                w
                for w in [
                    "red",
                    "blue",
                    "green",
                    "white",
                    "yellow",
                    "pink",
                    "brown",
                    "navy",
                    "grey",
                    "gray",
                ]
                if w in query_words
            ]
            if (
                color_matches
                and val in ["black", "white", "blue", "red", "green"]
                and val not in color_matches
            ):
                has_direct_conflict = True
                conflict_reason = f"Current request explicitly asks for {color_matches[0]}, overriding historical {val}."

        if has_direct_conflict:
            assessments.append(
                MemoryApplicability(
                    memory_id=mem_id,
                    applicability="conflicting",
                    use_policy="do_not_use",
                    reason=conflict_reason,
                    conflict_with_current_request=True,
                )
            )
            continue

        # 3. Domain and Category Scope Relevance Check
        if scope and scope not in {"general", "all", "any"}:
            scope_syns = CATEGORY_SYNONYMS.get(
                scope, {w for w in re.findall(r"\w+", scope) if len(w) > 2}
            )
            query_stems = {
                w.rstrip("s") for w in query_words if len(w) > 2
            } | query_words
            scope_stems = {w.rstrip("s") for w in scope_syns if len(w) > 2} | scope_syns
            overlap = scope_stems.intersection(query_stems)

            # Special case: Formal suit vs workout clothing
            if "formal" in query_words or "suit" in query_words:
                if (
                    scope == "workout clothing"
                    or "workout" in scope_syns
                    or "gym" in scope_syns
                ):
                    assessments.append(
                        MemoryApplicability(
                            memory_id=mem_id,
                            applicability="irrelevant",
                            use_policy="ignore",
                            reason=f"Historical preference for {scope} is irrelevant when shopping for formalwear/suits.",
                            conflict_with_current_request=False,
                        )
                    )
                    continue

            # Special case: Workout clothing for gym shirts
            if (
                "gym" in query_words or "workout" in query_words
            ) and scope == "workout clothing":
                overlap = {"workout"}

            if not overlap:
                # If neither scope words nor related synonyms appear in current request/product_type
                # check if there's any broad category match
                assessments.append(
                    MemoryApplicability(
                        memory_id=mem_id,
                        applicability="irrelevant",
                        use_policy="ignore",
                        reason=f"Memory scope '{scope}' does not match the current product request.",
                        conflict_with_current_request=False,
                    )
                )
                continue

        # 4. Contextual & episodic shopping history
        if cat == "contextual":
            # If shopping for the same domain (e.g. bags)
            scope_words = set(re.findall(r"\w+", scope))
            if scope_words & query_words or scope in {"general", "all"}:
                assessments.append(
                    MemoryApplicability(
                        memory_id=mem_id,
                        applicability="relevant",
                        use_policy="soft_preference",
                        reason="Contextual shopping history matches current domain.",
                        conflict_with_current_request=False,
                    )
                )
            else:
                assessments.append(
                    MemoryApplicability(
                        memory_id=mem_id,
                        applicability="irrelevant",
                        use_policy="ignore",
                        reason=f"Contextual shopping history for {scope} is not relevant to current query.",
                        conflict_with_current_request=False,
                    )
                )
            continue

        # 5. Applicable soft preference
        evidence_desc = (
            f" ({evidence_type} {strength})" if evidence_type or strength else ""
        )
        assessments.append(
            MemoryApplicability(
                memory_id=mem_id,
                applicability="relevant",
                use_policy="soft_preference",
                reason=f"Relevant historical {cat}{evidence_desc} for {attr}: {val}.",
                conflict_with_current_request=False,
            )
        )

    return assessments
