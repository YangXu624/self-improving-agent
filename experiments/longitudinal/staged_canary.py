"""Approval-gated canary orchestration. Default actions are offline plans, never paid calls.

Stage 1 uses the existing session runner for two OFF-only visits; Stage 2 delegates to the
unchanged longitudinal runner. No production policy, prompt, retrieval or scoring replacement.
"""

import argparse
import copy
import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from astra_eval.api_budget import ApiCostBudget, BudgetedPolicy
from astra_eval.customers import load_customers, validate_dataset
from astra_eval.dialogue import DialogueRunner
from astra_eval.disclosed_compliance import compliance
from astra_eval.experiment import ModelCallBudget
from astra_eval.longitudinal import (
    LongitudinalConfig,
    failure_scope,
    plan_longitudinal,
    run_longitudinal,
)
from astra_eval.oracle import CatalogueOracle
from astra_eval.scoring import ScoreConfig, score_session
from astra_eval.shopper_providers import (
    JsonShopperProvider,
    RequestJournal,
    V3Config,
    claude_key,
    claude_model,
)
from astra_eval.shopper_v3 import AutonomousShopper
from shopping_agent.agent import ShoppingAgent
from shopping_agent.provider import DeepSeekPolicy
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.sessions import SessionStore

BASELINE = Decimal("0.127290224")
INCREMENT = Decimal("1")
GLOBAL_CEILING = Decimal("10")
STAGE1_ALLOWANCE = Decimal("0.4")
PRIOR_LEDGER = Path(
    "data/eval/longitudinal/claude-sonnet55-readiness-20261101/live-24.api-cost.jsonl"
)
MODELS = {"shopper": "claude-sonnet-5-5", "astra": "deepseek-flash"}


def write(path: Path, value: dict) -> None:
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    )


def fingerprint() -> str:
    paths = sorted(Path("src").rglob("*.py")) + [Path(__file__)]
    return hashlib.sha256(
        b"".join(
            str(p.resolve().relative_to(Path.cwd())).encode() + p.read_bytes()
            for p in paths
        )
    ).hexdigest()


def subset(source: dict, names: tuple[str, ...], count: int) -> dict:
    selected = copy.deepcopy(source)
    by_id = {c["user_id"]: c for c in source["customers"]}
    selected["customers"] = []
    for name in names:
        customer = copy.deepcopy(by_id[name])
        if len(customer["visits"]) < count:
            raise ValueError("Insufficient frozen visits")
        customer["visits"] = customer["visits"][:count]
        customer["changes"] = [
            c for c in customer.get("changes", []) if c["before_sequence"] <= count
        ]
        selected["customers"].append(customer)
    return selected


