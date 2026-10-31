"""Experiment runner: scenarios x conditions, identical infrastructure, saved traces.

Conditions are the seam for the later memory comparison. Memory OFF is the only condition
implemented; `ExperienceSnapshot` and `AgentFactory` fix the interface so frozen learned
experience can be plugged in later without touching the harness. Every condition runs the
same scenarios with the same simulator settings, agent bounds, budgets and scoring; this is
asserted by one hashed `shared_config` recorded with every result.
"""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from shopping_agent.agent import ShoppingAgent
from shopping_agent.experience import ExperienceSnapshot
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.sessions import SessionStore

from . import VERSION
from .consistency import ConsistencyConfig
from .dialogue import DialogueRunner
from .oracle import CatalogueOracle
from .scenarios import load_ground_truth, load_scenarios
from .scoring import ScoreConfig, score_session
from .simulators import SimulatorConfig

MAX_CONSECUTIVE_PROVIDER_FAILURES = 3
MIN_FORBIDDEN_TITLE = 15


@dataclass(frozen=True)
class Condition:
    name: str = "memory_off"
    experience: ExperienceSnapshot | None = None


AgentFactory = Callable[..., object]


def default_agent_factory(condition, store, search, policy, *, max_calls, max_searches):
    """The unchanged ASTRA baseline. Experience memory does not exist yet."""
    if condition.experience is not None:
        raise NotImplementedError(
            "Memory ON needs an agent factory that injects the frozen snapshot; "
            "experience memory is not implemented in this harness."
        )
    return ShoppingAgent(
        store, search, policy, max_calls=max_calls, max_searches=max_searches
    )


def experiential_agent_factory(
    condition, store, search, policy, *, max_calls, max_searches
):
    """ASTRA agent factory with experiential memory snapshot support."""
    return ShoppingAgent(
        store,
        search,
        policy,
        max_calls=max_calls,
        max_searches=max_searches,
        experience=condition.experience,
    )


class ModelCallBudget:
    """Hard cap on agent model calls across the whole run (the paid resource)."""

    def __init__(self, max_calls):
        self.max_calls, self.used = max_calls, 0

    def allow(self, calls):
        return self.used + calls <= self.max_calls

    def charge(self, calls):
        self.used += calls


