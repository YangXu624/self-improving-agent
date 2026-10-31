"""Offline regression tests for the Experiment A runner: no network, key or real data."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_retrieval import product

from experiments.experiment_a import run
from experiments.experiment_a.finalize import finalize
from experiments.experiment_a.prepare import prepare
from shopping_agent.cards import EXPERIMENT_PROFILES
from shopping_agent.provider import PolicyReply, ProviderError
from shopping_agent.retrieval import LexicalSearch, build_index, file_hash


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False):
        return SimpleNamespace(ids=text.split())


class FakePolicy:
    """Recommends the first visible product; records what was written before each call."""

    model = "fixture-model"

    def __init__(self, requests_file=None, errors=()):
        self.calls, self.requests_file, self.errors = [], requests_file, list(errors)
        self.lines_at_call = []

    def complete(self, messages):
        self.calls.append(messages)
        if self.requests_file is not None and Path(self.requests_file).exists():
            self.lines_at_call.append(
                len(Path(self.requests_file).read_text().splitlines())
            )
        else:
            self.lines_at_call.append(0)
        if self.errors:
            raise self.errors.pop(0)
        view = json.loads(messages[-1]["content"])["latest_search"]
        decision = {
            "based_on_state_version": 1,
            "updates": [],
            "action": {
                "type": "RECOMMEND",
                "search_id": view["search_id"],
                "product_ids": [view["candidates"][0]["id"]],
            },
            "reason": "fixture",
        }
        return PolicyReply(
            json.dumps(decision),
            {"usage": {"prompt_tokens": 1000, "completion_tokens": 50}},
        )


def task(ident, split, family, category="Boots"):
    return {
        "id": ident,
        "family": family,
        "split": split,
        "stratum": "literal",
        "request": "boots under 100",
        "query": "boots",
        "mode": "all",
        "requirements": [
            {
                "field": "price",
                "op": "lt",
                "value": 100.0,
                "strength": "hard",
                "quote": "under 100",
            }
        ],
        "relevance": {"category": category},
    }


class RunnerCase(unittest.TestCase):
    """Builds a synthetic verified frozen directory over a small generated catalogue."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        rows = [product(f"p{i:02}", 10 + i) for i in range(14)]
        self.source, self.index = self.root / "c.jsonl", self.root / "i.sqlite"
        self.source.write_text("".join(json.dumps(r) + "\n" for r in rows))
        build_index(self.source, self.index)
        tasks = [
            task("dev-1", "development", "f1"),
            task("dev-2", "development", "f2"),
            task("held-1", "held_out", "f3"),
            task("held-2", "held_out", "f4"),
            task("held-3", "held_out", "f5"),
            task("held-none", "held_out", "f6", category="Sandals"),
        ]
        tasks_path = self.root / "tasks.json"
        tasks_path.write_text(
            json.dumps({"catalogue_sha256": file_hash(self.source), "tasks": tasks})
        )
        draft = self.root / "draft"
        prepare(self.source, self.index, draft, tasks_path)
        baseline = json.loads((draft / "baseline.json").read_text())
        qrels = json.loads((draft / "qrels.json").read_text())
        labels, witnesses = {}, {}
        for t in tasks:
            feasible = qrels[t["id"]]["positive_count"] > 0
            ids = [c["id"] for c in baseline[t["id"]]["search_result"]["candidates"]]
            labels[t["id"]] = {
                ident: {
                    "relevant": feasible,
                    "hard_verdict": "pass",
                    "support": ["categories.Boots"],
                }
                for ident in ids
            }
            if feasible:
                witnesses[t["id"]] = {"id": ids[0], "support": ["categories.Boots"]}
        review = self.root / "review.json"
        review.write_text(json.dumps({"labels": labels, "witnesses": witnesses}))
        self.frozen = self.root / "frozen"
        manifest = finalize(draft, review, self.frozen)
        self.certify(manifest)
        self.tasks = tasks

    def certify(self, manifest=None):
        manifest = manifest or json.loads((self.frozen / "manifest.json").read_text())
        (self.frozen / "verification.json").write_text(
            json.dumps(
                {
                    "verified": True,
                    "manifest_sha256": file_hash(self.frozen / "manifest.json"),
                    **{
                        k: manifest[k]
                        for k in (
                            "tasks_sha256",
                            "qrels_sha256",
                            "baseline_sha256",
                            "review_sha256",
                        )
                    },
                }
            )
        )

    def loaded(self):
        return run.load_frozen(self.frozen)

    def context(self, task_id="held-1", profile="v3_k5"):
        _, tasks, baseline, _ = self.loaded()
        t = next(t for t in tasks if t["id"] == task_id)
        return t, baseline[task_id], run.decision_context(t, baseline[task_id], profile)

    def live(self, name="out", policy=None, **kwargs):
        policy = policy or FakePolicy(self.root / name / "requests.jsonl")
        with (
            patch.object(run, "DeepSeekPolicy") as provider,
            patch.object(run.subprocess, "check_output") as shell,
        ):
            provider.from_env_file.return_value = policy
            shell.side_effect = lambda args, **kw: (
                "" if args[:2] == ["git", "status"] else "deadbeef\n"
            )
            result = run.live(
                self.frozen,
                self.index,
                self.root / name,
                FakeTokenizer(),
                self.root / ".env",
                **kwargs,
            )
        return result, policy


