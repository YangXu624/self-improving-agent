"""Reversible card representation profiles; ranking and authoritative facts stay outside."""

import json
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class CardProfile:
    limit: int | None
    shared: bool


PROFILES = {
    "baseline": CardProfile(None, False),
    "v3_k10": CardProfile(10, False),
    "v3_k5": CardProfile(5, False),
    "shared_k10": CardProfile(10, True),
    "shared_k5": CardProfile(5, True),
}
EXPERIMENT_PROFILES = ("v3_k10", "v3_k5", "shared_k10", "shared_k5")


def profile_for(name: str) -> CardProfile:
    if name not in PROFILES:
        raise ValueError("Unknown card profile")
    return PROFILES[name]


def share_metadata(cards: list[dict]) -> dict:
    """Intern full repeated categories/source maps after visible-card selection."""
    paths, sources, path_keys, source_keys, packed = {}, {}, {}, {}, []

    def intern(value, table, keys, prefix):
        signature = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        if signature not in keys:
            ident = prefix + str(len(table))
            keys[signature] = ident
            table[ident] = deepcopy(value)
        return keys[signature]

    for card in cards:
        value = deepcopy(card)
        if "categories" in value:
            value["category_ref"] = intern(
                value.pop("categories"), paths, path_keys, "c"
            )
        if "sources" in value:
            value["source_ref"] = intern(
                value.pop("sources"), sources, source_keys, "s"
            )
        packed.append(value)
    return {
        "card_encoding": "shared-metadata-v1",
        "category_paths": paths,
        "fact_sources": sources,
        "candidates": packed,
    }


def semantic_cards(view: dict) -> list[dict]:
    """Recover exactly the v3 evidence objects; never fabricate missing/null fields."""
    cards = deepcopy(view["candidates"])
    if "card_encoding" not in view:
        return cards
    if view["card_encoding"] != "shared-metadata-v1":
        raise ValueError("Unsupported card encoding")
    for card in cards:
        if "category_ref" in card:
            if "categories" in card:
                raise ValueError("Ambiguous category encoding")
            card["categories"] = deepcopy(
                view["category_paths"][card.pop("category_ref")]
            )
        if "source_ref" in card:
            if "sources" in card:
                raise ValueError("Ambiguous source encoding")
            card["sources"] = deepcopy(view["fact_sources"][card.pop("source_ref")])
    return cards
