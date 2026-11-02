"""Offline regression tests for target-item mode and memory auto-consolidation in longitudinal runner."""

import json
import tempfile
import unittest
from pathlib import Path

from longitudinal_fixtures import MemoryPolicy, make_dataset

from astra_eval.longitudinal import (
    LongitudinalConfig,
    run_longitudinal,
)
from astra_eval.simulators import ScriptedShopper


class CapturingShopper(ScriptedShopper):
    def __init__(self):
        super().__init__()
        self.memories = []

    def respond(self, memory, view, feedback=()):
        self.memories.append(memory)
        return super().respond(memory, view, feedback)


class LongitudinalTargetRedesignTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source, self.catalogue, self.index, self.data = make_dataset(self.root)

    def test_target_item_mode_and_memory_isolation(self):
        cfg = LongitudinalConfig(
            customers=self.source,
            catalogue=self.catalogue,
            index=self.index,
            output=self.root / "eval_run",
            force_target_item_evaluation=True,
            auto_finalize_memory=True,
            memory_format="legacy",
        )
        policy = MemoryPolicy()
        shopper = CapturingShopper()
        summary = run_longitudinal(cfg, simulator=shopper, policy=policy)
        self.assertIsNotNone(summary)

        # Check results
        results_file = cfg.output / "results.jsonl"
        self.assertTrue(results_file.exists())
        rows = [json.loads(line) for line in results_file.read_text().splitlines()]
        self.assertTrue(len(rows) > 0)

        for row in rows:
            self.assertEqual(row["evaluation_mode"], "target_item")
            self.assertIn("score", row)
            self.assertIn("outcome", row["score"])
            self.assertIn("consolidation", row)
            if row["condition"] == "user_memory_off":
                self.assertIsNone(row["consolidation"])
            elif row["condition"] == "user_memory_on":
                self.assertIsNotNone(row["consolidation"])

        # Check user memory store isolation
        off_dir = cfg.output / "astra/user_memory_off/user-memory"
        on_dir = cfg.output / "astra/user_memory_on/user-memory"
        self.assertFalse(off_dir.exists())
        self.assertTrue(on_dir.exists())
        dbs = list(on_dir.glob("*/profile.db"))
        mds = list(on_dir.glob("*/profile.md"))
        self.assertEqual(len(dbs), 1)
        self.assertEqual(len(mds), 1)
