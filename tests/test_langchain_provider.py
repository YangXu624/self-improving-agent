"""Wire compatibility and unchanged cost journal tested with HTTP MockTransport only."""

import importlib.util
import json
import tempfile
import unittest

if importlib.util.find_spec("langchain") is None:
    raise unittest.SkipTest("Install optional langchain extra for framework tests")
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage

from astra_eval.api_budget import ApiCostBudget, CostLimitError
from astra_langchain.middleware import tools
from astra_langchain.provider import deepseek_model
from shopping_agent.provider import ProviderError


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.budget = ApiCostBudget(Path(self.tmp.name) / "cost.jsonl", "1")
        self.requests = []

    def model(self, *, usage=True, status=200):
        def handle(request):
            payload = json.loads(request.content)
            self.requests.append((str(request.url), payload))
            data = {
                "id": "mock",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "respond",
                                        "arguments": json.dumps(
                                            {
                                                "based_on_state_version": 0,
                                                "updates": [],
                                                "action": {
                                                    "type": "RESPOND",
                                                    "message": "Hello",
                                                },
                                                "reason": "fixture",
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
            if usage:
                data["usage"] = {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                }
            return httpx.Response(status, json=data)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        self.addCleanup(client.close)
        return deepseek_model(
            api_key="offline-test-key",
            model="deepseek-flash",
            budget=self.budget,
            http_client=client,
        )

    def test_exact_model_endpoint_native_tools_and_accounting(self):
        message = self.model().bind_tools(tools(False)).invoke([HumanMessage("hello")])
        url, payload = self.requests[0]
        self.assertEqual(url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 2000)
        self.assertEqual(payload["temperature"], 0)
        self.assertNotIn("response_format", payload)
        self.assertEqual(len(payload["tools"]), 4)
        for tool in payload["tools"]:
            self.assertNotIn("runtime", tool["function"]["parameters"]["properties"])
        self.assertEqual(message.tool_calls[0]["name"], "respond")
        rows = [json.loads(s) for s in self.budget.path.read_text().splitlines()]
        self.assertEqual(
            [r["kind"] for r in rows],
            ["budget_open", "request_reserved", "usage_settled"],
        )
        self.assertGreater(rows[1]["input_cap"], len(json.dumps(payload["tools"])))
        self.assertNotIn("offline-test-key", self.budget.path.read_text())

    def test_unknown_usage_retained_and_next_request_blocked(self):
        model = self.model(usage=False).bind_tools(tools(False))
        with self.assertRaises(CostLimitError):
            model.invoke([HumanMessage("hello")])
        self.assertTrue(self.budget.blocked)
        with self.assertRaises(CostLimitError):
            model.invoke([HumanMessage("again")])
        self.assertEqual(len(self.requests), 1)
        self.assertGreater(self.budget.total, 0)

    def test_http_failure_has_no_retries_and_keeps_reservation(self):
        model = self.model(status=500).bind_tools(tools(False))
        with self.assertRaises(ProviderError):
            model.invoke([HumanMessage("hello")])
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.budget.blocked)

    def test_unsupported_model_fails_without_http(self):
        with self.assertRaises(ValueError):
            deepseek_model(api_key="unused", model="unknown", budget=self.budget)
        self.assertEqual(self.requests, [])

    def test_call_overrides_cannot_escape_reserved_model_or_output_cap(self):
        for options in [{"max_tokens": 4000}, {"model": "unknown"}]:
            with self.subTest(options=options):
                with self.assertRaises(ProviderError):
                    self.model().bind(**options).invoke([HumanMessage("hello")])
        self.assertEqual(self.requests, [])
        self.assertEqual(len(self.budget.path.read_text().splitlines()), 1)
