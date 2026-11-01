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
    g.add_argument(
        "--evaluation-mode", choices=("preference", "target_item"), default="preference"
    )
    g.add_argument(
        "--target-group",
        choices=("distinguishable", "ambiguous", "all"),
        default="distinguishable",
    )
    g.add_argument("--no-target-per-split", type=int, default=0)
    g.add_argument("--seed", type=int, default=20261101)
    g.add_argument("--learning", type=int, default=12)
    g.add_argument("--development", type=int, default=8)
    g.add_argument("--held-out", type=int, default=24)
    g.add_argument("--max-user-turns", type=int, default=6)
    audit = sub.add_parser(
        "audit-targets", help="offline target eligibility and ambiguity counts"
    )
    audit.add_argument("--catalogue", default="data/catalogue/catalog.jsonl")
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
    r.add_argument("--headline-k", type=int)
    r.add_argument(
        "--evaluation-mode", choices=("preference", "target_item"), default="preference"
    )
    r.add_argument("--session-max-model-calls", type=int)
    r.add_argument("--turn-budget", type=int)
    r.add_argument("--price-input-per-million", type=float)
    r.add_argument("--price-output-per-million", type=float)
    r.add_argument(
        "--experience-snapshot", help="path to frozen experience snapshot JSON"
    )
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
    el = sub.add_parser(
        "extract-lessons", help="extract candidate lessons from learning traces"
    )
    el.add_argument(
        "--run", required=True, help="path to learning evaluation run directory"
    )
    el.add_argument(
        "--store",
        default="data/experience/store.sqlite",
        help="path to SQLite experience store",
    )

    rl = sub.add_parser(
        "review-lessons", help="inspect and review candidate/active lessons"
    )
    rl.add_argument(
        "--store",
        default="data/experience/store.sqlite",
        help="path to SQLite experience store",
    )
    rl.add_argument(
        "--status",
        choices=("candidate", "active", "rejected", "retracted", "superseded", "all"),
        default="all",
    )
    rl.add_argument("--confirm", help="lesson ID to confirm and activate")
    rl.add_argument("--reject", help="lesson ID to reject")
    rl.add_argument("--retract", help="lesson ID to retract")
    rl.add_argument(
        "--notes", default="Human supervisor review", help="review notes or rationale"
    )

    fl = sub.add_parser(
        "freeze-lessons", help="freeze active lessons into an immutable snapshot JSON"
    )
    fl.add_argument(
        "--store",
        default="data/experience/store.sqlite",
        help="path to SQLite experience store",
    )
    fl.add_argument("--output", required=True, help="output JSON path for snapshot")
    fl.add_argument("--snapshot-id", help="snapshot identifier")
    longitudinal = sub.add_parser(
        "longitudinal",
        help="validate/plan returning-customer evaluation; models only with --live",
    )
    longitudinal.add_argument(
        "--customers", default="experiments/longitudinal/customers.dev.json"
    )
    longitudinal.add_argument("--catalogue", default="data/catalogue/catalog.jsonl")
    longitudinal.add_argument("--index", default="data/index/catalogue.sqlite")
    longitudinal.add_argument("--output", required=True)
    longitudinal.add_argument("--limit-customers", type=int)
    longitudinal.add_argument("--headline-k", type=int, default=5)
    longitudinal.add_argument("--turn-budget", type=int)
    longitudinal.add_argument("--session-max-model-calls", type=int, default=18)
    longitudinal.add_argument("--max-model-calls", type=int)
    longitudinal.add_argument("--price-input-per-million", type=float)
    longitudinal.add_argument("--price-output-per-million", type=float)
    longitudinal.add_argument("--env-file", default=".env")
    longitudinal.add_argument("--live", action="store_true")
    add_sim_args(longitudinal)
    return p


def main(argv=None):
    try:
        return run_command(parser().parse_args(argv))
    except ValueError as error:  # bad option values: report plainly, spend nothing
        print(f"error: {error}", file=sys.stderr)
        return 2


