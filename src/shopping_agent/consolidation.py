"""End-of-session user memory consolidation.

Processes full session dialogue once at session completion, allowing the LLM to
interpret durable facts, preferences, corrections, and conflicts without regex gates.
Python enforces transactional safety, provenance validation, and atomic commits.
"""

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from .contracts import Strict
from .sessions import Session
from .user_memory import UserMemoryStore

CONSOLIDATION_SYSTEM_PROMPT = """You are ASTRA's customer memory consolidation policy.
Your task is to analyze a completed shopping session dialogue and update the customer's durable memory profile.

Analyze what the customer explicitly stated about their enduring preferences, habits, sizes, or dislikes.
Do NOT store one-off situational needs (e.g. "for a friend's wedding", "gift for my dad", "just for today", or temporary budgets) as durable customer preferences.

Review the existing active memory records provided in context. Determine appropriate operations:
- ADD: A genuinely new durable preference or fact not present in the existing profile.
- REINFORCE: The customer reaffirmed an existing memory without changing it (refreshes recency).
- SUPERSEDE: The customer updated or changed an earlier memory (e.g., switched from slim-fit to oversized, or changed shoe size). Provide target_id of the existing memory.
- DELETE: The customer explicitly requested to forget or remove an existing preference. Provide target_id.
- NOOP: No durable information worth remembering, or dialogue was inconclusive.

Rules:
1. quote MUST be an exact verbatim excerpt from the customer's messages in this session.
2. attribute must be a concise lowercase key (e.g. 'color', 'size', 'style', 'brand', 'fit', 'material').
3. scope should specify domain (e.g. 'workout clothing', 'bags', 'shoes') or 'general'.
4. Do NOT invent memories or infer preferences from recommendations the customer did not accept.
5. If no durable memory was disclosed, return empty operations.

Output JSON matching the schema:
{
  "reason": "Short summary of memory updates",
  "operations": [
    {
      "op": "ADD | REINFORCE | SUPERSEDE | DELETE | NOOP",
      "category": "preference | fact | dislike | purchase",
      "attribute": "lowercase_attribute",
      "value": "preferred value",
      "scope": "domain or general",
      "basis": "confirmed | inferred",
      "quote": "exact quote from customer",
      "target_id": "um-... (only for REINFORCE, SUPERSEDE, DELETE)",
      "confidence": 1.0,
      "rationale": "explanation"
    }
  ]
}
"""


class ConsolidationOperation(Strict):
    op: Literal["ADD", "REINFORCE", "UPDATE", "SUPERSEDE", "DELETE", "NOOP"] = "ADD"
    category: Literal["preference", "fact", "dislike", "purchase"] = "preference"
    attribute: str = Field(default="attribute", min_length=1, max_length=40)
    value: str = Field(default="", max_length=200)
    scope: str = Field(default="general", max_length=80)
    basis: Literal["confirmed", "inferred"] = "confirmed"
    quote: str = Field(default="", max_length=1000)
    target_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=500)


class ConsolidationDecision(Strict):
    reason: str = Field(default="", max_length=1000)
    operations: list[ConsolidationOperation] = Field(default_factory=list, max_length=10)


@dataclass(frozen=True)
class ConsolidationResult:
    session_id: str
    user_id: str
    idempotent: bool
    revision: int
    operations_applied: list[dict]
    rejected_operations: list[dict]
    reason: str


