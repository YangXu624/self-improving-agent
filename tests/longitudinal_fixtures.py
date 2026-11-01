"""Small synthetic customer data and policies for offline longitudinal acceptance."""

import json
import re
from pathlib import Path

import eval_fixtures as F
from test_retrieval import product

from astra_eval.customers import CustomerDataset, validate_dataset
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import build_index, file_hash


def fact(key, field, value, statement, kind="soft", op="eq"):
    return {
        "key": key,
        "field": field,
        "value": value,
        "statement": statement,
        "kind": kind,
        "op": op,
        "keywords": ["color", "colour"] if field == "color" else [field, "budget"],
    }


def make_dataset(root: Path, *, second_customer=False):
    catalogue, index = root / "catalog.jsonl", root / "index.sqlite"
    catalogue.write_text(
        "".join(
            json.dumps(product(color.lower(), price, Color=color, Material="Nylon"))
            + "\n"
            for color, price in [("Blue", 30), ("Red", 35), ("Green", 40)]
        )
    )
    build_index(catalogue, index)
    preference = {
        "category": "preference",
        "scope": "boots",
        "fact": fact("color", "color", "Blue", "I generally prefer Blue boots."),
    }
    changed = {
        **preference,
        "fact": fact(
            "color",
            "color",
            "Red",
            "Actually I now generally prefer Red boots instead of Blue.",
        ),
    }
    visits = []
    for seq in range(1, 5):
        category_statement = "I need boots."
        extra = (
            preference["fact"]["statement"]
            if seq == 1
            else changed["fact"]["statement"]
            if seq == 3
            else "This is a gift for my friend."
            if seq == 4
            else ""
        )
        visits.append(
            {
                "task_id": f"visit-{seq}",
                "sequence": seq,
                "goal": f"Shopping visit {seq}",
                "category": "boots",
                "recipient": "gift" if seq == 4 else "self",
                "evaluation_mode": "target_item" if seq in {2, 3} else "preference",
                "opening": category_statement + (" " + extra if extra else ""),
                "opening_keys": ["type", "color"] if seq in {1, 3} else ["type"],
                "disclosure": {
                    1: "progressive",
                    2: "recall_probe",
                    3: "announce_change",
                    4: "gift",
                }[seq],
                "hard": [
                    fact(
                        "type",
                        "product_type",
                        "boots",
                        category_statement,
                        "hard",
                        "contains",
                    ),
                    fact(
                        "budget", "price", 60.0, "My budget is under $60.", "hard", "lt"
                    ),
                ],
                "soft": [
                    fact("gift_color", "color", "Green", "My friend prefers Green.")
                ]
                if seq == 4
                else [],
                "persistent_keys": [] if seq == 4 else ["color"],
                "witness_id": "green" if seq == 4 else "red" if seq == 3 else "blue",
                "max_user_turns": 6,
            }
        )
    customer = {
        "user_id": "alice",
        "personality": "Careful and direct.",
        "background": "private-current-background",
        "preferences": [preference],
        "changes": [
            {
                "before_sequence": 3,
                "updates": [changed],
                "background": "private-future-change",
            }
        ],
        "visits": visits,
    }
    data = CustomerDataset.model_validate(
        {
            "dataset_id": "synthetic-development",
            "catalogue_sha256": file_hash(catalogue),
            "provenance": "Synthetic unit-test fixture",
            "customers": [customer],
        }
    )
    if second_customer:
        other = data.customers[0].model_copy(deep=True)
        other.user_id = "bob"
        for visit in other.visits:
            visit.task_id = "bob-" + visit.task_id
        data.customers.append(other)
    validate_dataset(data, catalogue, require_evidence=False)
    path = root / "customers.json"
    path.write_text(data.model_dump_json(indent=2))
    return path, catalogue, index, data


class MemoryPolicy(F.HeuristicPolicy):
    """Only reads real policy context; never receives a private customer or target."""

    model = "mock-deepseek"

    def __init__(self):
        super().__init__(ask_department=False)

    def complete(self, messages):
        reply = super().complete(messages)
        value = json.loads(reply.content)
        context = json.loads(messages[-1]["content"])
        message = context["current_user_message"]
        memory = context.get("user_memory")
        if memory is not None and context["edits_allowed"]:
            match = re.search(
                r"(?:Actually I now generally prefer (Red) boots instead of Blue\.|I generally prefer (Blue) boots\.)",
                message,
            )
            if match:
                target = next(
                    (r for r in memory["records"] if r["attribute"] == "color"), None
                )
                value["user_memory_updates"] = [
                    {
                        "op": "REPLACE" if target else "ADD",
                        "category": "preference",
                        "attribute": "color",
                        "value": match.group(1) or match.group(2),
                        "scope": "boots",
                        "basis": "confirmed",
                        "quote": match.group(0),
                        "target_id": target["id"] if target else None,
                    }
                ]
        if value["action"]["type"] == "RECOMMEND" and memory:
            color = next(
                (r["value"] for r in memory["records"] if r["attribute"] == "color"),
                None,
            )
            if color:
                candidates = sorted(
                    context["latest_search"]["candidates"],
                    key=lambda p: (
                        str(p.get("facts", {}).get("color", "")).casefold()
                        != color.casefold()
                    ),
                )
                value["action"]["product_ids"] = [p["id"] for p in candidates][:3]
        return PolicyReply(json.dumps(value), reply.metadata)
