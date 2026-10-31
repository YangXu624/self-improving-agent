"""Explicit demo policy: limited phrase matching, real tool results, no network or LLM.

This is a UI demonstration adapter, never a silent fallback for DeepSeek. It recognises
common product types, simple USD upper budgets, colours/materials and explicit new goals.
It does not claim general natural-language understanding or experience learning.
"""

import json
import re

from .provider import PolicyReply

TYPES = (
    "hiking boots",
    "running shoes",
    "backpack",
    "sneakers",
    "sandals",
    "handbag",
    "jacket",
    "dress",
    "boots",
    "shoes",
    "shirt",
    "jeans",
    "socks",
    "wallet",
    "belt",
    "watch",
)
COLOURS = (
    "black",
    "white",
    "red",
    "blue",
    "green",
    "brown",
    "beige",
    "pink",
    "grey",
    "gray",
)
MATERIALS = ("leather", "cotton", "wool", "linen", "polyester", "nylon")
BUDGET = re.compile(
    r"\b(under|below|less than|at most|up to|max(?:imum)?(?: of)?|budget(?: is| of)?)\s*\$?\s*(\d+(?:\.\d{1,2})?)(?:\s*USD)?\b",
    re.I,
)


def _match(words: tuple[str, ...], message: str) -> re.Match | None:
    return re.search(
        r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", message, re.I
    )


class MockShoppingPolicy:
    """Stateless DecisionPolicy implementation for the local, explicitly labelled UI demo."""

    def complete(self, messages: list[dict]) -> PolicyReply:
        context = json.loads(messages[-1]["content"])
        action, updates = self._decide(context)
        value = {
            "based_on_state_version": context["state"]["version"],
            "updates": updates,
            "action": action,
            "reason": "Scripted mock decision for the UI demonstration",
        }
        return PolicyReply(
            json.dumps(value),
            {"provider": "mock", "model": "scripted-demo-v1", "usage": {}},
        )

    def _decide(self, context: dict) -> tuple[dict, list[dict]]:
        if context["validation_feedback"] or context["state"]["conflicts"]:
            return {
                "type": "CLARIFY",
                "attribute": "product_type",
                "question": "I couldn't apply that safely in this demo. Please inspect the shopping state, or start a new chat.",
            }, []
        if not context["edits_allowed"]:
            result = context["latest_search"]
            if result and result["candidates"]:
                return {
                    "type": "RECOMMEND",
                    "search_id": result["search_id"],
                    "product_ids": [p["id"] for p in result["candidates"][:3]],
                }, []
            return {
                "type": "RESPOND",
                "message": "No verified matches came back for that search with your current requirements. Try another product type or explicitly change your budget, colour or material.",
            }, []

        message = context["current_user_message"]
        active = list(context["state"]["requirements"])
        updates: list[dict] = []
        new_goal = re.search(r"\bnew (?:goal|search)\s*:", message, re.I)
        if new_goal:
            updates.append({"op": "NEW_GOAL", "quote": new_goal.group()})
            active = []

        def set_field(
            field: str, op: str, value: str | float, quote: str, strength: str = "hard"
        ) -> None:
            # Optional preferences never retire an existing hard requirement.
            old = next(
                (
                    r
                    for r in active
                    if r["field"] == field and r["strength"] == strength
                ),
                None,
            )
            update = {
                "op": "REPLACE" if old else "ADD",
                "quote": quote,
                "requirement": {
                    "field": field,
                    "op": op,
                    "value": value,
                    "quote": quote,
                    "strength": strength,
                },
            }
            if old:
                update["target_id"] = old["id"]
            updates.append(update)

        kind = _match(TYPES, message)
        if kind:
            set_field("product_type", "contains", kind.group().lower(), kind.group())
        budget = BUDGET.search(message)
        if budget:
            op = (
                "lt"
                if budget.group(1).lower() in {"under", "below", "less than"}
                else "lte"
            )
            set_field("price", op, float(budget.group(2)), budget.group())
        elif re.fullmatch(r"\s*\$?\d+(?:\.\d{1,2})?(?:\s*USD)?\s*", message, re.I):
            # A numeric answer is accepted only after a budget clarification.
            prior = next(
                (
                    h
                    for h in reversed(context["recent_dialogue"][:-1])
                    if h["role"] == "assistant"
                ),
                None,
            )
            if (
                prior
                and isinstance(prior["content"], dict)
                and prior["content"].get("attribute") == "price"
            ):
                value = float(re.sub(r"[^\d.]", "", message))
                set_field("price", "lte", value, message.strip())

        withdrawal = re.search(
            r"\b(?:leather is (?:okay|ok|fine)|allow leather)\b", message, re.I
        )
        if withdrawal:
            for old in active:
                if (
                    old["field"] == "material"
                    and old["op"] in {"neq", "not_contains", "not_in"}
                    and old["value"] == "leather"
                ):
                    updates.append(
                        {
                            "op": "RETRACT",
                            "target_id": old["id"],
                            "quote": withdrawal.group(),
                        }
                    )
        for field, words in [("color", COLOURS), ("material", MATERIALS)]:
            match = _match(words, message)
            if not match or (field == "material" and withdrawal):
                continue
            value = match.group().lower()
            negative = re.search(
                r"\b(?:no|not)\s+" + re.escape(value) + r"\b", message, re.I
            )
            if negative:
                set_field(field, "not_contains", value, negative.group())
            else:
                soft = bool(
                    re.search(
                        r"\b(?:prefer|ideally)\s+(?:\w+\s+){0,2}"
                        + re.escape(value)
                        + r"\b",
                        message,
                        re.I,
                    )
                )
                set_field(
                    field, "contains", value, match.group(), "soft" if soft else "hard"
                )

        type_update = next(
            (
                u["requirement"]["value"]
                for u in updates
                if u.get("requirement", {}).get("field") == "product_type"
            ),
            None,
        )
        current_type = next(
            (r["value"] for r in active if r["field"] == "product_type"), None
        )
        query = type_update or current_type
        if not query:
            return {
                "type": "CLARIFY",
                "attribute": "product_type",
                "question": "What would you like to find? Try boots, a backpack, a dress or a jacket. You can include a USD budget.",
            }, updates
        if not updates:
            if re.search(r"\b(thanks|thank you)\b", message, re.I):
                return {
                    "type": "RESPOND",
                    "message": "You're welcome. Your shopping requirements are saved in this chat.",
                }, []
            return {
                "type": "RESPOND",
                "message": "This scripted demo supports a product type, an upper USD budget, colour/material, 'no leather', 'leather is okay', and 'new goal: ...'. Try 'under $60' or 'prefer red'.",
            }, []
        return {"type": "SEARCH", "query": str(query), "limit": 6}, updates
