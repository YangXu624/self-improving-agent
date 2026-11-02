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

Differentiate memory types and properties:

1. DURABLE EXPLICIT PREFERENCES AND DISLIKES (category: "preference" or "dislike"):
- Stable personal preferences for colors, styles, fits, brands, or materials (e.g. "I always buy black workout clothing", "I prefer minimalist designs").
- Strength: Use "hard" ONLY if the customer stated a non-negotiable rule ("always", "must", "strictly"). Otherwise use "soft" ("usually", "prefer", "tend to").
- Scoped preferences: If a preference applies to a specific domain (e.g. "for formal events, I prefer cream"), set scope to that domain (e.g. "formalwear") rather than "general". Do NOT overwrite or delete a general preference when establishing a narrower domain-specific preference.

2. STABLE FACTS AND SIZES (category: "fact"):
- Enduring physical measurements, shoe sizes, clothing sizes (e.g. "I wear size 10 shoes"). Strength is typically "hard", confidence 1.0.

3. CONTEXTUAL & EPISODIC SHOPPING HISTORY (category: "contextual"):
- Categories previously shopped for, shopping goals, or recipient context for personal use.
- Example: When the customer asks "I'm looking for a women's bag for myself", record this under category: "contextual", attribute: "shopping_history", value: "previously shopped for women's bags for personal use", scope: "bags", strength: "soft", confidence: 0.9.
- Note: This captures useful context for future visits. Do NOT infer that the customer is a woman, or that all future bags must be women's bags.

4. INFERRED PREFERENCES (basis: "inferred", strength: "inferred"):
- Repeated purchases or consistent choices sharing an attribute without an explicit statement. Confidence should be moderate (0.6 - 0.7). Never present as confirmed facts.

5. GIFT PURCHASES & OTHER RECIPIENTS:
- When recipient_context is "gift" or the customer notes the item is for someone else (e.g., "for my sister"), DO NOT attribute the recipient's preferences to the customer's personal profile. If relevant, record as contextual history (e.g. "shopped for sister's birthday gift: red bag").

6. STRICT IDENTITY RESTRICTION:
- Never infer a customer's gender, age, or personal demographic identity solely from product categories or items purchased.

Review existing active memory records provided in context. Determine appropriate operations:
- ADD: A genuinely new preference, fact, or contextual history not present in the existing profile.
- REINFORCE: The customer reaffirmed or purchased in alignment with an existing memory (refreshes recency).
- SUPERSEDE: The customer updated or changed an earlier memory. Provide target_id of the existing memory.
- DELETE: The customer explicitly requested to forget or remove an existing preference. Provide target_id.
- NOOP: No new durable or contextual information worth remembering.

Rules:
1. quote MUST be an exact verbatim excerpt from the customer's messages in this session or from a confirmed purchase record.
2. attribute must be a concise lowercase key (e.g. 'color', 'size', 'style', 'brand', 'fit', 'material', 'shopping_history').
3. scope should specify domain (e.g. 'workout clothing', 'bags', 'formalwear', 'shoes') or 'general'.
4. Do NOT invent memories or infer preferences from recommendations the customer did not accept.
5. If no durable memory was disclosed or demonstrated, return empty operations.

Output JSON matching the schema:
{
  "reason": "Short summary of memory updates",
  "operations": [
    {
      "op": "ADD | REINFORCE | SUPERSEDE | DELETE | NOOP",
      "category": "preference | fact | dislike | contextual | purchase",
      "attribute": "lowercase_attribute",
      "value": "preferred value or context description",
      "scope": "domain or general",
      "strength": "hard | soft | inferred",
      "evidence_type": "explicit | inferred",
      "confidence": 1.0,
      "basis": "confirmed | inferred",
      "quote": "exact quote from customer or purchase record",
      "target_id": "um-... (only for REINFORCE, SUPERSEDE, DELETE)",
      "rationale": "explanation"
    }
  ]
}
"""


class ConsolidationOperation(Strict):
    op: Literal["ADD", "REINFORCE", "UPDATE", "SUPERSEDE", "DELETE", "NOOP"] = "ADD"
    category: Literal["preference", "fact", "dislike", "contextual", "purchase"] = (
        "preference"
    )
    attribute: str = Field(default="attribute", min_length=1, max_length=40)
    value: str = Field(default="", max_length=200)
    scope: str = Field(default="general", max_length=80)
    strength: Literal["hard", "soft", "inferred"] = "soft"
    evidence_type: Literal["explicit", "inferred"] = "explicit"
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
            "strength": getattr(r, "strength", "soft"),
            "evidence_type": getattr(r, "evidence_type", "explicit"),
            "confidence": getattr(r, "confidence", 1.0),
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
