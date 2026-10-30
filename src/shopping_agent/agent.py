"""Bounded orchestration. Policies propose; trusted state/search guards execute."""

import hashlib
import time
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from .context import PROMPT_VERSION, ContextLimitError, build_context, latest_search
from .contracts import Decision
from .provider import PolicyReply, ProviderError
from .sessions import SessionError, dumps
from .state import StateError, apply_updates


class DecisionPolicy(Protocol):
    def complete(self, messages: list[dict]) -> PolicyReply: ...


class ActionError(ValueError):
    pass


class ShoppingAgent:
    def __init__(
        self,
        store,
        search,
        policy: DecisionPolicy,
        *,
        context_builder=build_context,
        max_calls=3,
        max_searches=2,
    ):
        if not 1 <= max_calls <= 6 or not 1 <= max_searches <= 3:
            raise ValueError("Invalid execution bounds")
        self.store, self.search, self.policy = store, search, policy
        self.context_builder = context_builder
        self.max_calls, self.max_searches = max_calls, max_searches

    def turn(self, user_id, session_id, message, *, request_id=None):
        if not isinstance(message, str) or not message.strip() or len(message) > 8000:
            raise ValueError("Message must contain 1–8000 characters")
        request_id = request_id or uuid4().hex
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("Invalid request ID")
        with self.store.open(user_id, session_id) as session:
            previous = [e for e in session.events if e.turn_id == request_id]
            if previous:
                original = next(
                    (
                        e.payload["message"]
                        for e in previous
                        if e.type == "user_message"
                    ),
                    None,
                )
                if original != message:
                    raise SessionError("request_id_message_mismatch")
                completed = next(
                    (e for e in previous if e.type == "turn_completed"), None
                )
                if completed:
                    return completed.payload["response"]
                raise SessionError(
                    "interrupted_turn; inspect history and use a new request ID"
                )
            session.append(
                "turn_started",
                {"max_calls": self.max_calls, "max_searches": self.max_searches},
                request_id,
            )
            user_event = session.append(
                "user_message", {"message": message}, request_id
            )
            calls, searches, feedback, edits_allowed = 0, 0, [], True
            failure = "decision_budget_exhausted"
            while calls < self.max_calls:
                result = latest_search(
                    session, self.search.catalogue_version, self.search.strategy_version
                )
                try:
                    messages = self.context_builder(
                        session,
                        message,
                        result,
                        feedback,
                        {
                            "model_calls": self.max_calls - calls,
                            "searches": self.max_searches - searches,
                        },
                        edits_allowed,
                    )
                except ContextLimitError:
                    failure = "essential_context_limit"
                    break
                calls += 1
                session.append(
                    "model_request",
                    {
                        "ordinal": calls,
                        "prompt_version": PROMPT_VERSION,
                        "context_sha256": hashlib.sha256(
                            dumps(messages).encode()
                        ).hexdigest(),
                        "messages": messages,
                    },
                    request_id,
                )
                start = time.monotonic()
                try:
                    reply = self.policy.complete(messages)
                except ProviderError as exc:
                    # Only provider-defined safe codes; never persist transport exceptions.
                    failure = str(exc)
                    session.append(
                        "model_error", {"code": failure, "ordinal": calls}, request_id
                    )
                    break
                session.append(
                    "model_response",
                    {
                        "ordinal": calls,
                        "content": reply.content,
                        "metadata": reply.metadata,
                        "duration_seconds": time.monotonic() - start,
                    },
                    request_id,
                )
                try:
                    decision = Decision.model_validate_json(reply.content)
                    if not edits_allowed and decision.updates:
                        raise ActionError("state_updates_already_accepted_this_turn")
                    state = apply_updates(
                        session.state,
                        decision.updates,
                        expected_version=decision.based_on_state_version,
                        user_message=message,
                        source_event_id=user_event.event_id,
                    )
                    session.append(
                        "decision_validated", decision.model_dump(), request_id
                    )
                    if state.version != session.state.version:
                        session.commit(
                            state,
                            [u.model_dump() for u in decision.updates],
                            request_id,
                        )
                    edits_allowed = False
                    action = decision.action
                    if (
                        action.type in {"SEARCH", "RECOMMEND"}
                        and session.state.conflicts
                    ):
                        raise ActionError(
                            "resolve_state_conflicts_before_search_or_recommendation"
                        )
                    if action.type == "SEARCH":
                        if searches >= self.max_searches:
                            raise ActionError("search_budget_exhausted")
                        if calls >= self.max_calls:
                            raise ActionError(
                                "search_requires_a_remaining_decision_call"
                            )
                        searches += 1
                        session.append(
                            "tool_call",
                            {
                                "tool": "product_search",
                                "ordinal": searches,
                                "action": action.model_dump(),
                                "state_version": session.state.version,
                            },
                            request_id,
                        )
                        started = time.monotonic()
                        try:
                            found = self.search.search(action, session.state)
                        except ValueError:
                            raise ActionError("invalid_search_query_or_state") from None
                        session.append("search_result", found, request_id)
                        session.append(
                            "tool_completed",
                            {
                                "search_id": found["search_id"],
                                "duration_seconds": time.monotonic() - started,
                            },
                            request_id,
                        )
                        feedback = []
                        continue
                    if action.type == "RECOMMEND":
                        # Must be a result actually provided to THIS decision, still current
                        # after any state edit, and from this session/catalogue only.
                        if (
                            not result
                            or action.search_id != result["search_id"]
                            or result["state_version"] != session.state.version
                            or result["catalogue_version"]
                            != self.search.catalogue_version
                        ):
                            raise ActionError(
                                "recommendation_requires_inspected_current_search"
                            )
                        candidates = {p["id"]: p for p in result["candidates"]}
                        if any(pid not in candidates for pid in action.product_ids):
                            raise ActionError(
                                "recommendation_contains_unseen_product_id"
                            )
                        if any(
                            not self.search.eligible(pid, session.state)
                            for pid in action.product_ids
                        ):
                            raise ActionError(
                                "recommendation_failed_constraint_recheck"
                            )
                        products = [candidates[pid] for pid in action.product_ids]
                        response = {
                            "status": "ok",
                            "action": "RECOMMEND",
                            "message": "Catalogue matches (historical facts; variant availability unverified).",
                            "products": products,
                            "search_id": result["search_id"],
                        }
                        session.append(
                            "recommendation",
                            {
                                "search_id": result["search_id"],
                                "product_ids": action.product_ids,
                                "state_version": session.state.version,
                            },
                            request_id,
                        )
                    elif action.type == "CLARIFY":
                        response = {
                            "status": "ok",
                            "action": "CLARIFY",
                            "message": action.question,
                            "attribute": action.attribute,
                            "products": [],
                        }
                    else:
                        response = {
                            "status": "ok",
                            "action": "RESPOND",
                            "message": action.message,
                            "products": [],
                        }
                    return self._complete(
                        session, request_id, response, calls, searches
                    )
                except (ValidationError, StateError, ActionError) as exc:
                    if isinstance(exc, ValidationError):
                        feedback = [
                            {
                                "code": "invalid_decision_schema",
                                "errors": exc.errors(
                                    include_input=False,
                                    include_context=False,
                                    include_url=False,
                                ),
                            }
                        ]
                    else:
                        feedback = [{"code": str(exc)}]
                    session.append(
                        "decision_rejected",
                        {
                            "feedback": feedback,
                            "ordinal": calls,
                            "state_version": session.state.version,
                        },
                        request_id,
                    )
            session.append(
                "turn_failed", {"code": failure, "last_feedback": feedback}, request_id
            )
            return self._complete(
                session,
                request_id,
                {
                    "status": "error",
                    "action": "RESPOND",
                    "message": "This turn could not complete safely. Inspect the trace or try again; accepted state changes are retained.",
                    "products": [],
                    "error": failure,
                },
                calls,
                searches,
            )

    @staticmethod
    def _complete(session, request_id, response, calls, searches):
        response = {
            **response,
            "session_id": session.id,
            "request_id": request_id,
            "state_version": session.state.version,
            "budget_used": {"model_calls": calls, "searches": searches},
        }
        session.append("assistant_response", response, request_id)
        session.append("turn_completed", {"response": response}, request_id)
        return response
