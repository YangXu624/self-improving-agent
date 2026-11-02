"""Bounded dynamic contexts and observable native model/tool calls."""

import time
from contextlib import closing
from typing import Annotated, Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import create_model

from shopping_agent.contracts import Clarify, Decision, Recommend, Respond, Search
from shopping_agent.user_memory import MemoryDecision

from .engine import TOOL_ACTIONS, Turn


def tools(memory_enabled: bool) -> list:
    """Schemas stay closed and versioned; runtime context is not model-controllable."""

    def make(name):
        def dispatch(runtime: ToolRuntime[Turn], **arguments):
            return runtime.context.execute(name, arguments)

        return StructuredTool(
            name=name,
            description=f"Propose ASTRA {TOOL_ACTIONS[name]}; include evidence-backed edits.",
            args_schema=create_model(
                "RuntimeDecision",
                action=(
                    {
                        "SEARCH": Search,
                        "CLARIFY": Clarify,
                        "RECOMMEND": Recommend,
                        "RESPOND": Respond,
                    }[TOOL_ACTIONS[name]],
                    ...,
                ),
                __base__=MemoryDecision if memory_enabled else Decision,
                runtime=(Annotated[Any, InjectedToolArg], ...),
            ),
            func=dispatch,
        )

    return [make(name) for name in TOOL_ACTIONS]


class AstraMiddleware(AgentMiddleware):
    """No implicit retries. A rejected tool can be repaired within the same turn cap."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        turn = runtime.context
        if turn.response is not None:
            return {"jump_to": "end"}
        if turn.calls >= turn.max_calls:
            code = (
                turn.feedback[-1]["code"]
                if turn.feedback
                else "decision_budget_exhausted"
            )
            turn.stop(
                code,
                error=code
                not in {
                    "search_budget_exhausted",
                    "repeated_empty_search",
                    "search_requires_a_remaining_decision_call",
                    "redundant_clarification",
                    "budget_currency_not_supported",
                },
            )
            return {"jump_to": "end"}
        return None

    def wrap_model_call(self, request, handler):
        turn = request.runtime.context
        messages = turn.prepared_messages
        turn.prepared_messages = None
        if messages is None:
            turn.retrieve_lessons()  # Refresh cues after tool/state changes.
            messages = turn.context()
        turn.calls += 1
        started = time.monotonic()
        # Each call sees the authoritative bounded ASTRA projection, not an unbounded
        # second conversation history. Native tool results enter that projection.
        response = handler(
            request.override(
                system_message=SystemMessage(messages[0]["content"]),
                messages=[HumanMessage(m["content"]) for m in messages[1:]],
            )
        )
        reply = response.result[-1]
        usage = getattr(reply, "usage_metadata", None) or {}
        normalized_usage = {
            target: usage[source]
            for source, target in (
                ("input_tokens", "prompt_tokens"),
                ("output_tokens", "completion_tokens"),
                ("total_tokens", "total_tokens"),
            )
            if source in usage
        }
        turn.audit(
            "model_response",
            ordinal=turn.calls,
            content=reply.content,
            tool_calls=getattr(reply, "tool_calls", []),
            metadata={"usage": normalized_usage},
            duration_seconds=time.monotonic() - started,
        )
        if (
            not isinstance(reply, AIMessage)
            or len(reply.tool_calls) != 1
            or reply.invalid_tool_calls
        ):
            raise ValueError("exactly_one_tool_call_required")
        if reply.tool_calls[0]["name"] not in TOOL_ACTIONS:
            raise ValueError("unknown_tool")
        return response

    def wrap_tool_call(self, request, handler):
        turn = request.runtime.context
        turn.audit(
            "framework_tool_requested",
            tool=request.tool_call["name"],
            call_id=request.tool_call["id"],
        )
        if turn.search_factory is None:
            result = handler(request)
            return self._tool_result(turn, result)
        # ToolNode runs tools on worker threads even for one tool call. SQLite
        # connections are request-scoped instead of disabling thread safety.
        original = turn.search
        with closing(turn.search_factory()) as local_search:
            turn.search = local_search
            try:
                result = handler(request)
                return self._tool_result(turn, result)
            finally:
                turn.search = original

    @staticmethod
    def _tool_result(turn, result):
        if getattr(result, "status", None) == "error":
            turn.feedback = [{"code": "invalid_tool_arguments"}]
            turn.audit("decision_rejected", feedback=turn.feedback, ordinal=turn.calls)
        return result
