"""End-of-session experience distillation.

Analyzes completed shopping sessions to extract reusable, privacy-preserving
procedural lessons without leaking individual customer identities or specific preferences.
"""

import json
import re
from dataclasses import dataclass

from ..sessions import Session
from .models import Lesson, digest_lesson_content
from .store import ExperienceStore

EXPERIENCE_DISTILLATION_PROMPT = """You are ASTRA's experiential learning and strategy policy.
Your goal is to distill a generalizable, reusable shopping strategy from a completed shopping interaction.

CRITICAL PRIVACY RULE:
Do NOT include any customer names, customer IDs, personal details, or private preferences from this session.
Distill a GENERAL strategy about shopping decision-making (e.g. clarification, query formulation, search narrowing, or candidate cutoff).

Input contains:
- Session trajectory: opening query, searches executed, clarification questions asked, candidate counts, recommendations.
- Outcome: success/failure, target found or missed, constraint violations.

Decide if there is a generalizable strategy worth recording:
- If the interaction was routine, inconclusive, or purely situational, output NOOP.
- If a clear strategy helped (or a mistake should be avoided):
  - situation: When this strategy applies (e.g. "Customer specifies a clothing color but leaves style ambiguous and results are broad").
  - strategy: What action to take (e.g. "Clarify style before issuing narrow recommendations").
  - rationale: Why this helps (e.g. "Reduces irrelevant candidates before recommendation").
  - expected_action: CLARIFY | SEARCH | RECOMMEND | RESPOND
  - trigger_type: attribute_clarification | initial_query | unsuccessful_search | recommend_cutoff

Output JSON:
{
  "has_lesson": true | false,
  "reason": "Brief explanation",
  "situation": "...",
  "strategy": "...",
  "rationale": "...",
  "directive": "Concise instruction under 350 chars",
  "expected_action": "CLARIFY | SEARCH | RECOMMEND | RESPOND",
  "trigger_type": "attribute_clarification | initial_query | unsuccessful_search | recommend_cutoff",
  "trigger_condition": {
    "is_underspecified": true
  },
  "action_signature": {
    "attribute": "style"
  }
}
"""


@dataclass(frozen=True)
class DistillationResult:
    session_id: str
    has_lesson: bool
    status: str  # "reinforced" | "added" | "noop" | "error"
    lesson: Lesson | None
    reason: str


def sanitize_session_for_distillation(session: Session) -> dict:
    """Extract session trajectory stripped of customer identity or private tokens."""
    events = session.events
    actions = []
    user_queries = []

    for ev in events:
        if ev.type == "user_message":
            msg = ev.payload.get("message", "")
            user_queries.append(msg)
        elif ev.type == "tool_call" and ev.payload.get("tool") == "product_search":
            action = ev.payload.get("action", {})
            actions.append({"tool": "SEARCH", "query": action.get("query"), "mode": action.get("mode")})
        elif ev.type == "decision_validated":
            action = ev.payload.get("action", {})
            act_type = action.get("type")
            if act_type in ("CLARIFY", "RECOMMEND", "RESPOND"):
                actions.append(action)

    return {
        "session_id": session.id,
        "customer_inputs": user_queries,
        "actions": actions,
        "state_summary": {
            "requirements": [
                {"field": r.field, "op": r.op, "strength": r.strength}
                for r in session.state.requirements
                if r.status == "active"
            ]
        },
    }


def distill_session_experience(
    session: Session,
    store: ExperienceStore,
    policy,
    *,
    outcome: dict | None = None,
    allow_non_learning: bool = True,
) -> DistillationResult:
    """Analyze a completed session and distill/reinforce a procedural lesson."""
    sanitized = sanitize_session_for_distillation(session)
    if not sanitized["customer_inputs"]:
        return DistillationResult(
            session_id=session.id,
            has_lesson=False,
            status="noop",
            lesson=None,
            reason="no_user_inputs",
        )

    context_payload = {
        "trajectory": sanitized,
        "outcome": outcome or {"status": "completed"},
    }

    messages = [
        {"role": "system", "content": EXPERIENCE_DISTILLATION_PROMPT},
        {"role": "user", "content": json.dumps(context_payload, indent=2)},
    ]

    try:
        reply = policy.complete(messages)
        content = reply.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n", "", content)
            content = re.sub(r"\n```$", "", content)
        data = json.loads(content)
    except Exception as exc:
        return DistillationResult(
            session_id=session.id,
            has_lesson=False,
            status="error",
            lesson=None,
            reason=f"policy_or_json_parsing_failed: {exc}",
        )

    if not data.get("has_lesson"):
        return DistillationResult(
            session_id=session.id,
            has_lesson=False,
            status="noop",
            lesson=None,
            reason=data.get("reason", "no_lesson_found"),
        )

    directive = (data.get("directive") or data.get("strategy") or "")[:350]
    trigger_type = data.get("trigger_type", "initial_query")
    scope = data.get("scope", "*")
    lesson_id = digest_lesson_content(scope, trigger_type, directive, version=1)

    candidate = Lesson(
        lesson_id=lesson_id,
        version=1,
        scope=scope,
        trigger_type=trigger_type,
        trigger_condition=data.get("trigger_condition") or {"has_search": True},
        directive=directive,
        expected_action=data.get("expected_action", "SEARCH"),
        action_signature=data.get("action_signature") or {},
        observed_outcome=data.get("observed_outcome", "improved_relevance"),
        hypothesized_cause=data.get("rationale", ""),
        evidence={"source_session_id": session.id, "source_split": "learning"},
        status="candidate",
        situation=data.get("situation", ""),
        strategy=data.get("strategy", ""),
        rationale=data.get("rationale", ""),
        confidence=0.85,
    )

    try:
        status, persisted = store.reinforce_or_add_lesson(
            candidate,
            allow_non_learning=allow_non_learning,
        )
        # Record event in session
        try:
            session.append(
                "experience_distilled",
                {
                    "lesson_id": persisted.lesson_id,
                    "status": status,
                    "directive": persisted.directive,
                    "situation": persisted.situation,
                    "strategy": persisted.strategy,
                },
                request_id=f"exp-distill-{session.id}",
            )
        except Exception:
            pass

        return DistillationResult(
            session_id=session.id,
            has_lesson=True,
            status=status,
            lesson=persisted,
            reason=data.get("reason", ""),
        )
    except Exception as exc:
        return DistillationResult(
            session_id=session.id,
            has_lesson=False,
            status="error",
            lesson=None,
            reason=f"lesson_validation_or_store_failed: {exc}",
        )
