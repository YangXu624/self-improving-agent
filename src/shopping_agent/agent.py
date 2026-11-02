"""Bounded orchestration. Policies propose; trusted state/search guards execute."""

import hashlib
import json
import re
import time
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from .attributes import (
    attribute_ledger,
    redundant_clarification,
)
from .context import (
    PROMPT_VERSION,
    BuiltContext,
    ContextIntegrityError,
    ContextLimitError,
    bind_context,
    build_decision_context,
    latest_search,
)
from .contracts import Decision
from .experience.cues import catalogue_categories, decision_cues
from .memory_views import (
    FORMATS,
    compact_user_memory,
    expand_decision,
    redundant_retractions,
)
from .provider import PolicyReply, ProviderError
from .runtime_config import RuntimeConfig
from .sessions import SessionError, dumps
from .state import StateError, apply_updates
from .user_memory import MemoryDecision, UserMemoryError


class DecisionPolicy(Protocol):
    def complete(self, messages: list[dict]) -> PolicyReply: ...


class ActionError(ValueError):
    pass


# A SEARCH that cannot execute once no decision call remains to repair it. The turn is
# closed with a fixed message; the model cannot spend more budget or invent a result.
UNEXECUTABLE_SEARCH = {
    "search_budget_exhausted",
    "repeated_empty_search",
    "search_requires_a_remaining_decision_call",
}
CLOSURE_MESSAGE = (
    "I could not run another search within this turn's limit, so no products are "
    "recommended. Your requirements are saved; send a follow-up to continue."
)


def verified_products(action, result, state, search, receipt):
    """Shared application/experiment guard: visible current IDs and full-fact recheck."""
    if state.conflicts:
        raise ActionError("resolve_state_conflicts_before_search_or_recommendation")
    if (
        not result
        or (action.search_id is not None and action.search_id != result["search_id"])
        or result["state_version"] != state.version
        or result["catalogue_version"] != search.catalogue_version
    ):
        raise ActionError("recommendation_requires_inspected_current_search")
    if (
        receipt is None
        or receipt.search_id != result["search_id"]
        or receipt.state_version != state.version
        or receipt.catalogue_version != search.catalogue_version
        or receipt.strategy_version != search.strategy_version
    ):
        raise ActionError("recommendation_requires_visible_current_search")
    if any(ident not in receipt.product_ids for ident in action.product_ids):
        raise ActionError("recommendation_contains_unseen_product_id")
    candidates = {p["id"]: p for p in result["candidates"]}
    if any(ident not in candidates for ident in action.product_ids):
        raise ActionError("recommendation_contains_unseen_product_id")
    if any(not search.eligible(ident, state) for ident in action.product_ids):
        raise ActionError("recommendation_failed_constraint_recheck")
    return [candidates[ident] for ident in action.product_ids]


