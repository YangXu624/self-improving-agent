"""Normal Streamlit composition with mocked DeepSeek HTTP; no live credentials or calls."""

import io
import json
import os
import unittest
from unittest.mock import patch

import test_ui as fixtures
from test_user_memory import preference

from shopping_agent.cli import parser


@unittest.skipUnless(fixtures.HAS_STREAMLIT, "Install [ui] for UI acceptance")
class UserMemoryUiTests(unittest.TestCase):
    def setUp(self):
        fixtures.StreamlitTests.setUp(self)
        env = patch.dict(
            os.environ, {"ASTRA_USER_MEMORY_ROOT": str(self.root / "users")}
        )
        env.start()
        self.addCleanup(env.stop)
        self.contexts = []

        def completion(request, timeout):
            payload = json.loads(request.data)
            context = json.loads(payload["messages"][-1]["content"])
            self.contexts.append(context)
            value = {
                "based_on_state_version": context["state"]["version"],
                "updates": [],
                "action": {"type": "RESPOND", "message": "Fixture response"},
                "reason": "Memory HTTP fixture",
            }
            if context["current_user_message"] == preference().quote:
                value["user_memory_updates"] = [preference().model_dump()]
            return io.BytesIO(
                json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"content": json.dumps(value)},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                ).encode()
            )

        self.transport.side_effect = completion

    def send(self, message):
        fixtures.StreamlitTests.send(self, message)

    def test_ui_opt_in_cross_chat_recall_and_off_switch(self):
        self.app.checkbox(key="user_memory_enabled").check().run()
        self.send(preference().quote)
        self.assertTrue(list((self.root / "users").glob("*/profile.md")))
        self.app.button(key="new_chat").click().run()
        self.send("bags")
        self.assertEqual(
            self.contexts[-1]["user_memory"]["records"][0]["value"], "blue"
        )
        self.app.checkbox(key="user_memory_enabled").uncheck().run()
        self.send("bags")
        self.assertNotIn("user_memory", self.contexts[-1])
        self.assertEqual(
            self.contexts[-1]["prompt_version"], "shopping-baseline-v5-experience"
        )


class UserMemoryCliTests(unittest.TestCase):
    def test_cli_toggle_is_explicit_and_default_off(self):
        baseline = parser().parse_args(["chat", "--user", "alice"])
        enabled = parser().parse_args(
            [
                "chat",
                "--user",
                "alice",
                "--user-memory",
                "--user-memory-root",
                "/tmp/fixture-users",
            ]
        )
        self.assertFalse(baseline.user_memory)
        self.assertTrue(enabled.user_memory)
        self.assertEqual(enabled.user_memory_root, "/tmp/fixture-users")
