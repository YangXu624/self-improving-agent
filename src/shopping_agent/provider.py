"""DeepSeek JSON-mode policy. No SDK, automatic retries, or credential persistence."""

import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .configuration import read_env_file

MAX_RESPONSE_BYTES = 128000
MAX_OUTPUT_TOKENS = 2000


class ProviderError(RuntimeError):
    """Safe error code only: remote response bodies/headers may contain sensitive data."""


@dataclass(frozen=True)
class PolicyReply:
    content: str
    metadata: dict


class DeepSeekPolicy:
    def __init__(self, *, api_key=None, model=None, timeout=25):
        self._key = (
            api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        )
        if not self._key.strip():
            raise ProviderError("missing_DEEPSEEK_API_KEY")
        self._key = self._key.strip()
        if len(self._key) > 512 or any(not 33 <= ord(c) <= 126 for c in self._key):
            raise ProviderError("invalid_DEEPSEEK_API_KEY_format")
        self.model = (
            model
            if model is not None
            else os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
        )
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", self.model):
            raise ProviderError("invalid_model_name")
        self.timeout = timeout

    @classmethod
    def from_env_file(cls, path):
        """Resolve fresh local settings without caching a file secret in os.environ."""
        settings = read_env_file(path)
        key = os.environ.get("DEEPSEEK_API_KEY", settings.get("DEEPSEEK_API_KEY", ""))
        model = os.environ.get(
            "DEEPSEEK_MODEL", settings.get("DEEPSEEK_MODEL", "deepseek-flash")
        )
        return cls(api_key=key, model=model)

    def complete(self, messages):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        request = Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(payload, allow_nan=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise ProviderError(f"provider_http_{code}") from None
        except (URLError, TimeoutError, OSError):
            raise ProviderError("provider_network_failure") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("provider_response_size_limit")
        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError()
            usage = data.get("usage") or {}
            # Whitelist response metadata; do not log arbitrary headers or reasoning_content.
            counts = {
                k: usage[k]
                for k in (
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "prompt_cache_hit_tokens",
                    "prompt_cache_miss_tokens",
                )
                if isinstance(usage.get(k), int) and usage[k] >= 0
            }
            meta = {
                "provider": "deepseek",
                "model": self.model,
                "usage": counts,
                "finish_reason": str(choice.get("finish_reason", "unknown"))[:50],
            }
            returned_model = data.get("model")
            if isinstance(returned_model, str) and re.fullmatch(
                r"[A-Za-z0-9._/-]{1,100}", returned_model
            ):
                meta["returned_model"] = returned_model
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("provider_invalid_envelope") from None
        return PolicyReply(content=content, metadata=meta)
