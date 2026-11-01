"""Default live composition verified through mocked HTTP, not a legacy-format fixture."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import test_agent as fixtures
import test_ui as ui_fixtures
from test_compact_memory_agent import decision, recommend
from test_sessions import add
from test_user_memory import preference

from shopping_agent.cli import main


@unittest.skipUnless(ui_fixtures.HAS_STREAMLIT, "Install [ui] to run UI acceptance")
class CompactMemoryUiTests(unittest.TestCase):
    def setUp(self):
        ui_fixtures.StreamlitTests.setUp(self)
        env = patch.dict(
            os.environ,
            {
                "ASTRA_USER_MEMORY_ROOT": str(self.root / "users"),
            },
        )
        env.start()
        os.environ.pop("ASTRA_MEMORY_FORMAT", None)
        self.addCleanup(env.stop)
        self.contexts = []

        def completion(request, timeout):
            context = json.loads(json.loads(request.data)["messages"][-1]["content"])
            self.contexts.append(context)
            if not context["edits_allowed"]:
                value = recommend(context)
            elif context["current_user_message"] == preference().quote:
                value = decision(
                    {"type": "RESPOND", "message": "Noted"},
                    memory=[preference().model_dump()],
                )
            elif context["current_user_message"] == "boots under 100":
                value = decision(
                    {"type": "SEARCH", "query": "boots"}, [add().model_dump()]
                )
            elif context["current_user_message"] == "I need bags":
                value = decision({"type": "RESPOND", "message": "What kind of bag?"})
            else:
                value = decision(
                    {"type": "SEARCH", "query": "boots"},
                    [
                        {
                            "op": "REPLACE",
                            "target_id": "hard.price.0",
                            "quote": "under 60",
                            "requirement": add(
                                value=60.0, quote="under 60"
                            ).requirement.model_dump(),
                        }
                    ],
                )
            return io.BytesIO(
                json.dumps(
                    {
                        "choices": [{"message": {"content": json.dumps(value)}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                ).encode()
            )

        self.transport.side_effect = completion
        self.app.run()

    def send(self, message):
        self.app.chat_input(key="shopping_input").set_value(message).run()
        self.assertFalse(self.app.exception)

    def test_default_compact_ui_search_correction_recall_and_snapshot(self):
        self.app.checkbox(key="user_memory_enabled").check().run()
        self.send(preference().quote)
        self.app.button(key="new_chat").click().run()
        self.send("I need bags")
        self.assertIn("blue", self.contexts[-1]["user_memory"]["records"][0]["text"])
        self.app.button(key="new_chat").click().run()
        self.send("boots under 100")
        # bags preference is irrelevant to boots, so it is not loaded for this goal.
        self.assertEqual(self.contexts[-1]["user_memory"]["records"], [])
        self.send("Actually under 60")
        self.assertEqual(self.contexts[-1]["state"]["hard"]["price"], [{"lt": 60.0}])
        self.assertTrue(all(c["memory_format"] == "compact" for c in self.contexts))
        sid = self.app.session_state["conversation"]
        snapshot = json.loads((self.sessions / sid / "state.json").read_text())
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["state"]["hard"]["price"], [{"lt": 60.0}])
        self.assertTrue(any(e.label == "Shopping details" for e in self.app.expander))
        self.assertTrue(any(e.label == "Audit history" for e in self.app.expander))
        self.assertTrue(list((self.root / "users").glob("*/profile.md")))


class CompactMemoryCliTests(unittest.TestCase):
    def setUp(self):
        fixtures.AgentTests.setUp(self)

    def test_default_chat_uses_compact_policy_and_snapshot(self):
        policy = fixtures.ScriptedPolicy(
            lambda c: decision(
                {"type": "SEARCH", "query": "boots"}, [add().model_dump()]
            ),
            recommend,
        )
        args = [
            "chat",
            "--user",
            "alice",
            "--catalogue",
            str(self.root / "catalog.jsonl"),
            "--index",
            str(self.root / "index.sqlite"),
            "--sessions-root",
            str(self.root / "cli-sessions"),
            "--env-file",
            str(self.root / "absent.env"),
            "--message",
            "under 100",
            "--json",
        ]
        with (
            patch("shopping_agent.cli.DeepSeekPolicy", return_value=policy),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(args), 0)
        response = json.loads(output.getvalue())
        self.assertEqual(response["status"], "ok")
        self.assertEqual(policy.contexts[0]["memory_format"], "compact")
        path = self.root / "cli-sessions" / response["session_id"] / "state.json"
        self.assertEqual(json.loads(path.read_text())["schema_version"], 2)
