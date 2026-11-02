"""Separate experimental CLI. Default is a labelled, free synthetic demonstration."""

import argparse
import json
from contextlib import ExitStack
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from shopping_agent.experience.store import ExperienceStore
from shopping_agent.provider import DeepSeekPolicy
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore
from shopping_agent.user_memory import UserMemoryStore

from . import BASELINE_COMMIT
from .demo import DemoModel, catalogue
from .provider import deepseek_model
from .workflow import LangChainShoppingAgent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("data/langchain-experiment/demo")
    )
    parser.add_argument(
        "--live", action="store_true", help="Paid; requires separate user approval"
    )
    parser.add_argument("--index", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--budget-usd", type=str)
    parser.add_argument("--prior-usd", default="0")
    parser.add_argument("--user", default="demo-customer")
    parser.add_argument("--session")
    parser.add_argument("--message", default="I want boots")
    parser.add_argument("--end-session", action="store_true")
    parser.add_argument("--user-memory", action="store_true")
    parser.add_argument(
        "--learn",
        action="store_true",
        help="Stage generalized procedural candidates only",
    )
    args = parser.parse_args(argv)
    if args.live and not (args.index and args.env_file and args.budget_usd):
        parser.error("--live requires --index, --env-file and --budget-usd")
    if args.session:
        if not (args.root / "manifest.json").exists():
            parser.error("Continuation requires an existing experiment root")
        manifest = json.loads((args.root / "manifest.json").read_text())
        if manifest != {
            "baseline": BASELINE_COMMIT,
            "live": args.live,
            "user_memory": args.user_memory,
            "learn": args.learn,
        }:
            parser.error(
                "Experiment mode and memory permissions cannot change during continuation"
            )
    else:
        args.root.mkdir(parents=True, exist_ok=False)
        (args.root / "manifest.json").write_text(
            json.dumps(
                {
                    "baseline": BASELINE_COMMIT,
                    "live": args.live,
                    "user_memory": args.user_memory,
                    "learn": args.learn,
                },
                indent=2,
            )
            + "\n"
        )
    with ExitStack() as stack:
        if args.live:
            # Accounting is reused unchanged, and remains outside the production package.
            from astra_eval.api_budget import ApiCostBudget

            settings = DeepSeekPolicy.from_env_file(args.env_file)
            ledger = args.root / "cost.api-cost.jsonl"
            # No paid continuation can silently reset accounting or uncertain reservations.
            if ledger.exists():
                parser.error(
                    "Existing paid ledger: review accounting and use a fresh experiment root"
                )
            budget = ApiCostBudget(ledger, args.budget_usd, prior=args.prior_usd)
            model = deepseek_model(
                api_key=settings._key, model=settings.model, budget=budget
            )
            index = args.index
        else:
            index = args.root / "demo.sqlite"
            if not index.exists():
                source = args.root / "demo.jsonl"
                source.write_text("".join(json.dumps(p) + "\n" for p in catalogue()))
                build_index(source, index)
            model = DemoModel()
        search = LexicalSearch(index)
        stack.callback(search.close)
        store = SessionStore(args.root / "sessions")
        sid = args.session or store.create(args.user)
        memory = (
            UserMemoryStore(args.root / "user-memory") if args.user_memory else None
        )
        experience = stack.enter_context(
            ExperienceStore(args.root / "experience.sqlite")
        )
        checkpoints = stack.enter_context(
            SqliteSaver.from_conn_string(str(args.root / "checkpoints.sqlite"))
        )
        agent = LangChainShoppingAgent(
            store,
            search,
            model,
            user_memory=memory,
            experience=experience,
            learn=args.learn,
            checkpointer=checkpoints,
        )
        result = agent.turn(args.user, sid, args.message, end_session=args.end_session)
        print(
            json.dumps(
                {"mode": "live" if args.live else "offline-demo", "response": result},
                indent=2,
            )
        )
        return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
