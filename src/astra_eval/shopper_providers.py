"""Thin, explicitly budgeted V3 transports. No network or credential access on import."""

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from shopping_agent.configuration import read_env_file

from .simulators import SimulatorConfig, SimulatorError

V3_VERSION = "shopper-v3-autonomous-1"
CLAUDE_API_VERSION = "2026-10-21"
TRANSPORT_VERSION = "shopper-transport-2"


@dataclass(frozen=True)
class V3Config(SimulatorConfig):
    protocol_version: str = field(default=V3_VERSION, init=False)
    provider: Literal["ollama", "claude"] = "ollama"
    max_malformed_retries: int = field(default=0, init=False)
    temperature: float | None = None
    claude_thinking: str | None = field(default=None, init=False)
    claude_effort: str | None = field(default=None, init=False)

    def __post_init__(self):
        requested_temperature = self.temperature
        if self.provider == "claude" and requested_temperature is not None:
            raise ValueError(
                "Claude shopper does not support temperature; omit the setting"
            )
        # The base validates shared bounds and Ollama defaults; Claude records no temperature.
        if requested_temperature is None:
            object.__setattr__(self, "temperature", 0.0)
        super().__post_init__()
        if self.provider == "claude":
            object.__setattr__(self, "temperature", None)
            if self.model.startswith("claude-sonnet-5-5"):
                object.__setattr__(self, "claude_thinking", "between_tools")
                object.__setattr__(self, "claude_effort", "low")
        if self.provider not in {"ollama", "claude"}:
            raise ValueError("Unknown shopper provider")
        if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", self.model):
            raise ValueError("Invalid shopper model")
        if self.provider == "claude" and not self.model.startswith("claude-"):
            raise ValueError("Claude shopper requires an explicit Claude model")

    @classmethod
    def from_env(cls, environ=None, **overrides):
        """Keep Ollama decoding settings; reject even zero temperature for Claude."""
        env = os.environ if environ is None else environ
        provider = overrides.pop("provider", "ollama")
        if provider == "claude" and (
            overrides.get("temperature") is not None or "ASTRA_SIM_TEMPERATURE" in env
        ):
            raise ValueError(
                "Claude shopper does not support temperature; omit the setting"
            )
        values = asdict(SimulatorConfig.from_env(env, **overrides))
        values.pop("protocol_version")
        values.pop("max_malformed_retries")
        if provider == "claude":
            values["temperature"] = None
        return cls(provider=provider, **values)


@dataclass(frozen=True)
class Completion:
    content: str
    usage: dict
    model: str


class ShopperProvider(Protocol):
    config: V3Config
    journal: "RequestJournal"
    usage: dict[str, float]

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


def claude_model(path: Path, environ: dict) -> str:
    """Resolve a configured shopper model, without mutating the process or contacting an API."""
    settings = read_env_file(path) if "ANTHROPIC_MODEL" not in environ else {}
    model = environ.get("ANTHROPIC_MODEL", settings.get("ANTHROPIC_MODEL", ""))
    if not re.fullmatch(r"claude-[A-Za-z0-9._:/-]{1,93}", model):
        raise ValueError("Set ANTHROPIC_MODEL or --sim-model to a Claude model ID")
    return model


def claude_key(path: Path, environ: dict) -> str:
    """Read a shared .env or explicit shopper file; never log or cache credentials."""
    settings = read_env_file(path) if "ANTHROPIC_API_KEY" not in environ else {}
    key = environ.get("ANTHROPIC_API_KEY", settings.get("ANTHROPIC_API_KEY", ""))
    if not key.strip():
        raise ValueError("Missing ANTHROPIC_API_KEY")
    return key


