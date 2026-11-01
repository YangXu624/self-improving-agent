"""Mocked transport contracts; no model endpoints or real credentials are used."""

import io
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from astra_eval.shopper_providers import (
    JsonShopperProvider,
    RequestJournal,
    V3Config,
    claude_key,
    claude_model,
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
            self.assertEqual(payload["options"]["temperature"], 0.0)
            self.assertEqual(payload["options"]["num_ctx"], 4096)
            self.assertEqual(payload["options"]["num_predict"], 220)
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
            for name in ("seed", "temperature", "top_p", "top_k", "options", "num_ctx"):
                self.assertNotIn(name, payload)
            self.assertEqual(headers["anthropic-version"], "2026-10-21")
            self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")
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

    def test_shared_env_loads_claude_model_without_crossing_deepseek_settings(self):
        from shopping_agent.provider import DeepSeekPolicy

        path = self.root / ".env"
        path.write_text(
            "DEEPSEEK_API_KEY=deepseek-fixture\nDEEPSEEK_MODEL=deepseek-flash\nANTHROPIC_API_KEY=claude-fixture\nANTHROPIC_MODEL=claude-sonnet-5-5\n"
        )
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(claude_key(path, {}), "claude-fixture")
            self.assertEqual(claude_model(path, {}), "claude-sonnet-5-5")
            self.assertEqual(
                DeepSeekPolicy.from_env_file(path)._key, "deepseek-fixture"
            )
            self.assertEqual(DeepSeekPolicy.from_env_file(path).model, "deepseek-flash")

    def test_claude_model_precedence_blank_and_secret_safe_errors(self):
        path = self.root / ".env"
        path.write_text("ANTHROPIC_MODEL=claude-sonnet-5-5\n")
        self.assertEqual(
            claude_model(path, {"ANTHROPIC_MODEL": "claude-fixture"}), "claude-fixture"
        )
        for value in ("", "secret-invalid model"):
            with self.assertRaises(ValueError) as error:
                claude_model(path, {"ANTHROPIC_MODEL": value})
            self.assertNotIn("secret-invalid model", str(error.exception))
        with self.assertRaises(ValueError):
            claude_key(path, {"ANTHROPIC_API_KEY": ""})

    def test_cli_uses_shared_model_field_and_explicit_model_wins(self):
        from astra_eval.cli import parser, sim_config

        path = self.root / ".env"
        path.write_text(
            "ANTHROPIC_MODEL=claude-sonnet-5-5\nANTHROPIC_API_KEY=fixture\nDEEPSEEK_API_KEY=other-fixture\n"
        )
        args = [
            "longitudinal",
            "--output",
            str(self.root / "unused"),
            "--shopper-version",
            "v3",
            "--shopper-provider",
            "claude",
            "--env-file",
            str(path),
        ]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("Network forbidden"),
            ),
        ):
            self.assertEqual(
                sim_config(parser().parse_args(args)).model, "claude-sonnet-5-5"
            )
            self.assertEqual(
                sim_config(
                    parser().parse_args(args + ["--sim-model", "claude-override"])
                ).model,
                "claude-override",
            )
            alternate = self.root / ".env.shopper"
            alternate.write_text("ANTHROPIC_MODEL=claude-alternate\n")
            self.assertEqual(
                sim_config(
                    parser().parse_args(args + ["--shopper-env-file", str(alternate)])
                ).model,
                "claude-alternate",
            )

    def test_sonnet_thinking_controls_are_recorded_and_unsupported_temperature_rejected(
        self,
    ):
        config = V3Config(provider="claude", model="claude-sonnet-5-5", max_tokens=512)
        self.assertIsNone(config.temperature)
        self.assertEqual(config.claude_thinking, "between_tools")
        self.assertEqual(config.claude_effort, "low")
        for temperature in (0, 0.1, 1):
            with self.assertRaisesRegex(ValueError, "does not support temperature"):
                V3Config(
                    provider="claude",
                    model="claude-sonnet-5-5",
                    temperature=temperature,
                )
        with self.assertRaisesRegex(ValueError, "does not support temperature"):
            V3Config.from_env(
                {"ASTRA_SIM_TEMPERATURE": "0"},
                provider="claude",
                model="claude-sonnet-5-5",
            )
        self.assertIsNone(
            V3Config.from_env(
                {}, provider="claude", model="claude-sonnet-5-5"
            ).temperature
        )
        self.assertEqual(
            V3Config.from_env({"ASTRA_SIM_TEMPERATURE": "0.7"}).temperature, 0.7
        )
        sent = []
        provider = JsonShopperProvider(
            config,
            self.journal(),
            api_key="fixture",
            transport=lambda url, payload, headers, timeout: (
                sent.append(payload)
                or {
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "{}"}],
                }
            ),
        )
        provider.complete(self.messages, self.schema, {})
        self.assertEqual(sent[0]["thinking"], {"type": "between_tools"})
        self.assertEqual(sent[0]["output_config"]["effort"], "low")
        self.assertEqual(sent[0]["max_tokens"], 512)

    def test_incomplete_refused_and_malformed_envelopes_keep_usage_and_raw_evidence(
        self,
    ):
        for i, override in enumerate(
            [
                {"stop_reason": "max_tokens"},
                {"stop_reason": "refusal"},
                {"content": []},
                {"content": [None]},
                {"content": [{"type": "text", "text": 7}]},
                {
                    "content": [
                        {"type": "text", "text": "{}"},
                        {"type": "text", "text": "{}"},
                    ]
                },
            ]
        ):
            with self.subTest(override=override):
                response = {
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "{}"}],
                    "usage": {
                        "input_tokens": 8,
                        "output_tokens": 4,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                    **override,
                }
                journal = self.journal(f"invalid-{i}.jsonl")
                provider = JsonShopperProvider(
                    V3Config(provider="claude", model="claude-fixture"),
                    journal,
                    api_key="fixture",
                    transport=lambda *args: response,
                )
                with self.assertRaisesRegex(SimulatorError, "shopper_invalid_envelope"):
                    provider.complete(self.messages, self.schema, {})
                self.assertEqual(journal.calls, 1)
                self.assertEqual(provider.usage["completion_tokens"], 4)
                rows = list(map(json.loads, journal.path.read_text().splitlines()))
                self.assertEqual(rows[1]["response"], response)
                self.assertTrue(rows[2]["usage_complete"])

    def test_http_failure_is_bounded_safe_and_missing_usage_is_explicit(self):
        def fail(*args):
            raise HTTPError(
                "https://api.anthropic.com/v1/messages",
                400,
                "fixture-secret",
                {},
                io.BytesIO(b"fixture-secret"),
            )

        journal = self.journal(cap=1)
        provider = JsonShopperProvider(
            V3Config(provider="claude", model="claude-fixture"),
            journal,
            api_key="fixture-secret",
            transport=fail,
        )
        with self.assertRaisesRegex(SimulatorError, "shopper_provider_failure"):
            provider.complete(self.messages, self.schema, {})
        self.assertNotIn("fixture-secret", journal.path.read_text())
        self.assertNotIn("prompt_tokens", provider.usage)
        self.assertEqual(journal.calls, 1)
        self.assertEqual(
            json.loads(journal.path.read_text().splitlines()[-1])["http_status"], 400
        )
        missing = JsonShopperProvider(
            V3Config(provider="claude", model="claude-fixture"),
            self.journal("missing.jsonl"),
            api_key="fixture",
            transport=lambda *args: {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "{}"}],
                "usage": {"input_tokens": True, "output_tokens": None},
            },
        )
        result = missing.complete(self.messages, self.schema, {})
        self.assertNotIn("prompt_tokens", result.usage)
        self.assertNotIn("completion_tokens", result.usage)
        self.assertFalse(
            json.loads(missing.journal.path.read_text().splitlines()[-1])[
                "usage_complete"
            ]
        )

    def test_thinking_block_is_not_concatenated_into_structured_text(self):
        provider = JsonShopperProvider(
            V3Config(provider="claude", model="claude-fixture"),
            self.journal(),
            api_key="fixture",
            transport=lambda *args: {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "thinking", "thinking": "private"},
                    {"type": "text", "text": "{}"},
                ],
            },
        )
        self.assertEqual(
            provider.complete(self.messages, self.schema, {}).content, "{}"
        )
