"""Development-only customer timelines compiled into existing session/scoring contracts.

Private timelines never enter ASTRA. Only the current visit's bounded roleplay context
enters the shopper; target IDs and catalogue evidence remain evaluator-only.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .consistency import errors, target_disclosures
from .experiment import digest
from .memory import ShopperMemory
from .models import (
    Fact,
    GroundTruth,
    Scenario,
    ShopperProfile,
    ShopperReply,
    Strict,
    TargetGroundTruth,
)
from .oracle import DETAIL_NAMES, CatalogueOracle, judge, raw_facts

SAFE_ID = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class PersistentPreference(Strict):
    category: Literal["preference", "dislike"] = "preference"
    scope: str = Field(min_length=1, max_length=80)
    fact: Fact


class CustomerChange(Strict):
    before_sequence: int = Field(ge=2)
    updates: list[PersistentPreference] = Field(default_factory=list)
    remove_keys: list[str] = Field(default_factory=list)
    background: str | None = Field(default=None, max_length=300)


class VisitEvidence(Strict):
    acceptable_count: int = Field(ge=1)
    acceptable_ids_sha256: str
    best_ids_sha256: str
    witness_sources: dict[str, str]


class ShoppingVisit(Strict):
    task_id: str = Field(pattern=SAFE_ID)
    sequence: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=80)
    recipient: Literal["self", "gift"] = "self"
    evaluation_mode: Literal["preference", "target_item"] = "preference"
    opening: str = Field(min_length=1, max_length=600)
    opening_keys: list[str] = Field(default_factory=lambda: ["type"])
    disclosure: Literal["progressive", "recall_probe", "announce_change", "gift"] = (
        "progressive"
    )
    hard: list[Fact]
    soft: list[Fact] = Field(default_factory=list)
    persistent_keys: list[str] = Field(default_factory=list)
    witness_id: str = Field(min_length=1, max_length=80)
    evidence: VisitEvidence | None = None
    max_user_turns: int = Field(default=6, ge=1, le=20)


class Customer(Strict):
    user_id: str = Field(pattern=SAFE_ID)
    personality: str = Field(min_length=1, max_length=250)
    background: str = Field(min_length=1, max_length=300)
    interests: list[str] = Field(default_factory=list, max_length=8)
    preferences: list[PersistentPreference] = Field(default_factory=list)
    changes: list[CustomerChange] = Field(default_factory=list)
    visits: list[ShoppingVisit] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if [v.sequence for v in self.visits] != list(range(1, len(self.visits) + 1)):
            raise ValueError(
                "Customer visits must be in contiguous chronological order"
            )
        keys = [p.fact.key for p in self.preferences]
        if len(keys) != len(set(keys)):
            raise ValueError("Persistent fact keys must be unique")
        boundaries = [c.before_sequence for c in self.changes]
        if boundaries != sorted(set(boundaries)) or any(
            n > len(self.visits) for n in boundaries
        ):
            raise ValueError("Changes need unique ordered visit boundaries")
        return self

    def state_at(self, sequence: int) -> tuple[str, dict[str, PersistentPreference]]:
        """Project only changes already effective; never return future timeline entries."""
        background = self.background
        preferences = {p.fact.key: p for p in self.preferences}
        for change in self.changes:
            if change.before_sequence > sequence:
                break
            for key in change.remove_keys:
                if key not in preferences:
                    raise ValueError("Cannot remove an unknown persistent fact")
                del preferences[key]
            for preference in change.updates:
                if preference.fact.key not in preferences:
                    raise ValueError(
                        "A preference change must identify an existing key"
                    )
                preferences[preference.fact.key] = preference
            if change.background is not None:
                background = change.background
        return background, preferences


class CustomerDataset(Strict):
    schema_version: Literal[1] = 1
    dataset_id: str = Field(pattern=SAFE_ID)
    split: Literal["development"] = "development"
    catalogue_sha256: str
    provenance: str
    customers: list[Customer] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        users = [c.user_id for c in self.customers]
        tasks = [v.task_id for c in self.customers for v in c.visits]
        if len(users) != len(set(users)) or len(tasks) != len(set(tasks)):
            raise ValueError("Customer and task IDs must be unique")
        return self


@dataclass(frozen=True)
class CompiledVisit:
    customer_id: str
    visit: ShoppingVisit
    scenario: Scenario
    preference_truth: GroundTruth
    target_truth: TargetGroundTruth
    shopper_context: dict


def validate_statement(fact: Fact) -> None:
    """Curated facts use literal disclosures; reuse the simulator's evidence checker."""
    profile = ShopperProfile(
        scenario_id="validate",
        persona="Validation only",
        facts=(fact,),
        opening_keys=(),
    )
    supported, flags = target_disclosures(
        ShopperReply(message=fact.statement, reveals=[fact.key]), ShopperMemory(profile)
    )
    if fact.key not in supported or errors(flags):
        raise ValueError(
            "Disclosure statement must express its frozen fact value/operator"
        )
    if fact.op in {"neq", "not_contains", "not_in"} and not re.search(
        r"\b(?:avoid|not|no|without|dislike|hate)\b", fact.statement, re.I
    ):
        raise ValueError("Negative facts require explicit negative disclosure")
    if fact.field == "price":
        operators = {
            "lt": r"under|below|less than",
            "lte": r"at most|no more than",
            "gt": r"over|above|more than",
            "gte": r"at least|no less than",
            "eq": r"exactly",
        }
        if fact.op not in operators or not re.search(
            r"\b(?:" + operators[fact.op] + r")\b", fact.statement, re.I
        ):
            raise ValueError("Price disclosure must state its exact budget operator")