class ShoppingAgent:
    def __init__(
        self,
        store,
        search,
        policy: DecisionPolicy,
        *,
        context_builder=build_decision_context,
        max_calls=3,
        max_searches=2,
        experience=None,
        user_memory=None,
        memory_format="legacy",
        auto_finalize: bool = False,
        runtime_config: RuntimeConfig | None = None,
        purchase_store=None,
    ):
        self.runtime_config = runtime_config
        if runtime_config is not None:
            max_calls = runtime_config.agent_max_calls
            max_searches = runtime_config.agent_max_searches
            if memory_format == "legacy" and runtime_config.memory_format != "legacy":
                memory_format = runtime_config.memory_format
        if not 1 <= max_calls <= 6 or not 1 <= max_searches <= 3:
            raise ValueError("Invalid execution bounds")
        self.store, self.search, self.policy = store, search, policy
        self.context_builder = context_builder
        self.max_calls, self.max_searches = max_calls, max_searches
        self.experience = experience
        self.user_memory = user_memory
        self.purchase_store = purchase_store
        self.auto_finalize = auto_finalize
        if memory_format not in FORMATS:
            raise ValueError("Unknown memory format")
        self.memory_format = memory_format
        self.category_vocabulary = (
            catalogue_categories(search) if experience is not None else frozenset()
        )

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

            # Check maximum conversation turns
            user_msg_count = sum(1 for e in session.events if e.type == "user_message")
            max_turns = (
                self.runtime_config.max_conversation_turns
                if self.runtime_config
                else 20
            )
            if user_msg_count >= max_turns:
                closure = "conversation_turn_limit_reached"
                msg = f"Maximum conversation turns ({max_turns}) reached for this session."
                resp = {
                    "status": "closed",
                    "action": "RESPOND",
                    "message": msg,
                    "products": [],
                    "closure": closure,
                }
                return self._complete(session, request_id, resp, 0, 0, closure=closure)

            # Check session API spending ceiling
            total_prompt_tok = sum(
                e.payload.get("metadata", {}).get("usage", {}).get("prompt_tokens", 0)
                for e in session.events
                if e.type == "model_response"
            )
            total_compl_tok = sum(
                e.payload.get("metadata", {})
                .get("usage", {})
                .get("completion_tokens", 0)
                for e in session.events
                if e.type == "model_response"
            )
            est_cost = (total_prompt_tok * 1.4e-7) + (total_compl_tok * 2.8e-7)
            cost_cap = (
                self.runtime_config.session_api_cost_ceiling_usd
                if self.runtime_config
                else 50.0
            )
            if est_cost > cost_cap:
                closure = "session_api_cost_ceiling_exceeded"
                msg = f"Session API spending limit (${cost_cap:.2f}) reached (estimated spend: ${est_cost:.3f})."
                resp = {
                    "status": "closed",
                    "action": "RESPOND",
                    "message": msg,
                    "products": [],
                    "closure": closure,
                }
                return self._complete(session, request_id, resp, 0, 0, closure=closure)

            session.append(
                "turn_started",
                {
                    "max_calls": self.max_calls,
                    "max_searches": self.max_searches,
                    **(
                        {"runtime_config": self.runtime_config.to_dict()}
                        if self.runtime_config
                        else {}
                    ),
                },
                request_id,
            )
            user_event = session.append(
                "user_message", {"message": message}, request_id
            )
            if self.user_memory is not None and hasattr(
                self.user_memory, "check_and_apply_explicit_forgetting"
            ):
                withdrawn = self.user_memory.check_and_apply_explicit_forgetting(
                    user_id, message
                )
                if withdrawn:
                    session.append(
                        "user_memory_withdrawn",
                        {"withdrawn_ids": withdrawn},
                        request_id,
                    )
            calls, searches, feedback, edits_allowed = 0, 0, [], True
            retrieved_experience: list[str] = []
            injected_experience: list[str] = []
            applied_experience: list[str] = []
            memory_changes, memory_rejections = [], []
            retrieved_user_memories: list[dict] = []
            injected_user_memories: list[dict] = []

            def finish(resp):
                if self.user_memory is not None:
                    resp["user_memory"] = {
                        "enabled": True,
                        "updates": memory_changes,
                        "rejected": memory_rejections,
                        "retrieved": [
                            r.get("id") for r in retrieved_user_memories if r.get("id")
                        ],
                        "injected": [
                            r.get("id") for r in injected_user_memories if r.get("id")
                        ],
                        "injected_records": injected_user_memories,
                    }
                exp_payload = {
                    "retrieved": retrieved_experience,
                    "injected": injected_experience,
                    "applied": applied_experience,
                }
                if self.experience is not None or retrieved_experience:
                    session.append("experience_audit", exp_payload, request_id)
                return self._complete(
                    session, request_id, resp, calls, searches, experience=exp_payload
                )

            def accepted(decision, sent_lessons):
                from .experience.verifier import verify_decision_application

                matched = [
                    lesson.lesson_id
                    for lesson in sent_lessons
                    if verify_decision_application(decision, lesson)
                ]
                for ident in matched:
                    if ident not in applied_experience:
                        applied_experience.append(ident)
                if self.experience is not None:
                    session.append(
                        "experience_action_accepted",
                        {
                            "ordinal": calls,
                            "action": decision.action.type,
                            "applied": matched,
                        },
                        request_id,
                    )

            failure = "decision_budget_exhausted"
            while calls < self.max_calls:
                memory_view = None
                if self.user_memory is not None:
                    try:
                        min_sim = (
                            self.runtime_config.user_memory_similarity_threshold
                            if self.runtime_config
                            else 0.35
                        )
                        top_k = (
                            self.runtime_config.user_memory_top_k
                            if self.runtime_config
                            else 5
                        )
                        cand_limit = (
                            self.runtime_config.user_memory_candidate_pool_size
                            if self.runtime_config
                            else 15
                        )
                        small_prof = (
                            self.runtime_config.user_memory_small_profile_threshold
                            if self.runtime_config
                            else 10
                        )
                        memory_view = self.user_memory.context(
                            session,
                            message,
                            min_similarity=min_sim,
                            limit=top_k,
                            candidate_limit=cand_limit,
                            small_profile_threshold=small_prof,
                        )
                    except (UserMemoryError, OSError):
                        failure = "user_memory_unavailable"
                        session.append(
                            "user_memory_error", {"code": failure}, request_id
                        )
                        break
                    session.append(
                        "user_memory_retrieved",
                        {
                            "revision": memory_view["revision"],
                            "count": len(memory_view.get("candidates", [])),
                            "candidates": [
                                r["id"] for r in memory_view.get("candidates", [])
                            ],
                            "embedding_provider": memory_view.get("embedding_provider"),
                        },
                        request_id,
                    )
                    session.append(
                        "user_memory_applicable",
                        {
                            "revision": memory_view["revision"],
                            "applicable": [
                                r["id"] for r in memory_view.get("records", [])
                            ],
                            "ignored": [
                                r["id"] for r in memory_view.get("ignored", [])
                            ],
                            "assessments": memory_view.get("assessments", []),
                        },
                        request_id,
                    )
                    session.append(
                        "user_memory_selection",
                        {
                            "revision": memory_view["revision"],
                            "retrieved": [
                                r["id"] for r in memory_view.get("records", [])
                            ],
                            "candidates": [
                                r["id"] for r in memory_view.get("candidates", [])
                            ],
                        },
                        request_id,
                    )
                    retrieved_user_memories = [
                        dict(r)
                        for r in memory_view.get(
                            "candidates", memory_view.get("records", [])
                        )
                    ]
                result = latest_search(
                    session, self.search.catalogue_version, self.search.strategy_version
                )
                retrieved_lessons = []
                guidance = None
                if self.experience is not None:
                    cues, scope, provenance = decision_cues(
                        session,
                        message,
                        result,
                        searches,
                        calls,
                        self.category_vocabulary,
                    )
                    if not cues["has_search"]:
                        possible_triggers = [
                            "initial_query",
                            "search_strategy",
                            "attribute_clarification",
                        ]
                    elif not cues["has_candidates"]:
                        possible_triggers = [
                            "empty_search_recovery",
                            "unsuccessful_search",
                            "query_reformulation",
                            "search_strategy",
                        ]
                    else:
                        possible_triggers = [
                            "recommend_cutoff",
                            "candidate_selection",
                            "attribute_clarification",
                        ]
                    if hasattr(self.experience, "retrieve_semantic"):
                        sem_matches = self.experience.retrieve_semantic(
                            message, limit=1, scope=scope, context_cues=cues
                        )
                        if sem_matches:
                            retrieved_lessons = [
                                lesson for lesson, score in sem_matches
                            ]
                    if not retrieved_lessons:
                        for trig in possible_triggers:
                            matches = self.experience.retrieve(
                                trigger_type=trig,
                                scope=scope,
                                context_cues=cues,
                                max_lessons=1,
                            )
                            if matches:
                                retrieved_lessons = matches
                                break
                    if retrieved_lessons:
                        for lesson in retrieved_lessons:
                            if lesson.lesson_id not in retrieved_experience:
                                retrieved_experience.append(lesson.lesson_id)
                        guidance = [
                            {
                                "lesson_id": lesson.lesson_id,
                                "directive": lesson.directive[:400],
                            }
                            for lesson in retrieved_lessons
                        ]
                    session.append(
                        "experience_selection",
                        {
                            "ordinal": calls + 1,
                            "selected": [
                                lesson.lesson_id for lesson in retrieved_lessons
                            ],
                            "cues": cues,
                            **provenance,
                        },
                        request_id,
                    )
                try:
                    context_options = {"procedural_guidance": guidance}
                    if self.memory_format == "compact":
                        context_options["memory_format"] = "compact"
                    if memory_view is not None:
                        context_options["user_memory"] = memory_view
                    if self.purchase_store is not None:
                        try:
                            rel_purchases = self.purchase_store.find_relevant_purchases(
                                user_id, message, limit=3
                            )
                            if rel_purchases:
                                context_options["purchases"] = rel_purchases
                                if calls == 0:
                                    session.append(
                                        "purchase_evidence_used",
                                        {
                                            "count": len(rel_purchases),
                                            "purchases": [
                                                p.to_dict()
                                                if hasattr(p, "to_dict")
                                                else p
                                                for p in rel_purchases
                                            ],
                                        },
                                        request_id,
                                    )
                        except Exception as exc:
                            if calls == 0:
                                session.append(
                                    "purchase_retrieval_failed",
                                    {
                                        "user_id": user_id,
                                        "error": str(exc),
                                        "error_type": type(exc).__name__,
                                    },
                                    request_id,
                                )
                    remaining_calls = self.max_calls - calls
                    remaining_searches = max(
                        0, min(self.max_searches - searches, remaining_calls - 1)
                    )
                    budget = {
                        "model_calls": remaining_calls,
                        "searches": remaining_searches,
                    }
                    try:
                        built = self.context_builder(
                            session,
                            message,
                            result,
                            feedback,
                            budget,
                            edits_allowed,
                            **context_options,
                        )
                    except TypeError:
                        built = self.context_builder(
                            session,
                            message,
                            result,
                            feedback,
                            budget,
                            edits_allowed,
                        )
                    if not isinstance(built, BuiltContext):
                        built = bind_context(built, result, state=session.state)
                    else:
                        checked = bind_context(
                            built.messages,
                            result,
                            built.cards_profile,
                            state=session.state,
                        )
                        if checked.visible_search != built.visible_search:
                            raise ContextIntegrityError("context_receipt_mismatch")
                        built = checked
                    messages = built.messages
                except ContextIntegrityError:
                    failure = "invalid_context_visibility"
                    break
                except ContextLimitError:
                    failure = "essential_context_limit"
                    break
                calls += 1
                memory_injected = False
                request_prompt_version = PROMPT_VERSION
                sent_context = {}
                try:
                    sent_context = json.loads(messages[-1]["content"])
                    request_prompt_version = sent_context.get(
                        "prompt_version", PROMPT_VERSION
                    )
                except (ValueError, KeyError, TypeError, AttributeError):
                    sent_context = {}
                compact = sent_context.get("memory_format") == "compact"
                if memory_view is not None:
                    try:
                        expected_memory = (
                            compact_user_memory(memory_view) if compact else memory_view
                        )
                        memory_injected = (
                            sent_context.get("user_memory") == expected_memory
                        )
                        request_prompt_version = sent_context.get(
                            "prompt_version", PROMPT_VERSION
                        )
                    except (ValueError, KeyError, TypeError, AttributeError):
                        pass
                    session.append(
                        "user_memory_injection",
                        {
                            "ordinal": calls,
                            "revision": memory_view["revision"],
                            "injected": [r["id"] for r in memory_view["records"]]
                            if memory_injected
                            else [],
                        },
                        request_id,
                    )
                    if memory_injected:
                        injected_user_memories = [
                            dict(r) for r in memory_view.get("records", [])
                        ]
                session.append(
                    "model_request",
                    {
                        "ordinal": calls,
                        "prompt_version": request_prompt_version,
                        "context_sha256": hashlib.sha256(
                            dumps(messages).encode()
                        ).hexdigest(),
                        "messages": messages,
                        **(
                            {
                                "memory_format": "compact",
                                "user_memory_records": memory_view
                                if memory_injected
                                else None,
                            }
                            if compact
                            else {}
                        ),
                        "cards_profile": built.cards_profile,
                        "visible_search": built.visible_search.trace()
                        if built.visible_search
                        else None,
                    },
                    request_id,
                )
                # Inspect the exact serialized policy payload, after legacy builders/bounds.
                sent_lessons = []
                try:
                    entries = json.loads(messages[-1]["content"]).get(
                        "procedural_guidance", []
                    )
                    sent_lessons = [
                        lesson
                        for lesson in retrieved_lessons
                        if {
                            "lesson_id": lesson.lesson_id,
                            "directive": lesson.directive[:400],
                        }
                        in entries
                    ]
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
                for lesson in sent_lessons:
                    if lesson.lesson_id not in injected_experience:
                        injected_experience.append(lesson.lesson_id)
                start = time.monotonic()
                decision_state = session.state.model_copy(deep=True)
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
                    contract = (
                        MemoryDecision
                        if (self.user_memory is not None and not compact)
                        else Decision
                    )
                    ignored_retractions = []
                    if compact:
                        try:
                            goal_start = min(
                                (
                                    e.state_version
                                    for e in session.events
                                    if e.type == "state_committed"
                                    and e.payload["state"].get("goal_epoch", 0)
                                    == session.state.goal_epoch
                                ),
                                default=0,
                            )
                            cleaned, ignored_retractions = redundant_retractions(
                                reply.content,
                                decision_state,
                                message,
                                goal_start_version=goal_start,
                            )
                            decision = expand_decision(
                                cleaned, decision_state, memory_view
                            )
                        except ValidationError:
                            raise
                        except ValueError as exc:
                            raise ActionError(str(exc)) from None
                    else:
                        decision = contract.model_validate_json(reply.content)
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
                    for ignored in ignored_retractions:
                        session.append(
                            "redundant_retraction_ignored", ignored, request_id
                        )
                    if state.version != session.state.version:
                        session.commit(
                            state,
                            [u.model_dump() for u in decision.updates],
                            request_id,
                        )
                    proposals = getattr(decision, "user_memory_updates", [])
                    if proposals:
                        try:
                            if not edits_allowed:
                                raise UserMemoryError(
                                    "user_memory_updates_already_processed_this_turn"
                                )
                            if not memory_injected:
                                raise UserMemoryError(
                                    "user_memory_context_not_injected"
                                )
                            memory_result = self.user_memory.apply(
                                session,
                                user_event,
                                proposals,
                                expected_revision=memory_view["revision"],
                                visible_ids={r["id"] for r in memory_view["records"]},
                            )
                            session.append(
                                "user_memory_updated", memory_result, request_id
                            )
                            memory_changes.append(memory_result)
                        except (UserMemoryError, OSError) as exc:
                            code = (
                                str(exc)
                                if isinstance(exc, UserMemoryError)
                                else "user_memory_write_failed"
                            )
                            session.append(
                                "user_memory_update_rejected",
                                {"code": code},
                                request_id,
                            )
                            memory_rejections.append(code)
                    edits_allowed = False
                    action = decision.action
                    currency = attribute_ledger(session)["disclosed_attributes"].get(
                        "currency", {}
                    )
                    if (
                        action.type in {"SEARCH", "RECOMMEND"}
                        and currency.get("status") == "answered"
                        and currency.get("value") not in {None, "USD"}
                        and any(
                            r.status == "active"
                            and r.field == "price"
                            and r.strength == "hard"
                            for r in state.requirements
                        )
                    ):
                        raise ActionError("budget_currency_not_supported")
                    if (
                        action.type in {"SEARCH", "RECOMMEND"}
                        and session.state.conflicts
                    ):
                        raise ActionError(
                            "resolve_state_conflicts_before_search_or_recommendation"
                        )
                    if action.type == "SEARCH":
                        fingerprint = hashlib.sha256(
                            dumps(
                                {
                                    "catalogue": self.search.catalogue_version,
                                    "strategy": self.search.strategy_version,
                                    "query": sorted(
                                        set(re.findall(r"\w+", action.query.casefold()))
                                    ),
                                    "mode": action.mode,
                                    "goal_epoch": session.state.goal_epoch,
                                    "requirements": sorted(
                                        [
                                            {
                                                "field": r.field,
                                                "op": r.op,
                                                "value": r.value,
                                                "strength": r.strength,
                                            }
                                            for r in session.state.requirements
                                            if r.status == "active"
                                        ],
                                        key=lambda r: dumps(r),
                                    ),
                                }
                            ).encode()
                        ).hexdigest()
                        if any(
                            e.type == "search_result"
                            and e.payload.get("request_fingerprint") == fingerprint
                            and not e.payload.get("candidates")
                            for e in session.events
                        ):
                            raise ActionError("repeated_empty_search")
                        if searches >= self.max_searches:
                            raise ActionError("search_budget_exhausted")
                        if calls >= self.max_calls:
                            raise ActionError(
                                "search_requires_a_remaining_decision_call"
                            )
                        if self.runtime_config:
                            candidate_cap = max(
                                30, self.runtime_config.candidate_retrieval_limit
                            )
                            action.limit = min(max(action.limit, 30), candidate_cap)
                        else:
                            action.limit = max(action.limit, 30)
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
                        fallback_opt = (
                            self.runtime_config.search_fallback
                            if self.runtime_config
                            else True
                        )
                        p_strength = (
                            self.runtime_config.personalization_strength
                            if self.runtime_config
                            else 0.5
                        )
                        p_max_bonus = (
                            self.runtime_config.personalization_max_bonus
                            if self.runtime_config
                            else 2.0
                        )
                        try:
                            found = self.search.search(
                                action,
                                session.state,
                                user_memory=memory_view,
                                fallback=fallback_opt,
                                personalization_strength=p_strength,
                                personalization_max_bonus=p_max_bonus,
                            )
                        except TypeError:
                            try:
                                found = self.search.search(
                                    action,
                                    session.state,
                                    user_memory=memory_view,
                                    fallback=fallback_opt,
                                )
                            except TypeError:
                                try:
                                    found = self.search.search(
                                        action, session.state, user_memory=memory_view
                                    )
                                except TypeError:
                                    found = self.search.search(action, session.state)
                        except ValueError:
                            raise ActionError("invalid_search_query_or_state") from None
                        found["request_fingerprint"] = fingerprint
                        session.append("search_result", found, request_id)
                        if found.get("memory_decision_audit") or found.get(
                            "baseline_rankings"
                        ):
                            session.append(
                                "product_reranking_audit",
                                {
                                    "search_id": found.get("search_id"),
                                    "initial_candidate_pool": found.get(
                                        "initial_candidate_pool", []
                                    ),
                                    "baseline_rankings": found.get(
                                        "baseline_rankings", []
                                    ),
                                    "personalized_rankings": found.get(
                                        "personalized_rankings", []
                                    ),
                                    "personalization_strength": found.get(
                                        "personalization_strength", 0.0
                                    ),
                                    "audit": found.get("memory_decision_audit", []),
                                },
                                request_id,
                            )
                        session.append(
                            "tool_completed",
                            {
                                "search_id": found["search_id"],
                                "duration_seconds": time.monotonic() - started,
                            },
                            request_id,
                        )
                        accepted(decision, sent_lessons)
                        if not found.get("candidates"):
                            feedback = [
                                {
                                    "code": "empty_search_zero_eligible",
                                    "message": (
                                        "The previous search returned zero eligible products. "
                                        "Do not repeat the exact same search query. "
                                        "Try broader keywords, adjust or remove restrictive constraints, "
                                        "or ask a clarifying question."
                                    ),
                                }
                            ]
                        else:
                            feedback = []
                        continue
                    if action.type == "RECOMMEND":
                        # Must be a result actually provided to THIS decision, still current
                        # after any state edit, and from this session/catalogue only.
                        if not action.product_ids:
                            raise ActionError(
                                "recommendation_requires_at_least_one_product"
                            )
                        q = getattr(action, "follow_up_question", None)
                        if not q or not str(q).strip():
                            raise ActionError(
                                "recommendation_requires_follow_up_question"
                            )

                        # Recommendations must be distinct eligible products (up to 10)
                        # Never fabricate or pad recommendations beyond what was selected
                        action.product_ids = list(dict.fromkeys(action.product_ids))[
                            :10
                        ]

                        products = verified_products(
                            action,
                            result,
                            session.state,
                            self.search,
                            built.visible_search,
                        )
                        msg = (
                            getattr(action, "message", None)
                            or "Here are verified recommendations based on your preferences."
                        )
                        response = {
                            "status": "ok",
                            "action": "RECOMMEND",
                            "message": msg,
                            "products": products,
                            "follow_up_question": str(q).strip(),
                            "search_id": result["search_id"],
                        }
                        session.append(
                            "recommendation",
                            {
                                "search_id": result["search_id"],
                                "product_ids": action.product_ids,
                                "follow_up_question": str(q).strip(),
                                "state_version": session.state.version,
                                "goal_epoch": session.state.goal_epoch,
                                "requirements": [
                                    r.model_dump(
                                        include={
                                            "id",
                                            "field",
                                            "op",
                                            "value",
                                            "strength",
                                            "source_event_id",
                                        }
                                    )
                                    for r in session.state.requirements
                                    if r.status == "active" and r.strength == "hard"
                                ],
                            },
                            request_id,
                        )
                    elif action.type == "NO_MATCH":
                        response = {
                            "status": "no_match",
                            "action": "NO_MATCH",
                            "message": getattr(
                                action,
                                "message",
                                "I could not find verified products matching all your requirements in the catalogue.",
                            ),
                            "follow_up_question": getattr(
                                action,
                                "follow_up_question",
                                "Which requirement would you like to relax (e.g. price, color, or style)?",
                            ),
                            "products": [],
                            "closure": "no_match",
                        }
                    elif action.type == "CLARIFY":
                        if redundant_clarification(session, action.attribute):
                            raise ActionError("redundant_clarification")
                        response = {
                            "status": "ok",
                            "action": "CLARIFY",
                            "message": action.question,
                            "attribute": action.attribute,
                            "products": [],
                            "follow_up_question": action.question,
                        }
                    else:
                        response = {
                            "status": "ok",
                            "action": "RESPOND",
                            "message": action.message,
                            "products": [],
                        }
                    accepted(decision, sent_lessons)
                    return finish(response)
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
            closure = (
                feedback[0]["code"]
                if failure == "decision_budget_exhausted"
                and len(feedback) == 1
                and feedback[0].get("code") in UNEXECUTABLE_SEARCH
                else None
            )
            if closure:
                session.append("turn_closed_safely", {"code": closure}, request_id)
                return finish(
                    {
                        "status": "ok",
                        "action": "RESPOND",
                        "message": (
                            "This search already returned no verified matches. Please change the query or requirements before trying again; no products are recommended."
                            if closure == "repeated_empty_search"
                            else CLOSURE_MESSAGE
                        ),
                        "products": [],
                        "closure": closure,
                    }
                )
            if feedback and feedback[-1].get("code") in {
                "redundant_clarification",
                "budget_currency_not_supported",
            }:
                return finish(
                    {
                        "status": "ok",
                        "action": "RESPOND",
                        "message": (
                            "Catalogue prices are historical USD. Please provide a USD budget; currency conversion is not available."
                            if feedback[-1]["code"] == "budget_currency_not_supported"
                            else "I already have that information. Please tell me if you would like to change it or add another requirement."
                        ),
                        "products": [],
                        "closure": feedback[-1]["code"],
                    }
                )
            session.append(
                "turn_failed", {"code": failure, "last_feedback": feedback}, request_id
            )
            return finish(
                {
                    "status": "error",
                    "action": "RESPOND",
                    "message": "This turn could not complete safely. Inspect the trace or try again; accepted state changes are retained.",
                    "products": [],
                    "error": failure,
                }
            )

    @staticmethod
    def _complete(session, request_id, response, calls, searches, experience=None):
        response = {
            **response,
            "session_id": session.id,
            "request_id": request_id,
            "state_version": session.state.version,
            "budget_used": {"model_calls": calls, "searches": searches},
            "experience": experience
            or {
                "retrieved": [],
                "injected": [],
                "applied": [],
            },
        }
        session.append("assistant_response", response, request_id)
        session.append("turn_completed", {"response": response}, request_id)
        return response

    def finalize_session(
        self,
        user_id: str,
        session_id: str,
        *,
        outcome: dict | None = None,
    ) -> dict:
        """Run end-of-session consolidation for user memory and experience distillation exactly once."""
        results = {"user_memory": None, "experience": None}
        with self.store.open(user_id, session_id) as session:
            if self.user_memory is not None:
                from .consolidation import consolidate_session

                try:
                    res = consolidate_session(
                        session,
                        user_id,
                        self.user_memory,
                        self.policy,
                        purchase_store=self.purchase_store,
                    )
                    results["user_memory"] = {
                        "idempotent": res.idempotent,
                        "revision": res.revision,
                        "applied": res.operations_applied,
                        "rejected": res.rejected_operations,
                        "reason": res.reason,
                    }
                except Exception as exc:
                    results["user_memory"] = {"error": str(exc)}

            if self.experience is not None:
                from .experience.distiller import distill_session_experience
                from .experience.store import ExperienceStore

                if isinstance(self.experience, ExperienceStore):
                    try:
                        exp_res = distill_session_experience(
                            session, self.experience, self.policy, outcome=outcome
                        )
                        results["experience"] = {
                            "has_lesson": exp_res.has_lesson,
                            "status": exp_res.status,
                            "lesson_id": exp_res.lesson.lesson_id
                            if exp_res.lesson
                            else None,
                            "reason": exp_res.reason,
                        }
                    except Exception as exc:
                        results["experience"] = {"error": str(exc)}
        return results
