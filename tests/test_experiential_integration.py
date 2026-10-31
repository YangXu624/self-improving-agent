"""Experiential memory integration tests: extraction, confirmation, snapshot, retrieval, and evaluation."""

import json
from unittest.mock import patch

import eval_fixtures as F

from astra_eval.cli import main
from astra_eval.experiment import (
    Condition,
    ExperimentConfig,
    experiential_agent_factory,
    run_experiment,
)
from astra_eval.report import build_report, write_report
from astra_eval.scenarios import generate, save
from astra_eval.scoring import ScoreConfig
from astra_eval.simulators import ScriptedShopper
from shopping_agent.experience import (
    ExperienceSnapshot,
    ExperienceStore,
    Lesson,
    LessonValidationError,
    extract_candidate_lesson,
    validate_lesson,
)
from shopping_agent.provider import PolicyReply


class ExperientialDecisionPolicy(F.HeuristicPolicy):
    """Subclasses HeuristicPolicy to demonstrate procedural guidance application."""

    def __init__(self):
        super().__init__(ask_department=False)
        self.contexts = []

    def complete(self, messages):
        ctx = json.loads(messages[-1]["content"])
        self.contexts.append(ctx)
        guidance = ctx.get("procedural_guidance", [])

        reply = super().complete(messages)
        data = json.loads(reply.content)
        if data["action"]["type"] == "SEARCH":
            if not guidance:
                # Without guidance: policy uses an unguided narrow query that fails
                data["action"]["query"] = "nonexistent_broken_query_keyword"
            else:
                # With guidance: ensures mode="all" matching action_signature
                data["action"]["mode"] = "all"
        return PolicyReply(json.dumps(data), reply.metadata)


