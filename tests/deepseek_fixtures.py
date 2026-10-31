"""Deterministic HTTP responses for tests only; no application import or fallback.

These fixtures prescribe decisions for exact synthetic test messages. They do not test
natural-language understanding and never contact DeepSeek or use a local credential file.
"""

import io
import json
from pathlib import Path

from shopping_agent.provider import DeepSeekPolicy
from shopping_agent.ui_service import ChatService

TEST_KEY = "test-only-deepseek-key"


def service(catalogue: Path, index: Path, sessions: Path) -> ChatService:
    return ChatService(
        catalogue,
        index,
        sessions,
        policy=DeepSeekPolicy(api_key=TEST_KEY, model="deepseek-flash"),
    )


def completion(request, timeout):
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    body = json.loads(request.data)
    context = json.loads(body["messages"][-1]["content"])
    action, updates = fixture_decision(context)
    decision = {
        "based_on_state_version": context["state"]["version"],
        "updates": updates,
        "action": action,
        "reason": "Synthetic HTTP test fixture",
    }
    return io.BytesIO(
        json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": json.dumps(decision)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 30,
                    "total_tokens": 130,
                },
            }
        ).encode()
    )


def fixture_decision(context):
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
            "message": "No verified matches for these requirements.",
        }, []
    message = context["current_user_message"]
    state = context["state"]["requirements"]
    edits = []

    def set_field(field, op, value, quote, strength="hard"):
        old = next(
            (r for r in state if r["field"] == field and r["strength"] == strength),
            None,
        )
        change = {
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
            change["target_id"] = old["id"]
        edits.append(change)

    if message == "hello":
        return {
            "type": "CLARIFY",
            "attribute": "product_type",
            "question": "What would you like to find?",
        }, []
    if message == "please teleport it":
        return {
            "type": "RESPOND",
            "message": "Please tell me more about what you need.",
        }, []
    cases = {
        "boots": [("product_type", "contains", "boots", "boots")],
        "boots under $100": [
            ("product_type", "contains", "boots", "boots"),
            ("price", "lt", 100.0, "under $100"),
        ],
        "boots under $60": [
            ("product_type", "contains", "boots", "boots"),
            ("price", "lt", 60.0, "under $60"),
        ],
        "boots under $1": [
            ("product_type", "contains", "boots", "boots"),
            ("price", "lt", 1.0, "under $1"),
        ],
        "red boots under $100": [
            ("product_type", "contains", "boots", "boots"),
            ("price", "lt", 100.0, "under $100"),
            ("color", "contains", "red", "red"),
        ],
        "boots under $100 no leather": [
            ("product_type", "contains", "boots", "boots"),
            ("price", "lt", 100.0, "under $100"),
            ("material", "not_contains", "leather", "no leather"),
        ],
        "actually under $60": [("price", "lt", 60.0, "under $60")],
        "under $60": [("price", "lt", 60.0, "under $60")],
        "prefer blue": [("color", "contains", "blue", "blue", "soft")],
        '<img src=x onerror="alert(1)"> boots under $60': [
            ("product_type", "contains", "boots", "boots"),
            ("price", "lt", 60.0, "under $60"),
        ],
    }
    if message == "new goal: backpack":
        edits.append({"op": "NEW_GOAL", "quote": "new goal: backpack"})
        state = []
        set_field("product_type", "contains", "backpack", "backpack")
    elif message == "leather is okay":
        old = next(r for r in state if r["field"] == "material")
        edits.append({"op": "RETRACT", "target_id": old["id"], "quote": message})
    else:
        if message not in cases:
            raise AssertionError("Unspecified HTTP test message")
        for change in cases[message]:
            set_field(*change)
    kind = next(
        (
            u["requirement"]["value"]
            for u in edits
            if u.get("requirement", {}).get("field") == "product_type"
        ),
        None,
    )
    kind = kind or next(
        (r["value"] for r in state if r["field"] == "product_type"), "boots"
    )
    return {"type": "SEARCH", "query": kind, "limit": 6}, edits
