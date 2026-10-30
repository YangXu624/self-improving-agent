import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from shopping_agent.provider import DeepSeekPolicy, ProviderError


class ProviderTests(unittest.TestCase):
    def response(self, content="{}", **extra):
        return io.BytesIO(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": content,
                                "reasoning_content": "never log this",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 6,
                        "secret": "hidden",
                    },
                    **extra,
                }
            ).encode()
        )

    def test_transport_contract_and_metadata_whitelist(self):
        with patch(
            "shopping_agent.provider.urlopen", return_value=self.response()
        ) as send:
            p = DeepSeekPolicy(api_key="test-secret", model="deepseek-flash")
            reply = p.complete([{"role": "system", "content": "JSON"}])
            request = send.call_args.args[0]
            body = json.loads(request.data)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertEqual(
                request.full_url, "https://api.deepseek.com/chat/completions"
            )
            self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
            self.assertEqual(send.call_count, 1)
            self.assertNotIn("test-secret", json.dumps(body))
            self.assertNotIn("secret", json.dumps(reply.metadata))
            self.assertNotIn("reasoning", json.dumps(reply.metadata))

    def test_http_and_network_errors_are_sanitized_no_retries(self):
        for error, code in [
            (
                HTTPError("https://example", 401, "test-secret", {}, None),
                "provider_http_401",
            ),
            (URLError("test-secret"), "provider_network_failure"),
        ]:
            with patch("shopping_agent.provider.urlopen", side_effect=error) as send:
                with self.assertRaisesRegex(ProviderError, code) as caught:
                    DeepSeekPolicy(api_key="test-secret").complete([])
                self.assertNotIn("test-secret", str(caught.exception))
                self.assertEqual(send.call_count, 1)

    def test_missing_key_blank_content_bad_envelope_and_size_limit(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ProviderError):
            DeepSeekPolicy()
        for raw, expected in [
            (io.BytesIO(b"{}"), "invalid_envelope"),
            (io.BytesIO(b"x" * 128001), "size_limit"),
        ]:
            with patch("shopping_agent.provider.urlopen", return_value=raw):
                with self.assertRaisesRegex(ProviderError, expected):
                    DeepSeekPolicy(api_key="test").complete([])
        # JSON-mode blank content is returned to the bounded orchestrator for validation.
        with patch(
            "shopping_agent.provider.urlopen", return_value=self.response(content="")
        ):
            self.assertEqual(DeepSeekPolicy(api_key="test").complete([]).content, "")

    def test_invalid_key_format_never_reaches_transport_or_error_text(self):
        for key in ["test-secret\nheader", "test-secret\x00", "test-secret⚠"]:
            with patch("shopping_agent.provider.urlopen") as send:
                with self.assertRaises(ProviderError) as caught:
                    DeepSeekPolicy(api_key=key)
                self.assertNotIn("test-secret", str(caught.exception))
                send.assert_not_called()