class ExperientialIntegrationTests(F.EvalCase):
    def setUp(self):
        super().setUp()
        scenarios, truths, manifest = generate(
            self.catalogue,
            42,
            {"learning": 2, "development": 2, "held_out": 2},
        )
        self.scenarios_dir = self.root / "scenarios"
        save(self.scenarios_dir, scenarios, truths, manifest)
        self.db_path = self.root / "experience.sqlite"
        self.store = ExperienceStore(self.db_path)

    def tearDown(self):
        self.store.close()
        super().tearDown()

    def test_complete_experiential_self_improvement_loop(self):
        """Vertical slice test: learn -> extract -> confirm -> freeze -> retrieve -> apply -> compare."""
        # 1. Extraction from learning trace
        learning_trace = {
            "scenario_id": "learn-task-001",
            "turns": [
                {
                    "turn": 1,
                    "action": "SEARCH",
                    "searches": 1,
                    "counts": [{"verified_eligible": 0}],
                }
            ],
        }
        outcome = {
            "outcome": "failure",
            "termination": "decision_budget_exhausted",
        }
        candidate = extract_candidate_lesson(
            trace=learning_trace,
            outcome=outcome,
            source_split="learning",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.status, "candidate")
        self.assertEqual(candidate.trigger_type, "initial_query")

        # Refine action_signature to test observable verification
        custom_candidate = Lesson(
            lesson_id=candidate.lesson_id,
            version=1,
            scope="*",
            trigger_type="initial_query",
            trigger_condition={"searches": 0},
            directive="Use primary category nouns such as Sandals in initial search",
            expected_action="SEARCH",
            action_signature={"mode": "all"},
            observed_outcome=candidate.observed_outcome,
            hypothesized_cause=candidate.hypothesized_cause,
            evidence=candidate.evidence,
            status="candidate",
        )
        self.store.add_candidate(custom_candidate)

        # Candidate is not retrieved before confirmation
        retrieved_before = self.store.retrieve("initial_query")
        self.assertEqual(retrieved_before, [])

        # 2. Explicit human confirmation
        confirmed = self.store.confirm(
            custom_candidate.lesson_id,
            review_notes="Reviewed and approved by human supervisor",
        )
        self.assertEqual(confirmed.status, "active")

        # 3. Freeze into immutable content-hashed snapshot
        snapshot = self.store.create_snapshot("exp-snapshot-dev")
        self.assertEqual(len(snapshot.lessons), 1)
        snapshot_file = self.root / "snapshot.json"
        self.store.save_snapshot(snapshot, snapshot_file)

        # 4. Run side-by-side evaluation on development split (different product family)
        policy = ExperientialDecisionPolicy()
        out_dir = self.root / "eval_out"
        config = ExperimentConfig(
            scenarios_dir=self.scenarios_dir,
            catalogue=self.catalogue,
            index=self.index,
            output=out_dir,
            split="development",
            limit=1,
            conditions=(
                Condition("memory_off"),
                Condition("memory_on", experience=snapshot),
            ),
            score=ScoreConfig(headline_k=1, turn_budget=3),
        )

        summary = run_experiment(
            config,
            simulator=ScriptedShopper(),
            policy=policy,
            agent_factory=experiential_agent_factory,
        )
        self.assertEqual(summary["sessions"], 2)

        # Verify results in results.jsonl
        results = [
            json.loads(line)
            for line in (out_dir / "results.jsonl").read_text().splitlines()
            if line
        ]
        off_res = next(r for r in results if r["condition"] == "memory_off")
        on_res = next(r for r in results if r["condition"] == "memory_on")

        # In memory_off: no lessons retrieved, injected, or applied
        self.assertEqual(off_res["experience"]["retrieved"], [])
        self.assertEqual(off_res["experience"]["injected"], [])
        self.assertEqual(off_res["experience"]["applied"], [])
        self.assertEqual(off_res["score"]["outcome"], "failure")

        # In memory_on: lesson was retrieved, injected, applied, and outcome succeeded
        self.assertIn(custom_candidate.lesson_id, on_res["experience"]["retrieved"])
        self.assertIn(custom_candidate.lesson_id, on_res["experience"]["injected"])
        self.assertIn(custom_candidate.lesson_id, on_res["experience"]["applied"])
        self.assertEqual(on_res["score"]["outcome"], "success")

        # Verify report generation
        write_report(out_dir)
        report = build_report(out_dir)
        self.assertIn("memory_on", report["run"]["conditions"])
        self.assertIn("memory_off", report["run"]["conditions"])

    def test_correction_retraction_and_superseding(self):
        """Test superseding and retracting lessons while preserving historical provenance."""
        l1 = Lesson(
            lesson_id="exp-test-01",
            version=1,
            scope="*",
            trigger_type="initial_query",
            directive="Initial search directive",
            status="active",
            evidence={"source_split": "learning"},
        )
        validate_lesson(l1)
        self.store.add_candidate(l1)
        self.store.confirm("exp-test-01")

        # Supersede with version 2
        l2 = Lesson(
            lesson_id="exp-test-02",
            scope="*",
            trigger_type="initial_query",
            directive="Improved search directive v2",
            evidence={"source_split": "learning"},
        )
        old, new = self.store.supersede(
            "exp-test-01", l2, reason="Refined query heuristic"
        )
        self.assertEqual(old.status, "superseded")
        self.assertEqual(old.superseded_by_id, "exp-test-02")
        self.assertEqual(new.version, 2)
        self.assertEqual(new.supersedes_id, "exp-test-01")

        # Retract v2
        retracted = self.store.retract("exp-test-02", reason="Discontinued heuristic")
        self.assertEqual(retracted.status, "retracted")

        # Provenance: all lessons remain in SQLite
        all_lessons = self.store.list_lessons()
        self.assertEqual(len(all_lessons), 2)
        # None are active
        active = self.store.list_lessons(status="active")
        self.assertEqual(len(active), 0)

    def test_contamination_prevention(self):
        """Evaluator targets and hidden ground truth are strictly rejected."""
        # Non-learning split is rejected by extractor
        none_lesson = extract_candidate_lesson(
            trace={"turns": [{"action": "SEARCH"}]},
            outcome={},
            source_split="held_out",
        )
        self.assertIsNone(none_lesson)

        # Non-learning split is rejected by validator
        with self.assertRaises(LessonValidationError):
            validate_lesson(
                Lesson(
                    lesson_id="exp-bad-split",
                    directive="Clean query",
                    evidence={"source_split": "development"},
                )
            )

        # ASIN pattern in directive is rejected
        with self.assertRaises(LessonValidationError):
            validate_lesson(
                Lesson(
                    lesson_id="exp-bad-asin",
                    directive="Always search for B001234567 product",
                    evidence={"source_split": "learning"},
                )
            )

        # Target title in directive is rejected
        with self.assertRaises(LessonValidationError):
            validate_lesson(
                Lesson(
                    lesson_id="exp-bad-title",
                    directive="Look for Acme Red Wool Scarf with fringe",
                    evidence={"source_split": "learning"},
                ),
                forbidden_titles=["Acme Red Wool Scarf"],
            )

    def test_cli_experience_snapshot_dry_run(self):
        """CLI accepts --experience-snapshot and schedules both conditions."""
        snapshot = ExperienceSnapshot.from_lessons("snap-cli", [])
        snap_path = self.root / "cli_snap.json"
        ExperienceStore.save_snapshot(snapshot, snap_path)

        cmd = [
            "run",
            "--scenarios",
            str(self.scenarios_dir),
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--output",
            str(self.root / "cli_out"),
            "--experience-snapshot",
            str(snap_path),
            "--limit",
            "1",
        ]
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
            self.assertEqual(main(cmd), 0)
