"""Closed model proposals; neither queries nor state edits are executable code."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FieldName = Literal[
    "product_type",
    "recipient",
    "use_case",
    "price",
    "department",
    "color",
    "material",
    "size",
    "brand",
    "rating",
    "rating_count",
    "keyword",
]
NUMERIC = {"price", "rating", "rating_count"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class RequirementSpec(Strict):
    field: FieldName
    op: Literal[
        "eq",
        "neq",
        "lt",
        "lte",
        "gt",
        "gte",
        "contains",
        "not_contains",
        "in",
        "not_in",
    ]
    value: str | float | list[str]
    strength: Literal["hard", "soft"] = "hard"
    quote: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def compatible_types(self):
        if self.field in NUMERIC:
            if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
                raise ValueError("Numeric requirement needs a finite number")
            if self.value < 0 or self.op not in {"eq", "neq", "lt", "lte", "gt", "gte"}:
                raise ValueError("Unsupported numeric requirement")
            if self.field == "rating" and self.value > 5:
                raise ValueError("Ratings range from zero to five")
            if self.field == "rating_count" and not float(self.value).is_integer():
                raise ValueError("Rating count must be integral")
        elif self.op in {"in", "not_in"}:
            if (
                not isinstance(self.value, list)
                or not 1 <= len(self.value) <= 8
                or any(not v.strip() or len(v) > 120 for v in self.value)
            ):
                raise ValueError("Text alternatives need one to eight short values")
        elif (
            not isinstance(self.value, str)
            or not self.value.strip()
            or len(self.value) > 120
            or self.op not in {"eq", "neq", "contains", "not_contains"}
        ):
            raise ValueError("Unsupported text requirement")
        if self.field in {"recipient", "use_case"} and self.strength != "soft":
            raise ValueError("Recipient and use case are contextual soft information")
        return self


class Requirement(RequirementSpec):
    id: str
    status: Literal["active", "superseded", "retracted"] = "active"
    source_event_id: str
    created_version: int = Field(ge=1)
    replaces_id: str | None = None


class ShoppingState(Strict):
    schema_version: Literal[1] = 1
    version: int = Field(default=0, ge=0)
    goal_epoch: int = Field(default=0, ge=0)
    requirements: list[Requirement] = Field(default_factory=list, max_length=200)
    conflicts: list[str] = Field(default_factory=list)


class StateUpdate(Strict):
    op: Literal["ADD", "REPLACE", "RETRACT", "NEW_GOAL"]
    requirement: RequirementSpec | None = None
    target_id: str | None = None
    quote: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def shape(self):
        if (self.op in {"ADD", "REPLACE"}) != (self.requirement is not None):
            raise ValueError(
                "ADD/REPLACE require a requirement; other edits cannot include one"
            )
        if (self.op in {"REPLACE", "RETRACT"}) != (self.target_id is not None):
            raise ValueError("Only REPLACE/RETRACT reference a target")
        return self


class Clarify(Strict):
    type: Literal["CLARIFY"]
    question: str = Field(min_length=1, max_length=1000)
    attribute: FieldName | Literal["currency", "width", "product_subtype"]


class Search(Strict):
    type: Literal["SEARCH"]
    query: str = Field(max_length=500)
    mode: Literal["all", "any"] = "all"
    limit: int = Field(default=10, ge=1, le=20)


class Recommend(Strict):
    type: Literal["RECOMMEND"]
    search_id: str
    product_ids: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("Recommendations must be distinct")
        return self


class Respond(Strict):
    type: Literal["RESPOND"]
    message: str = Field(min_length=1, max_length=1500)


Action = Annotated[Clarify | Search | Recommend | Respond, Field(discriminator="type")]


class Decision(Strict):
    based_on_state_version: int = Field(ge=0)
    updates: list[StateUpdate] = Field(default_factory=list, max_length=12)
    action: Action
    reason: str = Field(min_length=1, max_length=600)


class Event(Strict):
    schema_version: Literal[1] = 1
    event_id: str
    seq: int = Field(ge=1)
    state_version: int = Field(default=0, ge=0)
    session_id: str
    user_id: str
    timestamp: str
    turn_id: str | None
    type: str
    payload: dict[str, Any]
