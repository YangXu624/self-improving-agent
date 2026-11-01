"""Mocked transport contracts; no model endpoints or real credentials are used."""

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from astra_eval.shopper_providers import (
    JsonShopperProvider,
    RequestJournal,
    V3Config,
    claude_key,
)
from astra_eval.simulators import SimulatorError


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.messages = [
            {"role": "system", "content": "private persona"},
            {"role": "user", "content": "current situation"},
        ]
        self.schema = {"type": "object", "properties": {"message": {"type": "string"}}}

    def journal(self, name="calls.jsonl", cap=2):
        return RequestJournal(self.root / name, cap)

    def test_ollama_shape_usage_and_exact_journal(self):
        def transport(url, payload, headers, timeout):
            self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
            self.assertEqual(payload["format"], self.schema)
            self.assertEqual(payload["options"]["seed"], 7)
            return {
                "message": {"content": '{"message":"hello"}'},
                "model": "pinned-local",
                "prompt_eval_count": 40,
                "eval_count": 5,
            }

        journal = self.journal()
        result = JsonShopperProvider(V3Config(), journal, transport=transport).complete(
            self.messages, self.schema, {"owner": "a"}
        )
        self.assertEqual(result.usage["prompt_tokens"], 40)
        self.assertEqual(result.model, "pinned-local")
        rows = list(map(json.loads, journal.path.read_text().splitlines()))
        self.assertEqual(rows[0]["payload"]["messages"], self.messages)
        self.assertEqual(rows[1]["response"]["message"]["content"], result.content)

    def test_claude_shape_no_seed_usage_and_no_logged_secret(self):
        config = V3Config(provider="claude", model="claude-fixture")

        def transport(url, payload, headers, timeout):
            self.assertEqual(url, "https://api.anthropic.com/v1/messages")
            self.assertEqual(headers["x-api-key"], "fixture-secret")
            self.assertEqual(payload["system"], "private persona")
            self.assertEqual(payload["messages"], self.messages[1:])
            self.assertEqual(payload["output_config"]["format"]["schema"], self.schema)
            self.assertNotIn("seed", payload)
            return {
                "content": [{"type": "text", "text": '{"message":"hi"}'}],
                "model": "claude-fixture",
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 80,
                    "output_tokens": 6,
                    "cache_read_input_tokens": 20,
                },
            }

        journal = self.journal()
        result = JsonShopperProvider(
            config, journal, api_key="fixture-secret", transport=transport
        ).complete(self.messages, self.schema, {})
        self.assertEqual(result.usage["cache_read_tokens"], 20)
        self.assertNotIn("fixture-secret", journal.path.read_text())
        self.assertIn('"seed_supported": false', journal.path.read_text())

    def test_failed_attempts_consume_cap_and_errors_do_not_leak(self):
        def broken(*args):
            raise OSError("fixture-secret should not appear")

        journal = self.journal(cap=1)
        provider = JsonShopperProvider(V3Config(), journal, transport=broken)
        with self.assertRaisesRegex(SimulatorError, "shopper_provider_failure"):
            provider.complete(self.messages, self.schema, {})
        with self.assertRaisesRegex(SimulatorError, "shopper_call_budget_exhausted"):
            provider.complete(self.messages, self.schema, {})
        self.assertEqual(journal.calls, 1)
        self.assertNotIn("fixture-secret", journal.path.read_text())
        with self.assertRaises(FileExistsError):
            self.journal()

    def test_incomplete_claude_response_is_never_accepted(self):
        provider = JsonShopperProvider(
            V3Config(provider="claude", model="claude-fixture"),
            self.journal(),
            api_key="fixture",
            transport=lambda *args: {
                "stop_reason": "max_tokens",
                "content": [{"type": "text", "text": "{}"}],
            },
        )
        with self.assertRaisesRegex(SimulatorError, "shopper_invalid_envelope"):
            provider.complete(self.messages, self.schema, {})

    def test_construction_is_network_free_and_config_is_explicit(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            JsonShopperProvider(V3Config(), self.journal())
        with self.assertRaises(ValueError):
            V3Config(provider="claude")
        with self.assertRaises(ValueError):
            JsonShopperProvider(
                V3Config(provider="claude", model="claude-fixture"),
                self.journal("key.jsonl"),
            )
        self.assertEqual(
            asdict(V3Config())["protocol_version"], "shopper-v3-autonomous-1"
        )

    def test_separate_key_file_and_process_precedence(self):
        path = self.root / ".env.shopper"
        path.write_text('ANTHROPIC_API_KEY="fixture-key"\n')
        self.assertEqual(claude_key(path, {}), "fixture-key")
        self.assertEqual(
            claude_key(path, {"ANTHROPIC_API_KEY": "process-key"}), "process-key"
        )
        path.write_text("DEEPSEEK_API_KEY=not-a-shopper-setting\n")
        with self.assertRaises(ValueError):
            claude_key(path, {})
