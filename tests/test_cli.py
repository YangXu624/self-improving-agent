import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_agent import ScriptedPolicy, decision, recommend, search
from test_retrieval import product

from shopping_agent.cli import load_env, main
from shopping_agent.sessions import SessionStore


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalogue = self.root / "catalog.jsonl"
        self.images = self.root / "images.json"
        self.index = self.root / "search.sqlite"
        self.sessions = self.root / "sessions"
        self.catalogue.write_text(json.dumps(product("boot")) + "\n")
        self.images.write_text("{}")

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def build(self):
        code, out, err = self.run_cli(
            [
                "index",
                "--catalogue",
                str(self.catalogue),
                "--images",
                str(self.images),
                "--index",
                str(self.index),
            ]
        )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["count"], "1")

    def chat_args(self):
        return [
            "chat",
            "--memory-format",
            "legacy",
            "--user",
            "alice",
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--sessions-root",
            str(self.sessions),
            "--env-file",
            str(self.root / "absent.env"),
        ]

    def test_index_inspection_and_module_help_without_credentials(self):
        self.build()
        sid = SessionStore(self.sessions).create("alice")
        with patch.dict(os.environ, {}, clear=True):
            code, out, err = self.run_cli(
                [
                    "inspect",
                    "--user",
                    "alice",
                    "--session",
                    sid,
                    "--sessions-root",
                    str(self.sessions),
                    "--events",
                ]
            )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["state"]["version"], 0)
        self.assertEqual(json.loads(out)["events"][0]["type"], "session_created")
        help_result = subprocess.run(
            [sys.executable, "-m", "shopping_agent", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("inspect", help_result.stdout)

    def test_single_message_resume_and_idempotency_through_cli(self):
        self.build()
        policy = ScriptedPolicy(
            search,
            recommend,
            lambda c: decision(c, {"type": "RESPOND", "message": "You are welcome"}),
        )
        with patch("shopping_agent.cli.DeepSeekPolicy", return_value=policy):
            code, out, err = self.run_cli(
                self.chat_args()
                + ["--message", "boots", "--request-id", "one", "--json"]
            )
            self.assertEqual((code, err), (0, ""))
            response = json.loads(out)
            self.assertEqual(response["products"][0]["id"], "boot")
            sid = response["session_id"]
            code, out, err = self.run_cli(
                self.chat_args()
                + [
                    "--session",
                    sid,
                    "--message",
                    "boots",
                    "--request-id",
                    "one",
                    "--json",
                ]
            )
            self.assertEqual(json.loads(out), response)
            code, out, err = self.run_cli(
                self.chat_args() + ["--session", sid, "--message", "thanks", "--json"]
            )
            self.assertEqual(json.loads(out)["message"], "You are welcome")
        self.assertEqual(len(policy.contexts), 3)

    def test_interactive_state_and_exit_do_not_call_model(self):
        self.build()
        policy = ScriptedPolicy()
        with (
            patch("shopping_agent.cli.DeepSeekPolicy", return_value=policy),
            patch("builtins.input", side_effect=["/state", "/quit"]),
        ):
            code, out, err = self.run_cli(self.chat_args())
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Session:", out)
        self.assertIn('"version": 0', out)
        self.assertEqual(policy.contexts, [])

    def test_missing_key_fails_before_session_creation(self):
        self.build()
        with patch.dict(os.environ, {}, clear=True):
            code, out, err = self.run_cli(self.chat_args() + ["--message", "boots"])
        self.assertEqual(code, 1)
        self.assertIn("missing_DEEPSEEK_API_KEY", err)
        self.assertFalse(self.sessions.exists())

    def test_env_no_evaluation_and_process_environment_precedence(self):
        env = self.root / ".env"
        env.write_text(
            'DEEPSEEK_API_KEY="local-test-value"\nDEEPSEEK_MODEL=deepseek-flash\n'
        )
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "process-value"}, clear=True):
            load_env(env)
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "process-value")
            self.assertEqual(os.environ["DEEPSEEK_MODEL"], "deepseek-flash")
        env.write_text("DEEPSEEK_API_KEY=$(do-not-execute)\n")
        with patch.dict(os.environ, {}, clear=True):
            load_env(env)
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "$(do-not-execute)")
        env.write_text("UNSUPPORTED_KEY=test-secret\n")
        with self.assertRaises(ValueError) as caught:
            load_env(env)
        self.assertNotIn("test-secret", str(caught.exception))

    def test_rebuild_explicit_and_stale_catalogue_rejected(self):
        self.build()
        code, _, _ = self.run_cli(
            [
                "index",
                "--catalogue",
                str(self.catalogue),
                "--images",
                str(self.images),
                "--index",
                str(self.index),
            ]
        )
        self.assertEqual(code, 1)
        self.catalogue.write_text(
            self.catalogue.read_text() + json.dumps(product("other")) + "\n"
        )
        with patch("shopping_agent.cli.DeepSeekPolicy", return_value=ScriptedPolicy()):
            code, out, err = self.run_cli(self.chat_args() + ["--message", "boots"])
        self.assertEqual(code, 1)
        self.assertIn("Stale catalogue index", err)
        self.assertFalse(self.sessions.exists())
