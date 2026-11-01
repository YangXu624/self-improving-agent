"""Explicit new-format timelines preserve scoring and point-in-time memory auditing."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from longitudinal_fixtures import make_dataset
from test_compact_memory_agent import decision, recommend
from test_sessions import add

from astra_eval.longitudinal import LongitudinalConfig, run_longitudinal
from astra_eval.simulators import ScriptedShopper
from shopping_agent.provider import PolicyReply


class CompactPolicy:
    """Only actual serialized context is available; no persona or target access."""

    model = "compact-test-policy"

    def complete(self, messages):
        context = json.loads(messages[-1]["content"])
        updates, memories, budget = [], [], None
        message = context["current_user_message"]
        hard = context["state"]["hard"]
        if context["edits_allowed"]:
            if "category" not in hard:
                updates.append(
                    add("product_type", "contains", "boots", "boots").model_dump()
                )
            budget = re.search(r"under \$(\d+)", message)
            if budget:
                updates.append(
                    add(value=float(budget.group(1)), quote=budget.group()).model_dump()
                )
            if "user_memory" in context:
                match = re.search(
                    r"(?:Actually I now generally prefer (Red) boots instead of Blue\.|I generally prefer (Blue) boots\.)",
                    message,
                )
                if match:
                    previous = next(iter(context["user_memory"]["records"]), None)
                    memories = [
                        {
                            "op": "REPLACE" if previous else "ADD",
                            "category": "preference",
                            "attribute": "color",
                            "value": match.group(1) or match.group(2),
                            "scope": "boots",
                            "quote": match.group(),
                            "target_id": previous["ref"] if previous else None,
                        }
                    ]
        if context["latest_search"] and not updates:
            value = recommend(context)
        elif "price" not in hard and not budget:
            value = decision(
                {
                    "type": "CLARIFY",
                    "attribute": "price",
                    "question": "What is your budget?",
                },
                updates,
                memories,
            )
        else:
            value = decision({"type": "SEARCH", "query": "boots"}, updates, memories)
        return PolicyReply(
            json.dumps(value),
            {
                "provider": "fixture",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )


class CompactMemoryEvaluationTests(unittest.TestCase):
    def test_opt_in_timeline_and_memory_audit_use_actual_compact_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, catalogue, index, _data = make_dataset(root)
            config = LongitudinalConfig(
                customers=source,
                catalogue=catalogue,
                index=index,
                output=root / "run",
                memory_format="compact",
            )
            summary = run_longitudinal(
                config, simulator=ScriptedShopper(), policy=CompactPolicy()
            )
            self.assertEqual(summary["sessions"], 8)
            rows = [
                json.loads(line)
                for line in (config.output / "results.jsonl").read_text().splitlines()
            ]
            on = [r for r in rows if r["condition"] == "user_memory_on"]
            off = [r for r in rows if r["condition"] == "user_memory_off"]
            self.assertTrue(on[1]["user_memory"]["injected_ids"])
            self.assertTrue(all(not r["user_memory"]["injected_ids"] for r in off))
            self.assertTrue(
                any(
                    f["type"] == "outdated_record_injected"
                    for f in on[2]["user_memory"]["flags"]
                )
            )
            self.assertTrue(
                all(
                    r["disclosed_requirement_compliance"]["violations"] == 0
                    for r in rows
                )
            )
            self.assertTrue(
                all(
                    r["termination"] == "target_found"
                    for r in rows
                    if r["evaluation_mode"] == "target_item"
                )
            )
            settings = json.loads((config.output / "run.json").read_text())[
                "shared_config"
            ]
            self.assertEqual(settings["plan"]["memory_format"], "compact")
            self.assertTrue(
                all(
                    v == "shopping-baseline-v7-compact-memory"
                    for v in settings["prompt_versions"].values()
                )
            )
