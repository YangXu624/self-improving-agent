"""DeepSeek native tools, with original cost-accounting injected at composition time."""

from typing import Any

from langchain_deepseek import ChatDeepSeek
from pydantic import Field

from shopping_agent.provider import MAX_OUTPUT_TOKENS, ProviderError


class BudgetedDeepSeek(ChatDeepSeek):
    """Reserve the full serialized request including tool schemas before each HTTP call.

    Accepts the existing ApiCostBudget interface without importing evaluation truth.
    Synchronous only; there is no SDK retry or hidden asynchronous bypass.
    """

    cost_budget: Any = Field(exclude=True, repr=False)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.max_retries != 0 or self.streaming:
            raise ProviderError("framework_retries_or_streaming_not_permitted")
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        if (
            payload.get("max_tokens") != MAX_OUTPUT_TOKENS
            or payload.get("model") != "deepseek-flash"
            or payload.get("stream", False)
        ):
            raise ProviderError("framework_output_cap_changed")
        reservation = self.cost_budget.reserve(
            "deepseek", self.model_name, payload, MAX_OUTPUT_TOKENS
        )
        try:
            result = super()._generate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except Exception:
            self.cost_budget.unknown(reservation)
            raise ProviderError("framework_provider_failure") from None
        usage = (result.llm_output or {}).get("token_usage") or {}
        self.cost_budget.settle(reservation, usage)
        return result

    async def _agenerate(self, *args, **kwargs):
        raise ProviderError("framework_async_not_supported")


def deepseek_model(*, api_key: str, model: str, budget, http_client=None):
    """Construct without making a request. Keep ASTRA's endpoint and decoding settings."""
    if model != "deepseek-flash":
        raise ValueError("Experimental accounting is verified only for deepseek-flash")
    return BudgetedDeepSeek(
        api_key=api_key,
        model=model,
        base_url="https://api.deepseek.com",
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
        timeout=25,
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
        streaming=False,
        disable_streaming=True,
        cost_budget=budget,
        http_client=http_client,
    )
