import copy
import tempfile
import unittest
from pathlib import Path

from longitudinal_fixtures import make_dataset

from astra_eval.customers import (
    CustomerDataset,
    compile_visit,
    load_customers,
    validate_dataset,
)


class CustomerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path, self.catalogue, self.index, self.data = make_dataset(Path(temp.name))

    def test_frozen_evidence_and_existing_contracts(self):
        compiled = validate_dataset(load_customers(self.path), self.catalogue)
        self.assertEqual(len(compiled), 4)
        self.assertTrue(all(c.target_truth.compatible_count == 1 for c in compiled))
        self.assertTrue(all(c.preference_truth.acceptable_count == 3 for c in compiled))
        self.assertTrue(
            all(c.scenario.profile.scenario_id == c.visit.task_id for c in compiled)
        )

    def test_current_boundary_no_future_or_truth_in_roleplay(self):
        customer = self.data.customers[0]
        first, private, _ = compile_visit(customer, customer.visits[0])
        self.assertEqual(private["background"], "private-current-background")
        self.assertNotIn("private-future-change", str(private))
        self.assertNotIn("witness_id", str(private))
        _, later, _ = compile_visit(customer, customer.visits[2])
        self.assertEqual(later["background"], "private-future-change")
        self.assertEqual(
            later["current_persistent_preferences"][0]["fact"]["value"], "Red"
        )
        self.assertNotIn("visits", private)
        self.assertEqual(first.profile.facts[-1].value, "Blue")

    def test_forged_evidence_wrong_catalogue_unknown_attribute_rejected(self):
        wrong = self.data.model_copy(deep=True)
        wrong.catalogue_sha256 = "wrong"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_dataset(wrong, self.catalogue)
        wrong = self.data.model_copy(deep=True)
        wrong.customers[0].visits[0].evidence.acceptable_count = 999
        with self.assertRaisesRegex(ValueError, "evidence mismatch"):
            validate_dataset(wrong, self.catalogue)
        wrong = self.data.model_copy(deep=True)
        wrong.customers[0].preferences[0].fact.value = "unsupported"
        with self.assertRaisesRegex(ValueError, "witness|Disclosure"):
            validate_dataset(wrong, self.catalogue)

    def test_order_identity_and_gift_scope_validation(self):
        raw = self.data.model_dump()
        wrong = copy.deepcopy(raw)
        wrong["customers"][0]["visits"][1]["sequence"] = 7
        with self.assertRaises(ValueError):
            CustomerDataset.model_validate(wrong)
        wrong = copy.deepcopy(raw)
        wrong["customers"].append(wrong["customers"][0])
        with self.assertRaises(ValueError):
            CustomerDataset.model_validate(wrong)
        customer = self.data.customers[0].model_copy(deep=True)
        customer.visits[3].persistent_keys = ["color"]
        with self.assertRaisesRegex(ValueError, "Gift scoring"):
            compile_visit(customer, customer.visits[3])

    def test_opening_requires_supported_disclosures(self):
        customer = self.data.customers[0]
        visit = customer.visits[0].model_copy(deep=True)
        visit.opening = "Something else"
        with self.assertRaisesRegex(ValueError, "Opening keys"):
            compile_visit(customer, visit)

    def test_statement_cannot_disagree_with_frozen_value_or_operator(self):
        customer = self.data.customers[0].model_copy(deep=True)
        customer.preferences[0].fact.statement = "I generally prefer Red boots."
        customer.visits[0].opening = "I need boots. I generally prefer Red boots."
        with self.assertRaisesRegex(ValueError, "Disclosure statement"):
            validate_dataset(
                self.data.model_copy(update={"customers": [customer]}), self.catalogue
            )
        customer = self.data.customers[0].model_copy(deep=True)
        customer.visits[0].hard[1].statement = "My budget is over $60."
        with self.assertRaisesRegex(ValueError, "Disclosure|operator"):
            compile_visit(customer, customer.visits[0])

    def test_witness_source_uses_usable_alias(self):
        import json

        from shopping_agent.retrieval import file_hash

        rows = [json.loads(line) for line in self.catalogue.read_text().splitlines()]
        rows[0]["details"]["Color"] = True
        rows[0]["details"]["Colour"] = "Blue"
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.data.catalogue_sha256 = file_hash(self.catalogue)
        result = validate_dataset(self.data, self.catalogue, require_evidence=False)
        self.assertEqual(result[0].target_truth.evidence["color"], "details.Colour")
