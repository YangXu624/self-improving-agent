"""Sequential evaluation-only cost reservations. Never change prompts or pricing silently."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from shopping_agent.provider import MAX_OUTPUT_TOKENS, ProviderError

# Conservative standard rates in USD per million tokens, checked 2026-11-01.
# Cache creation uses the more expensive 1h rate; DeepSeek uses peak rates.
RATES = {
    "claude": {"input": "2", "output": "10", "cache_read": "0.1", "cache_write": "4"},
    "deepseek": {"input": "0.3", "output": "1.2", "cache_read": "0.006"},
}
MILLION = Decimal(1_000_000)
FRAMING_ALLOWANCE = 4096


class CostLimitError(ValueError):
    """Safe local stop, before a request or when billing cannot be reconciled."""


def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid monetary limit") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Monetary limits must be finite and nonnegative")
    return result


def count(usage, key):
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CostLimitError("cost_usage_unknown")
    return value


class ApiCostBudget:
    """One process, both providers, reserve before I/O; ambiguous spend stays reserved.

    UTF-8 wire bytes plus framing are a conservative token allowance, not a provider
    billing guarantee. Actual usage is reconciled; exceeding that allowance blocks further
    calls. Journals cannot be resumed or overwritten. Decimal prevents rounding drift.
    """

    def __init__(self, path: Path, ceiling, prior=0):
        self.ceiling, self.total = money(ceiling), money(prior)
        if not self.ceiling or self.total >= self.ceiling:
            raise ValueError("Prior allowance must leave positive spending room")
        self.blocked = False
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)
        self.write(
            "budget_open",
            ceiling_usd=str(self.ceiling),
            prior_allowance_usd=str(self.total),
            rates=RATES,
            framing_tokens=FRAMING_ALLOWANCE,
        )

    def write(self, kind, **payload):
        with self.path.open("a") as handle:
            handle.write(
                json.dumps(
                    {"kind": kind, "accounted_usd": str(self.total), **payload},
                    sort_keys=True,
                )
                + "\n"
            )

    def reserve(self, provider, model, payload, output_cap):
        supported = (
            model == "claude-sonnet-5-5"
            if provider == "claude"
            else model == "deepseek-flash"
        )
        if not supported or provider not in RATES:
            raise CostLimitError("cost_rates_not_verified_for_model")
        if self.blocked:
            raise CostLimitError("cost_budget_blocked")
        wire = json.dumps(payload, ensure_ascii=True).encode()
        input_cap = len(wire) + FRAMING_ALLOWANCE
        rates = RATES[provider]
        input_rate = max(money(rates["input"]), money(rates.get("cache_write", 0)))
        amount = (
            input_cap * input_rate + output_cap * money(rates["output"])
        ) / MILLION
        if self.total + amount > self.ceiling:
            self.blocked = True
            self.write("request_denied", provider=provider, required_usd=str(amount))
            raise CostLimitError("spending_budget_exhausted")
        self.total += amount
        reservation = {
            "provider": provider,
            "model": model,
            "reserved_usd": str(amount),
            "input_cap": input_cap,
            "output_cap": output_cap,
            "payload_sha256": hashlib.sha256(wire).hexdigest(),
        }
        self.write("request_reserved", **reservation)
        return reservation

    def unknown(self, reservation):
        self.blocked = True
        self.write("usage_unknown_reservation_retained", **reservation)

    def settle(self, reservation, usage):
        try:
            inp, out = count(usage, "prompt_tokens"), count(usage, "completion_tokens")
            rates = RATES[reservation["provider"]]
            if reservation["provider"] == "claude":
                read, created = (
                    count(usage, "cache_read_tokens"),
                    count(usage, "cache_write_tokens"),
                )
                input_total = inp + read + created
                cost = (
                    inp * money(rates["input"])
                    + read * money(rates["cache_read"])
                    + created * money(rates["cache_write"])
                    + out * money(rates["output"])
                ) / MILLION
            else:
                # Without cache breakdown, all input is conservatively charged at miss rate.
                hit = (
                    count(usage, "prompt_cache_hit_tokens")
                    if "prompt_cache_hit_tokens" in usage
                    else 0
                )
                if hit > inp:
                    raise CostLimitError("cost_usage_inconsistent")
                input_total = inp
                cost = (
                    (inp - hit) * money(rates["input"])
                    + hit * money(rates["cache_read"])
                    + out * money(rates["output"])
                ) / MILLION
            if (
                input_total > reservation["input_cap"]
                or out > reservation["output_cap"]
            ):
                # Preserve the larger known charge too; block further calls either way.
                self.total += max(cost - money(reservation["reserved_usd"]), Decimal(0))
                raise CostLimitError("cost_usage_exceeds_reserved_token_bound")
        except CostLimitError:
            self.unknown(reservation)
            raise
        self.total += cost - money(reservation["reserved_usd"])
        self.write(
            "usage_settled",
            **reservation,
            usage=usage,
            conservative_estimated_usd=str(cost),
        )
        return cost


class BudgetedPolicy:
    """Wrap ASTRA's existing policy for evaluation accounting; delegate unchanged messages."""

    def __init__(self, policy, budget: ApiCostBudget):
        if policy.model != "deepseek-flash":
            raise ValueError("Cost rates are verified only for deepseek-flash")
        self.policy, self.budget, self.model = policy, budget, policy.model

    def complete(self, messages):
        try:
            reservation = self.budget.reserve(
                "deepseek",
                self.model,
                {"model": self.model, "messages": messages},
                MAX_OUTPUT_TOKENS,
            )
        except CostLimitError as error:
            raise ProviderError("provider_" + str(error)) from None
        try:
            reply = self.policy.complete(messages)
        except Exception:
            self.budget.unknown(reservation)
            raise
        try:
            self.budget.settle(reservation, reply.metadata.get("usage", {}))
        except CostLimitError as error:
            raise ProviderError("provider_" + str(error)) from None
        return reply