class FrozenArtifactTests(RunnerCase):
    def test_verified_directory_loads(self):
        manifest, tasks, baseline, qrels = self.loaded()
        self.assertEqual(len(tasks), 6)
        self.assertEqual(set(baseline), set(qrels))

    def test_missing_or_false_certificate_is_rejected(self):
        certificate = self.frozen / "verification.json"
        value = json.loads(certificate.read_text())
        certificate.write_text(json.dumps({**value, "verified": False}))
        with self.assertRaisesRegex(ValueError, "verification"):
            self.loaded()
        certificate.unlink()
        with self.assertRaises(FileNotFoundError):
            self.loaded()

    def test_certificate_bound_to_manifest_and_every_frozen_file(self):
        for name in (
            "tasks.json",
            "qrels.json",
            "baseline.json",
            "reviewed_labels.json",
        ):
            with self.subTest(name=name):
                path = self.frozen / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    self.loaded()
                path.write_bytes(original)
        manifest = self.frozen / "manifest.json"
        manifest.write_text(manifest.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "verification"):
            self.loaded()

    def test_changed_bm25_source_is_rejected(self):
        manifest_path = self.frozen / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["retrieval_source_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        self.certify(manifest)
        with self.assertRaisesRegex(ValueError, "Original BM25"):
            self.loaded()

    def test_tokenizer_must_be_the_pinned_asset(self):
        wrong = self.root / "tokenizer.json"
        wrong.write_text("{}")
        with self.assertRaisesRegex(ValueError, "pinned"):
            run.load_tokenizer(wrong)
        self.assertRegex(run.TOKENIZER_SHA256, r"^[0-9a-f]{64}$")

    def test_real_tokenizer_loads_when_present(self):
        path = Path(run.ROOT / "data/tokenizers/deepseek_v4/tokenizer.json")
        if not path.exists():
            self.skipTest("pinned tokenizer asset not installed")
        self.assertGreater(len(run.load_tokenizer(path).encode("boots").ids), 0)


class ReplayToleranceTests(unittest.TestCase):
    def search(self):
        return {
            "counts": {"lexical_matches": 3},
            "candidates": [
                {"id": "a", "bm25": -10.0, "title": "A"},
                {"id": "b", "bm25": -9.0, "title": "B"},
            ],
        }

    def test_last_digit_float_noise_is_accepted(self):
        noisy = copy.deepcopy(self.search())
        noisy["candidates"][0]["bm25"] = -10.0 * (1 + 2e-16)
        self.assertTrue(run.same_search(noisy, self.search()))

    def test_real_drift_is_rejected(self):
        for mutate in (
            lambda s: s["candidates"].reverse(),
            lambda s: s["candidates"].pop(),
            lambda s: s["counts"].update(lexical_matches=4),
            lambda s: s["candidates"][0].update(bm25=-10.001),
            lambda s: s["candidates"][1].update(title="changed"),
            lambda s: s["candidates"][1].update(extra=1),
        ):
            changed = copy.deepcopy(self.search())
            mutate(changed)
            with self.subTest(mutate=mutate):
                self.assertFalse(run.same_search(changed, self.search()))


class ScheduleAndContextTests(RunnerCase):
    def schedule(self, seed):
        _, tasks, baseline, _ = self.loaded()
        return run.build_schedule(tasks, baseline, seed)

    def test_only_held_out_tasks_with_every_profile_once(self):
        schedule = self.schedule(1)
        self.assertEqual(len(schedule), 4 * len(EXPERIMENT_PROFILES))
        by_task = {}
        for t, profile, _ in schedule:
            self.assertEqual(t["split"], "held_out")
            by_task.setdefault(t["id"], []).append(profile)
        self.assertEqual(set(by_task), {"held-1", "held-2", "held-3", "held-none"})
        for profiles in by_task.values():
            self.assertCountEqual(profiles, EXPERIMENT_PROFILES)

    def test_schedule_is_reproducible_and_seed_sensitive(self):
        def key(seed):
            return [(t["id"], p) for t, p, _ in self.schedule(seed)]

        self.assertEqual(key(7), key(7))
        self.assertTrue(any(key(7) != key(s) for s in range(8, 14)))

    def test_context_shows_only_the_profile_prefix_and_no_evaluator_metadata(self):
        for profile, limit in [("v3_k5", 5), ("v3_k10", 10), ("shared_k5", 5)]:
            _, entry, bundle = self.context(profile=profile)
            self.assertEqual(len(bundle.visible_search.product_ids), limit)
            expected = [c["id"] for c in entry["search_result"]["candidates"]][:limit]
            self.assertEqual(list(bundle.visible_search.product_ids), expected)
            text = json.dumps(bundle.messages)
            for forbidden in ("held-1", "positive_ids", "judgments"):
                self.assertNotIn(forbidden, text)

    def test_task_identifier_in_requirement_ids_is_a_leak(self):
        t, entry, _ = self.context()
        leaky = copy.deepcopy(entry)
        leaky["state"]["requirements"][0]["id"] = t["id"] + ":r0"
        with self.assertRaisesRegex(ValueError, "leaked"):
            run.decision_context(t, leaky, "v3_k5")


class ReplyValidationTests(RunnerCase):
    def reply(self, action, version=1, updates=None):
        return PolicyReply(
            json.dumps(
                {
                    "based_on_state_version": version,
                    "updates": updates or [],
                    "action": action,
                    "reason": "fixture",
                }
            ),
            {},
        )

    def check(self, action, profile="v3_k5", **kwargs):
        t, entry, bundle = self.context(profile=profile)
        search = LexicalSearch(self.index)
        self.addCleanup(search.close)
        action = action(bundle) if callable(action) else action
        return run.validate_reply(
            self.reply(action, **kwargs), t, entry, bundle, search
        )

    def recommend(self, ids):
        return lambda bundle: {
            "type": "RECOMMEND",
            "search_id": bundle.visible_search.search_id,
            "product_ids": ids,
        }

    def test_visible_recommendation_is_accepted(self):
        _, _, bundle = self.context()
        ids = list(bundle.visible_search.product_ids)[:2]
        outcome = self.check(self.recommend(ids))
        self.assertEqual((outcome["status"], outcome["accepted_ids"]), ("ok", ids))

    def test_candidate_hidden_by_the_card_limit_is_rejected(self):
        _, entry, _ = self.context()
        hidden = entry["search_result"]["candidates"][7]["id"]
        outcome = self.check(self.recommend([hidden]))
        self.assertEqual(outcome["error"], "recommendation_contains_unseen_product_id")
        self.assertEqual(outcome["accepted_ids"], [])
        self.assertEqual(outcome["attempted_ids"], [hidden])
        self.assertEqual(self.check(self.recommend([hidden]), "v3_k10")["status"], "ok")

    def test_non_terminal_stale_or_oversized_decisions_fail_without_repair(self):
        def reason(outcome):
            return outcome["status"], outcome["error"]

        self.assertEqual(
            reason(self.check({"type": "SEARCH", "query": "boots"})),
            ("invalid", "non_terminal_decision"),
        )
        self.assertEqual(
            reason(self.check({"type": "RESPOND", "message": "x"}, version=0)),
            ("invalid", "stale_state_version"),
        )
        _, _, bundle = self.context(profile="v3_k10")
        ids = list(bundle.visible_search.product_ids)[:4]
        self.assertEqual(
            reason(self.check(self.recommend(ids), "v3_k10")),
            ("invalid", "task_recommendation_limit"),
        )
        self.assertEqual(
            reason(
                self.check(
                    {"type": "RESPOND", "message": "x"},
                    updates=[
                        {
                            "op": "NEW_GOAL",
                            "quote": "boots",
                        }
                    ],
                )
            ),
            ("invalid", "fixed_state_update_rejected"),
        )

    def test_malformed_decision_is_an_invalid_schema_failure(self):
        t, entry, bundle = self.context()
        search = LexicalSearch(self.index)
        self.addCleanup(search.close)
        outcome = run.validate_reply(PolicyReply("{nope", {}), t, entry, bundle, search)
        self.assertEqual(outcome["error"], "invalid_decision_schema")

    def test_clarify_and_respond_are_valid_product_free_outcomes(self):
        for action in (
            {"type": "RESPOND", "message": "Nothing suitable."},
            {"type": "CLARIFY", "attribute": "size", "question": "Which size?"},
        ):
            outcome = self.check(action)
            self.assertEqual(outcome["status"], "ok")
            self.assertEqual(outcome["accepted_ids"], [])

    def test_failed_eligibility_recheck_rejects_a_visible_product(self):
        t, entry, bundle = self.context()
        search = LexicalSearch(self.index)
        self.addCleanup(search.close)
        ident = bundle.visible_search.product_ids[0]
        with patch.object(search, "eligible", return_value=False):
            outcome = run.validate_reply(
                self.reply(self.recommend([ident])(bundle)), t, entry, bundle, search
            )
        self.assertEqual(outcome["error"], "recommendation_failed_constraint_recheck")


class JsonlTests(unittest.TestCase):
    def test_unicode_line_separators_inside_records_do_not_split_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "x.jsonl"
            record = {"text": "a\u2028b\u2029c\x85d"}
            run.append_line(path, record)
            run.append_line(path, {"n": 2})
            lines = run.read_lines(path)
            self.assertEqual([json.loads(line) for line in lines], [record, {"n": 2}])


class UsageBudgetTests(unittest.TestCase):
    def test_reserve_then_settle_uses_reported_usage(self):
        budget = run.UsageBudget(requests=0, input_tokens=0, output_tokens=0)
        reservation = budget.reserve(1000)
        self.assertEqual(reservation, 1512)
        self.assertEqual(budget.snapshot()["output_tokens"], run.MAX_OUTPUT_TOKENS)
        self.assertTrue(
            budget.settle(reservation, {"prompt_tokens": 900, "completion_tokens": 40})
        )
        self.assertEqual(
            budget.snapshot(),
            {"requests": 1, "input_tokens": 900, "output_tokens": 40},
        )

    def test_missing_or_invalid_usage_keeps_the_conservative_reservation(self):
        for usage in (
            {},
            {"prompt_tokens": 1},
            {"prompt_tokens": -1, "completion_tokens": 1},
            {"prompt_tokens": True, "completion_tokens": 1},
        ):
            with self.subTest(usage=usage):
                budget = run.UsageBudget(requests=0, input_tokens=0, output_tokens=0)
                reservation = budget.reserve(1000)
                before = budget.snapshot()
                self.assertFalse(budget.settle(reservation, usage))
                self.assertEqual(budget.snapshot(), before)

    def test_each_cap_blocks_before_a_request(self):
        for kwargs, prompt in [
            ({"requests": 100}, 10),
            ({"input_tokens": 599_000}, 1000),
            ({"output_tokens": 199_000}, 10),
        ]:
            budget = run.UsageBudget(
                **{"requests": 0, "input_tokens": 0, "output_tokens": 0, **kwargs}
            )
            before = budget.snapshot()
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "experiment_budget_exhausted"):
                    budget.reserve(prompt)
                self.assertEqual(budget.snapshot(), before)

    def test_default_budget_includes_the_two_preflight_requests(self):
        self.assertEqual(run.UsageBudget().snapshot()["requests"], 2)


