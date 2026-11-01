"""Thin, explicitly budgeted V3 transports. No network or credential access on import."""

import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from .simulators import SimulatorConfig, SimulatorError

V3_VERSION = "shopper-v3-autonomous-1"


@dataclass(frozen=True)
class V3Config(SimulatorConfig):
    protocol_version: str = field(default=V3_VERSION, init=False)
    provider: Literal["ollama", "claude"] = "ollama"

    def __post_init__(self):
        super().__post_init__()
        if self.provider not in {"ollama", "claude"}:
            raise ValueError("Unknown shopper provider")
        if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", self.model):
            raise ValueError("Invalid shopper model")
        if self.provider == "claude" and self.temperature > 1:
            raise ValueError("Claude shopper temperature must be at most one")
        if self.provider == "claude" and not self.model.startswith("claude-"):
            raise ValueError("Claude shopper requires an explicit Claude model")


@dataclass(frozen=True)
class Completion:
    content: str
    usage: dict
    model: str


class ShopperProvider(Protocol):
    config: V3Config

    def complete(
        self, messages: list[dict], schema: dict, context: dict
    ) -> Completion: ...


class RequestJournal:
    """One new journal and a hard call cap, including failed attempts. Never log headers."""

    def __init__(self, path: Path, max_calls: int):
        if (
            isinstance(max_calls, bool)
            or not isinstance(max_calls, int)
            or max_calls < 1
        ):
            raise ValueError("Positive shopper call budget required")
        self.path, self.max_calls, self.calls = Path(path), max_calls, 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)

    def append(self, kind: str, **payload) -> None:
        with self.path.open("a") as handle:
            handle.write(
                json.dumps(
                    {"kind": kind, "utc": datetime.now(UTC).isoformat(), **payload},
                    ensure_ascii=False,
                )
                + "\n"
            )

    def begin(self, **payload) -> int:
        if self.calls >= self.max_calls:
            raise SimulatorError("shopper_call_budget_exhausted")
        self.calls += 1
        self.append("provider_request", call=self.calls, **payload)
        return self.calls


def post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("Oversized provider response")
    return json.loads(data)


def claude_key(path: Path, environ: dict) -> str:
    """Separate ignored .env.shopper; never change ASTRA's .env parser or log its contents."""
    if environ.get("ANTHROPIC_API_KEY"):
        return environ["ANTHROPIC_API_KEY"]
    path = Path(path)
    if not path.exists():
        raise ValueError("Missing ANTHROPIC_API_KEY")
    if path.stat().st_size > 16000:
        raise ValueError("Shopper environment file too large")
    settings = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key.strip() != "ANTHROPIC_API_KEY":
            raise ValueError("Unsupported shopper environment setting")
        value = value.strip()
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("Invalid shopper environment syntax")
            value = value[1:-1]
        settings[key.strip()] = value
    if not settings.get("ANTHROPIC_API_KEY"):
        raise ValueError("Missing ANTHROPIC_API_KEY")
    return settings["ANTHROPIC_API_KEY"]


class JsonShopperProvider:
    """Shared safe accounting; request and response shapes stay provider-specific."""

    def __init__(
        self,
        config: V3Config,
        journal: RequestJournal,
        *,
        api_key: str | None = None,
        transport=None,
    ):
        if config.provider == "claude" and (
            not api_key
            or len(api_key) > 512
            or any(not 33 <= ord(c) <= 126 for c in api_key)
        ):
            raise ValueError("Missing or invalid Claude shopper credential")
        self.config, self.journal = config, journal
        self._key, self.transport = api_key, transport or post_json

    def complete(self, messages: list[dict], schema: dict, context: dict) -> Completion:
        c = self.config
        if c.provider == "ollama":
            url, headers = c.url + "/api/chat", {"Content-Type": "application/json"}
            payload = {
                "model": c.model,
                "messages": messages,
                "stream": False,
                "format": schema,
                "options": {
                    "temperature": c.temperature,
                    "seed": c.seed,
                    "num_ctx": c.num_ctx,
                    "num_predict": c.max_tokens,
                },
            }
        else:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self._key,
                "anthropic-version": "2026-10-21",
            }
            payload = {
                "model": c.model,
                "system": messages[0]["content"],
                "messages": messages[1:],
                "temperature": c.temperature,
                "max_tokens": c.max_tokens,
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
            }
        call = self.journal.begin(
            provider=c.provider,
            configured_model=c.model,
            url=url,
            payload=payload,
            context=context,
            seed_supported=c.provider == "ollama",
        )
        started = time.perf_counter()
        try:
            data = self.transport(url, payload, headers, c.timeout)
        except Exception as exc:
            # Response bodies and exception text may contain credentials. Only safe metadata.
            code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            self.journal.append(
                "provider_error",
                call=call,
                error_type=type(exc).__name__,
                http_status=code,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise SimulatorError("shopper_provider_failure") from None
        elapsed = (time.perf_counter() - started) * 1000
        self.journal.append(
            "provider_response", call=call, response=data, latency_ms=elapsed
        )
        try:
            if not isinstance(data, dict):
                raise ValueError("Invalid provider envelope")
            if c.provider == "ollama":
                if data.get("done") is False or data.get("done_reason") == "length":
                    raise ValueError("Incomplete shopper response")
                content = data["message"]["content"]
                source = {
                    "prompt_tokens": data.get("prompt_eval_count"),
                    "completion_tokens": data.get("eval_count"),
                }
            else:
                if data.get("stop_reason") != "end_turn":
                    raise ValueError("Incomplete or refused shopper response")
                content = "".join(
                    b["text"] for b in data["content"] if b.get("type") == "text"
                )
                raw_usage = data.get("usage", {})
                source = {
                    "prompt_tokens": raw_usage.get("input_tokens"),
                    "completion_tokens": raw_usage.get("output_tokens"),
                    "cache_read_tokens": raw_usage.get("cache_read_input_tokens"),
                    "cache_write_tokens": raw_usage.get("cache_creation_input_tokens"),
                }
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Missing shopper text")
            usage = {
                k: v
                for k, v in source.items()
                if isinstance(v, int) and not isinstance(v, bool) and v >= 0
            }
            usage["latency_ms"] = elapsed
            if not math.isfinite(elapsed):
                raise ValueError("Invalid elapsed time")
            model = data.get("model", c.model)
            if not isinstance(model, str):
                raise ValueError("Invalid model identity")
        except (KeyError, TypeError, ValueError):
            raise SimulatorError("shopper_invalid_envelope") from None
        return Completion(content, usage, model)
