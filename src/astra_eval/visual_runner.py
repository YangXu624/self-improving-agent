"""Visual synthetic customer evaluation runner for Streamlit Developer Console.

Enables interactive, visual evaluation of synthetic customers across visits:
- Loads benchmark fixtures (dev-expanded, memory-sensitive, dev)
- Supports single customer, individual visits, or complete visit sequences
- Executes Paired Comparison (Memory OFF vs ON), Memory ON only, or Memory OFF only
- Runs in either Offline Mock/Deterministic mode (free, instant) or Live model-driven mode
- Ensures strict ground-truth target isolation (no target leakage to agent)
- Saves and loads previous run artifacts for instant review without spending API credits
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from shopping_agent.agent import ShoppingAgent
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.runtime_config import RuntimeConfig
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore

from .customers import CustomerDataset, compile_visit
from .dialogue import DialogueRunner
from .experiment import digest
from .models import TargetGroundTruth
from .oracle import CatalogueOracle
from .scenarios import GroundTruth
from .scoring import ScoreConfig, score_session
from .simulators import ScriptedShopper, SimulatorConfig
from .target_scoring import TargetRule, target_score


@dataclass
class VisitSummary:
    task_id: str
    sequence: int
    goal: str
    evaluation_mode: str
    target_hit: bool
    turn_hit: int | None
    total_turns: int
    hard_violations: int
    model_calls: int
    searches: int
    tokens: int
    transcript: list[dict[str, str]]
    retrieved_memories: list[str]
    consolidated_memories: list[dict[str, Any]]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArmResult:
    condition: str
    total_visits: int = 0
    successful_visits: int = 0
    target_success_rate: float = 0.0
    mean_turns_to_success: float | None = None
    total_hard_violations: int = 0
    total_model_calls: int = 0
    total_searches: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0
    visits: list[VisitSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisualEvalResult:
    run_id: str
    timestamp: str
    dataset_id: str
    customer_id: str
    customer_name: str
    mode: str
    runner_type: str
    off_arm: ArmResult | None = None
    on_arm: ArmResult | None = None
    comparison: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "dataset_id": self.dataset_id,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "mode": self.mode,
            "runner_type": self.runner_type,
            "off_arm": self.off_arm.to_dict() if self.off_arm else None,
            "on_arm": self.on_arm.to_dict() if self.on_arm else None,
            "comparison": self.comparison,
        }


def find_datasets(project_root: Path) -> list[dict[str, Any]]:
    """Scan project for available synthetic customer datasets."""
    datasets_dir = project_root / "experiments/longitudinal"
    candidates = [
        (
            "customers.memory-sensitive.json",
            "Memory-Sensitive Target Benchmark (Helpful / Neutral / Conflicting)",
        ),
        (
            "customers.dev-expanded.json",
            "Expanded Longitudinal Returning Customers (10 Personas)",
        ),
        (
            "customers.dev.json",
            "Standard Longitudinal Dev Set (Alice / Bob / Carol / Dave)",
        ),
    ]
    results = []
    for filename, title in candidates:
        p = datasets_dir / filename
        if p.exists():
            try:
                data = json.loads(p.read_text())
                results.append(
                    {
                        "path": str(p),
                        "filename": filename,
                        "title": title,
                        "dataset_id": data.get("dataset_id", filename),
                        "customer_count": len(data.get("customers", [])),
                        "provenance": data.get("provenance", ""),
                    }
                )
            except (OSError, json.JSONDecodeError):
                pass
    return results


def load_dataset_customers(dataset_path: Path) -> list[dict[str, Any]]:
    """Load customer list and their visit counts from dataset JSON."""
    data = json.loads(dataset_path.read_text())
    customers = []
    for c in data.get("customers", []):
        customers.append(
            {
                "user_id": c.get("user_id"),
                "personality": c.get("personality", ""),
                "background": c.get("background", ""),
                "visit_count": len(c.get("visits", [])),
                "visits": [
                    {
                        "task_id": v.get("task_id"),
                        "sequence": v.get("sequence"),
                        "goal": v.get("goal"),
                        "category": v.get("category"),
                        "evaluation_mode": v.get("evaluation_mode", "target_item"),
                    }
                    for v in c.get("visits", [])
                ],
            }
        )
    return customers


def execute_visual_evaluation(
    dataset_path: Path,
    customer_id: str,
    visit_sequence: list[int] | None = None,
    mode: Literal["paired", "user_memory_on", "user_memory_off"] = "paired",
    runner_type: Literal["offline", "live"] = "offline",
    policy: Any = None,
    catalogue_path: Path | None = None,
    index_path: Path | None = None,
    output_dir: Path | None = None,
    config: RuntimeConfig | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> VisualEvalResult:
    """Run interactive visual evaluation for a customer and return structured comparisons."""
    cfg = config or RuntimeConfig()
    cat_path = catalogue_path or Path("data/catalogue/catalog.jsonl")
    idx_path = index_path or Path("data/index/catalogue.sqlite")
    out_dir = output_dir or Path(f"data/eval-ui/{int(time.time())}")
    out_dir.mkdir(parents=True, exist_ok=True)

    data = CustomerDataset.model_validate_json(dataset_path.read_text())
    customers_dict = {c.user_id: c for c in data.customers}
    if customer_id not in customers_dict:
        raise ValueError(f"Customer {customer_id} not found in {dataset_path.name}")

    target_customer = customers_dict[customer_id]
    tasks_all = [
        v
        for v in target_customer.visits
        if visit_sequence is None or v.sequence in visit_sequence
    ]
    tasks_all.sort(key=lambda v: v.sequence)

    # Initialize oracle and search tool
    oracle = CatalogueOracle(cat_path)
    expected_hash = file_hash(cat_path) if cat_path.exists() else data.catalogue_sha256
    search = LexicalSearch(idx_path, expected_catalogue_hash=expected_hash)

    # Simulator setup
    simulator = ScriptedShopper(SimulatorConfig(window_turns=cfg.eval_max_agent_turns))

    # Determine execution arms
    arms_to_run = []
    if mode in {"paired", "user_memory_off"}:
        arms_to_run.append(("user_memory_off", False))
    if mode in {"paired", "user_memory_on"}:
        arms_to_run.append(("user_memory_on", True))

    total_steps = len(arms_to_run) * len(tasks_all)
    current_step = 0

    results_by_arm: dict[str, ArmResult] = {}

    for arm_name, memory_enabled in arms_to_run:
        arm_dir = out_dir / arm_name
        arm_dir.mkdir(parents=True, exist_ok=True)

        store = SessionStore(arm_dir / "sessions", snapshot_format=cfg.memory_format)
        memory_store = (
            UserMemoryStore(
                arm_dir / "user-memory",
            )
            if memory_enabled
            else None
        )

        agent = ShoppingAgent(
            store,
            search,
            policy,
            max_calls=cfg.agent_max_calls,
            max_searches=cfg.agent_max_searches,
            user_memory=memory_store,
            memory_format=cfg.memory_format,
            auto_finalize=memory_enabled,
            runtime_config=cfg,
        )

        arm_res = ArmResult(condition=arm_name)
        start_arm_time = time.monotonic()

        # Run visits in strict chronological order
        for v in tasks_all:
            current_step += 1
            if progress_callback:
                progress_callback(
                    current_step / max(total_steps, 1),
                    f"[{arm_name.replace('user_memory_', '').upper()}] Visit {v.sequence}/{len(tasks_all)}: {v.goal}",
                )

            # Compile scenario and truth for this visit
            scenario, shopper_ctx, facts = compile_visit(target_customer, v)
            hard = [f for f in facts if f.kind == "hard"]
            soft = [f for f in facts if f.kind == "soft"]
            row = oracle.row(v.witness_id)
            target_title = row.get("title", "") if row else ""

            target_truth = TargetGroundTruth(
                scenario_id=v.task_id,
                target_id=v.witness_id,
                target_title=target_title,
                acceptable_target_ids=v.acceptable_target_ids,
                catalogue_sha256=oracle.sha256,
                profile_sha256=digest(scenario.profile.model_dump()),
                hard=hard,
                soft=soft,
                ambiguity="distinguishable",
                compatible_count=1,
                compatible_ids_sha256=digest([v.witness_id]),
            )
            pref_truth = GroundTruth(
                scenario_id=v.task_id,
                kind="feasible",
                hard=hard,
                soft=soft,
                acceptable_count=1,
                unknown_required_count=0,
                ideal_grades=[],
                acceptable_sample=[],
                catalogue_sha256=oracle.sha256,
                evidence_contract="visual-runner",
            )

            v_dir = arm_dir / f"visit-{v.sequence}"
            v_dir.mkdir(parents=True, exist_ok=True)

            runner = DialogueRunner(
                agent,
                store,
                simulator,
                run_id=f"vis-{v.sequence}",
            )

            is_target = v.evaluation_mode == "target_item"
            forbidden = (
                (target_truth.target_title,) if target_truth.target_title else ()
            )

            # Target rule strictly isolates target product IDs from agent
            target_rule = (
                TargetRule(
                    target_truth.target_id,
                    cfg.candidate_retrieval_limit,
                    acceptable_target_ids=tuple(target_truth.acceptable_target_ids)
                    if target_truth.acceptable_target_ids
                    else None,
                )
                if is_target
                else None
            )

            record = runner.run(
                scenario,
                condition=arm_name,
                transcript_path=v_dir / "transcript.jsonl",
                forbidden=forbidden,
                target_rule=target_rule,
                turn_limit=cfg.eval_max_agent_turns,
                session_user_id=customer_id,
                shopper_context=shopper_ctx,
            )

            # Score session
            score = (
                target_score(
                    record,
                    target_truth,
                    oracle,
                    ScoreConfig(),
                    max_turns=cfg.eval_max_agent_turns,
                )
                if is_target
                else score_session(
                    record,
                    pref_truth,
                    oracle,
                    ScoreConfig(),
                    max_turns=cfg.eval_max_agent_turns,
                )
            )

            # Turn metrics
            hit = record.target_hit
            is_hit = (
                hit is not None
                and hit.get("turn") is not None
                and hit["turn"] <= cfg.eval_max_agent_turns
            )
            turn_hit = hit.get("turn") if hit else None

            # Memory audit
            retrieved_mems = []
            consolidated_mems = []
            with store.open(customer_id, record.astra_session_id) as s:
                for e in s.events:
                    if e.type == "user_memory_injection":
                        retrieved_mems.extend(e.payload.get("injected", []))
                    elif e.type == "session_finalized":
                        consolidated_mems.extend(
                            e.payload.get("operations_applied", [])
                        )

            # Transcript
            transcript_rows = []
            for t in record.turns:
                transcript_rows.append({"role": "user", "message": t.message})
                action_text = f"[{t.action}] {t.closure or ''}"
                if t.recommended_ids:
                    action_text += f" (Recommended {len(t.recommended_ids)} product(s): {', '.join(t.recommended_ids)})"
                transcript_rows.append({"role": "assistant", "message": action_text})

            hard_viols = score.get("violations", {}).get("hard_fail", 0)
            calls_sum = sum(t.model_calls for t in record.turns)
            searches_sum = sum(t.searches for t in record.turns)
            tok_sum = sum(
                t.usage.get("prompt_tokens", 0) + t.usage.get("completion_tokens", 0)
                for t in record.turns
            )

            arm_res.visits.append(
                VisitSummary(
                    task_id=v.task_id,
                    sequence=v.sequence,
                    goal=v.goal,
                    evaluation_mode=v.evaluation_mode,
                    target_hit=bool(is_hit),
                    turn_hit=turn_hit if is_hit else None,
                    total_turns=len(record.turns),
                    hard_violations=hard_viols,
                    model_calls=calls_sum,
                    searches=searches_sum,
                    tokens=tok_sum,
                    transcript=transcript_rows,
                    retrieved_memories=retrieved_mems,
                    consolidated_memories=consolidated_mems,
                    status=record.termination,
                )
            )

        # Aggregate arm metrics
        arm_res.total_visits = len(arm_res.visits)
        arm_res.successful_visits = sum(1 for v in arm_res.visits if v.target_hit)
        arm_res.target_success_rate = (
            round(arm_res.successful_visits / arm_res.total_visits, 4)
            if arm_res.total_visits
            else 0.0
        )
        successful_turns = [
            v.turn_hit for v in arm_res.visits if v.turn_hit is not None
        ]
        arm_res.mean_turns_to_success = (
            round(sum(successful_turns) / len(successful_turns), 2)
            if successful_turns
            else None
        )
        arm_res.total_hard_violations = sum(v.hard_violations for v in arm_res.visits)
        arm_res.total_model_calls = sum(v.model_calls for v in arm_res.visits)
        arm_res.total_searches = sum(v.searches for v in arm_res.visits)
        arm_res.total_tokens = sum(v.tokens for v in arm_res.visits)
        arm_res.total_duration_seconds = round(time.monotonic() - start_arm_time, 2)

        results_by_arm[arm_name] = arm_res

    # Build comparison summary if paired
    comparison = {}
    off = results_by_arm.get("user_memory_off")
    on = results_by_arm.get("user_memory_on")
    if off and on:
        delta_rate = round((on.target_success_rate - off.target_success_rate) * 100, 1)
        mean_off = off.mean_turns_to_success or 0.0
        mean_on = on.mean_turns_to_success or 0.0
        turn_delta = round(mean_on - mean_off, 2)
        comparison = {
            "success_rate_off": f"{off.target_success_rate * 100:.1f}%",
            "success_rate_on": f"{on.target_success_rate * 100:.1f}%",
            "success_rate_delta": f"{'+' if delta_rate >= 0 else ''}{delta_rate}%",
            "mean_turns_off": f"{mean_off:.1f}" if off.mean_turns_to_success else "N/A",
            "mean_turns_on": f"{mean_on:.1f}" if on.mean_turns_to_success else "N/A",
            "mean_turns_delta": f"{'+' if turn_delta >= 0 else ''}{turn_delta}",
            "hard_violations_off": off.total_hard_violations,
            "hard_violations_on": on.total_hard_violations,
            "searches_off": off.total_searches,
            "searches_on": on.total_searches,
            "model_calls_off": off.total_model_calls,
            "model_calls_on": on.total_model_calls,
        }

    run_result = VisualEvalResult(
        run_id=out_dir.name,
        timestamp=datetime.now(UTC).isoformat(),
        dataset_id=data.dataset_id,
        customer_id=customer_id,
        customer_name=target_customer.personality[:60],
        mode=mode,
        runner_type=runner_type,
        off_arm=off,
        on_arm=on,
        comparison=comparison,
    )

    # Save artifact
    (out_dir / "eval_result.json").write_text(
        json.dumps(run_result.to_dict(), indent=2)
    )
    return run_result


def list_saved_runs(runs_root: Path) -> list[dict[str, Any]]:
    """Scan eval-ui output folder for completed evaluations."""
    if not runs_root.exists():
        return []
    runs = []
    for d in sorted(runs_root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        res_file = d / "eval_result.json"
        if res_file.exists():
            try:
                data = json.loads(res_file.read_text())
                runs.append(
                    {
                        "run_id": data.get("run_id", d.name),
                        "timestamp": data.get("timestamp", ""),
                        "customer_id": data.get("customer_id", ""),
                        "dataset_id": data.get("dataset_id", ""),
                        "mode": data.get("mode", ""),
                        "comparison": data.get("comparison", {}),
                        "path": str(res_file),
                    }
                )
            except (OSError, json.JSONDecodeError):
                pass
    return runs
