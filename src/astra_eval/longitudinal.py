"""Thin returning-customer orchestration over the existing dialogue runner and scorers."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from shopping_agent.agent import ShoppingAgent
from shopping_agent.context import PROMPT_VERSION, USER_MEMORY_PROMPT_VERSION
from shopping_agent.memory_views import COMPACT_PROMPT_VERSION, FORMATS
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore

from .consistency import ConsistencyConfig
from .customers import load_customers, validate_dataset
from .dialogue import DialogueRunner
from .disclosed_compliance import compliance
from .experiment import (
    ModelCallBudget,
    append_line,
    digest,
    git_state,
    policy_descriptor,
)
from .oracle import CatalogueOracle
from .scoring import ScoreConfig, score_session
from .simulators import SimulatorConfig
from .target_scoring import TargetRule, target_score

CONDITIONS = (("user_memory_off", False), ("user_memory_on", True))


@dataclass(frozen=True)
class LongitudinalConfig:
    customers: Path
    catalogue: Path
    index: Path
    output: Path
    limit_customers: int | None = None
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    score: ScoreConfig = field(default_factory=lambda: ScoreConfig(headline_k=5))
    agent_max_calls: int = 3
    agent_max_searches: int = 2
    session_max_model_calls: int = 18
    max_model_calls: int | None = None
    memory_format: str = "legacy"

    def __post_init__(self):
        if self.memory_format not in FORMATS:
            raise ValueError("Unknown memory format")
        if not 1 <= self.agent_max_calls <= 6 or not 1 <= self.agent_max_searches <= 3:
            raise ValueError("Invalid agent bounds")
        if self.session_max_model_calls < self.agent_max_calls:
            raise ValueError("Session call cap must permit at least one bounded turn")
        for value in (
            self.limit_customers,
            self.max_model_calls,
            self.score.turn_budget,
        ):
            if value is not None and value < 1:
                raise ValueError("Limits must be positive")
        if (
            not 1 <= self.score.headline_k <= 5
            or self.score.headline_k not in self.score.k_values
        ):
            raise ValueError("Primary K must be 1..5 and included in k_values")


def _prepare(config: LongitudinalConfig):
    data = load_customers(config.customers)
    compiled = validate_dataset(data, config.catalogue)
    customers = data.customers[: config.limit_customers]
    selected = {c.user_id for c in customers}
    tasks = [t for t in compiled if t.customer_id in selected]
    if config.score.turn_budget and any(
        config.score.turn_budget > t.visit.max_user_turns for t in tasks
    ):
        raise ValueError("Turn budget exceeds a frozen visit's maximum")
    tool = LexicalSearch(config.index, expected_catalogue_hash=data.catalogue_sha256)
    tool.close()
    return data, customers, tasks


def _plan(config, customers, tasks):
    return {
        "evaluation_mode": "longitudinal_user_memory",
        "memory_format": config.memory_format,
        "development_only": True,
        "customers": len(customers),
        "sessions": len(tasks) * len(CONDITIONS),
        "conditions": [
            {"name": name, "user_memory": enabled, "procedural_memory": False}
            for name, enabled in CONDITIONS
        ],
        "customer_order": [c.user_id for c in customers],
        "condition_order": {
            c.user_id: [name for name, _ in CONDITIONS[i % 2 :] + CONDITIONS[: i % 2]]
            for i, c in enumerate(customers)
        },
        "tasks": [
            {
                "customer_id": t.customer_id,
                "task_id": t.visit.task_id,
                "sequence": t.visit.sequence,
                "category": t.visit.category,
                "mode": t.visit.evaluation_mode,
            }
            for t in tasks
        ],
        "worst_case_agent_model_calls": 2
        * sum(
            min(
                (config.score.turn_budget or t.visit.max_user_turns)
                * config.agent_max_calls,
                config.session_max_model_calls,
            )
            for t in tasks
        ),
        "max_model_calls": config.max_model_calls,
    }


def plan_longitudinal(config: LongitudinalConfig) -> dict:
    """Validate frozen inputs and index; no model, output directory or user store is opened."""
    _data, customers, tasks = _prepare(config)
    return _plan(config, customers, tasks)


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def run_longitudinal(config: LongitudinalConfig, *, simulator, policy) -> dict:
    """New run only. Conditions experience the same visit order with isolated learned state."""
    from .longitudinal_report import memory_audit, write_longitudinal_report

    if config.output.exists():
        raise FileExistsError(
            "Use a new output directory; timeline runs are not resumed"
        )
    data, customers, tasks = _prepare(config)
    if simulator.config != config.simulator:
        raise ValueError(
            "Actual shopper settings must match recorded simulator settings"
        )
    plan = _plan(config, customers, tasks)
    shared = {
        "evaluation_mode": "longitudinal_user_memory",
        "dataset_id": data.dataset_id,
        "customers_sha256": file_hash(config.customers),
        "catalogue_sha256": data.catalogue_sha256,
        "index_sha256": file_hash(config.index),
        "compiled_truth_sha256": digest(
            [
                {
                    "preference": t.preference_truth.model_dump(),
                    "target": t.target_truth.model_dump(),
                }
                for t in tasks
            ]
        ),
        "decision_policy": {
            **policy_descriptor(policy),
            "prompt_version": COMPACT_PROMPT_VERSION
            if config.memory_format == "compact"
            else PROMPT_VERSION,
        },
        "prompt_versions": {
            name: COMPACT_PROMPT_VERSION
            if config.memory_format == "compact"
            else USER_MEMORY_PROMPT_VERSION
            if enabled
            else PROMPT_VERSION
            for name, enabled in CONDITIONS
        },
        "simulator": asdict(config.simulator),
        "score": asdict(config.score),
        "agent_max_calls": config.agent_max_calls,
        "agent_max_searches": config.agent_max_searches,
        "session_max_model_calls": config.session_max_model_calls,
        "plan": plan,
    }
    shared_hash = digest(shared)
    config.output.mkdir(parents=True)
    (config.output / "customers.frozen.json").write_bytes(config.customers.read_bytes())
    write_json(
        config.output / "run.json",
        {
            "shared_config": shared,
            "shared_config_sha256": shared_hash,
            "code": git_state(),
        },
    )
    budget = (
        ModelCallBudget(config.max_model_calls)
        if config.max_model_calls is not None
        else None
    )
    oracle = CatalogueOracle(config.catalogue)
    search = LexicalSearch(config.index, expected_catalogue_hash=data.catalogue_sha256)
    rows, blocked, stopped = [], [], None
    try:
        stores, memories, agents = {}, {}, {}
        for name, enabled in CONDITIONS:
            root = config.output / "astra" / name
            stores[name] = SessionStore(
                root / "sessions", snapshot_format=config.memory_format
            )
            memories[name] = UserMemoryStore(root / "user-memory") if enabled else None
            agents[name] = ShoppingAgent(
                stores[name],
                search,
                policy,
                max_calls=config.agent_max_calls,
                max_searches=config.agent_max_searches,
                user_memory=memories[name],
                experience=None,
                memory_format=config.memory_format,
            )
        for customer_index, customer in enumerate(customers):
            order = CONDITIONS[customer_index % 2 :] + CONDITIONS[: customer_index % 2]
            visits = [t for t in tasks if t.customer_id == customer.user_id]
            for name, _enabled in order:
                for task_index, task in enumerate(visits):
                    directory = (
                        config.output
                        / "sessions"
                        / name
                        / customer.user_id
                        / task.visit.task_id
                    )
                    directory.mkdir(parents=True)
                    max_turns = config.score.turn_budget or task.visit.max_user_turns
                    runner = DialogueRunner(
                        agents[name],
                        stores[name],
                        simulator,
                        run_id=shared_hash[:8],
                        consistency=ConsistencyConfig(),
                        budget=budget,
                    )
                    record = runner.run(
                        task.scenario,
                        condition=name,
                        transcript_path=directory / "transcript.jsonl",
                        forbidden=(task.target_truth.target_title,)
                        if task.target_truth.target_title
                        else (),
                        target_rule=TargetRule(
                            task.target_truth.target_id, config.score.headline_k
                        )
                        if task.visit.evaluation_mode == "target_item"
                        else None,
                        session_max_calls=config.session_max_model_calls,
                        turn_limit=max_turns,
                        session_user_id=customer.user_id,
                        shopper_context=task.shopper_context,
                    )
                    suitability = score_session(
                        record,
                        task.preference_truth,
                        oracle,
                        config.score,
                        max_turns=max_turns,
                    )
                    score = (
                        target_score(
                            record,
                            task.target_truth,
                            oracle,
                            config.score,
                            max_turns=max_turns,
                        )
                        if task.visit.evaluation_mode == "target_item"
                        else suitability
                    )
                    disclosed = compliance(record, oracle)
                    first_success = score.get(
                        "first_success_turn", score.get("turns_to_first_success")
                    )
                    prefix = [
                        turn
                        for turn in record.turns
                        if first_success is not None and turn.turn <= first_success
                    ]
                    with stores[name].open(
                        customer.user_id, record.astra_session_id
                    ) as session:
                        audit = memory_audit(session.events, customer, task, oracle)
                    row = {
                        "customer_id": customer.user_id,
                        "user_id": record.user_id,
                        "task_id": task.visit.task_id,
                        "sequence": task.visit.sequence,
                        "astra_session_id": record.astra_session_id,
                        "condition": name,
                        "evaluation_mode": task.visit.evaluation_mode,
                        "recipient": task.visit.recipient,
                        "termination": record.termination,
                        "turn_budget": max_turns,
                        "efficiency_to_first_success": {
                            "searches": sum(t.searches for t in prefix),
                            "clarifications": sum(
                                t.action == "CLARIFY" for t in prefix
                            ),
                        }
                        if first_success is not None
                        else None,
                        "shared_config_sha256": shared_hash,
                        "session_dir": str(directory.relative_to(config.output)),
                        "score": score,
                        "suitability": suitability,
                        "disclosed_requirement_compliance": disclosed,
                        "user_memory": audit,
                        "token_accounting": {
                            "simulator_failure_may_have_unreported_attempts": record.termination
                            in {"simulator_error", "simulator_failure"}
                        },
                    }
                    write_json(
                        directory / "trace.json",
                        {
                            "customer_id": customer.user_id,
                            "task_id": task.visit.task_id,
                            "sequence": task.visit.sequence,
                            "condition": name,
                            "astra_session_id": record.astra_session_id,
                            "termination": record.termination,
                            "turns": [asdict(t) for t in record.turns],
                            "user_memory": audit,
                        },
                    )
                    write_json(directory / "result.json", row)
                    append_line(config.output / "results.jsonl", row)
                    rows.append(row)
                    if record.termination == "run_budget_exhausted":
                        stopped = "run_model_call_budget_exhausted"
                    if (
                        not score.get("valid", False)
                        or record.termination == "agent_exception"
                    ):
                        blocked.extend(
                            {
                                "customer_id": customer.user_id,
                                "condition": name,
                                "task_id": remaining.visit.task_id,
                                "reason": "prior_session_invalid",
                            }
                            for remaining in visits[task_index + 1 :]
                        )
                        break
                if stopped:
                    break
            if stopped:
                break
    finally:
        search.close()
    summary = {
        "sessions": len(rows),
        "planned_sessions": plan["sessions"],
        "model_calls_used": budget.used
        if budget
        else sum(r["score"]["resources"]["model_calls"] for r in rows),
        "stopped_early": stopped,
        "blocked_visits": blocked,
        "shared_config_sha256": shared_hash,
    }
    write_json(config.output / "summary.json", summary)
    write_longitudinal_report(config.output)
    return summary