class JsonShopperProvider:
    """Shared safe accounting; request and response shapes stay provider-specific."""

    def __init__(
        self,
        config: V3Config,
        journal: RequestJournal,
        *,
        api_key: str | None = None,
        transport=None,
        cost_budget=None,
    ):
        if config.provider == "claude" and (
            not api_key
            or len(api_key) > 512
            or any(not 33 <= ord(c) <= 126 for c in api_key)
        ):
            raise ValueError("Missing or invalid Claude shopper credential")
        self.config, self.journal = config, journal
        self._key, self.transport = api_key, transport or post_json
        self.usage: dict[str, float] = {}
        self.cost_budget = cost_budget

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
                "anthropic-version": CLAUDE_API_VERSION,
            }
            payload = {
                "model": c.model,
                "system": messages[0]["content"],
                "messages": messages[1:],
                "max_tokens": c.max_tokens,
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
            }
            if c.claude_thinking is not None:
                payload["thinking"] = {"type": c.claude_thinking}
                payload["output_config"]["effort"] = c.claude_effort
        if self.journal.calls >= self.journal.max_calls:
            raise SimulatorError("shopper_call_budget_exhausted")
        reservation = None
        if self.cost_budget is not None:
            try:
                reservation = self.cost_budget.reserve(
                    c.provider, c.model, payload, c.max_tokens
                )
            except ValueError:
                raise SimulatorError("shopper_spending_budget_exhausted") from None
        call = self.journal.begin(
            provider=c.provider,
            transport_version=TRANSPORT_VERSION,
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
            if reservation is not None:
                self.cost_budget.unknown(reservation)
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
        usage = response_usage(data, c.provider)
        usage["latency_ms"] = elapsed
        if reservation is not None:
            try:
                self.cost_budget.settle(reservation, usage)
            except ValueError:
                raise SimulatorError("shopper_cost_usage_unknown") from None
        for key, value in usage.items():
            self.usage[key] = self.usage.get(key, 0) + value
        self.journal.append(
            "provider_usage",
            call=call,
            usage=usage,
            usage_complete=all(
                k in usage
                for k in (
                    (
                        "prompt_tokens",
                        "completion_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                    )
                    if c.provider == "claude"
                    else ("prompt_tokens", "completion_tokens")
                )
            ),
        )
        try:
            if not isinstance(data, dict):
                raise ValueError("Invalid provider envelope")
            if c.provider == "ollama":
                if data.get("done") is False or data.get("done_reason") == "length":
                    raise ValueError("Incomplete shopper response")
                content = data["message"]["content"]
            else:
                if data.get("stop_reason") != "end_turn":
                    raise ValueError("Incomplete or refused shopper response")
                blocks = data["content"]
                if not isinstance(blocks, list) or any(
                    not isinstance(b, dict) for b in blocks
                ):
                    raise ValueError("Malformed content blocks")
                text = [b["text"] for b in blocks if b.get("type") == "text"]
                if len(text) != 1:
                    raise ValueError("Expected exactly one structured text block")
                content = text[0]
            if (
                not isinstance(content, str)
                or not content.strip()
                or not math.isfinite(elapsed)
            ):
                raise ValueError("Missing shopper text or invalid elapsed time")
            model = data.get("model", c.model)
            if not isinstance(model, str):
                raise ValueError("Invalid model identity")
        except (KeyError, TypeError, ValueError):
            raise SimulatorError("shopper_invalid_envelope") from None
        return Completion(content, usage, model)


def response_usage(data, provider: str) -> dict:
    """Whitelisted counts; missing/invalid usage is absent, never coerced to zero."""
    if not isinstance(data, dict):
        return {}
    if provider == "claude":
        raw = data.get("usage")
        if not isinstance(raw, dict):
            return {}
        source = {
            "prompt_tokens": raw.get("input_tokens"),
            "completion_tokens": raw.get("output_tokens"),
            "cache_read_tokens": raw.get("cache_read_input_tokens"),
            "cache_write_tokens": raw.get("cache_creation_input_tokens"),
        }
    else:
        source = {
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
        }
    return {
        k: v
        for k, v in source.items()
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0
    }