def compile_visit(
    customer: Customer, visit: ShoppingVisit
) -> tuple[Scenario, dict, list[Fact]]:
    background, persistent = customer.state_at(visit.sequence)
    if visit.recipient == "gift" and visit.persistent_keys:
        raise ValueError(
            "Gift scoring must not inherit the customer's personal preferences"
        )
    if any(key not in persistent for key in visit.persistent_keys):
        raise ValueError("Visit references an unknown current persistent preference")
    selected = [persistent[key].fact for key in visit.persistent_keys]
    if any(f.kind != "hard" for f in visit.hard) or any(
        f.kind != "soft" for f in visit.soft + selected
    ):
        raise ValueError(
            "Hard/soft requirements and persistent preferences must keep their declared strength"
        )
    facts = visit.hard + visit.soft + selected
    for fact in facts:
        validate_statement(fact)
    keys = [f.key for f in facts]
    if len(keys) != len(set(keys)):
        raise ValueError("Visit fact keys must be unique")
    if not any(
        f.field == "product_type"
        and f.op == "contains"
        and str(f.value).casefold() == visit.category.casefold()
        for f in visit.hard
    ):
        raise ValueError("Each visit needs its explicit hard product category")
    for key in visit.opening_keys:
        fact = next((f for f in facts if f.key == key), None)
        if fact is None or fact.statement not in visit.opening:
            raise ValueError(
                "Opening keys must have their literal fact statement in the opening"
            )
    profile = ShopperProfile(
        scenario_id=visit.task_id,
        persona=customer.personality,
        facts=tuple(facts),
        opening_keys=tuple(visit.opening_keys),
    )
    scenario = Scenario(
        id=visit.task_id,
        split="development",
        kind="underspecified",
        family=visit.category,
        opening=visit.opening,
        max_user_turns=visit.max_user_turns,
        profile=profile,
    )
    context = {
        "background": background,
        "interests": customer.interests,
        "current_persistent_preferences": [p.model_dump() for p in persistent.values()],
        "current_goal": visit.goal,
        "recipient": visit.recipient,
        "disclosure": visit.disclosure,
        "instructions": (
            "Roleplay only the current visit. Background is not a product requirement. "
            "State only the current hidden-profile facts as shopping constraints. Never invent prior dialogue. "
            "For recall_probe, do not repeat persistent preferences unprompted; answer honestly if asked. "
            "For announce_change, explain the current change when relevant. For gifts, use recipient facts, "
            "not your personal preferences. Keep persistence words in explicit persistent disclosures. "
            "Only facts in the hidden shopping profile can be listed in reveals."
        ),
    }
    return scenario, context, facts