def prepare(
    root: Path,
    source: Path,
    catalogue: Path,
    index: Path,
    *,
    stage1_ids=("dev-activewear", "dev-jewelry-simple"),
    memory_id="dev-activewear",
) -> dict:
    root, source, catalogue, index = map(Path, (root, source, catalogue, index))
    data = json.loads(source.read_text())
    validate_dataset(load_customers(source), catalogue)
    tool = LexicalSearch(index, expected_catalogue_hash=data["catalogue_sha256"])
    tool.close()
    # The previous combined ledger already includes old uncertainty and prior smoke/pilot costs.
    previous = PRIOR_LEDGER
    if (
        Decimal(json.loads(previous.read_text().splitlines()[-1])["accounted_usd"])
        != BASELINE
    ):
        raise ValueError("Prior accounting changed; re-review the allowance")
    root.mkdir(parents=True, exist_ok=False)
    for stage, names, count in [("stage1", stage1_ids, 1), ("stage2", (memory_id,), 2)]:
        write(root / f"{stage}.customers.json", subset(data, names, count))
        validate_dataset(load_customers(root / f"{stage}.customers.json"), catalogue)
    manifest = {
        "status": "prepared_not_authorized",
        "prior_ledger": str(previous),
        "prior_ledger_sha256": file_hash(previous),
        "reviewed_pr28_commit": subprocess.check_output(
            ["git", "rev-parse", "origin/fix/conversation-reliability"], text=True
        ).strip(),
        "source": str(source),
        "catalogue": str(catalogue),
        "index": str(index),
        "source_sha256": file_hash(source),
        "catalogue_sha256": file_hash(catalogue),
        "index_sha256": file_hash(index),
        "subsets": {
            stage: file_hash(root / f"{stage}.customers.json")
            for stage in ("stage1", "stage2")
        },
        "runtime_sha256": fingerprint(),
        "models": MODELS,
        "prior_accounted_usd": str(BASELINE),
        "incremental_cap_usd": str(INCREMENT),
        "absolute_cap_usd": str(min(GLOBAL_CEILING, BASELINE + INCREMENT)),
        "stage1_cap_usd": str(min(GLOBAL_CEILING, BASELINE + STAGE1_ALLOWANCE)),
        "stage1_sessions": 2,
        "stage2_sessions": 4,
        "limits": {
            "stage1_agent_calls": 36,
            "stage1_shopper_attempts": 24,
            "stage2_agent_calls": 72,
            "stage2_shopper_attempts": 48,
            "turns": 6,
            "session_agent_calls": 18,
        },
    }
    write(root / "manifest.json", manifest)
    return manifest


PAIRED_DEFAULT_PRIOR_LEDGER = Path(
    "data/eval/canaries/v3-staged-20261101/stage2.api-cost.jsonl"
)
PAIRED_INCREMENT = Decimal("0.50")


def prepare_paired(
    root: Path,
    source: Path,
    catalogue: Path,
    index: Path,
    *,
    prior_ledger: Path = PAIRED_DEFAULT_PRIOR_LEDGER,
    incremental_cap: Decimal = PAIRED_INCREMENT,
    customer_id: str = "dev-activewear",
    visits: int = 2,
) -> dict:
    root, source, catalogue, index, prior_ledger = map(
        Path, (root, source, catalogue, index, prior_ledger)
    )
    data = json.loads(source.read_text())
    validate_dataset(load_customers(source), catalogue)
    tool = LexicalSearch(index, expected_catalogue_hash=data["catalogue_sha256"])
    tool.close()
    lines = [
        line.strip() for line in prior_ledger.read_text().splitlines() if line.strip()
    ]
    if not lines:
        raise ValueError("Prior ledger is empty")
    last_entry = json.loads(lines[-1])
    prior_accounted = Decimal(str(last_entry["accounted_usd"]))
    root.mkdir(parents=True, exist_ok=False)
    customer_subset = subset(data, (customer_id,), visits)
    write(root / "paired.customers.json", customer_subset)
    validate_dataset(load_customers(root / "paired.customers.json"), catalogue)
    absolute_cap = min(GLOBAL_CEILING, prior_accounted + incremental_cap)
    manifest = {
        "status": "prepared_not_authorized",
        "action": "paired",
        "prior_ledger": str(prior_ledger),
        "prior_ledger_sha256": file_hash(prior_ledger),
        "source": str(source),
        "catalogue": str(catalogue),
        "index": str(index),
        "source_sha256": file_hash(source),
        "catalogue_sha256": file_hash(catalogue),
        "index_sha256": file_hash(index),
        "subsets": {"paired": file_hash(root / "paired.customers.json")},
        "runtime_sha256": fingerprint(),
        "models": MODELS,
        "prior_accounted_usd": str(prior_accounted),
        "incremental_cap_usd": str(incremental_cap),
        "absolute_cap_usd": str(absolute_cap),
        "planned_sessions": visits * 2,
        "limits": {
            "paired_agent_calls": 72,
            "paired_shopper_attempts": 48,
            "turns": 6,
            "session_agent_calls": 18,
        },
    }
    write(root / "manifest.json", manifest)
    return manifest


