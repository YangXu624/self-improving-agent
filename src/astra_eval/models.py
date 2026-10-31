"""Typed records shared by the evaluation components (no behaviour, no I/O)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIELDS = ("product_type", "price", "department", "color", "material", "size", "brand")
OPS = (
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
)
SPLITS = ("learning", "development", "held_out")
KINDS = ("feasible", "underspecified", "no_valid_product")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Fact(Strict):
    """One hidden preference with the sentence a shopper would say to reveal it."""

    key: str = Field(min_length=1, max_length=40)
    kind: Literal["hard", "soft"]
    field: Literal[
        "product_type", "price", "department", "color", "material", "size", "brand"
    ]
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
    statement: str = Field(min_length=1, max_length=300)
    # Words in an assistant question that this fact answers (lexical, deterministic).
    keywords: list[str] = Field(default_factory=list, max_length=12)


class ShopperProfile(Strict):
    """Everything the simulated shopper may know. Immutable; sent on every model call."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    scenario_id: str
    persona: str = Field(max_length=300)
    facts: tuple[Fact, ...]
    opening_keys: tuple[str, ...]
    no_preference_reply: str = "I don't have a strong preference about that."

    @model_validator(mode="after")
    def keys_exist(self):
        keys = [f.key for f in self.facts]
        if len(set(keys)) != len(keys) or not set(self.opening_keys) <= set(keys):
            raise ValueError("Profile fact keys must be unique and cover the opening")
        return self

    def fact(self, key):
        return next((f for f in self.facts if f.key == key), None)


class Scenario(Strict):
    """What the runner needs to play one conversation. No ground truth lives here."""

    id: str
    split: Literal["learning", "development", "held_out"]
    kind: Literal["feasible", "underspecified", "no_valid_product"]
    family: str
    opening: str = Field(min_length=1, max_length=600)
    max_user_turns: int = Field(default=6, ge=1, le=20)
    profile: ShopperProfile


class GroundTruth(Strict):
    """Frozen scoring truth. Loaded only by the scorer and audit checks."""

    scenario_id: str
    kind: Literal["feasible", "underspecified", "no_valid_product"]
    hard: list[Fact]
    soft: list[Fact]
    acceptable_count: int = Field(ge=0)
    unknown_required_count: int = Field(ge=0)
    ideal_grades: list[int]
    acceptable_sample: list[dict[str, Any]]
    catalogue_sha256: str
    evidence_contract: str


class ShopperReply(Strict):
    """Structured simulator output; malformed output is detected, not repaired."""

    message: str = Field(min_length=1, max_length=600)
    reveals: list[str] = Field(default_factory=list, max_length=10)
    action: Literal["reply", "accept", "give_up"] = "reply"