class LiveReplayOfflineTests(RunnerCase):
    def lines(self, name, filename):
        path = self.root / name / filename
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_live_run_records_every_trial_before_and_after_each_request(self):
        result, policy = self.live()
        self.assertEqual(result["trials"], 16)
        requests, outcomes = (
            self.lines("out", "requests.jsonl"),
            self.lines("out", "outcomes.jsonl"),
        )
        self.assertEqual(len(requests), 16)
        self.assertEqual(
            [r["trial_id"] for r in requests], [o["trial_id"] for o in outcomes]
        )
        self.assertEqual(policy.lines_at_call, list(range(1, 17)))
        run_meta = json.loads((self.root / "out" / "run.json").read_text())
        self.assertEqual(run_meta["git_commit"], "deadbeef")
        self.assertEqual(run_meta["trials"], 16)
        self.assertTrue((self.root / "out" / "completed.json").exists())
        self.assertTrue(all(o["usage_complete"] for o in outcomes))
        self.assertEqual(
            self.lines("out", "outcomes.jsonl")[-1]["usage_accounted"]["requests"],
            2 + 16,
        )
        self.assertEqual(
            json.loads((self.root / "out" / "budget.json").read_text())["requests"], 18
        )

    def test_dirty_tree_existing_output_and_unverified_data_make_no_provider_call(self):
        policy = FakePolicy()
        with patch.object(run.subprocess, "check_output", return_value=" M file\n"):
            with self.assertRaisesRegex(ValueError, "Commit the exact"):
                run.live(
                    self.frozen,
                    self.index,
                    self.root / "dirty",
                    FakeTokenizer(),
                    self.root / ".e",
                )
        (self.root / "taken").mkdir()
        with self.assertRaises(FileExistsError):
            self.live("taken", policy=policy)
        (self.frozen / "verification.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.live("unverified", policy=policy)
        self.assertEqual(policy.calls, [])

    def test_provider_error_is_recorded_without_retry_and_run_continues(self):
        policy = FakePolicy(errors=[ProviderError("provider_http_500")])
        self.live(policy=policy)
        self.assertEqual(len(policy.calls), 16)
        first = self.lines("out", "outcomes.jsonl")[0]
        self.assertEqual(first["outcome"]["error"], "provider_http_500")
        self.assertEqual(first["outcome"]["status"], "error")
        self.assertIsNone(first["response"])
        self.assertFalse(first["usage_complete"])
        self.assertTrue(first["metrics"]["failure"])

    def test_budget_exhaustion_stops_before_the_next_request(self):
        real = run.UsageBudget
        small = lambda: real(requests=98, input_tokens=0, output_tokens=0)  # noqa: E731
        policy = FakePolicy()
        with patch.object(run, "UsageBudget", small):
            with self.assertRaisesRegex(ValueError, "experiment_budget_exhausted"):
                self.live(policy=policy)
        self.assertEqual(len(policy.calls), 2)
        self.assertEqual(len(self.lines("out", "requests.jsonl")), 2)
        self.assertFalse((self.root / "out" / "completed.json").exists())

    def test_replay_reproduces_outcomes_without_a_provider(self):
        self.live()
        with patch.object(
            run, "DeepSeekPolicy", side_effect=AssertionError("provider used")
        ):
            result = run.replay(self.frozen, self.root / "out", self.index)
        self.assertEqual(result, {"replayed": 16, "provider_calls": 0, "exact": True})

    def test_replay_detects_changed_outcome_or_context(self):
        self.live()
        outcomes = self.root / "out" / "outcomes.jsonl"
        original = outcomes.read_text()
        records = [json.loads(line) for line in original.splitlines()]
        records[0]["outcome"]["accepted_ids"] = ["tampered"]
        outcomes.write_text("".join(json.dumps(r) + "\n" for r in records))
        with self.assertRaisesRegex(ValueError, "outcome/scoring drift"):
            run.replay(self.frozen, self.root / "out", self.index)
        outcomes.write_text(original)
        requests = self.root / "out" / "requests.jsonl"
        records = [json.loads(line) for line in requests.read_text().splitlines()]
        records[0]["messages"][-1]["content"] += " "
        requests.write_text("".join(json.dumps(r) + "\n" for r in records))
        with self.assertRaisesRegex(ValueError, "context drift"):
            run.replay(self.frozen, self.root / "out", self.index)

    def test_offline_scores_every_task_and_profile_and_refuses_overwrite(self):
        out = self.root / "offline"
        summary = run.offline(self.frozen, self.index, out, FakeTokenizer())
        self.assertEqual((summary["tasks"], summary["profile_trials"]), (6, 24))
        document = json.loads((out / "offline.json").read_text())
        rows = document["rows"]
        self.assertEqual({r["profile"] for r in rows}, set(EXPERIMENT_PROFILES))
        k5 = next(
            r for r in rows if r["profile"] == "v3_k5" and r["task_id"] == "held-1"
        )
        k10 = next(
            r for r in rows if r["profile"] == "v3_k10" and r["task_id"] == "held-1"
        )
        self.assertEqual(k5["visible_ids"], k10["visible_ids"][:5])
        self.assertLess(k5["content_tokens"], k10["content_tokens"])
        shared = next(
            r for r in rows if r["profile"] == "shared_k10" and r["task_id"] == "held-1"
        )
        self.assertEqual(shared["semantic_sha256"], k10["semantic_sha256"])
        with self.assertRaises(FileExistsError):
            run.offline(self.frozen, self.index, out, FakeTokenizer())

    def test_offline_detects_bm25_drift_against_the_frozen_baseline(self):
        original = run.LexicalSearch.search

        def drifted(self, action, state):
            result = original(self, action, state)
            result["candidates"].reverse()
            return result

        with patch.object(run.LexicalSearch, "search", drifted):
            with self.assertRaisesRegex(ValueError, "replay drift"):
                run.offline(
                    self.frozen, self.index, self.root / "drift", FakeTokenizer()
                )


class CompatibilityTests(RunnerCase):
    def test_baseline_profile_and_legacy_builder_preserve_default_behaviour(self):
        from shopping_agent.agent import ShoppingAgent
        from shopping_agent.context import build_context, builder_for_profile
        from shopping_agent.sessions import SessionStore

        store = SessionStore(self.root / "sessions")
        sid = store.create("shopper")
        _, entry, _ = self.context()
        with store.open("shopper", sid) as session:
            legacy = build_context(
                session, "boots", entry["search_result"], [], {}, True
            )
            current = builder_for_profile("baseline")(
                session, "boots", entry["search_result"], [], {}, True
            )
            # The default profile may not change what the model sees, only add a receipt.
            self.assertEqual(legacy, current.messages)
        policy = FakePolicy()

        def respond(messages):
            ctx = json.loads(messages[-1]["content"])
            return PolicyReply(
                json.dumps(
                    {
                        "based_on_state_version": ctx["state"]["version"],
                        "updates": [],
                        "action": {"type": "RESPOND", "message": "Hello."},
                        "reason": "fixture",
                    }
                ),
                {},
            )

        policy.complete = respond
        search = LexicalSearch(self.index)
        self.addCleanup(search.close)
        for builder in (build_context, None):
            kwargs = {"context_builder": builder} if builder else {}
            out = ShoppingAgent(store, search, policy, **kwargs).turn(
                "shopper", sid, "hi"
            )
            self.assertEqual((out["status"], out["action"]), ("ok", "RESPOND"))


if __name__ == "__main__":
    unittest.main()