def validate_dataset(
    dataset: CustomerDataset, catalogue: str | Path, *, require_evidence: bool = True
) -> list[CompiledVisit]:
    """Check every goal/witness against raw catalogue evidence; never call a model."""
    oracle = CatalogueOracle(catalogue)
    if oracle.sha256 != dataset.catalogue_sha256:
        raise ValueError("Customer dataset catalogue hash mismatch")
    entries = [(row["parent_asin"], raw_facts(row)) for row in oracle.rows()]
    compiled = []
    for customer in dataset.customers:
        for visit in customer.visits:
            scenario, context, facts = compile_visit(customer, visit)
            hard = [f for f in facts if f.kind == "hard"]
            soft = [f for f in facts if f.kind == "soft"]
            if len(hard) != len(visit.hard):
                raise ValueError(
                    "Persistent preferences and visit soft facts must not introduce hidden hard requirements"
                )
            graded, best, unknown = [], [], 0
            for product_id, values in entries:
                verdict = judge(values, hard, soft)
                if verdict["grade"]:
                    graded.append((product_id, verdict["grade"]))
                if judge(values, hard + soft, [])["hard"] == "pass":
                    best.append(product_id)
                unknown += verdict["hard"] == "unknown"
            row = oracle.row(visit.witness_id)
            if row is None or judge(raw_facts(row), hard + soft, [])["hard"] != "pass":
                raise ValueError(
                    f"{visit.task_id}: witness must satisfy hard and all soft facts"
                )
            sources = {}
            for fact in facts:
                if fact.field == "product_type":
                    sources[fact.key] = "categories"
                elif fact.field == "price":
                    sources[fact.key] = "price"
                else:
                    sources[fact.key] = "details." + next(
                        name
                        for name in DETAIL_NAMES[fact.field]
                        if isinstance(
                            row.get("details", {}).get(name), (str, int, float)
                        )
                        and not isinstance(row["details"][name], bool)
                        and str(row["details"][name]).strip()
                    )
            best = sorted(best)
            evidence = VisitEvidence(
                acceptable_count=len(graded),
                acceptable_ids_sha256=digest(sorted(i for i, _ in graded)),
                best_ids_sha256=digest(best),
                witness_sources=sources,
            )
            if require_evidence and visit.evidence != evidence:
                raise ValueError(f"{visit.task_id}: frozen catalogue evidence mismatch")
            truth = GroundTruth(
                scenario_id=visit.task_id,
                kind="feasible",
                hard=hard,
                soft=soft,
                acceptable_count=len(graded),
                unknown_required_count=unknown,
                ideal_grades=sorted((grade for _, grade in graded), reverse=True)[:20],
                acceptable_sample=[],
                catalogue_sha256=oracle.sha256,
                evidence_contract="longitudinal-development-v1/raw-catalogue",
            )
            target = TargetGroundTruth(
                scenario_id=visit.task_id,
                target_id=visit.witness_id,
                catalogue_sha256=oracle.sha256,
                profile_sha256=digest(scenario.profile.model_dump()),
                hard=hard,
                soft=soft,
                ambiguity="distinguishable" if len(best) == 1 else "ambiguous",
                compatible_count=len(best),
                compatible_ids_sha256=digest(best),
                evidence=sources,
                target_title=row.get("title"),
            )
            if not require_evidence:
                visit.evidence = evidence
            compiled.append(
                CompiledVisit(customer.user_id, visit, scenario, truth, target, context)
            )
    return compiled


def load_customers(path: str | Path) -> CustomerDataset:
    return CustomerDataset.model_validate_json(Path(path).read_text())
