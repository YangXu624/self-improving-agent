import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shopping_agent.configuration import read_env_file
from shopping_agent.provider import DeepSeekPolicy, ProviderError


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".env"

    def test_file_resolution_does_not_cache_credentials_in_process_environment(self):
        self.path.write_text(
            'DEEPSEEK_API_KEY="first-test-value"\nDEEPSEEK_MODEL=deepseek-flash\n'
        )
        with patch.dict(os.environ, {}, clear=True):
            first = DeepSeekPolicy.from_env_file(self.path)
            self.path.write_text('DEEPSEEK_API_KEY="replacement-test-value"\n')
            second = DeepSeekPolicy.from_env_file(self.path)
            self.assertNotIn("DEEPSEEK_API_KEY", os.environ)
            self.assertNotEqual(first._key, second._key)
            self.assertEqual(second.model, "deepseek-flash")

    def test_process_values_take_precedence_and_explicit_blank_fails_closed(self):
        self.path.write_text("DEEPSEEK_API_KEY=file-test-value\n")
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "process-test-value"}, clear=True
        ):
            self.assertEqual(
                DeepSeekPolicy.from_env_file(self.path)._key, "process-test-value"
            )
            with self.assertRaisesRegex(ProviderError, "missing_DEEPSEEK_API_KEY"):
                DeepSeekPolicy(api_key="")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=True):
            with self.assertRaisesRegex(ProviderError, "missing_DEEPSEEK_API_KEY"):
                DeepSeekPolicy.from_env_file(self.path)

    def test_missing_invalid_and_unsupported_configuration_never_echo_values(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(read_env_file(self.path), {})
            with self.assertRaisesRegex(ProviderError, "missing_DEEPSEEK_API_KEY"):
                DeepSeekPolicy.from_env_file(self.path)
        for text in [
            "OTHER_SETTING=private-test-value\n",
            'DEEPSEEK_API_KEY="private-test-value\n',
        ]:
            self.path.write_text(text)
            with self.assertRaises(ValueError) as error:
                read_env_file(self.path)
            self.assertNotIn("private-test-value", str(error.exception))

    def test_parse_is_literal_and_does_not_evaluate_shell(self):
        self.path.write_text("DEEPSEEK_API_KEY=$(never-execute)\n")
        self.assertEqual(
            read_env_file(self.path)["DEEPSEEK_API_KEY"], "$(never-execute)"
        )