def validated(root: Path) -> dict:
    root = Path(root)
    m = json.loads((root / "manifest.json").read_text())
    if file_hash(Path(m["prior_ledger"])) != m["prior_ledger_sha256"]:
        raise ValueError("Prior accounting changed after preparation")
    if fingerprint() != m["runtime_sha256"]:
        raise ValueError("Runtime changed after preparation; do not run this snapshot")
    for field in ("source", "catalogue", "index"):
        if file_hash(Path(m[field])) != m[field + "_sha256"]:
            raise ValueError("Frozen input changed")
    for stage, expected_hash in m["subsets"].items():
        if file_hash(root / f"{stage}.customers.json") != expected_hash:
            raise ValueError("Frozen subset changed")
    return m


def stage1_end(root: Path, review_path: Path) -> Decimal:
    """Carry actual accounting forward, never reset a dollar allowance at the stage boundary."""
    root = Path(root)
    report = json.loads((root / "stage1/summary.json").read_text())
    review = json.loads(Path(review_path).read_text())
    if (
        review.get("decision") != "pass"
        or review.get("summary_sha256") != file_hash(root / "stage1/summary.json")
        or review.get("ledger_sha256") != file_hash(root / "stage1.api-cost.jsonl")
    ):
        raise ValueError("Stage 1 requires an evidence-bound passing review")
    if (
        report["systemic_stop"]
        or len(report["results"]) != 2
        or not all(
            r["score"]["valid"]
            and r["score"]["termination"]
            in {"accepted", "gave_up", "max_turns", "search_stalled"}
            for r in report["results"]
        )
    ):
        raise ValueError("Stage 1 failed reliability prerequisites")
    ledger = [
        json.loads(x) for x in (root / "stage1.api-cost.jsonl").read_text().splitlines()
    ]
    if any(
        x["kind"] in {"usage_unknown_reservation_retained", "request_denied"}
        for x in ledger
    ) or sum(x["kind"] == "request_reserved" for x in ledger) != sum(
        x["kind"] == "usage_settled" for x in ledger
    ):
        raise ValueError("Stage 1 accounting is incomplete or stopped")
    m = validated(root)
    final = Decimal(ledger[-1]["accounted_usd"])
    if (
        ledger[0]["kind"] != "budget_open"
        or Decimal(ledger[0]["prior_allowance_usd"])
        != Decimal(m["prior_accounted_usd"])
        or Decimal(ledger[0]["ceiling_usd"]) != Decimal(m["stage1_cap_usd"])
        or not Decimal(m["prior_accounted_usd"]) <= final < Decimal(m["stage1_cap_usd"])
    ):
        raise ValueError("Stage 1 ledger does not match the frozen budget")
    return final


def config(
    root: Path,
    stage: str,
    prior: Decimal,
    manifest: dict,
    *,
    bypass_semantic_validation: bool = False,
) -> LongitudinalConfig:
    return LongitudinalConfig(
        customers=Path(root) / f"{stage}.customers.json",
        catalogue=Path(manifest["catalogue"]),
        index=Path(manifest["index"]),
        output=Path(root) / stage,
        simulator=V3Config(
            provider="claude",
            model=MODELS["shopper"],
            max_tokens=512,
            num_ctx=4096,
            seed=7,
        ),
        score=ScoreConfig(headline_k=5, turn_budget=6),
        max_model_calls=manifest["limits"][f"{stage}_agent_calls"],
        max_shopper_calls=manifest["limits"][f"{stage}_shopper_attempts"],
        max_cost_usd=float(
            manifest["stage1_cap_usd"]
            if stage == "stage1"
            else manifest["absolute_cap_usd"]
        ),
        prior_cost_usd=float(prior),
        memory_format="compact",
        execution_order="off_then_on",
        stop_on_error=True,
        max_consecutive_simulator_failures=3,
        bypass_semantic_validation=bypass_semantic_validation,
    )


