"""Generate and freeze experiments/longitudinal/customers.memory-sensitive.json."""

import json
from pathlib import Path

from astra_eval.customers import CatalogueOracle, CustomerDataset, validate_dataset


def build_benchmark():
    catalogue_path = Path("data/catalogue/catalog.jsonl")
    oracle = CatalogueOracle(catalogue_path)

    benchmark = {
        "schema_version": 1,
        "dataset_id": "memory-sensitive-target-benchmark-v1",
        "split": "evaluation",
        "catalogue_sha256": oracle.sha256,
        "provenance": (
            "Dedicated memory-sensitive evaluation fixture partitioned into three scenario groups: "
            "memory-helpful (historical preference applies to new task without restatement), "
            "memory-neutral (historical memory unrelated to task), and "
            "memory-conflicting (explicit preference override or gift recipient). "
            "All targets pre-registered and cryptographically frozen against the 50k catalogue."
        ),
        "customers": [
            # Group 1: Memory-Helpful (Activewear)
            {
                "user_id": "mem-helpful-activewear",
                "personality": "Direct and active; values quality workout clothing.",
                "background": "Runs and trains regularly; builds a coordinated athletic wardrobe.",
                "interests": ["running", "training", "fitness"],
                "preferences": [
                    {
                        "category": "preference",
                        "scope": "workout clothing",
                        "fact": {
                            "key": "workout_color",
                            "kind": "soft",
                            "field": "color",
                            "op": "eq",
                            "value": "Black",
                            "statement": "I generally prefer Black workout clothing.",
                            "keywords": ["color", "colour", "shade"],
                        },
                    }
                ],
                "changes": [],
                "visits": [
                    {
                        "task_id": "mem-help-active-01",
                        "sequence": 1,
                        "goal": "Buy a workout tank top.",
                        "category": "Tanks Tops",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Tanks Tops. I generally prefer Black workout clothing.",
                        "opening_keys": ["type", "workout_color"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-helpful",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Tanks Tops",
                                "statement": "I need Tanks Tops.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 40.0,
                                "statement": "My budget is under 40 USD.",
                                "keywords": ["budget", "price", "cost"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["workout_color"],
                        "witness_id": "B088LHSNW4",
                        "max_user_turns": 6,
                    },
                    {
                        "task_id": "mem-help-active-02",
                        "sequence": 2,
                        "goal": "Buy an active shirt for training.",
                        "category": "Active Shirts & Tees",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Active Shirts & Tees.",
                        "opening_keys": ["type"],
                        "disclosure": "recall_probe",
                        "scenario_group": "memory-helpful",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Active Shirts & Tees",
                                "statement": "I need Active Shirts & Tees.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 45.0,
                                "statement": "My budget is under 45 USD.",
                                "keywords": ["budget", "price", "cost"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["workout_color"],
                        "witness_id": "B08L5CNVZ6",
                        "max_user_turns": 6,
                    },
                ],
            },
            # Group 1: Memory-Helpful (Commuter Gear)
            {
                "user_id": "mem-helpful-commuter",
                "personality": "Practical commuter; keeps reliable rain gear.",
                "background": "Walks to the transit station and keeps umbrellas for home and work.",
                "interests": ["commuting", "city life"],
                "preferences": [
                    {
                        "category": "preference",
                        "scope": "umbrellas",
                        "fact": {
                            "key": "umbrella_color",
                            "kind": "soft",
                            "field": "color",
                            "op": "eq",
                            "value": "Yellow",
                            "statement": "I generally prefer Yellow umbrellas.",
                            "keywords": ["color", "colour", "shade"],
                        },
                    }
                ],
                "changes": [],
                "visits": [
                    {
                        "task_id": "mem-help-commute-01",
                        "sequence": 1,
                        "goal": "Buy a compact folding umbrella.",
                        "category": "Folding Umbrellas",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Folding Umbrellas. I generally prefer Yellow umbrellas.",
                        "opening_keys": ["type", "umbrella_color"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-helpful",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Folding Umbrellas",
                                "statement": "I need Folding Umbrellas.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 40.0,
                                "statement": "My budget is under 40 USD.",
                                "keywords": ["budget", "price", "cost"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["umbrella_color"],
                        "witness_id": "B08MDRTL62",
                        "max_user_turns": 6,
                    },
                    {
                        "task_id": "mem-help-commute-02",
                        "sequence": 2,
                        "goal": "Keep a stick umbrella at work.",
                        "category": "Stick Umbrellas",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Stick Umbrellas.",
                        "opening_keys": ["type"],
                        "disclosure": "recall_probe",
                        "scenario_group": "memory-helpful",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Stick Umbrellas",
                                "statement": "I need Stick Umbrellas.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 50.0,
                                "statement": "My budget is under 50 USD.",
                                "keywords": ["budget", "price", "cost"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["umbrella_color"],
                        "witness_id": "B0714MVRLH",
                        "max_user_turns": 6,
                    },
                ],
            },
            # Group 2: Memory-Neutral (Traveler with Unrelated Wallet)
            {
                "user_id": "mem-neutral-traveler",
                "personality": "Frequent traveler needing specific items for upcoming trips.",
                "background": "Keeps travel gear organized; purchases items across varied departments.",
                "interests": ["travel", "organization"],
                "preferences": [
                    {
                        "category": "preference",
                        "scope": "umbrellas",
                        "fact": {
                            "key": "umbrella_color",
                            "kind": "soft",
                            "field": "color",
                            "op": "eq",
                            "value": "Yellow",
                            "statement": "I generally prefer Yellow umbrellas.",
                            "keywords": ["color", "colour", "shade"],
                        },
                    }
                ],
                "changes": [],
                "visits": [
                    {
                        "task_id": "mem-neut-travel-01",
                        "sequence": 1,
                        "goal": "Buy an umbrella for travel.",
                        "category": "Folding Umbrellas",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Folding Umbrellas. I generally prefer Yellow umbrellas.",
                        "opening_keys": ["type", "umbrella_color"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-neutral",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Folding Umbrellas",
                                "statement": "I need Folding Umbrellas.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 40.0,
                                "statement": "My budget is under 40 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["umbrella_color"],
                        "witness_id": "B08MDRTL62",
                        "max_user_turns": 6,
                    },
                    {
                        "task_id": "mem-neut-travel-02",
                        "sequence": 2,
                        "goal": "Buy a travel wallet for documents.",
                        "category": "Travel Wallets",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Travel Wallets.",
                        "opening_keys": ["type"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-neutral",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Travel Wallets",
                                "statement": "I need Travel Wallets.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 30.0,
                                "statement": "My budget is under 30 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": [],
                        "witness_id": "B010LVBVKA",
                        "max_user_turns": 6,
                    },
                ],
            },
            # Group 2: Memory-Neutral (Jewelry owner shopping for Daypack)
            {
                "user_id": "mem-neutral-daypack",
                "personality": "Casual weekend adventurer with diverse interests.",
                "background": "Enjoys outdoor day trips and casual accessories.",
                "interests": ["hiking", "accessories"],
                "preferences": [
                    {
                        "category": "preference",
                        "scope": "jewelry",
                        "fact": {
                            "key": "jewelry_color",
                            "kind": "soft",
                            "field": "color",
                            "op": "eq",
                            "value": "Silver",
                            "statement": "I generally prefer Silver necklaces.",
                            "keywords": ["color", "colour", "metal"],
                        },
                    }
                ],
                "changes": [],
                "visits": [
                    {
                        "task_id": "mem-neut-pack-01",
                        "sequence": 1,
                        "goal": "Buy a casual silver necklace.",
                        "category": "Necklaces",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Necklaces. I generally prefer Silver necklaces.",
                        "opening_keys": ["type", "jewelry_color"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-neutral",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Necklaces",
                                "statement": "I need Necklaces.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 30.0,
                                "statement": "My budget is under 30 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["jewelry_color"],
                        "witness_id": "B07CBQ79F9",
                        "max_user_turns": 6,
                    },
                    {
                        "task_id": "mem-neut-pack-02",
                        "sequence": 2,
                        "goal": "Buy a casual daypack for day trips.",
                        "category": "Casual Daypacks",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Casual Daypacks.",
                        "opening_keys": ["type"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-neutral",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Casual Daypacks",
                                "statement": "I need Casual Daypacks.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 60.0,
                                "statement": "My budget is under 60 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": [],
                        "witness_id": "B001MUKWQ4",
                        "max_user_turns": 6,
                    },
                ],
            },
            # Group 3: Memory-Conflicting (Explicit Preference Override)
            {
                "user_id": "mem-conflicting-override",
                "personality": "Style-conscious shopper updating aesthetic preferences.",
                "background": "Moving away from dark colors toward light and cream tones.",
                "interests": ["bags", "fashion accessories"],
                "preferences": [
                    {
                        "category": "preference",
                        "scope": "bags",
                        "fact": {
                            "key": "bag_color",
                            "kind": "soft",
                            "field": "color",
                            "op": "eq",
                            "value": "Black",
                            "statement": "I generally prefer Black bags.",
                            "keywords": ["color", "colour", "shade"],
                        },
                    }
                ],
                "changes": [
                    {
                        "before_sequence": 2,
                        "updates": [
                            {
                                "category": "preference",
                                "scope": "bags",
                                "fact": {
                                    "key": "bag_color",
                                    "kind": "soft",
                                    "field": "color",
                                    "op": "eq",
                                    "value": "Cream",
                                    "statement": "I now prefer Cream bags.",
                                    "keywords": ["color", "colour", "shade"],
                                },
                            }
                        ],
                        "remove_keys": [],
                        "background": "Updated bag color preference to cream.",
                    }
                ],
                "visits": [
                    {
                        "task_id": "mem-conf-override-01",
                        "sequence": 1,
                        "goal": "Buy an everyday tote bag.",
                        "category": "Totes",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Totes. I generally prefer Black bags.",
                        "opening_keys": ["type", "bag_color"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-conflicting",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Totes",
                                "statement": "I need Totes.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 60.0,
                                "statement": "My budget is under 60 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["bag_color"],
                        "witness_id": "B00GDOUL92",
                        "max_user_turns": 6,
                    },
                    {
                        "task_id": "mem-conf-override-02",
                        "sequence": 2,
                        "goal": "Buy a phone bag with updated color preference.",
                        "category": "Crossbody Bags",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Crossbody Bags. I am no longer looking for black; I now prefer Cream bags.",
                        "opening_keys": ["type", "bag_color"],
                        "disclosure": "announce_change",
                        "scenario_group": "memory-conflicting",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Crossbody Bags",
                                "statement": "I need Crossbody Bags.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "bag_color",
                                "kind": "hard",
                                "field": "color",
                                "op": "eq",
                                "value": "Cream",
                                "statement": "I now prefer Cream bags.",
                                "keywords": ["color", "colour", "shade"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 55.0,
                                "statement": "My budget is under 55 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": [],
                        "witness_id": "B096NDXZ3X",
                        "max_user_turns": 6,
                    },
                ],
            },
            # Group 3: Memory-Conflicting (Gift for Recipient with Different Preferences)
            {
                "user_id": "mem-conflicting-gift",
                "personality": "Thoughtful gift giver who separates personal preferences from recipient tastes.",
                "background": "Normally wears silver jewelry but shops for gold pieces when gifting.",
                "interests": ["jewelry", "gift giving"],
                "preferences": [
                    {
                        "category": "preference",
                        "scope": "jewelry",
                        "fact": {
                            "key": "personal_jewelry_color",
                            "kind": "soft",
                            "field": "color",
                            "op": "eq",
                            "value": "Silver",
                            "statement": "I generally prefer Silver necklaces.",
                            "keywords": ["color", "colour", "metal"],
                        },
                    }
                ],
                "changes": [],
                "visits": [
                    {
                        "task_id": "mem-conf-gift-01",
                        "sequence": 1,
                        "goal": "Buy a personal silver necklace.",
                        "category": "Necklaces",
                        "recipient": "self",
                        "evaluation_mode": "target_item",
                        "opening": "I need Necklaces. I generally prefer Silver necklaces.",
                        "opening_keys": ["type", "personal_jewelry_color"],
                        "disclosure": "progressive",
                        "scenario_group": "memory-conflicting",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Necklaces",
                                "statement": "I need Necklaces.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 30.0,
                                "statement": "My budget is under 30 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": ["personal_jewelry_color"],
                        "witness_id": "B07CBQ79F9",
                        "max_user_turns": 6,
                    },
                    {
                        "task_id": "mem-conf-gift-02",
                        "sequence": 2,
                        "goal": "Buy a gold bangle as a gift for a friend.",
                        "category": "Bangle",
                        "recipient": "gift",
                        "evaluation_mode": "target_item",
                        "opening": "I need Bangle. This is a gift for a friend. My friend prefers Gold jewelry.",
                        "opening_keys": ["type", "gift_color"],
                        "disclosure": "gift",
                        "scenario_group": "memory-conflicting",
                        "hard": [
                            {
                                "key": "type",
                                "kind": "hard",
                                "field": "product_type",
                                "op": "contains",
                                "value": "Bangle",
                                "statement": "I need Bangle.",
                                "keywords": ["type", "category"],
                            },
                            {
                                "key": "gift_color",
                                "kind": "hard",
                                "field": "color",
                                "op": "eq",
                                "value": "Gold",
                                "statement": "My friend prefers Gold jewelry.",
                                "keywords": ["color", "colour", "metal"],
                            },
                            {
                                "key": "budget",
                                "kind": "hard",
                                "field": "price",
                                "op": "lt",
                                "value": 50.0,
                                "statement": "My budget is under 50 USD.",
                                "keywords": ["budget", "price"],
                            },
                        ],
                        "soft": [],
                        "persistent_keys": [],
                        "witness_id": "B00KV7CERY",
                        "max_user_turns": 6,
                    },
                ],
            },
        ],
    }

    raw_json = json.dumps(benchmark, indent=2)
    temp_obj = CustomerDataset.model_validate_json(raw_json)

    # Compute cryptographic evidence hashes for all visits against the frozen catalogue
    compiled = validate_dataset(temp_obj, catalogue_path, require_evidence=False)
    print(
        f"Successfully compiled {len(compiled)} visits across {len(temp_obj.customers)} customers."
    )

    # Populate verified evidence in dataset
    for cust in temp_obj.customers:
        for visit in cust.visits:
            cv = next(c for c in compiled if c.visit.task_id == visit.task_id)
            visit.evidence = cv.visit.evidence
            visit.acceptable_target_ids = cv.target_truth.acceptable_target_ids

    # Serialize finalized frozen dataset
    final_json = temp_obj.model_dump_json(indent=2)
    output_path = Path("experiments/longitudinal/customers.memory-sensitive.json")
    output_path.write_text(final_json)
    print(f"Written finalized benchmark to {output_path}")

    # Re-validate with require_evidence=True
    validated = validate_dataset(
        CustomerDataset.model_validate_json(output_path.read_text()),
        catalogue_path,
        require_evidence=True,
    )
    print(
        f"Strict validation PASSED: {len(validated)} visits cryptographically verified!"
    )


if __name__ == "__main__":
    build_benchmark()
