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
        return False

    if action.type == "SEARCH":
        matched_any = False
        if "mode" in sig:
            if action.mode != sig["mode"]:
                return False
            matched_any = True

        query = (action.query or "").lower()
        if "query_not_contains" in sig:
            forbidden_terms = sig["query_not_contains"]
            if any(term.lower() in query for term in forbidden_terms):
                return False
            matched_any = True

        if "query_contains" in sig:
            required_terms = sig["query_contains"]
            if any(term.lower() not in query for term in required_terms):
                return False
            matched_any = True

        return matched_any

    elif action.type == "CLARIFY":
        matched_any = False
        if "attribute" in sig:
            if action.attribute != sig["attribute"]:
                return False
            matched_any = True
        if "attribute_in" in sig:
            if action.attribute not in sig["attribute_in"]:
                return False
            matched_any = True
        return matched_any

    elif action.type == "RECOMMEND":
        matched_any = False
        if "min_products" in sig:
            if len(action.product_ids) < sig["min_products"]:
                return False
            matched_any = True
        if "max_products" in sig:
            if len(action.product_ids) > sig["max_products"]:
                return False
            matched_any = True
        return matched_any

    elif action.type == "RESPOND":
        matched_any = False
        if "message_contains" in sig:
            msg = (action.message or "").lower()
            if any(term.lower() not in msg for term in sig["message_contains"]):
                return False
            matched_any = True
        return matched_any

    return False
