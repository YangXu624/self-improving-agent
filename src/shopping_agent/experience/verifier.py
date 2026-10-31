"""Deterministic verification that an emitted Decision conformed to procedural guidance."""

from typing import Any

from ..contracts import Decision
from .models import Lesson


def verify_decision_application(decision: Decision, lesson: Lesson) -> bool:
    """Check if the decision matches the lesson's expected action and structural signature.

    Returns True only if observable decision fields demonstrate application of the directive.
    """
    action = decision.action
    if action.type != lesson.expected_action:
        return False

    sig: dict[str, Any] = lesson.action_signature
    if not sig:
        return True

    if action.type == "SEARCH":
        query = (action.query or "").lower()
        forbidden_terms = sig.get("query_not_contains", [])
        if any(term.lower() in query for term in forbidden_terms):
            return False

        required_terms = sig.get("query_contains", [])
        if any(term.lower() not in query for term in required_terms):
            return False

        if "mode" in sig and action.mode != sig["mode"]:
            return False

    elif action.type == "CLARIFY":
        if "attribute" in sig and action.attribute != sig["attribute"]:
            return False
        if "attribute_in" in sig and action.attribute not in sig["attribute_in"]:
            return False

    elif action.type == "RECOMMEND":
        if "min_products" in sig and len(action.product_ids) < sig["min_products"]:
            return False
        if "max_products" in sig and len(action.product_ids) > sig["max_products"]:
            return False

    return True
