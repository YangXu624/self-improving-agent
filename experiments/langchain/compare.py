"""Reproducible offline orchestration comparison; no recommendation-quality claim.

Uses existing synthetic fixtures. Ground truth stays in tests/evaluation, never agent
context. Run from repository root: python -m experiments.langchain.compare.
"""

import argparse
import json
import socket
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from langchain_core.utils.function_calling import convert_to_openai_tool  # noqa: E402
from test_agent import AgentTests, ScriptedPolicy, decision, recommend, search  # noqa: E402
from test_langchain_refactor import ScriptedChat  # noqa: E402
from test_sessions import add  # noqa: E402

from astra_langchain import BASELINE_COMMIT  # noqa: E402
from astra_langchain.middleware import tools  # noqa: E402
from astra_langchain.workflow import LangChainShoppingAgent  # noqa: E402
from shopping_agent.agent import ShoppingAgent  # noqa: E402


def scenarios():
    def respond(c):
        return decision(c, {"type": "RESPOND", "message": "Ready."})

    def constrained(c):
        return search(c, [add(value=60.0, quote="under 60 USD").model_dump()])

    def empty(c):
        return decision(c, {"type": "SEARCH", "query": "nonexistent"})

    return {
        "respond": ("hello", [respond], {}),
        "search_recommend": ("boots", [search, recommend], {}),
        "hard_price": ("boots under 60 USD", [constrained, recommend], {}),
        "repair_unseen_id": (
            "boots",
            [search, lambda c: recommend(c, ["invented"]), recommend],
            {},
        ),
        "deduplicate_empty": ("nonexistent", [empty, empty, empty], {}),
        "terminal_search_budget": ("boots", [search], {"max_calls": 1}),
    }


def run(repeats=20):
    fixture = AgentTests()
    fixture.setUp()
    samples = []
    try:
        with patch.object(
            socket.socket, "connect", side_effect=AssertionError("Offline only")
        ):
            for name, (message, steps, options) in scenarios().items():
                for repeat in range(repeats):
                    pair = {}
                    # Alternate ordering to reduce systematic warm-cache bias.
                    order = (
                        ["custom", "framework"]
                        if repeat % 2 == 0
                        else ["framework", "custom"]
                    )
                    for implementation in order:
                        sid = fixture.store.create(implementation)
                        start = time.perf_counter()
                        if implementation == "custom":
                            agent = ShoppingAgent(
                                fixture.store,
                                fixture.search,
                                ScriptedPolicy(*steps),
                                **options,
                            )
                        else:
                            agent = LangChainShoppingAgent(
                                fixture.store,
                                fixture.search,
                                ScriptedChat(steps=list(steps)),
                                **options,
                            )
                        constructed = time.perf_counter()
                        response = agent.turn(implementation, sid, message)
                        duration = time.perf_counter() - constructed
                        with fixture.store.open(implementation, sid) as session:
                            requests = [
                                e.payload["messages"]
                                for e in session.events
                                if e.type == "model_request"
                            ]
                        schemas = [convert_to_openai_tool(t) for t in tools(False)]
                        payload_bytes = sum(
                            len(
                                json.dumps(
                                    {
                                        "messages": m,
                                        **(
                                            {"tools": schemas}
                                            if implementation == "framework"
                                            else {}
                                        ),
                                    },
                                    ensure_ascii=True,
                                ).encode()
                            )
                            for m in requests
                        )
                        semantic = {
                            key: response.get(key)
                            for key in [
                                "status",
                                "action",
                                "budget_used",
                                "state_version",
                                "closure",
                            ]
                        }
                        semantic["products"] = [
                            (p["id"], p["facts"]) for p in response["products"]
                        ]
                        pair[implementation] = semantic
                        samples.append(
                            {
                                "scenario": name,
                                "implementation": implementation,
                                "construction_ms": (constructed - start) * 1000,
                                "turn_ms": duration * 1000,
                                "payload_bytes": payload_bytes,
                                "model_calls": response["budget_used"]["model_calls"],
                                "searches": response["budget_used"]["searches"],
                            }
                        )
                    if pair["custom"] != pair["framework"]:
                        raise AssertionError(f"Parity failure in {name}: {pair}")
    finally:
        fixture.doCleanups()
    summary = {}
    for name in scenarios():
        summary[name] = {}
        for implementation in ("custom", "framework"):
            group = [
                r
                for r in samples
                if r["scenario"] == name and r["implementation"] == implementation
            ]
            summary[name][implementation] = {
                k: statistics.median(r[k] for r in group)
                for k in (
                    "construction_ms",
                    "turn_ms",
                    "payload_bytes",
                    "model_calls",
                    "searches",
                )
            }
    return {
        "baseline": BASELINE_COMMIT,
        "repeats_per_scenario": repeats,
        "parity": "passed",
        "provider_calls": 0,
        "summary": summary,
        "samples": samples,
        "limitations": "Synthetic latency; wire-size proxy is not token usage. Legacy context, not compact v7. No quality measurement.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("data/langchain-experiment/comparison.json")
    )
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("--repeats must be 1..100")
    if args.output.exists():
        parser.error("Output exists; choose a fresh path")
    result = run(args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
