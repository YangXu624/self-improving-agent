import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepseek_fixtures import TEST_KEY, completion, service
from test_retrieval import product

from shopping_agent.retrieval import build_index

HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
if HAS_STREAMLIT:
    from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def tearDownModule() -> None:
    # Streamlit 1.66 creates this testing-only directory at import. Explicit cleanup
    # keeps strict ResourceWarning checks clean at interpreter exit; no vendor edit.
    if HAS_STREAMLIT:
        from streamlit.testing.v1 import app_test

        directory = getattr(app_test, "TMP_DIR", None)
        if directory is not None:
            directory.cleanup()


@unittest.skipUnless(HAS_STREAMLIT, "Install the [ui] extra to run UI acceptance tests")
class StreamlitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue, self.index = (
            self.root / "catalog.jsonl",
            self.root / "index.sqlite",
        )
        self.sessions = self.root / "sessions"
        rows = [
            product("red", 45, Color="Red", Material="Cotton"),
            product("blue", 80, Color="Blue", Material="Leather"),
            product("missing", None),
        ]
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.catalogue, self.index)
        self.environment = patch.dict(
            os.environ,
            {
                "ASTRA_CATALOGUE": str(self.catalogue),
                "ASTRA_INDEX": str(self.index),
                "ASTRA_UI_SESSIONS": str(self.sessions),
                "DEEPSEEK_API_KEY": TEST_KEY,
                "DEEPSEEK_MODEL": "deepseek-flash",
                "ASTRA_ENV_FILE": str(self.root / "absent.env"),
                "ASTRA_MEMORY_FORMAT": "legacy",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.network = patch(
            "shopping_agent.provider.urlopen",
            side_effect=completion,
        )
        self.transport = self.network.start()
        self.addCleanup(self.network.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(self.app.exception)

    def send(self, message):
        self.app.chat_input(key="shopping_input").set_value(message).run()
        self.assertFalse(self.app.exception)

    def view(self):
        chat = service(self.catalogue, self.index, self.sessions)
        return chat.view(
            self.app.session_state["owner"], self.app.session_state["conversation"]
        )

    def button(self, label):
        return next(b for b in self.app.button if b.label == label)

    def test_chat_cards_state_activity_correction_and_rerun_no_duplicate(self):
        self.send("hello")
        self.assertEqual(self.view()["messages"][-1]["action"], "CLARIFY")
        self.send("boots under $100")
        self.assertEqual(len(self.app.chat_message), 4)
        self.assertEqual(self.view()["messages"][-1]["action"], "RECOMMEND")
        self.assertTrue(any("View activity" == e.label for e in self.app.expander))
        self.assertTrue(any("USD 45.00" in m.value for m in self.app.markdown))
        self.assertTrue(any("Price < USD 100" in t.value for t in self.app.text))
        self.send("actually under $60")
        response = self.view()["messages"][-1]
        self.assertEqual([p["id"] for p in response["products"]], ["red"])
        self.assertEqual(len(self.app.chat_message), 6)
        before = len(self.view()["messages"])
        self.app.checkbox(key="show_images").uncheck().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.view()["messages"]), before)
        state = self.view()["state"]
        self.assertEqual(
            [r["status"] for r in state["requirements"] if r["field"] == "price"],
            ["superseded", "active"],
        )

    def test_new_chat_selection_resume_and_owner_switch(self):
        self.send("boots under $60")
        first = self.app.session_state["conversation"]
        self.app.button(key="new_chat").click().run()
        second = self.app.session_state["conversation"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.view()["messages"], [])
        self.app.selectbox(key="conversation_picker").select(first).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.chat_message), 2)
        self.app.text_input(key="owner_input").set_value("bob")
        self.button("Switch shopper").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.view()["messages"], [])
        self.assertNotIn(first, self.app.selectbox(key="conversation_picker").options)
        self.app.text_input(key="resume_id").set_value(first)
        self.button("Resume chat").click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("Cannot open" in e.value for e in self.app.error))
        self.assertEqual(self.view()["messages"], [])

    def test_persistent_chat_resumes_in_fresh_app(self):
        self.send("boots under $60")
        sid = self.app.session_state["conversation"]
        self.app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(self.app.exception)
        self.app.text_input(key="resume_id").set_value(sid)
        self.button("Resume chat").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["conversation"], sid)
        self.assertEqual(len(self.app.chat_message), 2)

    def test_empty_result_and_missing_images_keep_text_and_trace_visible(self):
        self.send("boots under $1")
        self.assertEqual(self.view()["messages"][-1]["products"], [])
        self.assertTrue(any("No verified matches" in t.value for t in self.app.text))
        self.send("under $60")
        self.assertTrue(any("Image unavailable" in c.value for c in self.app.caption))
        self.assertTrue(any("USD 45.00" in m.value for m in self.app.markdown))

    def test_untrusted_input_rendered_as_text_and_live_usage_labelled(self):
        self.send('<img src=x onerror="alert(1)"> boots under $60')
        self.assertTrue(any("<img src=x" in t.value for t in self.app.text))
        self.assertTrue(any("DeepSeek" in c.value for c in self.app.caption))
        responses = [e for e in self.view()["events"] if e["type"] == "model_response"]
        self.assertTrue(
            all(e["payload"]["metadata"]["provider"] == "deepseek" for e in responses)
        )

    def test_missing_index_shows_setup_and_disables_input(self):
        with patch.dict(os.environ, {"ASTRA_INDEX": str(self.root / "absent.sqlite")}):
            app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("catalogue index" in e.value for e in app.error))
        self.assertTrue(app.chat_input[0].disabled)

    def test_unknown_card_profile_is_named_not_reported_as_a_missing_index(self):
        with patch.dict(os.environ, {"ASTRA_CARDS_PROFILE": "nope"}):
            app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("card profile" in e.value for e in app.error))
        self.assertFalse(any("catalogue index" in e.value for e in app.error))
        self.assertTrue(app.chat_input[0].disabled)

    def test_busy_session_send_error_is_visible_without_losing_session(self):
        sid = self.app.session_state["conversation"]
        with patch(
            "shopping_agent.ui_service.ChatService.send",
            side_effect=ValueError("session_busy"),
        ):
            self.send("boots")
        self.assertEqual(self.app.session_state["conversation"], sid)
        self.assertTrue(any("could not finish" in e.value for e in self.app.error))

    def test_transient_picker_reset_preserves_selected_session(self):
        self.send("boots under $100")
        selected = self.app.session_state["conversation"]
        self.app.session_state["conversation_picker"] = None
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["conversation"], selected)
        self.send("actually under $60")
        self.assertEqual(self.app.session_state["conversation"], selected)
        self.assertEqual(len(self.view()["messages"]), 4)

    def test_malformed_image_reference_does_not_break_product_cards(self):
        mapping = self.root / "images.json"
        mapping.write_text(json.dumps({"red": "http://["}))
        build_index(self.catalogue, self.index, mapping, replace=True)
        self.send("boots under $60")
        self.assertTrue(any("Image unavailable" in c.value for c in self.app.caption))
        self.assertTrue(any("USD 45.00" in m.value for m in self.app.markdown))

    def test_missing_key_disables_chat_without_creating_a_session(self):
        fresh_root = self.root / "no-key-sessions"
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "", "ASTRA_UI_SESSIONS": str(fresh_root)}
        ):
            app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.chat_input[0].disabled)
        self.assertTrue(any("missing_DEEPSEEK_API_KEY" in e.value for e in app.error))
        self.assertFalse(fresh_root.exists())

    def test_auth_error_is_reported_without_scripted_fallback_or_key_leak(self):
        from urllib.error import HTTPError

        self.transport.side_effect = HTTPError(
            "https://api.deepseek.com", 401, "private-header-content", {}, None
        )
        self.send("boots under $60")
        response = self.view()["messages"][-1]
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"], "provider_http_401")
        self.assertEqual(self.transport.call_count, 1)
        self.assertTrue(any("provider_http_401" in e.value for e in self.app.error))
        encoded = json.dumps(self.view())
        self.assertNotIn(TEST_KEY, encoded)
        self.assertNotIn("private-header-content", encoded)

    def test_reported_usage_is_visible_without_api_calls_on_widget_reruns(self):
        self.send("boots under $60")
        self.assertTrue(
            any(
                "Reported tokens: 200 input / 60 output" in c.value
                for c in self.app.caption
            )
        )
        calls = self.transport.call_count
        self.app.checkbox(key="show_images").uncheck().run()
        self.assertEqual(self.transport.call_count, calls)
