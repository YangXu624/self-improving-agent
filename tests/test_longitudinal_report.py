import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import eval_fixtures as F
from longitudinal_fixtures import MemoryPolicy, make_dataset

from astra_eval.cli import main
from astra_eval.customers import PersistentPreference, validate_dataset
from astra_eval.longitudinal import LongitudinalConfig, run_longitudinal
from astra_eval.longitudinal_report import memory_audit, summarize
from astra_eval.oracle import CatalogueOracle
from astra_eval.simulators import OllamaShopper, ScriptedShopper


class LongitudinalReportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path, self.catalogue, self.index, self.data = make_dataset(self.root)
        self.config = LongitudinalConfig(
            customers=self.path,
            catalogue=self.catalogue,
            index=self.index,
            output=self.root / "run",
        )

    def rows(self):
        run_longitudinal(
            self.config, simulator=ScriptedShopper(), policy=MemoryPolicy()
        )
        return [
            json.loads(line)
            for line in (self.config.output / "results.jsonl").read_text().splitlines()
        ]

    def test_numeric_first_hit_and_failure_denominators(self):
        target = next(r for r in self.rows() if r["evaluation_mode"] == "target_item")
        hit, failure = copy.deepcopy(target), copy.deepcopy(target)
        hit["score"].update(
            outcome="success", first_success_turn=4, first_hit_mrr_at_k=0.5
        )
        hit["efficiency_to_first_success"] = {"searches": 2, "clarifications": 2}
        failure["score"].update(
            outcome="failure", first_success_turn=None, first_hit_mrr_at_k=0
        )
        failure["efficiency_to_first_success"] = None
        result = summarize([hit, failure])["by_mode"]["target_item"]
        self.assertEqual(result["success_rate_all_started"], 0.5)
        self.assertEqual(result["mean_first_hit_mrr_at_k"], 0.25)
        self.assertEqual(result["mttc_successes_only"], 4)
        self.assertEqual(result["penalized_mttc"], 5.5)
        self.assertEqual(result["cumulative_success_by_turn"]["3"], 0)
        self.assertEqual(result["cumulative_success_by_turn"]["4"], 0.5)

    def test_audit_does_not_confuse_preference_and_dislike(self):
        customer = self.data.customers[0]
        dislike = customer.preferences[0].model_dump()
        dislike.update(category="dislike")
        dislike["fact"].update(
            key="avoid_red",
            value="Red",
            op="neq",
            statement="I generally avoid Red boots.",
        )
        customer.preferences.append(PersistentPreference.model_validate(dislike))
        task = validate_dataset(self.data, self.catalogue)[0]
        events = [
            SimpleNamespace(
                type="model_request",
                turn_id="test",
                payload={
                    "messages": [
                        {
                            "content": json.dumps(
                                {
                                    "user_memory": {
                                        "records": [
                                            {
                                                "id": "memory-blue",
                                                "category": "preference",
                                                "attribute": "color",
                                                "value": "Blue",
                                                "scope": "boots",
                                            }
                                        ]
                                    }
                                }
                            )
                        }
                    ]
                },
            )
        ]
        audit = memory_audit(events, customer, task, CatalogueOracle(self.catalogue))
        self.assertEqual(audit["flags"], [])

    def test_mocked_ollama_transport_records_private_context_and_tokens(self):
        transport = F.FakeOllama()
        shopper = OllamaShopper(self.config.simulator, transport=transport)
        run_longitudinal(self.config, simulator=shopper, policy=MemoryPolicy())
        report = json.loads((self.config.output / "report.json").read_text())
        usage = report["conditions"]["user_memory_on"]["resources"]["simulator_usage"]
        self.assertGreater(usage["prompt_tokens"], 0)
        self.assertGreater(usage["completion_tokens"], 0)
        self.assertTrue(
            any(
                "private-current-background" in p["messages"][0]["content"]
                for p in transport.payloads
            )
        )
        self.assertTrue(all("witness_id" not in str(p) for p in transport.payloads))

    def test_cli_dry_run_never_loads_credentials_or_contacts_models(self):
        args = [
            "longitudinal",
            "--customers",
            str(self.path),
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--output",
            str(self.config.output),
        ]
        with (
            patch(
                "shopping_agent.provider.DeepSeekPolicy.from_env_file",
                side_effect=AssertionError("credentials forbidden"),
            ),
            patch(
                "astra_eval.simulators._post_json",
                side_effect=AssertionError("network forbidden"),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(args), 0)
        self.assertIn('"sessions": 8', output.getvalue())
        self.assertFalse(self.config.output.exists())

    def test_live_flag_requires_explicit_budget_before_model_composition(self):
        args = [
            "longitudinal",
            "--customers",
            str(self.path),
            "--catalogue",
            str(self.catalogue),
            "--index",
            str(self.index),
            "--output",
            str(self.config.output),
            "--live",
        ]
        with patch(
            "shopping_agent.provider.DeepSeekPolicy.from_env_file",
            side_effect=AssertionError("must not compose"),
        ):
            self.assertEqual(main(args), 2)
        self.assertFalse(self.config.output.exists())

    def test_existing_report_command_dispatches_longitudinal_mode(self):
        self.rows()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["report", str(self.config.output)]), 0)
        self.assertIn("Returning-customer development evaluation", output.getvalue())
        self.assertEqual(
            json.loads((self.config.output / "report.json").read_text())[
                "evaluation_mode"
            ],
            "longitudinal_user_memory",
        )
