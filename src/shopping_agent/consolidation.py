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
Your task is to analyze a completed shopping session dialogue, customer decisions, and any simulated purchase records, then update the customer's durable memory profile.

Analyze what the customer explicitly stated about their enduring preferences, habits, sizes, or dislikes, as well as confirmed purchase choices:
- Explicit statement + purchase: If the customer stated a preference (e.g. "I usually prefer minimalist bags") and then purchased a matching item, this strongly reinforces that preference.
- Single purchase: A single purchase (e.g. one black bag) is factual episodic evidence of that decision, not definitive proof of a general rule unless supported by customer statements or repeated purchases.
- Repeated purchases: Multiple purchases sharing an attribute (e.g., multiple black bags) support a tentative generalization (basis: "inferred").
- GIFT PURCHASES: When recipient_context is "gift" or the customer notes the item is a gift, DO NOT infer that the customer's personal style matches the gift recipient's preferences.
- STRICT IDENTITY RESTRICTION: Never infer a customer's gender, age, or personal identity solely from product categories or items purchased.
- Do NOT store the entire purchase history as duplicate semantic memories; keep the purchase ledger as the source of truth and distill only useful, supported summaries.
- Do NOT store one-off situational needs (e.g. "for a friend's wedding", "gift for my dad", "just for today", or temporary budgets) as durable customer preferences.

Review the existing active memory records provided in context. Determine appropriate operations:
- ADD: A genuinely new durable preference or fact not present in the existing profile.
- REINFORCE: The customer reaffirmed or purchased in alignment with an existing memory (refreshes recency).
- SUPERSEDE: The customer updated or changed an earlier memory. Provide target_id of the existing memory.
- DELETE: The customer explicitly requested to forget or remove an existing preference. Provide target_id.
- NOOP: No durable information worth remembering, or dialogue/purchases were inconclusive.

Rules:
1. quote MUST be an exact excerpt from the customer's messages in this session or from a confirmed purchase record in this session.
2. attribute must be a concise lowercase key (e.g. 'color', 'size', 'style', 'brand', 'fit', 'material').
3. scope should specify domain (e.g. 'workout clothing', 'bags', 'shoes') or 'general'.
4. Do NOT invent memories or infer preferences from recommendations the customer did not accept.
5. If no durable memory was disclosed or demonstrated, return empty operations.

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
      "quote": "exact quote from customer or purchase record",
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
    operations: list[ConsolidationOperation] = Field(
        default_factory=list, max_length=10
    )


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
    purchase_store=None,
    purchases: list[dict] | None = None,
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

    # Collect dialogue history and session purchases
    user_messages = []
    dialogue_summary = []
    session_purchases = list(purchases or [])

    for ev in session.events:
        if ev.type == "user_message":
            msg = ev.payload.get("message", "")
            user_messages.append(msg)
            dialogue_summary.append({"role": "customer", "message": msg})
        elif ev.type == "decision_validated":
            action = ev.payload.get("action", {})
            act_type = action.get("type", "")
            if act_type == "CLARIFY":
                dialogue_summary.append(
                    {
                        "role": "assistant",
                        "action": "CLARIFY",
                        "question": action.get("question", ""),
                    }
                )
            elif act_type == "RECOMMEND":
                dialogue_summary.append(
                    {
                        "role": "assistant",
                        "action": "RECOMMEND",
                        "products": action.get("product_ids", []),
                    }
                )
            elif act_type == "RESPOND":
                dialogue_summary.append(
                    {
                        "role": "assistant",
                        "action": "RESPOND",
                        "message": action.get("message", ""),
                    }
                )
        elif ev.type == "purchase_recorded":
            p_data = ev.payload.copy()
            if not any(
                p.get("purchase_id") == p_data.get("purchase_id")
                for p in session_purchases
            ):
                session_purchases.append(p_data)

    if purchase_store is not None:
        try:
            store_purchases = purchase_store.get_purchases(
                user_id, session_id=session.id, include_cancelled=False
            )
            for sp in store_purchases:
                sp_dict = sp.to_dict() if hasattr(sp, "to_dict") else sp
                if not any(
                    p.get("purchase_id") == sp_dict.get("purchase_id")
                    for p in session_purchases
                ):
                    session_purchases.append(sp_dict)
        except Exception:
            pass

    if not user_messages and not session_purchases:
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
    if session_purchases:
        context_payload["session_purchases"] = [
            {
                "purchase_id": p.get("purchase_id"),
                "product_id": p.get("product_id"),
                "title": p.get("title"),
                "price": p.get("price"),
                "attributes": p.get("attribute_snapshot", {}),
                "recipient_context": p.get("recipient_context", "self"),
                "timestamp": p.get("timestamp"),
            }
            for p in session_purchases
        ]

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
    purchase_evidence_strings = [
        f"{p.get('title', '')} {p.get('product_id', '')} "
        + " ".join(f"{k} {v}" for k, v in p.get("attribute_snapshot", {}).items())
        for p in session_purchases
    ]
    all_allowed_evidence = full_user_text + "\n" + "\n".join(purchase_evidence_strings)

    validated_ops = []
    rejected_ops = []
    reinforced_from_purchase = []

    for op in decision.operations:
        op_dict = op.model_dump()
        if op.op == "NOOP":
            continue

        # 1. Quote provenance check: quote must be in customer messages or confirmed purchase evidence
        if op.op != "DELETE":
            q = op.quote.strip()
            if not q or (
                q not in all_allowed_evidence
                and q.casefold() not in all_allowed_evidence.casefold()
            ):
                rejected_ops.append(
                    {
                        "operation": op_dict,
                        "rejection_reason": "quote_not_found_in_session_user_messages",
                    }
                )
                continue

        # 2. Target ID validation for update/supersede/delete/reinforce
        if op.op in ("REINFORCE", "UPDATE", "SUPERSEDE", "DELETE"):
            if not op.target_id or op.target_id not in active_ids:
                rejected_ops.append(
                    {
                        "operation": op_dict,
                        "rejection_reason": "target_id_not_active_in_user_profile",
                    }
                )
                continue

        # 3. Content completeness
        if op.op in ("ADD", "UPDATE", "SUPERSEDE") and not op.value.strip():
            rejected_ops.append(
                {
                    "operation": op_dict,
                    "rejection_reason": "value_cannot_be_empty",
                }
            )
            continue

        # Track if this operation utilized purchase evidence
        if session_purchases and (
            any(
                p.get("product_id", "").lower() in op.rationale.lower()
                or p.get("title", "").lower() in op.rationale.lower()
                or op.category == "purchase"
                for p in session_purchases
            )
        ):
            reinforced_from_purchase.append(op_dict)

        validated_ops.append(op_dict)

    applied_result = memory_store.apply_consolidation_operations(
        user_id=user_id,
        session_id=session.id,
        operations=validated_ops,
    )

    # Append audit events to session
    try:
        if session_purchases:
            session.append(
                "purchase_evidence_used",
                {
                    "count": len(session_purchases),
                    "purchases": session_purchases,
                },
                turn_id=f"consolidation-purchases-{session.id}",
            )
        if reinforced_from_purchase:
            session.append(
                "memory_reinforced_from_purchase",
                {
                    "operations": reinforced_from_purchase,
                },
                turn_id=f"consolidation-reinforced-{session.id}",
            )
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
            turn_id=f"consolidation-{session.id}",
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
