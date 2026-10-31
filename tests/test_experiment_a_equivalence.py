import json
import shutil
import unittest

import test_experiment_a_run as fixtures

from experiments.experiment_a.verify_equivalence import compare


class EquivalenceTests(fixtures.RunnerCase):
    def copy_with(self, mutate):
        other = self.root / "other"
        shutil.copytree(self.frozen, other)
        path = other / "baseline.json"
        data = json.loads(path.read_text())
        mutate(data)
        path.write_text(json.dumps(data))
        return other

    def test_opaque_ids_search_ids_and_float_noise_are_equivalent(self):
        def renamed(data):
            for entry in data.values():
                entry["search_result"]["search_id"] = "different"
                entry["search_result"]["candidates"][0]["bm25"] *= 1 + 2e-16
                ids = {
                    r["id"]: f"opaque{i}"
                    for i, r in enumerate(entry["state"]["requirements"])
                }
                users = {
                    r["source_event_id"]: "opaque-user"
                    for r in entry["state"]["requirements"]
                }
                for r in entry["state"]["requirements"]:
                    r["id"], r["source_event_id"] = ids[r["id"]], "opaque-user"
                result = entry["search_result"]
                for c in result["candidates"]:
                    c["matched_hard_ids"] = [ids[i] for i in c["matched_hard_ids"]]
                for f in result["applied_hard_filters"]:
                    f["id"], f["source_event_id"] = (
                        ids[f["id"]],
                        users[f["source_event_id"]],
                    )

        self.assertTrue(all(compare(self.frozen, self.copy_with(renamed)).values()))

    def test_any_substantive_change_is_detected(self):
        def reorder(d):
            for e in d.values():
                e["search_result"]["candidates"].reverse()

        def count(d):
            next(iter(d.values()))["search_result"]["counts"]["lexical_matches"] += 1

        def requirement(d):
            next(iter(d.values()))["state"]["requirements"][0]["value"] = 1.0

        def title(d):
            next(iter(d.values()))["search_result"]["candidates"][0]["title"] = "x"

        for mutate, check in [
            (reorder, "candidate_order_equal"),
            (count, "counts_equal"),
            (requirement, "requirement_content_equal_except_ids"),
            (title, "card_evidence_equal_after_id_mapping"),
        ]:
            with self.subTest(check=check):
                self.assertFalse(
                    compare(self.frozen, self.copy_with_fresh(mutate))[check]
                )

    def copy_with_fresh(self, mutate):
        other = self.root / "other"
        if other.exists():
            shutil.rmtree(other)
        return self.copy_with(mutate)

    def test_changed_labels_are_detected(self):
        other = self.copy_with(lambda d: None)
        (other / "qrels.json").write_text((other / "qrels.json").read_text() + " ")
        self.assertFalse(compare(self.frozen, other)["qrels.json"])


if __name__ == "__main__":
    unittest.main()
