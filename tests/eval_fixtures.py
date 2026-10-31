"""Offline fixtures for the simulated-shopper evaluation: no Ollama, no DeepSeek, no network.

The decision policies here are TEST-ONLY stand-ins for DeepSeek (the application has no
scripted policy). FakeOllama stands in for Ollama's /api/chat.
"""

import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from shopping_agent.provider import PolicyReply, ProviderError
from shopping_agent.retrieval import LexicalSearch, build_index, file_hash
from shopping_agent.sessions import SessionStore

TYPES = [
    "Boots",
    "Sandals",
    "Sneakers",
    "Watches",
    "Hoodies",
    "Jackets",
    "Scarves",
    "Gloves",
]
COLORS = ["Black", "Red", "Blue", "Brown"]
MATERIALS = ["Leather", "Cotton", "Wool", "Nylon"]
BRANDS = ["Acme", "Zenith", "Orbit"]
DEPARTMENTS = ["Men", "Women"]


def catalogue_rows(per_type=60):
    rows = []
    for t_index, leaf in enumerate(TYPES):
        for i in range(per_type):
            department = DEPARTMENTS[i % 2]
            details = {"Department": department}
            if i % 5 != 4:
                details["Color"] = COLORS[(i // 2) % len(COLORS)]
            if i % 3 != 2:
                details["Material"] = MATERIALS[(i // 3) % len(MATERIALS)]
            if i % 4 == 0:
                details["Brand"] = BRANDS[(i // 4) % len(BRANDS)]
            rows.append(
                {
                    "parent_asin": f"B0{t_index}{i:07d}",
                    "title": f"{details.get('Color', '')} {leaf[:-1]} {leaf} model {i}".strip(),
                    "features": [f"Comfortable {leaf.lower()}"],
                    "description": [],
                    "categories": ["Clothing, Shoes & Jewelry", department, leaf],
                    "details": details,
                    # one in six has no usable price: unknown, never acceptable
                    "price": None if i % 6 == 5 else float(10 + (i * 7) % 90),
                    "average_rating": 4.2,
                    "rating_number": 12,
                    "store": "Not a brand",
                }
            )
    return rows


class EvalCase(unittest.TestCase):
    """Synthetic catalogue, BM25 index, session store: shared by evaluation tests."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.catalogue = root / "catalog.jsonl"
        cls.catalogue.write_text(
            "".join(json.dumps(r) + "\n" for r in catalogue_rows())
        )
        cls.index = root / "index.sqlite"
        build_index(cls.catalogue, cls.index)
        cls.catalogue_sha = file_hash(cls.catalogue)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.search = LexicalSearch(
            self.index, expected_catalogue_hash=self.catalogue_sha
        )
        self.addCleanup(self.search.close)
        self.store = SessionStore(self.root / "sessions")


def decision(ctx, action, updates=None, reason="fixture"):
    return {
        "based_on_state_version": ctx["state"]["version"],
        "updates": updates or [],
        "action": action,
        "reason": reason,
    }


def update(field, op, value, quote, strength="hard"):
    return {
        "op": "ADD",
        "quote": quote,
        "requirement": {
            "field": field,
            "op": op,
            "value": value,
            "strength": strength,
            "quote": quote,
        },
    }


class HeuristicPolicy:
    """Minimal rule-based ASTRA policy: extract, ask for what is missing, search, recommend."""

    def __init__(self, *, ignore=(), ask_department=True, usage=True):
        self.ignore, self.ask_department, self.usage = (
            set(ignore),
            ask_department,
            usage,
        )
        self.contexts = []

    def extract(self, message, existing):
        out = []
        have = {r["field"] for r in existing}
        lowered = message.lower()
        for leaf in TYPES:
            if "product_type" not in have and "product_type" not in self.ignore:
                m = re.search(re.escape(leaf.lower()), lowered)
                if m:
                    out.append(
                        update(
                            "product_type",
                            "contains",
                            leaf.lower(),
                            message[m.start() : m.end()],
                        )
                    )
                    break
        m = re.search(r"under \$(\d+(?:\.\d+)?)", message)
        if m and "price" not in have and "price" not in self.ignore:
            out.append(update("price", "lt", float(m.group(1)), m.group(0)))
        m = re.search(r"for (a man|a woman)", lowered)
        if m and "department" not in have and "department" not in self.ignore:
            out.append(
                update(
                    "department",
                    "eq",
                    "women" if "woman" in m.group(1) else "men",
                    message[m.start() : m.end()],
                )
            )
        m = re.search(r"in (black|red|blue|brown)", lowered)
        if m and "color" not in have and "color" not in self.ignore:
            out.append(
                update("color", "eq", m.group(1), message[m.start() : m.end()], "soft")
            )
        return out

    def complete(self, messages):
        ctx = json.loads(messages[-1]["content"])
        self.contexts.append(ctx)
        message = ctx["current_user_message"]
        existing = ctx["state"]["requirements"]
        updates = self.extract(message, existing) if ctx["edits_allowed"] else []
        fields = {r["field"] for r in existing} | {
            u["requirement"]["field"] for u in updates
        }
        said = " ".join(
            m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            for m in ctx["recent_dialogue"]
            if m["role"] == "assistant"
        ).lower()
        result = ctx["latest_search"]
        if (
            result
            and result["state_version"] == ctx["state"]["version"]
            and not updates
        ):
            ids = [p["id"] for p in result["candidates"]][:3]
            action = (
                {
                    "type": "RECOMMEND",
                    "search_id": result["search_id"],
                    "product_ids": ids,
                }
                if ids
                else {"type": "RESPOND", "message": "I found no verified matches."}
            )
        elif "product_type" not in fields:
            action = {
                "type": "CLARIFY",
                "attribute": "product_type",
                "question": "What kind of product are you looking for?",
            }
        elif "price" not in fields and "budget" not in said:
            action = {
                "type": "CLARIFY",
                "attribute": "price",
                "question": "What is your budget?",
            }
        elif (
            self.ask_department
            and "department" not in fields
            and "who is this for" not in said
        ):
            action = {
                "type": "CLARIFY",
                "attribute": "department",
                "question": "Who is this for?",
            }
        else:
            query = next(
                (
                    u["requirement"]["value"]
                    for u in updates
                    if u["requirement"]["field"] == "product_type"
                ),
                None,
            )
            if query is None:
                query = next(
                    (r["value"] for r in existing if r["field"] == "product_type"), ""
                )
            action = {"type": "SEARCH", "query": str(query), "mode": "all", "limit": 10}
        usage = (
            {
                "prompt_tokens": sum(len(str(m["content"])) for m in messages) // 4,
                "completion_tokens": 30,
            }
            if self.usage
            else {}
        )
        return PolicyReply(
            json.dumps(decision(ctx, action, updates)),
            {"provider": "fixture", "usage": usage},
        )


class AlwaysSearchPolicy:
    """Proposes SEARCH forever: exhausts the agent's per-turn budget."""

    def complete(self, messages):
        ctx = json.loads(messages[-1]["content"])
        return PolicyReply(
            json.dumps(decision(ctx, {"type": "SEARCH", "query": "boots"})),
            {"usage": {}},
        )


class AlwaysClarifyPolicy:
    def complete(self, messages):
        ctx = json.loads(messages[-1]["content"])
        action = {
            "type": "CLARIFY",
            "attribute": "color",
            "question": "Which colour do you like?",
        }
        return PolicyReply(json.dumps(decision(ctx, action)), {"usage": {}})


class FailingPolicy:
    def __init__(self, code="provider_http_500"):
        self.code, self.calls = code, 0

    def complete(self, messages):
        self.calls += 1
        raise ProviderError(self.code)


KEYWORDS = {
    "budget": ["budget", "price", "spend"],
    "department": ["who", "for whom", "gender"],
    "color": ["color", "colour"],
    "material": ["material", "fabric"],
    "type": ["kind", "type"],
    "brand": ["brand"],
}


class FakeOllama:
    """Callable transport impersonating Ollama /api/chat. Replies come from the PROMPT only."""

    def __init__(self, mode="good"):
        self.mode, self.payloads, self.calls = mode, [], 0

    def profile_from(self, system):
        return json.loads(
            re.search(r"Hidden profile \(JSON\): (\[.*\])", system).group(1)
        )

    def good(self, payload):
        system = payload["messages"][0]["content"]
        user = json.loads(payload["messages"][1]["content"])
        facts = {f["key"]: f["what_you_would_say"] for f in self.profile_from(system)}
        parts, reveals = [], []
        for q in user["now"]["questions"]:
            for key, words in KEYWORDS.items():
                if (
                    key in facts
                    and any(w in q["question"].lower() for w in words)
                    and key not in reveals
                ):
                    parts.append(facts[key])
                    reveals.append(key)
        if not parts:
            parts = ["I don't have a strong preference about that."]
        action = "accept" if user["now"]["products_shown"] else "reply"
        return {"message": " ".join(parts), "reveals": reveals[:2], "action": action}

    def __call__(self, url, payload, timeout):
        self.calls += 1
        self.payloads.append(payload)
        if self.mode == "http_error":
            import urllib.error

            raise urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(b""))
        if self.mode == "unreachable":
            import urllib.error

            raise urllib.error.URLError("refused")
        if self.mode == "bad_envelope":
            return {"unexpected": True}
        if self.mode == "always_malformed" or (
            self.mode == "malformed_once" and self.calls == 1
        ):
            content = "Sure! Here is my reply: not json"
        else:
            reply = self.good(payload)
            if self.mode == "contradict":
                reply["message"] += " I really want it in purple."
            elif self.mode == "leak":
                reply["message"] += " Maybe product B001234567 would suit me."
            elif self.mode == "overreveal":
                reply["reveals"] = ["type", "budget", "department"]
            elif self.mode == "price_drift":
                reply["message"] = "My budget is under $999."
            elif self.mode == "contradict_once" and self.calls == 1:
                reply["message"] += " I really want it in purple."
            content = json.dumps(reply)
        return {
            "message": {"role": "assistant", "content": content},
            "done": True,
            "prompt_eval_count": 111,
            "eval_count": 22,
            "total_duration": 5,
        }
