"""Scripted shopper and the Ollama adapter (mocked HTTP only; no server needed)."""

import json
import unittest
import urllib.error
from unittest.mock import patch

import eval_fixtures as F
from test_eval_memory import profile, view

from astra_eval.memory import ShopperMemory
from astra_eval.simulators import (
    REPLY_SCHEMA,
    OllamaShopper,
    ScriptedShopper,
    SimulatorConfig,
    SimulatorError,
    check_ollama,
)


def memory():
    m = ShopperMemory(profile(), window_turns=4)
    m.record_shopper(1, "Boots please.", ["type"])
    return m


def ask(m, text, turn=1, products=()):
    v = view(text, turn, products)
    m.record_assistant(v)
    return v


class ScriptedShopperTests(unittest.TestCase):
    def test_answers_the_asked_fact_and_only_that_fact(self):
        m = memory()
        reply = ScriptedShopper().respond(m, ask(m, "What is your budget?")).reply
        self.assertEqual(
            (reply.message, reply.reveals, reply.action),
            ("My budget is under $60.", ["budget"], "reply"),
        )

    def test_repeated_question_gets_the_same_answer_consistently(self):
        m = memory()
        first = ScriptedShopper().respond(m, ask(m, "What is your budget?")).reply
        m.apply(2, first)
        second = (
            ScriptedShopper().respond(m, ask(m, "Sorry, what is your budget?", 2)).reply
        )
        self.assertIn("under $60", second.message)
        self.assertTrue(second.message.startswith("As I said"))

    def test_question_about_nothing_in_the_profile_gets_no_preference(self):
        m = memory()
        reply = ScriptedShopper().respond(m, ask(m, "Do you want free shipping?")).reply
        self.assertEqual(reply.message, profile().no_preference_reply)
        self.assertEqual(reply.reveals, [])

    def test_progressive_reveal_when_nothing_is_asked(self):
        m = memory()
        reply = ScriptedShopper().respond(m, ask(m, "Let me look into that.")).reply
        self.assertEqual(reply.reveals, ["budget"])  # next unrevealed, not everything

    def test_reacts_to_visible_prices_and_gives_up_when_it_has_nothing_left(self):
        m = memory()
        cheap = [{"title": "Boot", "price": 30.0}]
        self.assertEqual(
            ScriptedShopper().respond(m, ask(m, "Here you go.", 1, cheap)).reply.action,
            "accept",
        )
        dear = [{"title": "Boot", "price": 90.0}]
        reply = ScriptedShopper().respond(m, ask(m, "Here you go.", 2, dear)).reply
        self.assertEqual(reply.action, "reply")
        self.assertIn("over my budget", reply.message)
        for key in ("budget", "color"):
            m.revealed[key] = {"turn": 1, "statement": "x"}
        self.assertEqual(
            ScriptedShopper().respond(m, ask(m, "Hmm.", 3)).reply.action, "give_up"
        )


class ConfigTests(unittest.TestCase):
    def test_defaults_target_llama31_on_localhost(self):
        c = SimulatorConfig.from_env({})
        self.assertEqual(
            (c.model, c.url, c.temperature, c.num_ctx),
            ("llama3.1:latest", "http://127.0.0.1:11434", 0.0, 4096),
        )
        self.assertEqual(c.prompt_budget, 4096 - 220 - 128)

    def test_environment_variables_and_overrides(self):
        env = {
            "ASTRA_SIM_MODEL": "m:1",
            "ASTRA_SIM_OLLAMA_URL": "http://host:1/",
            "ASTRA_SIM_TEMPERATURE": "0.3",
            "ASTRA_SIM_SEED": "9",
            "ASTRA_SIM_NUM_CTX": "8192",
            "ASTRA_SIM_MAX_TOKENS": "100",
            "ASTRA_SIM_TIMEOUT": "5",
            "ASTRA_SIM_WINDOW_TURNS": "10",
        }
        c = SimulatorConfig.from_env(env)
        self.assertEqual(
            (
                c.model,
                c.url,
                c.temperature,
                c.seed,
                c.num_ctx,
                c.max_tokens,
                c.timeout,
                c.window_turns,
            ),
            ("m:1", "http://host:1", 0.3, 9, 8192, 100, 5.0, 10),
        )
        self.assertEqual(SimulatorConfig.from_env(env, model="x", seed=1).seed, 1)

    def test_invalid_settings_are_rejected(self):
        for env in (
            {"ASTRA_SIM_OLLAMA_URL": "ftp://x"},
            {"ASTRA_SIM_NUM_CTX": "100"},
            {"ASTRA_SIM_TEMPERATURE": "9"},
            {"ASTRA_SIM_SEED": "abc"},
        ):
            with self.subTest(env=env), self.assertRaises(ValueError):
                SimulatorConfig.from_env(env)


