"""Native tool execution with ASTRA's existing deterministic guards.

The framework owns iteration. This module owns trust boundaries and side effects.
No LLM may choose filesystem paths, owners, limits, or session-end authorization.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from shopping_agent.agent import ActionError, verified_products
from shopping_agent.attributes import attribute_ledger, redundant_clarification
from shopping_agent.context import build_decision_context, latest_search
from shopping_agent.contracts import Decision
from shopping_agent.experience.cues import catalogue_categories, decision_cues
from shopping_agent.experience.verifier import verify_decision_application
from shopping_agent.sessions import dumps
from shopping_agent.state import StateError, apply_updates
from shopping_agent.user_memory import (
    MemoryDecision,
    UserMemoryError,
    validate_proposal,
)

TOOL_ACTIONS = {
    "search_products": "SEARCH",
    "recommend_products": "RECOMMEND",
    "clarify": "CLARIFY",
    "respond": "RESPOND",
}


@dataclass
class Turn:
    """Ephemeral trusted context, never serialized into a graph checkpoint."""

    session: Any
    search: Any
    message: str
    request_id: str
    user_event: Any
    max_calls: int = 3
    max_searches: int = 2
    user_memory: Any = None
    experience: Any = None
    end_session: bool = False
    learn: bool = False
    calls: int = 0
    searches: int = 0
    edits_allowed: bool = True
    feedback: list = field(default_factory=list)
    memory_view: dict | None = None
    lessons: list = field(default_factory=list)
    retrieved: set = field(default_factory=set)
    injected: set = field(default_factory=set)
    applied: set = field(default_factory=set)
    prepared_messages: list | None = None
    built: Any = None
    result: dict | None = None
    response: dict | None = None
    memory_rejections: list = field(default_factory=list)
    search_factory: Any = None
    vocabulary: Any = field(default_factory=frozenset)

    def audit(self, kind: str, **payload) -> None:
        self.session.append(kind, payload, self.request_id)

    def retrieve_user(self) -> None:
        if self.user_memory is not None:
            self.memory_view = self.user_memory.context(self.session, self.message)
            self.audit(
                "user_memory_selection",
                revision=self.memory_view["revision"],
                retrieved=[r["id"] for r in self.memory_view["records"]],
            )

    def retrieve_lessons(self) -> None:
        self.result = latest_search(
            self.session, self.search.catalogue_version, self.search.strategy_version
        )
        self.lessons = []
        if self.experience is None:
            return
        self.vocabulary = self.vocabulary or catalogue_categories(self.search)
        cues, scope, _ = decision_cues(
            self.session,
            self.message,
            self.result,
            self.searches,
            self.calls,
            self.vocabulary,
        )
        triggers = ("initial_query", "search_strategy", "attribute_clarification")
        if cues["has_search"]:
            triggers = (
                ("recommend_cutoff", "candidate_selection", "attribute_clarification")
                if cues["has_candidates"]
                else (
                    "empty_search_recovery",
                    "unsuccessful_search",
                    "query_reformulation",
                    "search_strategy",
                )
            )
        for trigger in triggers:
            self.lessons = self.experience.retrieve(
                trigger_type=trigger, scope=scope, context_cues=cues, max_lessons=1
            )
            if self.lessons:
                break
        self.retrieved.update(x.lesson_id for x in self.lessons)
        self.audit("experience_selection", selected=[x.lesson_id for x in self.lessons])

    def context(self) -> list[dict]:
        self.result = latest_search(
            self.session, self.search.catalogue_version, self.search.strategy_version
        )
        options = {
            "procedural_guidance": [
                {"lesson_id": x.lesson_id, "directive": x.directive[:400]}
                for x in self.lessons
            ]
        }
        if self.memory_view is not None:
            options["user_memory"] = self.memory_view
        self.built = build_decision_context(
            self.session,
            self.message,
            self.result,
            self.feedback,
            {
                "model_calls": self.max_calls - self.calls,
                "searches": self.max_searches - self.searches,
            },
            self.edits_allowed,
            **options,
        )
        messages = [dict(m) for m in self.built.messages]
        # The tool schemas carry the contract; avoid sending the legacy JSON schema twice.
        messages[0]["content"] = (
            messages[0]["content"]
            .split("\nDecision JSON schema:\n", 1)[0]
            .replace(
                "Output exactly one JSON object\nmatching the supplied Decision schema.",
                "Use the named tools with their supplied schemas.",
            )
        )
        messages[0]["content"] += (
            "\nTRANSPORT OVERRIDE: Call exactly ONE named tool per response, passing the "
            "Decision fields as tool arguments. Match the action.type to the tool name. "
            "Never return a bare JSON answer or parallel tool calls. Tool rejection is "
            "feedback; repair within the remaining call budget. User memory proposals "
            "are staged and persisted only on explicit application session end."
        )
        self.injected.update(x.lesson_id for x in self.lessons)
        if self.memory_view is not None:
            self.audit(
                "user_memory_injection",
                revision=self.memory_view["revision"],
                injected=[r["id"] for r in self.memory_view["records"]],
            )
        self.audit(
            "model_request",
            ordinal=self.calls + 1,
            messages=messages,
            prompt_version="langchain-native-tools-v1",
            visible_search=self.built.visible_search.trace()
            if self.built.visible_search
            else None,
        )
        return messages

    def execute(self, name: str, arguments: dict) -> str:
        """Accept at most one state transaction per turn; validate before every action."""
        try:
            contract = MemoryDecision if self.user_memory is not None else Decision
            decision = contract.model_validate(arguments)
            if decision.action.type != TOOL_ACTIONS[name]:
                raise ActionError("tool_action_mismatch")
            if not self.edits_allowed and decision.updates:
                raise ActionError("state_updates_already_accepted_this_turn")
            state = apply_updates(
                self.session.state,
                decision.updates,
                expected_version=decision.based_on_state_version,
                user_message=self.message,
                source_event_id=self.user_event.event_id,
            )
            self.audit("decision_validated", **decision.model_dump())
            if state.version != self.session.state.version:
                self.session.commit(
                    state, [u.model_dump() for u in decision.updates], self.request_id
                )
            self.stage_memories(getattr(decision, "user_memory_updates", []))
            self.edits_allowed = False
            action = decision.action
            currency = attribute_ledger(self.session)["disclosed_attributes"].get(
                "currency", {}
            )
            if action.type in {"SEARCH", "RECOMMEND"}:
                if (
                    currency.get("status") == "answered"
                    and currency.get("value") not in {None, "USD"}
                    and any(
                        r.status == "active"
                        and r.field == "price"
                        and r.strength == "hard"
                        for r in state.requirements
                    )
                ):
                    raise ActionError("budget_currency_not_supported")
                if state.conflicts:
                    raise ActionError(
                        "resolve_state_conflicts_before_search_or_recommendation"
                    )
            if action.type == "SEARCH":
                output = self.run_search(action)
            elif action.type == "RECOMMEND":
                products = verified_products(
                    action, self.result, state, self.search, self.built.visible_search
                )
                self.audit(
                    "recommendation",
                    search_id=action.search_id,
                    product_ids=action.product_ids,
                    state_version=state.version,
                    goal_epoch=state.goal_epoch,
                    requirements=[
                        r.model_dump()
                        for r in state.requirements
                        if r.status == "active" and r.strength == "hard"
                    ],
                )
                output = self.finish(
                    "RECOMMEND",
                    "Catalogue matches (historical facts; variant availability unverified).",
                    products=products,
                    search_id=action.search_id,
                )
            elif action.type == "CLARIFY":
                if redundant_clarification(self.session, action.attribute):
                    raise ActionError("redundant_clarification")
                output = self.finish(
                    "CLARIFY", action.question, attribute=action.attribute
                )
            else:
                output = self.finish("RESPOND", action.message)
            self.applied.update(
                x.lesson_id
                for x in self.lessons
                if verify_decision_application(decision, x)
            )
            self.feedback = []
            return dumps(output)
        except (ValidationError, StateError, ActionError) as exc:
            code = (
                "invalid_decision_schema"
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            self.feedback = [{"code": code}]
            self.audit("decision_rejected", feedback=self.feedback, ordinal=self.calls)
            return dumps({"error": code})

    def stage_memories(self, proposals: list) -> None:
        if not proposals:
            return
        try:
            if not self.edits_allowed:
                raise UserMemoryError("user_memory_updates_already_processed_this_turn")
            if self.memory_view is None:
                raise UserMemoryError("user_memory_context_not_injected")
            visible = [r["id"] for r in self.memory_view["records"]]
            for proposal in proposals:
                validate_proposal(proposal, self.message)
                if proposal.target_id and proposal.target_id not in visible:
                    raise UserMemoryError("memory_correction_requires_visible_target")
            self.audit(
                "framework_memory_staged",
                source_event_id=self.user_event.event_id,
                proposals=[p.model_dump() for p in proposals],
                visible_ids=visible,
                revision=self.memory_view["revision"],
            )
        except UserMemoryError as exc:
            self.memory_rejections.append(str(exc))
            self.audit("user_memory_update_rejected", code=str(exc))

    def run_search(self, action) -> dict:
        fingerprint = hashlib.sha256(
            dumps(
                {
                    "catalogue": self.search.catalogue_version,
                    "strategy": self.search.strategy_version,
                    "query": sorted(set(re.findall(r"\w+", action.query.casefold()))),
                    "mode": action.mode,
                    "goal_epoch": self.session.state.goal_epoch,
                    "requirements": sorted(
                        [
                            r.model_dump(include={"field", "op", "value", "strength"})
                            for r in self.session.state.requirements
                            if r.status == "active"
                        ],
                        key=dumps,
                    ),
                }
            ).encode()
        ).hexdigest()
        if any(
            e.type == "search_result"
            and e.payload.get("request_fingerprint") == fingerprint
            and not e.payload.get("candidates")
            for e in self.session.events
        ):
            raise ActionError("repeated_empty_search")
        if self.searches >= self.max_searches:
            raise ActionError("search_budget_exhausted")
        if self.calls >= self.max_calls:
            raise ActionError("search_requires_a_remaining_decision_call")
        self.searches += 1
        self.audit(
            "tool_call",
            tool="product_search",
            ordinal=self.searches,
            action=action.model_dump(),
            state_version=self.session.state.version,
        )
        try:
            result = self.search.search(action, self.session.state)
        except ValueError:
            raise ActionError("invalid_search_query_or_state") from None
        result["request_fingerprint"] = fingerprint
        self.session.append("search_result", result, self.request_id)
        return {"search_id": result["search_id"], "counts": result["counts"]}

    def finish(self, action: str, message: str, **extra) -> dict:
        self.response = {
            "status": "ok",
            "action": action,
            "message": message,
            "products": [],
            **extra,
        }
        return self.response

    def stop(self, code: str, *, error: bool = False) -> None:
        self.finish(
            "RESPOND",
            "This turn ended safely; no products are recommended.",
            **({"error": code, "status": "error"} if error else {"closure": code}),
        )
        self.audit("turn_failed" if error else "turn_closed_safely", code=code)
