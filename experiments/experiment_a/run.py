"""Controlled BM25 presentation pilot. Local/replay modes cannot call a provider.

Live mode requires an independently verified frozen artifact, a fresh output directory,
bounded usage and a clean Git tree. It makes one terminal decision per scheduled trial.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from shopping_agent.agent import ActionError, verified_products
from shopping_agent.cards import EXPERIMENT_PROFILES
from shopping_agent.context import bind_context, builder_for_profile
from shopping_agent.contracts import Decision, Search, ShoppingState
from shopping_agent.provider import (
    MAX_OUTPUT_TOKENS,
    DeepSeekPolicy,
    PolicyReply,
    ProviderError,
)
from shopping_agent.retrieval import LexicalSearch, file_hash
from shopping_agent.sessions import dumps

from .metrics import outcome_metrics, shortlist_metrics
from .prepare import ROOT, write_json

# DeepSeek's published V4 tokenizer.json (deepseek_v4_tokenizer.zip); see the README.
TOKENIZER_SHA256 = "89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614"
BM25_RELATIVE_TOLERANCE = 1e-9


def load_tokenizer(path):
    """Load only the pinned tokenizer asset; token counts must be comparable across runs."""
    if file_hash(path) != TOKENIZER_SHA256:
        raise ValueError("Tokenizer is not the pinned DeepSeek V4 tokenizer.json")
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(path))


def same_search(fresh, original):
    """Exact counts, IDs, order and evidence; BM25 floats only within SQLite rounding noise.

    Different SQLite builds can differ in the last float digit of a BM25 score. Anything
    larger, or any other changed field, is still drift.
    """
    if fresh["counts"] != original["counts"]:
        return False
    a, b = fresh["candidates"], original["candidates"]
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if not math.isclose(
            x["bm25"], y["bm25"], rel_tol=BM25_RELATIVE_TOLERANCE, abs_tol=0.0
        ):
            return False
        if dumps({k: v for k, v in x.items() if k != "bm25"}) != dumps(
            {k: v for k, v in y.items() if k != "bm25"}
        ):
            return False
    return True


def load_frozen(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    certificate = json.loads((directory / "verification.json").read_text())
    if certificate.get("verified") is not True or certificate[
        "manifest_sha256"
    ] != file_hash(directory / "manifest.json"):
        raise ValueError("Missing/mismatched independent verification")
    for name, key in [
        ("tasks.json", "tasks_sha256"),
        ("qrels.json", "qrels_sha256"),
        ("baseline.json", "baseline_sha256"),
        ("reviewed_labels.json", "review_sha256"),
    ]:
        if (
            file_hash(directory / name) != manifest[key]
            or certificate[key] != manifest[key]
        ):
            raise ValueError("Frozen artifact hash mismatch")
    if (
        file_hash(ROOT / "src/shopping_agent/retrieval.py")
        != manifest["retrieval_source_sha256"]
    ):
        raise ValueError("Original BM25 implementation changed")
    return (
        manifest,
        json.loads((directory / "tasks.json").read_text())["tasks"],
        json.loads((directory / "baseline.json").read_text()),
        json.loads((directory / "qrels.json").read_text()),
    )


def decision_context(task, entry, profile):
    state = ShoppingState.model_validate(entry["state"])
    current = SimpleNamespace(type="user_message", payload={"message": task["request"]})
    session = SimpleNamespace(state=state, events=[current])
    bundle = builder_for_profile(profile)(
        session,
        task["request"],
        entry["search_result"],
        [],
        {"model_calls": 1, "searches": 0},
        False,
    )
    checked = bind_context(bundle.messages, entry["search_result"], profile)
    if checked.visible_search != bundle.visible_search:
        raise ValueError("Unauthenticated visibility receipt")
    # Explicit leakage guard: evaluator labels/split/IDs never enter application context.
    serialized = dumps(bundle.messages)
    if (
        task["id"] in serialized
        or '"positive_ids"' in serialized
        or '"judgments"' in serialized
    ):
        raise ValueError("Evaluator metadata leaked into prompt")
    return checked


def validate_reply(reply, task, entry, bundle, search):
    outcome = {
        "status": "invalid",
        "action": None,
        "attempted_ids": [],
        "accepted_ids": [],
        "error": None,
    }
    try:
        decision = Decision.model_validate_json(reply.content)
        outcome["action"] = decision.action.type
        state = ShoppingState.model_validate(entry["state"])
        if decision.based_on_state_version != state.version:
            raise ActionError("stale_state_version")
        if decision.updates:
            raise ActionError("fixed_state_update_rejected")
        if decision.action.type == "SEARCH":
            raise ActionError("non_terminal_decision")
        if decision.action.type == "RECOMMEND":
            outcome["attempted_ids"] = decision.action.product_ids
            verified_products(
                decision.action,
                entry["search_result"],
                state,
                search,
                bundle.visible_search,
            )
            if len(decision.action.product_ids) > 3:
                raise ActionError("task_recommendation_limit")
            outcome["accepted_ids"] = decision.action.product_ids
        outcome.update(status="ok", reason=decision.reason)
    except ValidationError:
        outcome["error"] = "invalid_decision_schema"
    except ActionError as exc:
        outcome["error"] = str(exc)
    return outcome


def counts(messages, tokenizer):
    return sum(
        len(tokenizer.encode(message["content"], add_special_tokens=False).ids)
        for message in messages
    )


def payload_tokens(bundle, tokenizer):
    result = json.loads(bundle.messages[-1]["content"])["latest_search"]
    # Include shared headers, not just packed rows, in the charged result representation.
    return len(
        tokenizer.encode(dumps(result, compact=True), add_special_tokens=False).ids
    )


def timed_summary(values):
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
    }


def offline(directory, index, output, tokenizer):
    manifest, tasks, baseline, qrels = load_frozen(directory)
    output = Path(output)
    if output.exists():
        raise FileExistsError("Output exists")
    tool = LexicalSearch(index, expected_catalogue_hash=manifest["catalogue_sha256"])
    rows, latency = [], []
    try:
        for task in tasks:
            entry = baseline[task["id"]]
            state = ShoppingState.model_validate(entry["state"])
            action = Search(
                type="SEARCH", query=task["query"], mode=task["mode"], limit=10
            )
            fresh = tool.search(action, state)
            original = entry["search_result"]
            if not same_search(fresh, original):
                raise ValueError("Frozen BM25 replay drift")
            samples = []
            for _ in range(5):
                start = time.perf_counter()
                tool.search(action, state)
                samples.append((time.perf_counter() - start) * 1000)
            latency.append({"task_id": task["id"], "samples_ms": samples})
            for profile in EXPERIMENT_PROFILES:
                samples = []
                for _ in range(5):
                    start = time.perf_counter()
                    bundle = decision_context(task, entry, profile)
                    samples.append((time.perf_counter() - start) * 1000)
                ids = bundle.visible_search.product_ids
                rows.append(
                    {
                        "task_id": task["id"],
                        "split": task["split"],
                        "stratum": task["stratum"],
                        "profile": profile,
                        "feasible": qrels[task["id"]]["feasible"],
                        "shortlist": shortlist_metrics(ids, qrels[task["id"]]),
                        "visible_ids": list(ids),
                        "semantic_sha256": bundle.visible_search.semantic_sha256,
                        "projection_sha256": bundle.visible_search.projection_sha256,
                        "context_sha256": hashlib.sha256(
                            dumps(bundle.messages).encode()
                        ).hexdigest(),
                        "content_tokens": counts(bundle.messages, tokenizer),
                        "result_tokens": payload_tokens(bundle, tokenizer),
                        "formatting": timed_summary(samples),
                    }
                )
    finally:
        tool.close()
    output.mkdir(parents=True)
    write_json(
        output / "offline.json",
        {
            "manifest": manifest,
            "rows": rows,
            "search_latency": latency,
            "warm_search": timed_summary([n for r in latency for n in r["samples_ms"]]),
        },
    )
    return {
        "tasks": len(tasks),
        "profile_trials": len(rows),
        "warm_search": timed_summary([n for r in latency for n in r["samples_ms"]]),
    }


class UsageBudget:
    """Persisted conservative accounting; transport failures keep their reservation."""

    def __init__(self, *, requests=2, input_tokens=4893, output_tokens=198):
        self.requests, self.input_tokens, self.output_tokens = (
            requests,
            input_tokens,
            output_tokens,
        )

    def reserve(self, prompt_tokens):
        reservation = prompt_tokens + 512
        if (
            self.requests + 1 > 100
            or self.input_tokens + reservation > 600_000
            or self.output_tokens + MAX_OUTPUT_TOKENS > 200_000
        ):
            raise ValueError("experiment_budget_exhausted")
        self.requests += 1
        self.input_tokens += reservation
        self.output_tokens += MAX_OUTPUT_TOKENS
        return reservation

    def settle(self, reservation, usage):
        if not all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("prompt_tokens", "completion_tokens")
        ):
            return False
        self.input_tokens += usage["prompt_tokens"] - reservation
        self.output_tokens += usage["completion_tokens"] - MAX_OUTPUT_TOKENS
        return True

    def snapshot(self):
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


def append_line(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(dumps(value, compact=True) + "\n")
        handle.flush()
        __import__("os").fsync(handle.fileno())


def build_schedule(tasks, baseline, seed):
    """Seed-fixed held-out schedule: shuffled tasks, each with its own shuffled profiles."""
    eligible_tasks = [task for task in tasks if task["split"] == "held_out"]
    rng = random.Random(seed)
    rng.shuffle(eligible_tasks)
    schedule = []
    for task in eligible_tasks:
        profiles = list(EXPERIMENT_PROFILES)
        rng.shuffle(profiles)
        for profile in profiles:
            bundle = decision_context(task, baseline[task["id"]], profile)
            schedule.append((task, profile, bundle))
    return schedule


def live(directory, index, output, tokenizer, env_file, *, seed=20261031):
    manifest, tasks, baseline, qrels = load_frozen(directory)
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip():
        raise ValueError("Commit the exact tested implementation before paid trials")
    output = Path(output)
    if output.exists():
        raise FileExistsError(
            "Use a new run; interrupted paid trials are not automatically retried"
        )
    schedule = build_schedule(tasks, baseline, seed)
    policy = DeepSeekPolicy.from_env_file(env_file)
    search = LexicalSearch(index, expected_catalogue_hash=manifest["catalogue_sha256"])
    output.mkdir(parents=True)
    budget = UsageBudget()
    write_json(
        output / "run.json",
        {
            "protocol": manifest["protocol"],
            "manifest_sha256": file_hash(Path(directory) / "manifest.json"),
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "requested_model": policy.model,
            "seed": seed,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0,
            "thinking": "disabled",
            "trials": len(schedule),
            "started": datetime.now(UTC).isoformat(),
            "initial_usage": budget.snapshot(),
        },
    )
    try:
        for ordinal, (task, profile, bundle) in enumerate(schedule, 1):
            content_tokens = counts(bundle.messages, tokenizer)
            reservation = budget.reserve(content_tokens)
            trial_id = f"trial-{ordinal:03}"
            append_line(
                output / "requests.jsonl",
                {
                    "trial_id": trial_id,
                    "task_id": task["id"],
                    "profile": profile,
                    "messages": bundle.messages,
                    "visible_search": bundle.visible_search.trace(),
                    "context_sha256": hashlib.sha256(
                        dumps(bundle.messages).encode()
                    ).hexdigest(),
                    "content_tokens": content_tokens,
                    "result_tokens": payload_tokens(bundle, tokenizer),
                    "usage_reserved": budget.snapshot(),
                },
            )
            started = time.perf_counter()
            try:
                reply = policy.complete(bundle.messages)
                elapsed = (time.perf_counter() - started) * 1000
                usage_complete = budget.settle(
                    reservation, reply.metadata.get("usage", {})
                )
                outcome = validate_reply(
                    reply, task, baseline[task["id"]], bundle, search
                )
                response = {"content": reply.content, "metadata": reply.metadata}
            except ProviderError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                usage_complete = False
                outcome = {
                    "status": "error",
                    "action": None,
                    "attempted_ids": [],
                    "accepted_ids": [],
                    "error": str(exc),
                }
                response = None
            outcome["runtime_hard_failures"] = sum(
                not search.eligible(
                    ident, ShoppingState.model_validate(baseline[task["id"]]["state"])
                )
                for ident in outcome["attempted_ids"]
            )
            record = {
                "trial_id": trial_id,
                "task_id": task["id"],
                "profile": profile,
                "response": response,
                "outcome": outcome,
                "metrics": outcome_metrics(outcome, qrels[task["id"]]),
                "latency_ms": elapsed,
                "usage_complete": usage_complete,
                "usage_accounted": budget.snapshot(),
            }
            append_line(output / "outcomes.jsonl", record)
            write_json(output / "budget.json", budget.snapshot())
            if ordinal % 8 == 0:
                print(
                    dumps(
                        {
                            "completed": ordinal,
                            "planned": len(schedule),
                            "usage": budget.snapshot(),
                        }
                    ),
                    flush=True,
                )
            if budget.input_tokens > 600_000 or budget.output_tokens > 200_000:
                raise ValueError(
                    "Provider usage exceeded reserved accounting; stop without another request"
                )
        write_json(
            output / "completed.json",
            {
                "trials": len(schedule),
                "usage": budget.snapshot(),
                "finished": datetime.now(UTC).isoformat(),
            },
        )
    finally:
        search.close()
    return {"trials": len(schedule), "usage": budget.snapshot()}


def read_lines(path):
    """Physical JSONL lines only: U+2028/2029 may appear unescaped inside JSON strings."""
    return [line for line in Path(path).read_text(encoding="utf-8").split("\n") if line]


def replay(directory, run, index):
    manifest, tasks, baseline, qrels = load_frozen(directory)
    task_map = {task["id"]: task for task in tasks}
    requests = {
        r["trial_id"]: r
        for r in map(
            json.loads, (Path(run) / "requests.jsonl").read_text().splitlines()
        )
    }
    results = list(
        map(json.loads, (Path(run) / "outcomes.jsonl").read_text().splitlines())
    )
    tool = LexicalSearch(index, expected_catalogue_hash=manifest["catalogue_sha256"])
    try:
        for result in results:
            if result["response"] is None:
                continue
            request = requests[result["trial_id"]]
            task = task_map[result["task_id"]]
            bundle = decision_context(task, baseline[task["id"]], result["profile"])
            if (
                request["messages"] != bundle.messages
                or request["context_sha256"]
                != hashlib.sha256(dumps(bundle.messages).encode()).hexdigest()
            ):
                raise ValueError("Saved context drift")
            reply = PolicyReply(**result["response"])
            outcome = validate_reply(reply, task, baseline[task["id"]], bundle, tool)
            outcome["runtime_hard_failures"] = result["outcome"][
                "runtime_hard_failures"
            ]
            if (
                outcome != result["outcome"]
                or outcome_metrics(outcome, qrels[task["id"]]) != result["metrics"]
            ):
                raise ValueError("Saved outcome/scoring drift")
    finally:
        tool.close()
    return {"replayed": len(results), "provider_calls": 0, "exact": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("offline", "live", "replay"))
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--index", default="data/index/catalogue.sqlite", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--env-file", default=".env", type=Path)
    args = parser.parse_args()
    if args.mode == "replay":
        print(dumps(replay(args.frozen, args.output, args.index)))
        return
    if args.tokenizer is None:
        parser.error(
            "Offline/live token measurement requires the pinned audit tokenizer"
        )
    tokenizer = load_tokenizer(args.tokenizer)
    if args.mode == "offline":
        result = offline(args.frozen, args.index, args.output, tokenizer)
    else:
        result = live(args.frozen, args.index, args.output, tokenizer, args.env_file)
    print(dumps(result))


if __name__ == "__main__":
    main()