class OllamaAdapterTests(unittest.TestCase):
    def shopper(self, mode="good", **kw):
        self.transport = F.FakeOllama(mode)
        return OllamaShopper(SimulatorConfig(**kw), transport=self.transport)

    def run_once(self, shopper):
        m = memory()
        return shopper.respond(m, ask(m, "What is your budget?"))

    def test_request_shape_uses_chat_api_json_schema_and_configured_options(self):
        result = self.run_once(
            self.shopper(
                model="llama3.1:latest",
                temperature=0.2,
                seed=3,
                num_ctx=2048,
                max_tokens=150,
            )
        )
        payload = self.transport.payloads[0]
        self.assertEqual(payload["model"], "llama3.1:latest")
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["format"], REPLY_SCHEMA)
        self.assertEqual(
            payload["options"],
            {"temperature": 0.2, "seed": 3, "num_ctx": 2048, "num_predict": 150},
        )
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertEqual(result.reply.message, "My budget is under $60.")
        self.assertEqual(
            (result.usage["prompt_tokens"], result.usage["completion_tokens"]),
            (111, 22),
        )
        self.assertEqual(result.attempts, 1)

    def test_every_call_carries_the_immutable_profile(self):
        shopper = self.shopper()
        m = memory()
        for turn in range(1, 5):
            shopper.respond(m, ask(m, "What is your budget?", turn))
        systems = {p["messages"][0]["content"] for p in self.transport.payloads}
        self.assertEqual(len(systems), 1)
        self.assertIn("I'd like it in red.", systems.pop())

    def test_one_malformed_reply_is_retried_then_accepted(self):
        result = self.run_once(self.shopper("malformed_once"))
        self.assertEqual(result.attempts, 2)
        retry = self.transport.payloads[1]["messages"]
        self.assertEqual(retry[-1]["role"], "user")
        self.assertIn("valid JSON", retry[-1]["content"])

    def test_persistently_malformed_output_raises_a_safe_code(self):
        with self.assertRaises(SimulatorError) as raised:
            self.run_once(self.shopper("always_malformed"))
        self.assertEqual(raised.exception.code, "simulator_malformed_reply")
        self.assertEqual(self.transport.calls, 2)

    def test_schema_violations_count_as_malformed(self):
        shopper = self.shopper()
        shopper.transport = lambda *a: {
            "message": {"content": json.dumps({"message": "hi", "action": "dance"})}
        }
        with self.assertRaises(SimulatorError):
            self.run_once(shopper)

    def test_transport_failures_map_to_safe_codes(self):
        for mode, code in (
            ("http_error", "simulator_http_500"),
            ("unreachable", "simulator_unreachable"),
            ("bad_envelope", "simulator_invalid_envelope"),
        ):
            with self.subTest(mode=mode), self.assertRaises(SimulatorError) as raised:
                self.run_once(self.shopper(mode))
            self.assertEqual(raised.exception.code, code)

    def test_context_that_cannot_fit_is_a_simulator_error_not_a_truncation(self):
        with self.assertRaises(SimulatorError) as raised:
            self.run_once(self.shopper(num_ctx=512, max_tokens=300))
        self.assertEqual(raised.exception.code, "simulator_context_overflow")
        self.assertEqual(self.transport.calls, 0)

    def test_import_and_construction_never_touch_the_network(self):
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("network used")
        ):
            OllamaShopper(SimulatorConfig())
            ScriptedShopper()


class CheckOllamaTests(unittest.TestCase):
    config = SimulatorConfig()

    def tags(self, *names):
        return lambda url, timeout: {"models": [{"name": n} for n in names]}

    def test_healthy_server_with_the_model_passes_the_structured_probe(self):
        report = check_ollama(
            self.config, transport=F.FakeOllama(), getter=self.tags("llama3.1:latest")
        )
        self.assertTrue(
            report["reachable"] and report["model_present"] and report["probe_ok"]
        )
        self.assertEqual(report["problems"], [])

    def test_unreachable_server_explains_how_to_fix_it(self):
        def down(url, timeout):
            raise urllib.error.URLError("refused")

        report = check_ollama(self.config, getter=down)
        self.assertFalse(report["reachable"])
        self.assertIn("Start it", report["problems"][0])

    def test_missing_model_names_the_pull_command(self):
        report = check_ollama(self.config, getter=self.tags("mistral:latest"))
        self.assertTrue(report["reachable"])
        self.assertFalse(report["model_present"])
        self.assertIn("ollama pull llama3.1:latest", report["problems"][0])

    def test_probe_failures_and_poor_consistency_are_reported(self):
        report = check_ollama(
            self.config,
            transport=F.FakeOllama("always_malformed"),
            getter=self.tags("llama3.1:latest"),
        )
        self.assertFalse(report["probe_ok"])
        self.assertIn("simulator_malformed_reply", report["problems"][0])

        class Forgetful(F.FakeOllama):
            def good(self, payload):
                return {"message": "Whatever.", "reveals": [], "action": "reply"}

        report = check_ollama(
            self.config, transport=Forgetful(), getter=self.tags("llama3.1:latest")
        )
        self.assertFalse(report["probe_ok"])
        self.assertIn("did not state the budget", report["problems"][0])

    def test_model_name_without_tag_matches_latest(self):
        report = check_ollama(
            SimulatorConfig(model="llama3.1"),
            transport=F.FakeOllama(),
            getter=self.tags("llama3.1:latest"),
        )
        self.assertTrue(report["model_present"])


if __name__ == "__main__":
    unittest.main()