def providers(
    cfg: LongitudinalConfig, env_file: str
) -> tuple[AutonomousShopper, BudgetedPolicy]:
    """Called only after explicit --live. Constructors are network-free; requests are bounded."""
    if cfg.output.exists():
        raise ValueError("Fresh stage output required; no restart or resume")
    if claude_model(Path(env_file), os.environ) != cfg.simulator.model:
        raise ValueError("Configured shopper model differs from frozen plan")
    base = DeepSeekPolicy.from_env_file(env_file)
    if base.model != MODELS["astra"]:
        raise ValueError("Configured ASTRA model differs from frozen plan")
    key = claude_key(Path(env_file), os.environ)
    budget = ApiCostBudget(
        cfg.output.with_name(cfg.output.name + ".api-cost.jsonl"),
        cfg.max_cost_usd,
        cfg.prior_cost_usd,
    )
    journal = RequestJournal(
        cfg.output.with_name(cfg.output.name + ".shopper-v3.jsonl"),
        cfg.max_shopper_calls,
    )
    return AutonomousShopper(
        JsonShopperProvider(cfg.simulator, journal, api_key=key, cost_budget=budget)
    ), BudgetedPolicy(base, budget)


def reliability(
    cfg: LongitudinalConfig, shopper: AutonomousShopper, policy: BudgetedPolicy
) -> dict:
    """Exactly one visit each, OFF only, same existing loop and unchanged scorer."""
    if cfg.output.exists():
        raise ValueError("Fresh stage output required")
    if shopper.config != cfg.simulator:
        raise ValueError("Actual shopper configuration differs from the frozen plan")
    if (
        shopper.history
        or shopper.identity is not None
        or shopper.provider.journal.calls
    ):
        raise ValueError("Fresh shopper history and journal required")
    budget = shopper.provider.cost_budget
    if (
        shopper.provider.journal.max_calls != cfg.max_shopper_calls
        or budget is None
        or getattr(policy, "budget", None) is not budget
        or float(budget.ceiling) != cfg.max_cost_usd
        or float(budget.total) != cfg.prior_cost_usd
    ):
        raise ValueError(
            "Both providers must share the recorded fresh cost budget and caps"
        )
    data = load_customers(cfg.customers)
    tasks = validate_dataset(data, cfg.catalogue)
    if (
        len(tasks) != 2
        or len({t.customer_id for t in tasks}) != 2
        or any(
            t.visit.sequence != 1 or t.visit.evaluation_mode != "preference"
            for t in tasks
        )
    ):
        raise ValueError(
            "Reliability canary requires two independent first preference visits"
        )
    tool = LexicalSearch(cfg.index, expected_catalogue_hash=data.catalogue_sha256)
    cfg.output.mkdir(parents=True)
    (cfg.output / "customers.frozen.json").write_bytes(cfg.customers.read_bytes())
    write(
        cfg.output / "run.json",
        {"config": asdict(cfg), "models": MODELS, "condition": "user_memory_off"},
    )
    store = SessionStore(cfg.output / "astra/sessions", snapshot_format="compact")
    agent = ShoppingAgent(
        store,
        tool,
        policy,
        user_memory=None,
        experience=None,
        memory_format="compact",
        max_calls=cfg.agent_max_calls,
        max_searches=cfg.agent_max_searches,
    )
    calls = ModelCallBudget(cfg.max_model_calls)
    oracle = CatalogueOracle(cfg.catalogue)
    results = []
    stop = None
    try:
        for task in tasks:
            directory = cfg.output / "sessions" / task.customer_id
            directory.mkdir(parents=True)
            record = DialogueRunner(
                agent, store, shopper, run_id="canary-stage1", budget=calls
            ).run(
                task.scenario,
                condition="user_memory_off",
                session_user_id=task.customer_id,
                shopper_context=task.shopper_context,
                transcript_path=directory / "transcript.jsonl",
                session_max_calls=18,
                turn_limit=6,
            )
            row = {
                "customer_id": task.customer_id,
                "task_id": task.visit.task_id,
                "condition": "user_memory_off",
                "score": score_session(
                    record, task.preference_truth, oracle, cfg.score, max_turns=6
                ),
                "failure_scope": failure_scope(record),
                "compliance": compliance(record, oracle),
                "session_id": record.astra_session_id,
            }
            write(directory / "record.json", asdict(record))
            write(directory / "result.json", row)
            results.append(row)
            with (cfg.output / "results.jsonl").open("a") as f:
                f.write(json.dumps(row) + "\n")
            if row["failure_scope"] == "infrastructure":
                stop = record.error or record.termination
                break
    finally:
        tool.close()
    summary = {
        "stage": "reliability",
        "results": results,
        "systemic_stop": stop,
        "stage2_authorized": False,
        "review_required": True,
        "agent_calls": calls.used,
    }
    write(cfg.output / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "stage1", "stage2", "prepare-paired", "paired"]
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("experiments/longitudinal/customers.dev-expanded.json"),
    )
    parser.add_argument(
        "--catalogue", type=Path, default=Path("data/catalogue/catalog.jsonl")
    )
    parser.add_argument(
        "--index", type=Path, default=Path("data/index/catalogue.sqlite")
    )
    parser.add_argument(
        "--prior-ledger",
        type=Path,
        default=PAIRED_DEFAULT_PRIOR_LEDGER,
    )
    parser.add_argument(
        "--incremental-cap",
        type=Decimal,
        default=PAIRED_INCREMENT,
    )
    parser.add_argument(
        "--customer-id",
        default="dev-activewear",
    )
    parser.add_argument(
        "--bypass-semantic-validation",
        action="store_true",
        default=False,
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "prepare":
        if args.live:
            raise ValueError("Prepare is offline only")
        print(
            json.dumps(
                prepare(args.root, args.source, args.catalogue, args.index), indent=2
            )
        )
        return 0
    if args.action == "prepare-paired":
        if args.live:
            raise ValueError("Prepare is offline only")
        print(
            json.dumps(
                prepare_paired(
                    args.root,
                    args.source,
                    args.catalogue,
                    args.index,
                    prior_ledger=args.prior_ledger,
                    incremental_cap=args.incremental_cap,
                    customer_id=args.customer_id,
                ),
                indent=2,
            )
        )
        return 0
    m = validated(args.root)
    provisional = args.action == "stage2" and args.review is None
    if provisional and args.live:
        raise ValueError("Live Stage 2 requires a passing Stage 1 review")
    if args.action in ("stage1", "paired") or provisional:
        prior = Decimal(m["prior_accounted_usd"])
    else:
        prior = stage1_end(args.root, args.review)
    cfg = config(
        args.root,
        args.action,
        prior,
        m,
        bypass_semantic_validation=args.bypass_semantic_validation,
    )
    if not args.live:
        plan = plan_longitudinal(cfg)
        if args.action == "stage1":
            plan.update(
                sessions=2,
                conditions=[
                    {
                        "name": "user_memory_off",
                        "user_memory": False,
                        "procedural_memory": False,
                    }
                ],
                worst_case_agent_model_calls=36,
            )
            plan["timeline_order"] = [
                v for v in plan["timeline_order"] if v["condition"] == "user_memory_off"
            ]
            plan["condition_order"] = {
                k: ["user_memory_off"] for k in plan["condition_order"]
            }
        print(
            json.dumps(
                {
                    "plan": plan,
                    "live": False,
                    "stage1_review_required": args.action == "stage2",
                    "prior_cost_provisional_until_stage1_completed": provisional,
                },
                indent=2,
            )
        )
        return 0
    shopper, policy = providers(cfg, args.env_file)
    result = (
        reliability(cfg, shopper, policy)
        if args.action == "stage1"
        else run_longitudinal(cfg, simulator=shopper, policy=policy)
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