def run_command(args):
    if args.command == "longitudinal":
        from .longitudinal import (
            LongitudinalConfig,
            plan_longitudinal,
            run_longitudinal,
        )

        config = LongitudinalConfig(
            customers=Path(args.customers),
            catalogue=Path(args.catalogue),
            index=Path(args.index),
            output=Path(args.output),
            limit_customers=args.limit_customers,
            simulator=sim_config(args),
            score=ScoreConfig(
                headline_k=args.headline_k,
                turn_budget=args.turn_budget,
                price_input_per_million=args.price_input_per_million,
                price_output_per_million=args.price_output_per_million,
            ),
            session_max_model_calls=args.session_max_model_calls,
            max_model_calls=args.max_model_calls,
        )
        longitudinal_plan = plan_longitudinal(config)
        if not args.live:
            print(json.dumps({"plan": longitudinal_plan}, indent=2, sort_keys=True))
            print("Dry run: no models contacted and no output or user memory created.")
            return 0
        if config.max_model_calls is None:
            raise ValueError("--live requires --max-model-calls")
        from shopping_agent.provider import DeepSeekPolicy

        if config.output.exists():
            raise ValueError("Use a new longitudinal output directory")
        result = run_longitudinal(
            config,
            simulator=OllamaShopper(config.simulator),
            policy=DeepSeekPolicy.from_env_file(args.env_file),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"Report: {config.output / 'report.md'}")
        return 0
    if args.command == "extract-lessons":
        from shopping_agent.experience import (
            ExperienceStore,
            extract_candidate_lesson,
            validate_lesson,
        )

        run_path = Path(args.run)
        if not run_path.exists():
            print(f"error: run directory not found: {args.run}", file=sys.stderr)
            return 2
        sessions_dir = run_path / "sessions"
        if not sessions_dir.exists():
            print(f"error: sessions directory not found in {args.run}", file=sys.stderr)
            return 2

        store = ExperienceStore(args.store)
        extracted = []
        for sdir in sorted(sessions_dir.iterdir()):
            if not sdir.is_dir():
                continue
            trace_path = sdir / "trace.json"
            result_path = sdir / "result.json"
            if not trace_path.exists() or not result_path.exists():
                continue
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if trace.get("split") != "learning":
                continue
            candidate = extract_candidate_lesson(
                trace, result.get("score", {}), source_split="learning"
            )
            if candidate is not None:
                validate_lesson(candidate)
                store.add_candidate(candidate)
                extracted.append(candidate)

        store.close()
        print(f"Extracted {len(extracted)} candidate lesson(s) into {args.store}:")
        for lesson in extracted:
            print(
                f"  - [{lesson.lesson_id[:12]}] ({lesson.trigger_type}) directive: {lesson.directive[:80]}"
            )
        print(
            "\nRun `python -m astra_eval review-lessons` to inspect and confirm candidate lessons."
        )
        return 0

    if args.command == "review-lessons":
        from shopping_agent.experience import ExperienceStore

        store = ExperienceStore(args.store)
        if args.confirm:
            confirmed = store.confirm(args.confirm, review_notes=args.notes)
            print(
                f"Confirmed lesson {confirmed.lesson_id} (status: {confirmed.status})"
            )
        elif args.reject:
            rejected = store.reject(args.reject, review_notes=args.notes)
            print(f"Rejected lesson {rejected.lesson_id} (status: {rejected.status})")
        elif args.retract:
            retracted = store.retract(args.retract, reason=args.notes)
            print(
                f"Retracted lesson {retracted.lesson_id} (status: {retracted.status})"
            )

        status_filter = None if args.status == "all" else args.status
        lessons = store.list_lessons(status=status_filter)
        print(
            f"\n--- Lesson Review Report ({args.store}) [{len(lessons)} lesson(s)] ---"
        )
        print(
            "Procedural templates are experimental hypotheses; confirmation is approval for use, not evidence of causal improvement."
        )
        for lesson in lessons:
            ev = lesson.evidence
            print("=" * 80)
            print(f"Lesson ID:           {lesson.lesson_id} (v{lesson.version})")
            print(f"Status:              {lesson.status.upper()}")
            print(f"Scope:               {lesson.scope}")
            print(f"Trigger Type:        {lesson.trigger_type}")
            print(f"Trigger Condition:   {json.dumps(lesson.trigger_condition)}")
            print(f"Expected Action:     {lesson.expected_action}")
            print(f"Action Signature:    {json.dumps(lesson.action_signature)}")
            print(f"Directive:           {lesson.directive}")
            print(f"Hypothesized Cause:  {lesson.hypothesized_cause}")
            print(f"Observed Failure:    {lesson.observed_outcome}")
            print(
                f"Source Evidence:     scenario={ev.get('source_scenario_id')}, split={ev.get('source_split')}, "
                f"turn={ev.get('turn')}, termination={ev.get('termination')}"
            )
            if lesson.review_notes:
                print(f"Review Notes:        {lesson.review_notes}")
            if lesson.supersedes_id:
                print(f"Supersedes:          {lesson.supersedes_id}")
            if lesson.superseded_by_id:
                print(f"Superseded By:       {lesson.superseded_by_id}")
        print("=" * 80)
        print("Explicit Confirmation Instructions:")
        print(
            f'  Confirm: python -m astra_eval review-lessons --store {args.store} --confirm <LESSON_ID> --notes "<NOTES>"'
        )
        print(
            f'  Reject:  python -m astra_eval review-lessons --store {args.store} --reject <LESSON_ID> --notes "<REASON>"'
        )
        print(
            f'  Retract: python -m astra_eval review-lessons --store {args.store} --retract <LESSON_ID> --notes "<REASON>"'
        )
        store.close()
        return 0

    if args.command == "freeze-lessons":
        import uuid

        from shopping_agent.experience import ExperienceStore

        store = ExperienceStore(args.store)
        snap_id = args.snapshot_id or f"snap-{uuid.uuid4().hex[:8]}"
        snapshot = store.create_snapshot(snap_id)
        out_path = Path(args.output)
        store.save_snapshot(snapshot, out_path)
        print(
            f"Saved frozen snapshot '{snapshot.snapshot_id}' (SHA-256: {snapshot.sha256[:16]}...) "
            f"with {len(snapshot.lessons)} active lesson(s) to {out_path}"
        )
        store.close()
        return 0

    if args.command == "audit-targets":
        from .target_scenarios import TargetPool

        print(json.dumps(TargetPool(args.catalogue).audit(), indent=2))
        return 0
    if args.command == "generate":
        per_split = {
            "learning": args.learning,
            "development": args.development,
            "held_out": args.held_out,
        }
        if args.evaluation_mode == "target_item":
            from .target_scenarios import generate_targets

            scenarios, truths, manifest = generate_targets(
                args.catalogue,
                args.seed,
                per_split,
                max_user_turns=args.max_user_turns,
                group=args.target_group,
                no_target_per_split=args.no_target_per_split,
            )
        else:
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
        run_meta = json.loads((Path(args.run_dir) / "run.json").read_text())
        if (
            run_meta["shared_config"].get("evaluation_mode")
            == "longitudinal_user_memory"
        ):
            from .longitudinal_report import write_longitudinal_report

            write_longitudinal_report(Path(args.run_dir))
        else:
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
    if getattr(args, "experience_snapshot", None):
        from shopping_agent.experience import ExperienceStore

        snapshot = ExperienceStore.load_snapshot(args.experience_snapshot)
        conditions = (
            Condition("memory_off"),
            Condition("memory_on", experience=snapshot),
        )
    else:
        conditions = (Condition(),)
    config = ExperimentConfig(
        scenarios_dir=Path(args.scenarios),
        evaluation_mode=args.evaluation_mode,
        session_max_model_calls=args.session_max_model_calls
        if args.session_max_model_calls is not None
        else (18 if args.evaluation_mode == "target_item" else None),
        catalogue=Path(args.catalogue),
        index=Path(args.index),
        output=Path(args.output),
        split=args.split,
        limit=args.limit,
        conditions=conditions,
        simulator=sim_config(args),
        score=ScoreConfig(
            k_values=tuple(args.k),
            headline_k=args.headline_k
            if args.headline_k is not None
            else (5 if args.evaluation_mode == "target_item" else 3),
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

    from .experiment import default_agent_factory, experiential_agent_factory

    policy = DeepSeekPolicy.from_env_file(args.env_file)
    simulator = (
        OllamaShopper(config.simulator)
        if args.simulator == "ollama"
        else ScriptedShopper(config.simulator)
    )
    factory = (
        experiential_agent_factory
        if getattr(args, "experience_snapshot", None)
        else default_agent_factory
    )
    result = run_experiment(
        config, simulator=simulator, policy=policy, agent_factory=factory
    )
    write_report(config.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"Report: {config.output / 'report.md'}")
    return 0
