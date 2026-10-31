"""Command line: generate scenarios, check Ollama, run, report, show a transcript.

Ollama is needed only by `check-simulator` and `run --simulator ollama`. DeepSeek (paid)
is used only by `run --live`, which also requires --max-model-calls. Without --live, `run`
prints a plan and contacts nothing.
"""

import argparse
import json
import sys
from pathlib import Path

from .consistency import ConsistencyConfig
from .experiment import Condition, ExperimentConfig, plan, run_experiment
from .report import show_transcript, write_report
from .scenarios import generate, save
from .scoring import ScoreConfig
from .simulators import OllamaShopper, ScriptedShopper, SimulatorConfig, check_ollama


def add_sim_args(p):
    p.add_argument("--sim-model")
    p.add_argument("--sim-url")
    p.add_argument("--sim-temperature", type=float)
    p.add_argument("--sim-seed", type=int)
    p.add_argument("--sim-num-ctx", type=int)
    p.add_argument("--sim-max-tokens", type=int)
    p.add_argument("--sim-timeout", type=float)
    p.add_argument("--window-turns", type=int)


def sim_config(args):
    return SimulatorConfig.from_env(
        model=args.sim_model,
        url=args.sim_url,
        temperature=args.sim_temperature,
        seed=args.sim_seed,
        num_ctx=args.sim_num_ctx,
        max_tokens=args.sim_max_tokens,
        timeout=args.sim_timeout,
        window_turns=args.window_turns,
    )


def parser():
    p = argparse.ArgumentParser(prog="python -m astra_eval", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser(
        "generate", help="create a frozen scenario set from the catalogue"
    )
    g.add_argument("--catalogue", default="data/catalogue/catalog.jsonl")
    g.add_argument("--output", required=True)
    g.add_argument("--seed", type=int, default=20261101)
    g.add_argument("--learning", type=int, default=12)
    g.add_argument("--development", type=int, default=8)
    g.add_argument("--held-out", type=int, default=24)
    g.add_argument("--max-user-turns", type=int, default=6)
    c = sub.add_parser(
        "check-simulator", help="verify Ollama, the model and structured output"
    )
    add_sim_args(c)
    r = sub.add_parser("run", help="run scenarios (prints a plan unless --live)")
    r.add_argument("--scenarios", required=True)
    r.add_argument("--catalogue", default="data/catalogue/catalog.jsonl")
    r.add_argument("--index", default="data/index/catalogue.sqlite")
    r.add_argument("--output", required=True)
    r.add_argument("--split", choices=("learning", "development", "held_out"))
    r.add_argument("--limit", type=int)
    r.add_argument("--simulator", choices=("ollama", "scripted"), default="ollama")
    r.add_argument("--live", action="store_true", help="make paid DeepSeek requests")
    r.add_argument(
        "--max-model-calls",
        type=int,
        help="hard cap on DeepSeek calls (required with --live)",
    )
    r.add_argument("--env-file", default=".env")
    r.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    r.add_argument("--headline-k", type=int, default=3)
    r.add_argument("--turn-budget", type=int)
    r.add_argument("--price-input-per-million", type=float)
    r.add_argument("--price-output-per-million", type=float)
    add_sim_args(r)
    rp = sub.add_parser(
        "report", help="aggregate a finished run into report.json/report.md"
    )
    rp.add_argument("run_dir")
    s = sub.add_parser("show", help="print one transcript")
    s.add_argument("run_dir")
    s.add_argument("scenario_id")
    s.add_argument("--condition")
    s.add_argument(
        "--debug-scenarios", help="also print hidden profile/ground truth (debug only)"
    )
    return p


def main(argv=None):
    try:
        return run_command(parser().parse_args(argv))
    except ValueError as error:  # bad option values: report plainly, spend nothing
        print(f"error: {error}", file=sys.stderr)
        return 2


def run_command(args):
    if args.command == "generate":
        per_split = {
            "learning": args.learning,
            "development": args.development,
            "held_out": args.held_out,
        }
        scenarios, truths, manifest = generate(
            args.catalogue, args.seed, per_split, max_user_turns=args.max_user_turns
        )
        print(
            json.dumps(
                save(args.output, scenarios, truths, manifest), indent=2, sort_keys=True
            )
        )
        return 0
    if args.command == "check-simulator":
        report = check_ollama(sim_config(args))
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["probe_ok"] else 1
    if args.command == "report":
        write_report(args.run_dir)
        print((Path(args.run_dir) / "report.md").read_text(encoding="utf-8"))
        return 0
    if args.command == "show":
        print(
            show_transcript(
                args.run_dir, args.scenario_id, args.condition, args.debug_scenarios
            )
        )
        return 0
    config = ExperimentConfig(
        scenarios_dir=Path(args.scenarios),
        catalogue=Path(args.catalogue),
        index=Path(args.index),
        output=Path(args.output),
        split=args.split,
        limit=args.limit,
        conditions=(Condition(),),
        simulator=sim_config(args),
        score=ScoreConfig(
            k_values=tuple(args.k),
            headline_k=args.headline_k,
            turn_budget=args.turn_budget,
            price_input_per_million=args.price_input_per_million,
            price_output_per_million=args.price_output_per_million,
        ),
        consistency=ConsistencyConfig(),
        max_model_calls=args.max_model_calls,
    )
    summary = plan(config)
    print(json.dumps({"plan": summary}, indent=2, sort_keys=True))
    if not args.live:
        print(
            "Dry run: nothing was contacted. Add --live --max-model-calls N to run with DeepSeek."
        )
        return 0
    if not args.max_model_calls:
        print("--live requires --max-model-calls", file=sys.stderr)
        return 2
    if summary["worst_case_agent_model_calls"] > args.max_model_calls:
        print(
            "Warning: the cap is below the worst case; the run may stop early.",
            file=sys.stderr,
        )
    if args.simulator == "ollama":
        # Free check first: never start paying DeepSeek if the simulator cannot answer.
        probe = check_ollama(config.simulator)
        if not probe["probe_ok"]:
            print(
                "Simulator check failed; nothing was sent to DeepSeek:", file=sys.stderr
            )
            for problem in probe["problems"]:
                print(f"  - {problem}", file=sys.stderr)
            return 1
    from shopping_agent.provider import DeepSeekPolicy

    policy = DeepSeekPolicy.from_env_file(args.env_file)
    simulator = (
        OllamaShopper(config.simulator)
        if args.simulator == "ollama"
        else ScriptedShopper(config.simulator)
    )
    result = run_experiment(config, simulator=simulator, policy=policy)
    write_report(config.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"Report: {config.output / 'report.md'}")
    return 0
