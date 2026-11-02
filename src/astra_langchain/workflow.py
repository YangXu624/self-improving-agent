"""Explicit LangGraph lifecycle around a LangChain v1 native-tool agent."""

import hashlib
from functools import partial
from typing import TypedDict
from uuid import uuid4

from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from shopping_agent.agent import ShoppingAgent
from shopping_agent.retrieval import LexicalSearch
from shopping_agent.sessions import SessionError

from .engine import Turn
from .memory import consolidate_procedural, consolidate_user
from .middleware import AstraMiddleware, tools


class WorkflowState(TypedDict, total=False):
    """Small diagnostic checkpoints; authoritative data remains in ASTRA stores."""

    phase: str
    end_session: bool
    response: dict


class LangChainShoppingAgent:
    """Compatible turn adapter plus an explicit application-owned session-end signal.

    SessionStore ownership/locking and request replay remain authoritative. Graph
    checkpoints aid inspection; interrupted side effects are NOT automatically replayed.
    Instances are synchronous and must not be used concurrently across sessions.
    """

    def __init__(
        self,
        store,
        search,
        model,
        *,
        user_memory=None,
        experience=None,
        checkpointer=None,
        max_calls=3,
        max_searches=2,
        learn=False,
    ):
        if not 1 <= max_calls <= 6 or not 1 <= max_searches <= 3:
            raise ValueError("Invalid execution bounds")
        if learn and (experience is None or not hasattr(experience, "add_candidate")):
            raise ValueError("Learning requires a writable isolated experience store")
        self.store, self.search = store, search
        self.search_factory = None
        if isinstance(search, LexicalSearch):
            path = search.db.execute("PRAGMA database_list").fetchone()[2]
            self.search_factory = partial(
                LexicalSearch, path, expected_catalogue_hash=search.catalogue_version
            )
        self.user_memory, self.experience = user_memory, experience
        self.max_calls, self.max_searches, self.learn = max_calls, max_searches, learn
        self.agent = create_agent(
            model,
            tools=tools(user_memory is not None),
            middleware=[AstraMiddleware()],
            context_schema=Turn,
        )
        graph = StateGraph(WorkflowState, context_schema=Turn)
        graph.add_node("receive", self._receive)
        graph.add_node("retrieve_user_memories", self._user)
        graph.add_node("retrieve_procedural_lessons", self._lessons)
        graph.add_node("construct_context", self._context)
        graph.add_node("shopping_agent", self._shopping)
        graph.add_node("consolidate_user", self._consolidate_user)
        graph.add_node("consolidate_procedural", self._consolidate_procedural)
        graph.add_node("persist", self._persist)
        sequence = [
            START,
            "receive",
            "retrieve_user_memories",
            "retrieve_procedural_lessons",
            "construct_context",
            "shopping_agent",
        ]
        for left, right in zip(sequence, sequence[1:]):
            graph.add_edge(left, right)
        graph.add_conditional_edges(
            "shopping_agent",
            self._route,
            {"end": "consolidate_user", "continue": "persist"},
        )
        graph.add_edge("consolidate_user", "consolidate_procedural")
        graph.add_edge("consolidate_procedural", "persist")
        graph.add_edge("persist", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _phase(runtime, name):
        runtime.context.audit("framework_phase", phase=name)
        return {"phase": name}

    def _receive(self, state, runtime):
        return self._phase(runtime, "receive")

    def _user(self, state, runtime):
        runtime.context.retrieve_user()
        return self._phase(runtime, "retrieve_user_memories")

    def _lessons(self, state, runtime):
        runtime.context.retrieve_lessons()
        return self._phase(runtime, "retrieve_procedural_lessons")

    def _context(self, state, runtime):
        runtime.context.prepared_messages = runtime.context.context()
        return self._phase(runtime, "construct_context")

    def _shopping(self, state, runtime):
        turn = runtime.context
        try:
            self.agent.invoke({"messages": []}, {"recursion_limit": 60}, context=turn)
        except Exception as exc:
            # Arbitrary SDK exception text may contain credentials/remote payloads.
            # Detailed successful requests and deterministic rejections are already audited.
            turn.audit("framework_failure", exception_type=type(exc).__name__)
            turn.stop("framework_model_or_tool_failure", error=True)
        if turn.response is None:
            turn.stop("missing_terminal_action", error=True)
        return {**self._phase(runtime, "shopping_agent"), "response": turn.response}

    @staticmethod
    def _route(state):
        return (
            "end"
            if state["end_session"] and state["response"]["status"] == "ok"
            else "continue"
        )

    def _consolidate_user(self, state, runtime):
        consolidate_user(runtime.context)
        return self._phase(runtime, "consolidate_user")

    def _consolidate_procedural(self, state, runtime):
        consolidate_procedural(runtime.context)
        return self._phase(runtime, "consolidate_procedural")

    def _persist(self, state, runtime):
        turn = runtime.context
        if turn.end_session and turn.response["status"] == "ok":
            turn.audit(
                "framework_session_ended", user_memory_rejections=turn.memory_rejections
            )
        if turn.user_memory is not None:
            turn.response["user_memory"] = {
                "enabled": True,
                "mode": "session_end",
                "rejected": turn.memory_rejections,
            }
        result = ShoppingAgent._complete(
            turn.session,
            turn.request_id,
            turn.response,
            turn.calls,
            turn.searches,
            experience={
                "retrieved": sorted(turn.retrieved),
                "injected": sorted(turn.injected),
                "applied": sorted(turn.applied),
            },
        )
        return {"phase": "persist", "response": result}

    def turn(self, user_id, session_id, message, *, request_id=None, end_session=False):
        if not isinstance(message, str) or not message.strip() or len(message) > 8000:
            raise ValueError("Message must contain 1–8000 characters")
        request_id = request_id or uuid4().hex
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("Invalid request ID")
        with self.store.open(user_id, session_id) as session:
            previous = [e for e in session.events if e.turn_id == request_id]
            if previous:
                original = next(
                    (e.payload for e in previous if e.type == "user_message"), {}
                )
                if (
                    original.get("message") != message
                    or original.get("end_session", False) != end_session
                ):
                    raise SessionError("request_id_message_mismatch")
                completed = next(
                    (e for e in previous if e.type == "turn_completed"), None
                )
                if completed:
                    return completed.payload["response"]
                raise SessionError(
                    "interrupted_turn; inspect history and use a new request ID"
                )
            if any(e.type == "framework_session_ended" for e in session.events):
                raise SessionError("session_ended; create a new session")
            session.append(
                "turn_started",
                {"max_calls": self.max_calls, "max_searches": self.max_searches},
                request_id,
            )
            event = session.append(
                "user_message",
                {"message": message, "end_session": end_session},
                request_id,
            )
            turn = Turn(
                session,
                self.search,
                message,
                request_id,
                event,
                max_calls=self.max_calls,
                max_searches=self.max_searches,
                user_memory=self.user_memory,
                experience=self.experience,
                end_session=end_session,
                learn=self.learn,
                search_factory=self.search_factory,
            )
            # Owner is part of the key; no caller-controlled thread ID or checkpoint resume API.
            thread = hashlib.sha256(
                f"{user_id}:{session_id}:{request_id}".encode()
            ).hexdigest()
            with tracing_context(enabled=False):
                result = self.graph.invoke(
                    {"end_session": end_session, "response": {}},
                    {"configurable": {"thread_id": thread}},
                    context=turn,
                )
            return result["response"]
