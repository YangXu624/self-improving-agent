"""Small shopping/memory views; internal IDs and revision checks stay in the executor.

Views are projections, not another authority. Field/index references are valid only for
the exact current decision; canonical state and evidence remain in session events.
"""

from pydantic import Field

from .attributes import attribute_ledger
from .contracts import Action, Decision, ShoppingState, StateUpdate, Strict
from .user_memory import MemoryDecision, MemoryProposal

FORMATS = ("legacy", "compact")
COMPACT_PROMPT_VERSION = "shopping-baseline-v7-compact-memory"


class CompactDecision(Strict):
    updates: list[StateUpdate] = Field(default_factory=list, max_length=12)
    action: Action
    reason: str = Field(min_length=1, max_length=600)


class CompactMemoryProposal(MemoryProposal):
    target_id: str | None = Field(default=None, pattern=r"^memory\.\d+$")


class CompactMemoryDecision(CompactDecision):
    user_memory_updates: list[CompactMemoryProposal] = Field(
        default_factory=list, max_length=4
    )


def state_slots(state: ShoppingState):
    counters = {}
    for requirement in state.requirements:
        if requirement.status != "active":
            continue
        group = "hard" if requirement.strength == "hard" else "preferences"
        field = "category" if requirement.field == "product_type" else requirement.field
        key = (group, field)
        index = counters.get(key, 0)
        counters[key] = index + 1
        yield f"{group}.{field}.{index}", group, field, requirement


def compact_state(session) -> dict:
    """Retain every active predicate/operator without provenance or redundant values."""
    result = {"hard": {}, "preferences": {}}
    for _reference, group, field, requirement in state_slots(session.state):
        result[group].setdefault(field, []).append({requirement.op: requirement.value})
    ledger = attribute_ledger(session)
    clarifications = {}
    for attribute in sorted(
        set(ledger["asked_attributes"]) | set(ledger["disclosed_attributes"])
    ):
        asked = ledger["asked_attributes"].get(attribute)
        disclosed = ledger["disclosed_attributes"].get(attribute)
        entry = {"status": (disclosed or asked)["status"]}
        if asked:
            entry["asked"] = True
        if disclosed and "value" in disclosed:
            entry["value"] = disclosed["value"]
        clarifications[attribute] = entry
    if clarifications:
        result["clarifications"] = clarifications
    if session.state.conflicts:
        result["conflicts"] = list(session.state.conflicts)
    return result


def memory_text(record: dict) -> str:
    """Deterministic prose, not an LLM summary; the current value cannot be omitted."""
    attribute = record["attribute"].replace("_", " ")
    value = record["value"]
    category = record["category"]
    if category == "preference":
        text = f"Usually prefers {attribute}: {value}"
    elif category == "dislike":
        text = f"Avoids {attribute}: {value}"
    elif category == "purchase":
        text = f"Confirmed purchase: {value}"
    else:
        text = f"User fact — {attribute}: {value}"
    if record["scope"] != "general":
        text += f" (for {record['scope']})"
    if record["basis"] == "inferred":
        text += " [unconfirmed inference]"
    return text + "."


def compact_user_memory(view: dict) -> dict:
    return {
        "records": [
            {"ref": f"memory.{i}", "text": memory_text(record)}
            for i, record in enumerate(view["records"])
        ]
    }


def expand_decision(
    content: str, state: ShoppingState, memory_view: dict | None = None
) -> Decision:
    """Resolve current-view references; retain existing strict execution validation."""
    contract = CompactMemoryDecision if memory_view is not None else CompactDecision
    value = contract.model_validate_json(content).model_dump()
    handles = {
        reference: requirement.id
        for reference, _group, _field, requirement in state_slots(state)
    }
    for update in value["updates"]:
        if update["target_id"] is not None:
            if update["target_id"] not in handles:
                raise ValueError("invalid_current_state_reference")
            update["target_id"] = handles[update["target_id"]]
    for proposal in value.get("user_memory_updates", []):
        if proposal["target_id"] is not None:
            references = {
                f"memory.{i}": record["id"]
                for i, record in enumerate(memory_view["records"])
            }
            if proposal["target_id"] not in references:
                raise ValueError("invalid_current_memory_reference")
            proposal["target_id"] = references[proposal["target_id"]]
    value["based_on_state_version"] = state.version
    canonical = MemoryDecision if memory_view is not None else Decision
    return canonical.model_validate(value)
