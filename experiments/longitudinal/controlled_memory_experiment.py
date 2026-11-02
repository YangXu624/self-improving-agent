"""Controlled live cross-session memory experiment using real DeepSeek Flash.

Demonstrates whether ASTRA can learn a preference in Visit 1, remember it across
sessions, and use it to improve decisions in Visit 2 under identical customer input.
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time

from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy
from astra_eval.oracle import CatalogueOracle
from shopping_agent.agent import ShoppingAgent
from shopping_agent.provider import DeepSeekPolicy
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore


def get_action_type(resp: dict) -> str:
    if not isinstance(resp, dict):
        return ""
    act = resp.get("action")
    if isinstance(act, str):
        return act
    if isinstance(act, dict):
        return act.get("type", "")
    return ""


def run_experiment(
    root: Path,
    *,
    prior_ledger: Path,
    incremental_cap: Decimal = Decimal("0.25"),
    env_file: str = ".env",
) -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    catalogue_path = Path("data/catalogue/catalog.jsonl")
    index_path = Path("data/index/catalogue.sqlite")
    if not catalogue_path.exists() or not index_path.exists():
        raise FileNotFoundError("Catalogue or index file not found")

    cat_hash = file_hash(catalogue_path)
    search = LexicalSearch(index_path, expected_catalogue_hash=cat_hash)
    oracle = CatalogueOracle(catalogue_path)

    user_id = "dev-activewear"
    v1_session_dir = root / "sessions_visit1"
    v1_mem_dir = root / "user-memory"
    mem_store = UserMemoryStore(v1_mem_dir, bypass_semantic_validation=True)

    # Check if Visit 1 is already completed in root
    v1_already_done = False
    v1_ledger_file = root / "api-cost.jsonl"
    if v1_session_dir.exists() and (v1_mem_dir / "79896dcac7912dba269e1b381eb8f07be8560e60e27f287e9cf8ddf2d9ad848b" / "profile.md").exists():
        v1_already_done = True
        print("=== VISIT 1 already completed in root. Reusing Visit 1 session and memory ===")

    if v1_already_done:
        lines = [l.strip() for l in v1_ledger_file.read_text().splitlines() if l.strip()]
        last_rec = json.loads(lines[-1])
        prior_accounted = Decimal(str(last_rec["accounted_usd"]))
        # Original prior ledger baseline was from prior_ledger
        orig_lines = [l.strip() for l in prior_ledger.read_text().splitlines() if l.strip()]
        orig_prior = Decimal(str(json.loads(orig_lines[-1])["accounted_usd"]))
        ceiling = orig_prior + incremental_cap
        ledger_path = root / "api-cost-v2.jsonl"
        budget = ApiCostBudget(ledger_path, ceiling=ceiling, prior=prior_accounted)
    else:
        lines = [l.strip() for l in prior_ledger.read_text().splitlines() if l.strip()]
        if not lines:
            raise ValueError("Prior ledger is empty")
        last_record = json.loads(lines[-1])
        prior_accounted = Decimal(str(last_record["accounted_usd"]))
        ceiling = prior_accounted + incremental_cap
        ledger_path = root / "api-cost.jsonl"
        budget = ApiCostBudget(ledger_path, ceiling=ceiling, prior=prior_accounted)

    base_policy = DeepSeekPolicy.from_env_file(env_file)
    if base_policy.model != "deepseek-flash":
        raise ValueError(f"Unexpected model: {base_policy.model}")
    policy = BudgetedPolicy(base_policy, budget)

    results = {
        "experiment_root": str(root),
        "prior_accounted_usd": str(prior_accounted),
        "ceiling_usd": str(ceiling),
        "incremental_cap_usd": str(incremental_cap),
        "visit1": {},
        "visit2_off": {},
        "visit2_on": {},
    }

    # =========================================================================
    # VISIT 1 — Establish memory
    # =========================================================================
    if not v1_already_done:
        print("=== STARTING VISIT 1 (Establish Memory) ===")
        v1_msg = "I'm looking for workout clothes. I generally prefer black workout clothing."
        store_v1 = SessionStore(root / "sessions_visit1")
        agent_v1 = ShoppingAgent(
            store_v1,
            search,
            policy,
            max_calls=4,
            max_searches=2,
            user_memory=mem_store,
        )
        sid_v1 = store_v1.create(user_id)
        resp_v1 = agent_v1.turn(user_id, sid_v1, v1_msg)

        profile_v1 = mem_store.read(user_id)
        records_v1 = [r.model_dump() for r in profile_v1.records]
        results["visit1"] = {
            "session_id": sid_v1,
            "customer_message": v1_msg,
            "response": resp_v1,
            "revision": profile_v1.revision,
            "persisted_records": records_v1,
        }
        with store_v1.open(user_id, sid_v1) as s:
            results["visit1"]["events"] = [e.model_dump() for e in s.events]
    else:
        # Load existing Visit 1 data
        store_v1 = SessionStore(root / "sessions_visit1")
        # Find session ID
        sids = [p.name for p in (root / "sessions_visit1").iterdir() if p.is_dir()]
        sid_v1 = sids[0]
        profile_v1 = mem_store.read(user_id)
        records_v1 = [r.model_dump() for r in profile_v1.records]
        with store_v1.open(user_id, sid_v1) as s:
            events_v1 = [e.model_dump() for e in s.events]
        results["visit1"] = {
            "session_id": sid_v1,
            "customer_message": "I'm looking for workout clothes. I generally prefer black workout clothing.",
            "response": {"action": "RESPOND"},
            "revision": profile_v1.revision,
            "persisted_records": records_v1,
            "events": events_v1,
        }

    print(f"Visit 1 complete. Persisted records count: {len(records_v1)}")
    if records_v1:
        print(f"Persisted record: {json.dumps(records_v1[0], indent=2)}")
    else:
        print("FATAL: No memory persisted in Visit 1!")
        write_summary(root, results, budget, oracle)
        return results

    # =========================================================================
    # VISIT 2 — Memory OFF
    # =========================================================================
    print("\n=== STARTING VISIT 2 (Memory OFF) ===")
    v2_msg1 = "I'm looking for a workout shirt under $45. What would you recommend?"
    store_v2_off = SessionStore(root / "sessions_visit2_off")
    agent_v2_off = ShoppingAgent(
        store_v2_off,
        search,
        policy,
        max_calls=4,
        max_searches=2,
        user_memory=None,
    )
    sid_v2_off = store_v2_off.create(user_id)
    turns_off = []
    resp_off_1 = agent_v2_off.turn(user_id, sid_v2_off, v2_msg1)
    turns_off.append({"turn": 1, "user": v2_msg1, "response": resp_off_1})
    print(f"Turn 1 complete. Action: {get_action_type(resp_off_1)}")

    if get_action_type(resp_off_1) == "RESPOND" and not resp_off_1.get("products"):
        v2_msg2 = "No specific brand or sleeve length, just a comfortable workout shirt under $45."
        print(f"Agent asked clarification: {resp_off_1.get('message')}")
        print("Sending neutral follow-up...")
        resp_off_2 = agent_v2_off.turn(user_id, sid_v2_off, v2_msg2)
        turns_off.append({"turn": 2, "user": v2_msg2, "response": resp_off_2})
        print(f"Turn 2 complete. Action: {get_action_type(resp_off_2)}")

    with store_v2_off.open(user_id, sid_v2_off) as s:
        results["visit2_off"] = {
            "session_id": sid_v2_off,
            "turns": turns_off,
            "events": [e.model_dump() for e in s.events],
        }

    # =========================================================================
    # VISIT 2 — Memory ON
    # =========================================================================
    print("\n=== STARTING VISIT 2 (Memory ON) ===")
    store_v2_on = SessionStore(root / "sessions_visit2_on")
    agent_v2_on = ShoppingAgent(
        store_v2_on,
        search,
        policy,
        max_calls=4,
        max_searches=2,
        user_memory=mem_store,
    )
    sid_v2_on = store_v2_on.create(user_id)
    turns_on = []
    resp_on_1 = agent_v2_on.turn(user_id, sid_v2_on, v2_msg1)
    turns_on.append({"turn": 1, "user": v2_msg1, "response": resp_on_1})
    print(f"Turn 1 complete. Action: {get_action_type(resp_on_1)}")

    if get_action_type(resp_on_1) == "RESPOND" and not resp_on_1.get("products"):
        v2_msg2 = "No specific brand or sleeve length, just a comfortable workout shirt under $45."
        print(f"Agent asked clarification: {resp_on_1.get('message')}")
        print("Sending neutral follow-up...")
        resp_on_2 = agent_v2_on.turn(user_id, sid_v2_on, v2_msg2)
        turns_on.append({"turn": 2, "user": v2_msg2, "response": resp_on_2})
        print(f"Turn 2 complete. Action: {get_action_type(resp_on_2)}")

    with store_v2_on.open(user_id, sid_v2_on) as s:
        results["visit2_on"] = {
            "session_id": sid_v2_on,
            "turns": turns_on,
            "events": [e.model_dump() for e in s.events],
        }

    # =========================================================================
    # Analysis and Metrics
    # =========================================================================
    write_summary(root, results, budget, oracle)
    return results


def extract_session_details(session_data, oracle: CatalogueOracle):
    events = session_data.get("events", [])
    model_requests = [e for e in events if e.get("type") == "model_request"]
    decisions = [e for e in events if e.get("type") == "decision_validated"]
    actions = [e for e in events if e.get("type") == "action_executed"]
    memory_selections = [e for e in events if e.get("type") == "user_memory_selection"]
    memory_injections = [e for e in events if e.get("type") == "user_memory_injection"]
    memory_updates = [e for e in events if e.get("type") == "user_memory_updated"]

    searches = []
    for d in decisions:
        action = d.get("payload", {}).get("action", {})
        if action.get("type") == "SEARCH":
            searches.append(action)

    recommended_ids = []
    for d in decisions:
        action = d.get("payload", {}).get("action", {})
        if action.get("type") == "RECOMMEND":
            for pid in action.get("product_ids", []):
                if pid and pid not in recommended_ids:
                    recommended_ids.append(pid)
    for e in events:
        if e.get("type") == "recommendation":
            for pid in e.get("payload", {}).get("product_ids", []):
                if pid and pid not in recommended_ids:
                    recommended_ids.append(pid)

    products = []
    for pid in recommended_ids:
        row = oracle.row(pid)
        if row:
            products.append({
                "id": pid,
                "title": row.get("title"),
                "price": row.get("price"),
                "color": (row.get("details") or {}).get("Color") or (row.get("details") or {}).get("Colour"),
                "brand": (row.get("details") or {}).get("Brand"),
                "categories": row.get("categories"),
            })
        else:
            products.append({"id": pid, "not_in_catalogue": True})

    return {
        "model_calls": len(model_requests),
        "searches": searches,
        "recommendations": products,
        "memory_selections": [m.get("payload") for m in memory_selections],
        "memory_injections": [m.get("payload") for m in memory_injections],
        "memory_updates": [m.get("payload") for m in memory_updates],
        "final_action": decisions[-1].get("payload", {}).get("action") if decisions else None,
    }


def write_summary(root: Path, results: dict, budget: ApiCostBudget, oracle: CatalogueOracle):
    analysis = {
        "visit1": extract_session_details(results["visit1"], oracle) if results.get("visit1") else {},
        "visit2_off": extract_session_details(results["visit2_off"], oracle) if results.get("visit2_off") else {},
        "visit2_on": extract_session_details(results["visit2_on"], oracle) if results.get("visit2_on") else {},
        "cost_settled_usd": str(budget.total),
        "incremental_spent_usd": str(budget.total - Decimal(results["prior_accounted_usd"])),
    }
    results["analysis"] = analysis
    (root / "results.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults successfully written to {root / 'results.json'}")
    print(f"Total accounted cost: ${budget.total}")
    print(f"Incremental cost this run: ${analysis['incremental_spent_usd']}")


if __name__ == "__main__":
    root_dir = Path("data/eval/canaries/v3-controlled-memory-20261102")
    prior_ledger_file = Path("data/eval/canaries/v3-paired-bypass-20261102/paired.api-cost.jsonl")
    run_experiment(root_dir, prior_ledger=prior_ledger_file)
