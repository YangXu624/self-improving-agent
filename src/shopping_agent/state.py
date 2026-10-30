"""Apply evidence-linked edits without erasing superseded requirements."""

from decimal import Decimal
from uuid import uuid4

from .contracts import NUMERIC, Requirement, ShoppingState, StateUpdate


class StateError(ValueError):
    pass


def normalized(text):
    return " ".join(text.casefold().split())


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
        else:
            allowed, excluded = None, set()
            for r in rows:
                values = (
                    {normalized(v) for v in r.value}
                    if isinstance(r.value, list)
                    else {normalized(r.value)}
                )
                if r.op in {"eq", "in"}:
                    allowed = values if allowed is None else allowed & values
                elif r.op in {"neq", "not_in"}:
                    excluded |= values
            if allowed is not None and not allowed - excluded:
                found.append(field)
            positives = {normalized(r.value) for r in rows if r.op == "contains"}
            negatives = {normalized(r.value) for r in rows if r.op == "not_contains"}
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
        if normalized(u.quote) not in normalized(user_message):
            raise StateError("edit_evidence_not_in_current_user_message")
        if u.requirement and normalized(u.requirement.quote) not in normalized(
            user_message
        ):
            raise StateError("requirement_evidence_not_in_current_user_message")
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