def consolidate_session(
    session: Session,
    user_id: str,
    memory_store: UserMemoryStore,
    policy,
    *,
    idempotency_key: str | None = None,
) -> ConsolidationResult:
    """Run end-of-session memory consolidation exactly once for a completed session."""
    # Check if session is already consolidated in store
    profile = memory_store.read(user_id)
    if profile.last_consolidated_session_id == session.id:
        return ConsolidationResult(
            session_id=session.id,
            user_id=user_id,
            idempotent=True,
            revision=profile.revision,
            operations_applied=[],
            rejected_operations=[],
            reason="session_already_consolidated",
        )

    # Collect dialogue history
    user_messages = []
    dialogue_summary = []
    for ev in session.events:
        if ev.type == "user_message":
            msg = ev.payload.get("message", "")
            user_messages.append(msg)
            dialogue_summary.append({"role": "customer", "message": msg})
        elif ev.type == "decision_validated":
            action = ev.payload.get("action", {})
            act_type = action.get("type", "")
            if act_type == "CLARIFY":
                dialogue_summary.append({
                    "role": "assistant",
                    "action": "CLARIFY",
                    "question": action.get("question", ""),
                })
            elif act_type == "RECOMMEND":
                dialogue_summary.append({
                    "role": "assistant",
                    "action": "RECOMMEND",
                    "products": action.get("product_ids", []),
                })
            elif act_type == "RESPOND":
                dialogue_summary.append({
                    "role": "assistant",
                    "action": "RESPOND",
                    "message": action.get("message", ""),
                })

    if not user_messages:
        return ConsolidationResult(
            session_id=session.id,
            user_id=user_id,
            idempotent=False,
            revision=profile.revision,
            operations_applied=[],
            rejected_operations=[],
            reason="no_user_messages_in_session",
        )

    # Active records
    active_records = [
        {
            "id": r.id,
            "category": r.category,
            "attribute": r.attribute,
            "value": r.value,
            "scope": r.scope,
            "quote": r.quote,
            "created_at": r.created_at,
            "last_confirmed_at": r.last_confirmed_at,
        }
        for r in profile.records
        if r.status == "active"
    ]
    active_ids = {r["id"] for r in active_records}

    context_payload = {
        "session_id": session.id,
        "customer_id": user_id,
        "dialogue": dialogue_summary,
        "existing_active_memories": active_records,
    }

    messages = [
        {"role": "system", "content": CONSOLIDATION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context_payload, indent=2)},
    ]

    try:
        reply = policy.complete(messages)
        content = reply.content.strip()
        if content.startswith("```"):
            # Strip code fence
            content = re.sub(r"^```(?:json)?\n", "", content)
            content = re.sub(r"\n```$", "", content)
        data = json.loads(content)
        decision = ConsolidationDecision.model_validate(data)
    except Exception as exc:
        return ConsolidationResult(
            session_id=session.id,
            user_id=user_id,
            idempotent=False,
            revision=profile.revision,
            operations_applied=[],
            rejected_operations=[{"error": f"consolidation_policy_error: {exc}"}],
            reason="policy_or_json_parsing_failed",
        )

    # Python Engineering Validation
    full_user_text = "\n".join(user_messages)
    validated_ops = []
    rejected_ops = []

    for op in decision.operations:
        op_dict = op.model_dump()
        if op.op == "NOOP":
            continue

        # 1. Quote provenance check: quote must be in customer messages
        if op.op != "DELETE":
            q = op.quote.strip()
            if not q or (q not in full_user_text and q.casefold() not in full_user_text.casefold()):
                rejected_ops.append({
                    "operation": op_dict,
                    "rejection_reason": "quote_not_found_in_session_user_messages",
                })
                continue

        # 2. Target ID validation for update/supersede/delete/reinforce
        if op.op in ("REINFORCE", "UPDATE", "SUPERSEDE", "DELETE"):
            if not op.target_id or op.target_id not in active_ids:
                rejected_ops.append({
                    "operation": op_dict,
                    "rejection_reason": "target_id_not_active_in_user_profile",
                })
                continue

        # 3. Content completeness
        if op.op in ("ADD", "UPDATE", "SUPERSEDE") and not op.value.strip():
            rejected_ops.append({
                "operation": op_dict,
                "rejection_reason": "value_cannot_be_empty",
            })
            continue

        validated_ops.append(op_dict)

    applied_result = memory_store.apply_consolidation_operations(
        user_id=user_id,
        session_id=session.id,
        operations=validated_ops,
    )

    # Append audit event to session
    try:
        session.append(
            "user_memory_consolidated",
            {
                "session_id": session.id,
                "user_id": user_id,
                "operations_applied": validated_ops,
                "operations_rejected": rejected_ops,
                "new_revision": applied_result["revision"],
                "reason": decision.reason,
            },
            request_id=f"consolidation-{session.id}",
        )
    except Exception:
        pass

    return ConsolidationResult(
        session_id=session.id,
        user_id=user_id,
        idempotent=False,
        revision=applied_result["revision"],
        operations_applied=validated_ops,
        rejected_operations=rejected_ops,
        reason=decision.reason,
    )
