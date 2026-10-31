"""Pluggable shopper simulators: a deterministic scripted one and an Ollama-backed one.

Neither import nor construction needs Ollama; only `OllamaShopper.respond` and
`check_ollama` make HTTP calls, through an injectable transport so tests use mocks. The
simulator receives only the shopper's memory (profile, ledger, window) and the assistant's
visible message and cards: never ground truth, scores, ASTRA memory or the condition.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from .memory import AssistantView, ContextBudgetError, ShopperMemory
from .models import ShopperReply

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "reveals": {"type": "array", "items": {"type": "string"}},
        "action": {"type": "string", "enum": ["reply", "accept", "give_up"]},
    },
    "required": ["message", "reveals", "action"],
}


class SimulatorError(RuntimeError):
    """A simulator fault with a safe code; never carries prompts or secrets."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SimulatorConfig:
    model: str = "llama3.1:latest"
    url: str = "http://127.0.0.1:11434"
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 4096
    max_tokens: int = 220
    timeout: float = 120.0
    window_turns: int = 8
    max_malformed_retries: int = 1

    @classmethod
    def from_env(cls, environ=None, **overrides):
        """ASTRA_SIM_* variables; explicit overrides win. Unset values use defaults."""
        env = os.environ if environ is None else environ
        base = cls()
        parsed = {
            "model": env.get("ASTRA_SIM_MODEL", base.model),
            "url": env.get("ASTRA_SIM_OLLAMA_URL", base.url).rstrip("/"),
            "temperature": float(env.get("ASTRA_SIM_TEMPERATURE", base.temperature)),
            "seed": int(env.get("ASTRA_SIM_SEED", base.seed)),
            "num_ctx": int(env.get("ASTRA_SIM_NUM_CTX", base.num_ctx)),
            "max_tokens": int(env.get("ASTRA_SIM_MAX_TOKENS", base.max_tokens)),
            "timeout": float(env.get("ASTRA_SIM_TIMEOUT", base.timeout)),
            "window_turns": int(env.get("ASTRA_SIM_WINDOW_TURNS", base.window_turns)),
        }
        parsed.update({k: v for k, v in overrides.items() if v is not None})
        config = cls(**parsed)
        if not config.url.startswith(("http://", "https://")):
            raise ValueError("ASTRA_SIM_OLLAMA_URL must be an http(s) URL")
        if (
            not 0 <= config.temperature <= 2
            or config.num_ctx < 512
            or config.max_tokens < 32
        ):
            raise ValueError("Invalid simulator sampling/context settings")
        return config

    @property
    def prompt_budget(self):
        """Tokens available for the prompt after the reply and a safety margin."""
        return self.num_ctx - self.max_tokens - 128


@dataclass
class SimulatorResult:
    reply: ShopperReply
    attempts: int = 1
    usage: dict = field(default_factory=dict)
    prompt_info: dict = field(default_factory=dict)
    raw_sha256: str = ""


class ShopperSimulator(Protocol):
    config: SimulatorConfig

    def respond(
        self, memory: ShopperMemory, view: AssistantView, feedback=()
    ) -> SimulatorResult: ...


class ScriptedShopper:
    """Deterministic rule-based shopper for offline tests; it never calls a model.

    Answers the facts a question asks about (repeating earlier answers consistently), else
    reveals the next unrevealed fact, reacts to product prices it can see, and stops when
    it has nothing left to say.
    """

    def __init__(self, config=None):
        self.config = config or SimulatorConfig(window_turns=8)

    def respond(self, memory, view, feedback=()):
        profile = memory.profile
        questions = memory.current_questions(view)
        reveals, parts = [], []
        for _question, keys, answered in questions:
            for key in keys:
                fact = profile.fact(key)
                if key in reveals:
                    continue
                parts.append(
                    ("As I said, " if answered else "")
                    + fact.statement[0].lower()
                    + fact.statement[1:]
                    if answered
                    else fact.statement
                )
                reveals.append(key)
        if questions and not parts:
            parts.append(profile.no_preference_reply)
        action = "reply"
        if not questions and view.products:
            budget = [
                f for f in profile.facts if f.field == "price" and f.kind == "hard"
            ]
            over = [
                p
                for p in view.products
                if budget
                and isinstance(p.get("price"), (int, float))
                and p["price"] >= float(budget[0].value)
            ]
            if over:
                parts.append("Those are over my budget; do you have anything cheaper?")
            else:
                parts.append("Those look good, thank you.")
                action = "accept"
        elif not questions:
            pending = [
                f
                for f in profile.facts
                if f.key not in memory.revealed and f.key not in profile.opening_keys
            ]
            if pending:
                parts.append(pending[0].statement)
                reveals.append(pending[0].key)
            else:
                parts.append("Thanks anyway, I'll look elsewhere.")
                action = "give_up"
        message = " ".join(parts)
        return SimulatorResult(
            ShopperReply(message=message, reveals=reveals[:2], action=action)
        )


