"""Apply evidence-linked edits without erasing superseded requirements."""

import re
from decimal import Decimal
from itertools import product
from uuid import uuid4

from .category_matching import category_contains
from .contracts import NUMERIC, Requirement, ShoppingState, StateUpdate


class StateError(ValueError):
    pass


def normalized(text):
    return " ".join(text.casefold().split())


def has_evidence(quote):
    """A quote must contain a letter or digit; blank/invisible/punctuation-only text is none."""
    return any(ch.isalnum() for ch in quote)


# Department aliases mirror retrieval.facet so conflict checks agree with the eligibility
# gate. Tests pin both department alias tables.
DEPARTMENT_ALIASES = {
    "mens": "men",
    "men's": "men",
    "womens": "women",
    "women's": "women",
    "unisex-adult": "unisex",
    "unisex adult": "unisex",
}
MAX_TYPE_COMBINATIONS = 4096


def canonical(field, value):
    text = normalized(str(value))
    return DEPARTMENT_ALIASES.get(text, text) if field == "department" else text


def type_conflict(rows):
    """Prove a product_type contradiction using the gate's category-number semantics.

    The gate treats eq/in/contains as "category text contains every token of one
    alternative" and neq/not_in/not_contains as "contains none of these token sets".
    A category can hold any token union, so only a forbidden set that is covered by
    the chosen positives is contradictory. Unprovable (oversized) cases are not flagged.
    """

    def tokens(value):
        return frozenset(re.findall(r"\w+", normalized(str(value))))

    positives, forbidden = [], []
    for r in rows:
        values = r.value if isinstance(r.value, list) else [r.value]
        sets = [tokens(v) for v in values]
        if r.op in {"eq", "in", "contains"}:
            positives.append(sets)
        elif r.op in {"neq", "not_in", "not_contains"}:
            forbidden.extend(sets)
    if not (positives and forbidden):
        return False
    # Sufficient and cheap: a positive group whose every alternative is already banned.
    if any(
        all(
            any(category_contains(" ".join(alt), " ".join(b)) for b in forbidden)
            for alt in group
        )
        for group in positives
    ):
        return True
    positives = list({tuple(group) for group in positives})
    count = 1
    for group in positives:
        count *= len(group)
    if count > MAX_TYPE_COMBINATIONS:
        return False
    return not any(
        not any(
            category_contains(" ".join(set().union(*choice)), " ".join(banned))
            for banned in forbidden
        )
        for choice in product(*positives)
    )


def conflicts(requirements):
    found = []
    fields = {
        r.field for r in requirements if r.status == "active" and r.strength == "hard"
    }
    for field in sorted(fields):
        rows = [
            r
            for r in requirements
            if r.status == "active" and r.strength == "hard" and r.field == field
        ]
        if field in NUMERIC:
            low, high, low_open, high_open = (
                Decimal(0),
                Decimal("Infinity"),
                False,
                False,
            )
            for r in rows:
                v = Decimal(str(r.value))
                if r.op in {"gt", "gte", "eq"}:
                    if v > low:
                        low, low_open = v, r.op == "gt"
                    elif v == low:
                        low_open |= r.op == "gt"
                if r.op in {"lt", "lte", "eq"}:
                    if v < high:
                        high, high_open = v, r.op == "lt"
                    elif v == high:
                        high_open |= r.op == "lt"
            if (
                low > high
                or low == high
                and (
                    low_open
                    or high_open
                    or any(r.op == "neq" and Decimal(str(r.value)) == low for r in rows)
                )
            ):
                found.append(field)
        elif field == "product_type":
            if type_conflict(rows):
                found.append(field)
        else:
            allowed, excluded = None, set()
            for r in rows:
                values = (
                    {canonical(field, v) for v in r.value}
                    if isinstance(r.value, list)
                    else {canonical(field, r.value)}
                )
                if r.op in {"eq", "in"}:
                    allowed = values if allowed is None else allowed & values
                elif r.op in {"neq", "not_in"}:
                    excluded |= values
            if allowed is not None and not allowed - excluded:
                found.append(field)
            positives = {canonical(field, r.value) for r in rows if r.op == "contains"}
            negatives = {
                canonical(field, r.value) for r in rows if r.op == "not_contains"
            }
            if positives & negatives and field not in found:
                found.append(field)
    return found


def apply_updates(state, updates, *, expected_version, user_message, source_event_id):
    state = ShoppingState.model_validate(state.model_dump())
    if expected_version != state.version:
        raise StateError("stale_state_version")
    result = state.model_copy(deep=True)
    changed = False
    for raw in updates:
        u = StateUpdate.model_validate(
            raw.model_dump() if hasattr(raw, "model_dump") else raw
        )
        # An empty normalized quote is a substring of every message: it is no evidence.
        if not has_evidence(u.quote) or normalized(u.quote) not in normalized(
            user_message
        ):
            raise StateError("edit_evidence_not_in_current_user_message")
        if u.requirement and (
            not has_evidence(u.requirement.quote)
            or normalized(u.requirement.quote) not in normalized(user_message)
        ):
            raise StateError("requirement_evidence_not_in_current_user_message")
        if (
            u.requirement
            and u.requirement.field == "color"
            and u.requirement.strength == "hard"
        ):
            color_values = (
                u.requirement.value
                if isinstance(u.requirement.value, list)
                else [u.requirement.value]
            )
            clauses = re.split(r"[.;!?]", normalized(user_message))
            quote = " ".join(
                c for c in clauses if any(normalized(str(v)) in c for v in color_values)
            ) or normalized(u.requirement.quote)
            # Explicit hard language wins; otherwise conditional availability is a preference.
            hard = re.search(
                r"\b(?:must|required|require|non.?negotiable|only (?!a preference))\b",
                quote,
            )
            conditional = re.search(
                r"\b(?:if (?:you have|available|possible|in stock)|ideally|prefer|preference|would be nice)\b",
                quote,
            )
            if conditional and not hard:
                raise StateError("conditional_color_requires_soft_preference")
        if u.op == "NEW_GOAL":
            for r in result.requirements:
                if r.status == "active":
                    r.status = "superseded"
            result.goal_epoch += 1
            changed = True
            continue
        target = next(
            (
                r
                for r in result.requirements
                if r.id == u.target_id and r.status == "active"
            ),
            None,
        )
        if u.op in {"REPLACE", "RETRACT"} and target is None:
            raise StateError("target_is_not_an_active_requirement")
        if u.op == "RETRACT":
            target.status = "retracted"
            changed = True
            continue
        if target and target.field != u.requirement.field:
            raise StateError("replacement_must_modify_same_field")
        if target:
            target.status = "superseded"
        spec = u.requirement.model_dump()
        if u.op == "ADD" and any(
            r.status == "active"
            and all(
                getattr(r, k) == spec[k] for k in ["field", "op", "value", "strength"]
            )
            for r in result.requirements
        ):
            continue
        result.requirements.append(
            Requirement(
                **spec,
                id=uuid4().hex,
                source_event_id=source_event_id,
                created_version=state.version + 1,
                replaces_id=u.target_id,
            )
        )
        changed = True
    if changed:
        result.version += 1
        result.conflicts = conflicts(result.requirements)
    return ShoppingState.model_validate(result.model_dump())