@dataclass(frozen=True)
class ExperimentConfig:
    scenarios_dir: Path
    catalogue: Path
    index: Path
    output: Path
    split: str | None = None
    limit: int | None = None
    conditions: tuple = (Condition(),)
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    consistency: ConsistencyConfig = field(default_factory=ConsistencyConfig)
    consistency_retries: int = 1
    agent_max_calls: int = 3
    agent_max_searches: int = 2
    max_model_calls: int | None = None
    user_id: str = "eval-shopper"
    evaluation_mode: str = "preference"
    session_max_model_calls: int | None = None

    def __post_init__(self):
        if self.evaluation_mode not in {"preference", "target_item"}:
            raise ValueError("Unknown evaluation mode")
        if self.evaluation_mode == "target_item":
            if not 1 <= self.score.headline_k <= 5:
                raise ValueError("Target K must be in 1..5")
            if self.session_max_model_calls is None:
                raise ValueError(
                    "Target runs require an identical per-session model-call cap"
                )
        if (
            self.session_max_model_calls is not None
            and self.session_max_model_calls < 1
        ):
            raise ValueError("Per-session model-call cap must be positive")
        # Zero or negative values must not silently mean "unset" (a limit of 0 once meant all).
        for name, value in (
            ("limit", self.limit),
            ("max_model_calls", self.max_model_calls),
            ("turn_budget", self.score.turn_budget),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1 when given")
        if not self.score.k_values or min(self.score.k_values) < 1:
            raise ValueError("k_values must be positive")
        if self.score.headline_k not in self.score.k_values:
            raise ValueError("headline_k must be one of k_values")


def policy_descriptor(policy):
    """Identity of the decision policy for audit; never includes credentials."""
    from shopping_agent.context import PROMPT_VERSION

    return {
        "class": type(policy).__name__,
        "model": getattr(policy, "model", None),
        "prompt_version": PROMPT_VERSION,
    }


def shared_config(
    config,
    scenario_ids,
    truth_sha,
    scenarios_sha,
    catalogue_sha,
    policy=None,
    index_sha=None,
):
    """Everything that must be identical across conditions."""
    return {
        **(
            {
                "evaluation_mode": config.evaluation_mode,
                "session_max_model_calls": config.session_max_model_calls,
            }
            if config.evaluation_mode == "target_item"
            else {}
        ),
        "harness": VERSION,
        "scenario_ids": scenario_ids,
        "scenarios_sha256": scenarios_sha,
        "ground_truth_sha256": truth_sha,
        "catalogue_sha256": catalogue_sha,
        "index_sha256": index_sha,
        "decision_policy": policy_descriptor(policy) if policy is not None else None,
        "simulator": asdict(config.simulator),
        "score": asdict(config.score),
        "consistency": asdict(config.consistency),
        "consistency_retries": config.consistency_retries,
        "agent_max_calls": config.agent_max_calls,
        "agent_max_searches": config.agent_max_searches,
        "max_model_calls": config.max_model_calls,
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def git_state():
    try:
        root = Path(__file__).resolve().parents[2]
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
        return {"commit": head, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def check_budget(config, scenarios):
    """A turn budget longer than the conversation would be silently meaningless."""
    longest = max((s.max_user_turns for s in scenarios), default=0)
    if config.score.turn_budget and config.score.turn_budget > min(
        (s.max_user_turns for s in scenarios), default=0
    ):
        raise ValueError(
            f"turn_budget {config.score.turn_budget} exceeds a scenario's max_user_turns "
            f"(shortest {min((s.max_user_turns for s in scenarios), default=0)}, longest {longest})"
        )


def plan(config):
    """What a run would do and its worst-case agent model calls (no model is contacted)."""
    scenarios, manifest = load_scenarios(config.scenarios_dir, config.split)
    if manifest.get("evaluation_mode", "preference") != config.evaluation_mode:
        raise ValueError("Run mode must match frozen benchmark mode")
    if config.limit:
        scenarios = scenarios[: config.limit]
    check_budget(config, scenarios)
    sessions = len(scenarios) * len(config.conditions)
    worst = (
        sum(s.max_user_turns for s in scenarios)
        * len(config.conditions)
        * config.agent_max_calls
    )
    if config.evaluation_mode == "target_item":
        worst = sum(
            min(
                (config.score.turn_budget or s.max_user_turns) * config.agent_max_calls,
                config.session_max_model_calls,
            )
            for s in scenarios
        ) * len(config.conditions)
    return {
        "scenarios": len(scenarios),
        "conditions": [c.name for c in config.conditions],
        "sessions": sessions,
        "worst_case_agent_model_calls": worst,
        "max_model_calls": config.max_model_calls,
    }


def append_line(path, value):
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def run_experiment(config, *, simulator, policy, agent_factory=default_agent_factory):
    """Run every scenario under every condition into a NEW output directory."""
    output = Path(config.output)
    if output.exists():
        raise FileExistsError(
            "Use a new output directory; interrupted runs are not resumed"
        )
    scenarios, manifest = load_scenarios(config.scenarios_dir, config.split)
    if config.limit:
        scenarios = scenarios[: config.limit]
    if not scenarios:
        raise ValueError("No scenarios selected")
    from .target_scenarios import digest, load_target_truth
    from .target_scoring import TargetRule, target_score

    mode = manifest.get("evaluation_mode", "preference")
    if mode != config.evaluation_mode:
        raise ValueError("Run mode must match frozen benchmark mode")
    truths = (
        load_target_truth(config.scenarios_dir)
        if mode == "target_item"
        else load_ground_truth(config.scenarios_dir)
    )
    if mode == "target_item":
        for scenario in scenarios:
            truth = truths[scenario.id]
            if truth.profile_sha256 != digest(scenario.profile.model_dump()):
                raise ValueError("Target profile hash mismatch")
            if truth.catalogue_sha256 != manifest["catalogue_sha256"]:
                raise ValueError("Target truth catalogue hash mismatch")
    oracle = CatalogueOracle(config.catalogue)
    if oracle.sha256 != manifest["catalogue_sha256"]:
        raise ValueError("Catalogue does not match the scenario set")
    if mode == "target_item":
        from .oracle import judge, raw_facts

        for scenario in scenarios:
            truth = truths[scenario.id]
            if [f.model_dump() for f in scenario.profile.facts] != [
                f.model_dump() for f in truth.hard + truth.soft
            ]:
                raise ValueError("Target profile and truth requirements disagree")
            if truth.target_id is not None:
                row = oracle.row(truth.target_id)
                if (
                    row is None
                    or judge(raw_facts(row), truth.hard, truth.soft)["hard"] != "pass"
                ):
                    raise ValueError(
                        "Target does not satisfy its documented requirements"
                    )
            elif any(
                judge(raw_facts(row), truth.hard, truth.soft)["hard"] == "pass"
                for row in oracle.rows()
            ):
                raise ValueError("No-target task has a verified compatible product")
    names = [c.name for c in config.conditions]
    if len(set(names)) != len(names):
        raise ValueError("Condition names must be unique")
    if config.score.headline_k not in config.score.k_values:
        raise ValueError("headline_k must be one of k_values")
    check_budget(config, scenarios)
    shared = shared_config(
        config,
        [s.id for s in scenarios],
        manifest["ground_truth_sha256"],
        manifest["scenarios_sha256"],
        oracle.sha256,
        policy,
        file_hash(config.index),
    )
    shared_sha = digest(shared)
    output.mkdir(parents=True)
    (output / "run.json").write_text(
        json.dumps(
            {
                "shared_config": shared,
                "shared_config_sha256": shared_sha,
                "conditions": [
                    {
                        "name": c.name,
                        "experience_sha256": c.experience.sha256
                        if c.experience
                        else None,
                    }
                    for c in config.conditions
                ],
                "git": git_state(),
                "split": config.split,
                "limit": config.limit,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    results, provider_failures, stopped = [], 0, None
    budget = ModelCallBudget(config.max_model_calls) if config.max_model_calls else None
    search = LexicalSearch(
        config.index, expected_catalogue_hash=file_hash(config.catalogue)
    )
    try:
        stores = {
            c.name: SessionStore(output / "astra" / c.name) for c in config.conditions
        }
        agents = {
            c.name: agent_factory(
                c,
                stores[c.name],
                search,
                policy,
                max_calls=config.agent_max_calls,
                max_searches=config.agent_max_searches,
            )
            for c in config.conditions
        }
        for index, scenario in enumerate(scenarios):
            truth = truths[scenario.id]
            forbidden = (
                ([truth.target_title] if truth.target_title else [])
                if mode == "target_item"
                else [
                    s["title"]
                    for s in truth.acceptable_sample
                    if len(s["title"]) >= MIN_FORBIDDEN_TITLE
                ]
            )
            # Rotate condition order per scenario so neither condition always runs first.
            order = (
                config.conditions[index % len(config.conditions) :]
                + config.conditions[: index % len(config.conditions)]
            )
            for condition in order:
                directory = output / "sessions" / f"{scenario.id}__{condition.name}"
                directory.mkdir(parents=True)
                runner = DialogueRunner(
                    agents[condition.name],
                    stores[condition.name],
                    simulator,
                    run_id=shared_sha[:8],
                    user_id=config.user_id,
                    consistency=config.consistency,
                    consistency_retries=config.consistency_retries,
                    budget=budget,
                )
                record = runner.run(
                    scenario,
                    condition=condition.name,
                    transcript_path=directory / "transcript.jsonl",
                    forbidden=forbidden,
                    **(
                        {
                            "target_rule": TargetRule(
                                truth.target_id, config.score.headline_k
                            ),
                            "session_max_calls": config.session_max_model_calls,
                            "turn_limit": config.score.turn_budget
                            or scenario.max_user_turns,
                        }
                        if mode == "target_item"
                        else {}
                    ),
                )
                score = (target_score if mode == "target_item" else score_session)(
                    record,
                    truth,
                    oracle,
                    config.score,
                    max_turns=(config.score.turn_budget or scenario.max_user_turns)
                    if mode == "target_item"
                    else scenario.max_user_turns,
                )
                result = {
                    "scenario": {
                        "id": scenario.id,
                        "split": scenario.split,
                        "kind": scenario.kind,
                        "family": scenario.family,
                    },
                    "condition": condition.name,
                    "shared_config_sha256": shared_sha,
                    "astra_session_id": record.astra_session_id,
                    "user_id": record.user_id,
                    "session_dir": str(directory.relative_to(output)),
                    "experience": {
                        "retrieved": record.retrieved_experience,
                        "injected": record.injected_experience,
                        "applied": record.applied_experience,
                    },
                    "score": score,
                }
                (directory / "result.json").write_text(
                    json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n",
                    encoding="utf-8",
                )
                append_line(output / "results.jsonl", result)
                results.append(result)
                provider_failures = (
                    provider_failures + 1
                    if record.termination == "provider_error"
                    else 0
                )
                if record.termination == "run_budget_exhausted":
                    stopped = "run_model_call_budget_exhausted"
                elif provider_failures >= MAX_CONSECUTIVE_PROVIDER_FAILURES:
                    stopped = "consecutive_provider_failures"
                if stopped:
                    break
            if stopped:
                break
    finally:
        search.close()
    summary = {
        "sessions": len(results),
        "planned_sessions": len(scenarios) * len(config.conditions),
        "stopped_early": stopped,
        "model_calls_used": budget.used if budget else None,
        "shared_config_sha256": shared_sha,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