def _post_json(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - local URL
        return json.loads(response.read(2_000_000))


def _get_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read(2_000_000))


class OllamaShopper:
    """Ollama /api/chat adapter with a JSON schema, bounded retries and safe errors."""

    def __init__(self, config=None, *, transport=None):
        self.config = config or SimulatorConfig.from_env()
        self.transport = transport or _post_json

    def _call(self, messages):
        c = self.config
        payload = {
            "model": c.model,
            "messages": messages,
            "stream": False,
            "format": REPLY_SCHEMA,
            "options": {
                "temperature": c.temperature,
                "seed": c.seed,
                "num_ctx": c.num_ctx,
                "num_predict": c.max_tokens,
            },
        }
        started = time.perf_counter()
        try:
            data = self.transport(c.url + "/api/chat", payload, c.timeout)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()  # release the response body
            raise SimulatorError(f"simulator_http_{code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            raise SimulatorError("simulator_unreachable") from None
        except ValueError:
            raise SimulatorError("simulator_invalid_envelope") from None
        try:
            content = data["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (KeyError, TypeError):
            raise SimulatorError("simulator_invalid_envelope") from None
        usage = {
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
            "latency_ms": (time.perf_counter() - started) * 1000,
        }
        return content, usage

    def respond(self, memory, view, feedback=()):
        try:
            messages, info = memory.build_messages(
                view, self.config.prompt_budget, feedback
            )
        except ContextBudgetError:
            raise SimulatorError("simulator_context_overflow") from None
        attempts, last_error, totals = (
            0,
            "simulator_malformed_reply",
            {"latency_ms": 0.0},
        )
        while attempts <= self.config.max_malformed_retries:
            attempts += 1
            content, usage = self._call(messages)
            for key, value in usage.items():
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0) + value
            try:
                reply = ShopperReply.model_validate_json(content)
            except ValidationError:
                last_error = "simulator_malformed_reply"
                messages = messages + [
                    {"role": "assistant", "content": content[:500]},
                    {
                        "role": "user",
                        "content": "That was not a valid JSON object with keys "
                        "message, reveals, action. Reply again with ONLY that JSON object.",
                    },
                ]
                continue
            return SimulatorResult(
                reply,
                attempts,
                totals,
                info,
                hashlib.sha256(content.encode()).hexdigest(),
            )
        raise SimulatorError(last_error)


def check_ollama(config, *, transport=None, getter=None):
    """Connectivity, model presence and a tiny structured-output probe. Returns a report."""
    getter = getter or _get_json
    report = {
        "url": config.url,
        "model": config.model,
        "reachable": False,
        "model_present": False,
        "probe_ok": False,
        "problems": [],
    }
    try:
        tags = getter(config.url + "/api/tags", min(config.timeout, 15.0))
        report["reachable"] = True
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
        report["problems"].append(
            "Cannot reach Ollama. Start it (ollama serve / the desktop app) and check "
            "ASTRA_SIM_OLLAMA_URL."
        )
        return report
    names = {m.get("name", "") for m in tags.get("models", []) if isinstance(m, dict)}
    report["models_available"] = sorted(names)
    wanted = config.model if ":" in config.model else config.model + ":latest"
    report["model_present"] = wanted in names or config.model in names
    if not report["model_present"]:
        report["problems"].append(f"Model not found: run `ollama pull {config.model}`.")
        return report
    from .models import Fact
    from .scenarios import (
        ShopperProfile,
    )  # local import: probe uses a synthetic profile

    profile = ShopperProfile(
        scenario_id="probe",
        persona="Brief and consistent.",
        facts=(
            Fact(
                key="budget",
                kind="hard",
                field="price",
                op="lt",
                value=50.0,
                statement="My budget is under $50.",
                keywords=["budget", "price"],
            ),
            Fact(
                key="color",
                kind="soft",
                field="color",
                op="eq",
                value="red",
                statement="I'd like it in red.",
                keywords=["color"],
            ),
        ),
        opening_keys=(),
    )
    memory = ShopperMemory(profile, window_turns=config.window_turns)
    shopper = OllamaShopper(config, transport=transport)
    try:
        view = AssistantView("What is your budget?", turn=1, turns_left=3)
        memory.record_assistant(view)
        result = shopper.respond(memory, view)
        report["probe_ok"] = "50" in result.reply.message
        report["probe_reply"] = result.reply.message
        report["probe_latency_ms"] = round(result.usage.get("latency_ms", 0), 1)
        if not report["probe_ok"]:
            report["problems"].append(
                "Model replied in valid JSON but did not state the budget; consistency may be poor."
            )
    except SimulatorError as exc:
        report["problems"].append(f"Structured probe failed: {exc.code}")
    return report
