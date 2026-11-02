"""Explicit offline demonstration model and synthetic catalogue; never a live fallback."""

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class DemoModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "astra-offline-demo"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        context = json.loads(messages[-1].content)
        result = context["latest_search"]
        if result and result["candidates"]:
            name = "recommend_products"
            action = {
                "type": "RECOMMEND",
                "search_id": result["search_id"],
                "product_ids": [p["id"] for p in result["candidates"]][:2],
            }
        elif context["remaining_budget"]["searches"] == 2:
            name, action = "search_products", {"type": "SEARCH", "query": "boots"}
        else:
            name, action = "respond", {"type": "RESPOND", "message": "No demo matches."}
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "id": f"demo-{context['remaining_budget']['model_calls']}",
                    "args": {
                        "based_on_state_version": context["state"]["version"],
                        "updates": [],
                        "action": action,
                        "reason": "Explicit offline demo fixture",
                    },
                    "type": "tool_call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def catalogue() -> list[dict]:
    return [
        {
            "parent_asin": f"demo-{i}",
            "title": "Hiking boots",
            "features": ["walking outdoors"],
            "description": [],
            "categories": ["Shoes", "Boots"],
            "details": {"Color": color},
            "price": price,
            "average_rating": 4.5,
            "rating_number": 20,
            "store": "demo",
        }
        for i, (price, color) in enumerate([(45, "Red"), (80, "Blue")])
    ]
