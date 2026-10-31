"""Independent target-item cutoff, integrity, source-generation and scoring regressions."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_agent import ScriptedPolicy, decision

from astra_eval.dialogue import AgentTurn, DialogueRunner, SessionRecord
from astra_eval.experiment import ExperimentConfig, run_experiment
from astra_eval.models import (
    Fact,
    Scenario,
    ShopperProfile,
    ShopperReply,
    TargetGroundTruth,
)
from astra_eval.oracle import CatalogueOracle
from astra_eval.scenarios import save
from astra_eval.scoring import ScoreConfig
from astra_eval.simulators import SimulatorConfig, SimulatorResult
from astra_eval.target_scenarios import TargetPool, generate_targets
from astra_eval.target_scoring import TargetRule, target_score
from shopping_agent.agent import ShoppingAgent
from shopping_agent.provider import PolicyReply
from shopping_agent.retrieval import LexicalSearch, build_index
from shopping_agent.sessions import SessionStore


class PatientShopper:
    def __init__(self, *, accept=False):
        self.config = SimulatorConfig()
        self.calls = []
        self.accept = accept

    def respond(self, memory, view, feedback=()):
        self.calls.append((memory.profile.model_dump(), view))
        return SimulatorResult(
            ShopperReply(
                message="Those look good." if self.accept else "Please continue.",
                reveals=[],
                action="accept" if self.accept else "reply",
            )
        )


class TargetQATests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.catalogue = self.root / "catalogue.jsonl"
        self.rows = []
        for leaf in ("Boots", "Sandals", "Wallets", "Scarves"):
            for index in range(4):
                self.rows.append(
                    {
                        "parent_asin": f"{leaf}-{index}",
                        "title": f"Catalogue {leaf} unique edition {index}",
                        "categories": ["Fashion", leaf],
                        "details": {
                            "Department": "Men",
                            "Color": "Red" if index < 2 else "Blue",
                            "Brand": "Acme" if index < 2 else "Zenith",
                            "Material": "Cotton",
                        },
                        "features": [],
                        "description": [],
                        "price": 10.0 if index < 2 else 20.0 if index == 2 else None,
                    }
                )
        self.catalogue.write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        index = self.root / "index.sqlite"
        build_index(self.catalogue, index)
        self.tool = LexicalSearch(index)
        self.addCleanup(self.tool.close)
        self.store = SessionStore(self.root / "sessions")
        self.type_fact = Fact(
            key="type",
            kind="hard",
            field="product_type",
            op="contains",
            value="Boots",
            statement="I need boots.",
            keywords=["type", "kind"],
        )

    def scenario(self, turns=3):
        return Scenario(
            id="independent-target-fixture",
            split="development",
            family="Boots",
            kind="underspecified",
            opening="I need boots.",
            max_user_turns=turns,
            profile=ShopperProfile(
                scenario_id="independent-target-fixture",
                persona="Brief shopper.",
                facts=(self.type_fact,),
                opening_keys=("type",),
            ),
        )

    @staticmethod
    def search(ctx):
        return decision(ctx, {"type": "SEARCH", "query": "boots"})

    @staticmethod
    def recommend(*ids):
        return lambda c: decision(
            c,
            {
                "type": "RECOMMEND",
                "search_id": c["latest_search"]["search_id"],
                "product_ids": list(ids),
            },
        )

    @staticmethod
    def respond(ctx):
        return decision(ctx, {"type": "RESPOND", "message": "Please continue."})

    def run_dialogue(self, *steps, turns=3, target="Boots-2", k=5, shopper=None, **kw):
        self.policy = ScriptedPolicy(*steps)
        self.shopper = shopper or PatientShopper()
        agent = ShoppingAgent(self.store, self.tool, self.policy)
        runner = DialogueRunner(agent, self.store, self.shopper, run_id="qa-target")
        return runner.run(self.scenario(turns), target_rule=TargetRule(target, k), **kw)

    def truth(self, target="Boots-2", hard=None):
        return TargetGroundTruth(
            scenario_id="independent-target-fixture",
            target_id=target,
            catalogue_sha256=CatalogueOracle(self.catalogue).sha256,
            profile_sha256="fixture-profile-hash",
            hard=hard or [self.type_fact],
            ambiguity="no_target" if target is None else "ambiguous",
            compatible_count=0 if target is None else 4,
            compatible_ids_sha256="fixture-compatible-hash",
        )

    def test_first_turn_hit_stops_before_any_shopper_call(self):
        record = self.run_dialogue(self.search, self.recommend("Boots-0", "Boots-2"))
        self.assertEqual(record.termination, "target_found")
        self.assertEqual(record.target_hit["turn"], 1)
        self.assertEqual(record.target_hit["rank"], 2)
        self.assertEqual(self.shopper.calls, [])
        self.assertEqual(record.simulator["calls"], 0)
        self.assertEqual(len(self.policy.contexts), 2)
        self.assertEqual(sum(t.model_calls for t in record.turns), 2)
        self.assertEqual(record.turns[0].presented_ids, ["Boots-0", "Boots-2"])

    def test_hit_on_last_permitted_turn_wins_before_exhaustion(self):
        record = self.run_dialogue(
            self.respond, self.search, self.recommend("Boots-2"), turns=2
        )
        self.assertEqual(record.termination, "target_found")
        self.assertEqual(record.target_hit["turn"], 2)
        self.assertEqual(len(self.shopper.calls), 1)
        self.assertEqual(len(self.policy.contexts), 3)

    def test_late_hit_preserves_first_hit_rank_and_all_pre_hit_resources(self):
        record = self.run_dialogue(
            self.search,
            self.recommend("Boots-0"),
            self.recommend("Boots-1", "Boots-2"),
            turns=4,
        )
        self.assertEqual(record.target_hit["turn"], 2)
        self.assertEqual(len(self.shopper.calls), 1)
        scored = target_score(
            record, self.truth(), CatalogueOracle(self.catalogue), max_turns=4
        )
        self.assertEqual(scored["first_hit_mrr_at_k"], 0.5)
        self.assertEqual(scored["first_success_turn"], 2)
        self.assertEqual(scored["penalized_turns"], 2)
        self.assertEqual(scored["resources"]["model_calls"], 3)
        self.assertEqual(scored["resources"]["searches"], 1)

    def test_target_outside_primary_k_is_not_success(self):
        record = self.run_dialogue(
            self.search, self.recommend("Boots-0", "Boots-2"), turns=1, k=1
        )
        self.assertEqual(record.termination, "max_turns")
        self.assertIsNone(record.target_hit)
        scored = target_score(
            record,
            self.truth(),
            CatalogueOracle(self.catalogue),
            ScoreConfig(headline_k=1),
            max_turns=1,
        )
        self.assertFalse(scored["hit_at_k"])
        self.assertEqual(scored["first_hit_mrr_at_k"], 0)
        self.assertEqual(scored["penalized_turns"], 2)
        self.assertEqual(scored["resources"]["model_calls"], 2)

    def test_retrieved_target_without_presented_recommendation_does_not_count(self):
        record = self.run_dialogue(self.search, self.respond, turns=1)
        self.assertIn("Boots-2", record.turns[0].candidates_seen[0])
        self.assertEqual(record.turns[0].presented_ids, [])
        self.assertIsNone(record.target_hit)

    def test_incidental_target_text_does_not_count(self):
        record = self.run_dialogue(
            lambda c: decision(
                c, {"type": "RESPOND", "message": "Boots-2 was mentioned."}
            ),
            turns=1,
        )
        self.assertIsNone(record.target_hit)
        self.assertEqual(record.turns[0].presented_ids, [])

    def test_shopper_accepting_wrong_product_never_creates_target_success(self):
        record = self.run_dialogue(
            self.search, self.recommend("Boots-0"), shopper=PatientShopper(accept=True)
        )
        self.assertEqual(record.termination, "shopper_ended")
        self.assertIsNone(record.target_hit)
        scored = target_score(
            record, self.truth(), CatalogueOracle(self.catalogue), max_turns=3
        )
        self.assertEqual(scored["outcome"], "failure")
        self.assertFalse(scored["hit_at_k"])

    def test_recommendation_response_order_must_match_authoritative_event(self):
        rule = TargetRule("target", 5)
        response = {
            "status": "ok",
            "action": "RECOMMEND",
            "products": [{"id": "other"}, {"id": "target"}],
        }
        self.assertEqual(rule.check(response, ["other", "target"]), 2)
        for event_ids in (["target", "other"], ["other"], []):
            with self.subTest(event_ids=event_ids), self.assertRaises(ValueError):
                rule.check(response, event_ids)
        for cards in ([{"id": "target"}, {"id": "target"}], [], [{"id": ""}]):
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                rule.check({**response, "products": cards}, [p["id"] for p in cards])

    def test_error_or_nonrecommendation_does_not_qualify_and_k_is_bounded(self):
        for status, action in (
            ("error", "RECOMMEND"),
            ("ok", "RESPOND"),
            ("ok", "SEARCH"),
        ):
            with self.subTest(status=status, action=action):
                self.assertIsNone(
                    TargetRule("target").check(
                        {
                            "status": status,
                            "action": action,
                            "products": [{"id": "target"}],
                        },
                        [],
                    )
                )
        for k in (0, 6, -1):
            with self.subTest(k=k), self.assertRaises(ValueError):
                TargetRule("target", k)

    def test_session_call_cap_prevents_calls_before_insufficient_reservation(self):
        record = self.run_dialogue(
            self.search, self.recommend("Boots-2"), session_max_calls=2
        )
        self.assertEqual(record.termination, "budget_exhausted")
        self.assertEqual(record.error, "session_model_call_reservation")
        self.assertEqual(self.policy.contexts, [])
        self.assertEqual(self.shopper.calls, [])

    def test_exact_session_reservation_allows_last_turn_success(self):
        record = self.run_dialogue(
            self.search, self.recommend("Boots-2"), session_max_calls=3, turns=1
        )
        self.assertEqual(record.termination, "target_found")
        self.assertEqual(sum(t.model_calls for t in record.turns), 2)

    def test_target_metadata_is_not_sent_to_agent_or_shopper(self):
        record = self.run_dialogue(
            self.respond, self.search, self.recommend("Boots-2"), turns=2
        )
        self.assertEqual(record.termination, "target_found")
        for context in self.policy.contexts:
            for hidden in (
                "target_id",
                "target_title",
                "compatible_ids_sha256",
                "profile_sha256",
            ):
                self.assertNotIn(hidden, json.dumps(context))
        self.assertEqual(len(self.shopper.calls), 1)
        profile, view = self.shopper.calls[0]
        self.assertNotIn("target_id", json.dumps(profile))
        self.assertEqual(view.products, ())
        self.assertNotIn("Boots-2", json.dumps(profile))

    def test_scoring_invalidates_forged_target_hit_proof(self):
        record = self.run_dialogue(self.search, self.recommend("Boots-2"))
        record.target_hit["rank"] = 2
        scored = target_score(
            record, self.truth(), CatalogueOracle(self.catalogue), max_turns=3
        )
        self.assertFalse(scored["valid"])
        self.assertEqual(scored["termination"], "harness_error")
        self.assertFalse(scored["hit_at_k"])
        self.assertEqual(scored["first_hit_mrr_at_k"], 0)
        self.assertEqual(scored["resources"]["model_calls"], 2)

    def test_runner_invalidates_response_event_order_mismatch_before_shopper(self):
        policy = ScriptedPolicy(self.search, self.recommend("Boots-0", "Boots-2"))
        agent = ShoppingAgent(self.store, self.tool, policy)

        class ReorderedResponse:
            max_calls = agent.max_calls

            @staticmethod
            def turn(*args, **kwargs):
                response = copy.deepcopy(agent.turn(*args, **kwargs))
                response["products"].reverse()
                return response

        shopper = PatientShopper()
        runner = DialogueRunner(
            ReorderedResponse(), self.store, shopper, run_id="qa-integrity"
        )
        record = runner.run(self.scenario(), target_rule=TargetRule("Boots-2"))
        self.assertEqual(record.termination, "harness_error")
        self.assertIsNone(record.target_hit)
        self.assertEqual(shopper.calls, [])
        self.assertEqual(len(policy.contexts), 2)
        self.assertEqual(record.turns[0].model_calls, 2)
        scored = target_score(
            record, self.truth(), CatalogueOracle(self.catalogue), max_turns=3
        )
        self.assertFalse(scored["valid"])
        self.assertEqual(scored["outcome"], "failure")

    def test_no_target_false_recommendation_is_not_grounded_abstention(self):
        record = self.run_dialogue(
            self.search, self.recommend("Boots-0"), turns=1, target=None
        )
        budget = Fact(
            key="budget",
            kind="hard",
            field="price",
            op="lt",
            value=1.0,
            statement="Under 1 USD.",
            keywords=["budget"],
        )
        scored = target_score(
            record,
            self.truth(None, [self.type_fact, budget]),
            CatalogueOracle(self.catalogue),
            max_turns=1,
        )
        self.assertFalse(scored["grounded_abstention"])
        self.assertTrue(scored["false_recommendation"])
        self.assertEqual(scored["violations"]["hard_fail"], 1)

    def test_invalid_first_session_is_saved_and_batch_continues(self):
        scenarios, truths, manifest = generate_targets(
            self.catalogue, seed=73, per_split={"development": 2}, max_user_turns=1
        )
        frozen = self.root / "target-scenarios"
        save(frozen, scenarios, truths, manifest)
        changed = {"done": False}

        class GenericPolicy:
            @staticmethod
            def complete(messages):
                ctx = json.loads(messages[-1]["content"])
                result = ctx["latest_search"]
                if result:
                    action = {
                        "type": "RECOMMEND",
                        "search_id": result["search_id"],
                        "product_ids": [p["id"] for p in result["candidates"][:2]],
                    }
                else:
                    leaf = next(
                        name
                        for name in ("boots", "sandals", "wallets", "scarves")
                        if name in ctx["current_user_message"].lower()
                    )
                    action = {"type": "SEARCH", "query": leaf}
                return PolicyReply(
                    json.dumps(decision(ctx, action)), {"provider": "fixture"}
                )

        def factory(condition, store, search, policy, **kwargs):
            real = ShoppingAgent(store, search, policy, **kwargs)

            class OneMismatch:
                max_calls = real.max_calls

                @staticmethod
                def turn(*args, **turn_kwargs):
                    response = copy.deepcopy(real.turn(*args, **turn_kwargs))
                    if response["action"] == "RECOMMEND" and not changed["done"]:
                        response["products"].reverse()
                        changed["done"] = True
                    return response

            return OneMismatch()

        config = ExperimentConfig(
            scenarios_dir=frozen,
            catalogue=self.catalogue,
            index=self.root / "index.sqlite",
            output=self.root / "batch",
            evaluation_mode="target_item",
            session_max_model_calls=3,
            score=ScoreConfig(headline_k=5),
        )
        summary = run_experiment(
            config,
            simulator=PatientShopper(),
            policy=GenericPolicy(),
            agent_factory=factory,
        )
        self.assertEqual(summary["sessions"], 2)
        self.assertIsNone(summary["stopped_early"])
        with (config.output / "results.jsonl").open() as results:
            saved = [json.loads(line) for line in results]
        self.assertEqual(saved[0]["score"]["termination"], "harness_error")
        self.assertFalse(saved[0]["score"]["valid"])
        self.assertEqual(saved[0]["score"]["resources"]["model_calls"], 2)
        self.assertTrue(saved[1]["score"]["valid"])

    def test_empty_response_is_not_grounded_no_target_abstention(self):
        budget = Fact(
            key="budget",
            kind="hard",
            field="price",
            op="lt",
            value=1.0,
            statement="Under 1 USD.",
            keywords=["budget"],
        )
        truth = self.truth(None, [self.type_fact, budget])
        base = SessionRecord(
            "independent-target-fixture",
            "memory_off",
            "fixture",
            termination="max_turns",
        )
        base.final_requirements = [
            {k: v for k, v in f.model_dump().items() if k in {"field", "op", "value"}}
            | {"strength": "hard"}
            for f in truth.hard
        ]
        base.turns = [
            AgentTurn(
                1, "request", "ok", "RESPOND", "No verified matches.", model_calls=1
            )
        ]
        scored = target_score(base, truth, CatalogueOracle(self.catalogue), max_turns=2)
        self.assertFalse(scored["grounded_abstention"])
        base.turns[0].counts = [{"verified_eligible": 0}]
        scored = target_score(base, truth, CatalogueOracle(self.catalogue), max_turns=2)
        self.assertTrue(scored["grounded_abstention"])
        base.turns[0].message = "Please continue."
        self.assertFalse(
            target_score(base, truth, CatalogueOracle(self.catalogue), max_turns=2)[
                "grounded_abstention"
            ]
        )

    def test_source_population_ambiguity_is_reported_without_hints(self):
        pool = TargetPool(self.catalogue)
        audit = pool.audit()
        self.assertEqual(audit["catalogue_products"], 16)
        self.assertEqual(
            audit["counts"],
            {"ambiguous": 8, "distinguishable": 4, "insufficient_evidence": 4},
        )
        self.assertEqual(pool.matches["Boots-0"], {"Boots-0", "Boots-1"})
        self.assertEqual(pool.matches["Boots-2"], {"Boots-2"})
        self.assertNotIn("Boots-3", pool.profiles)

    def test_generation_is_deterministic_separate_and_profiles_are_source_grounded(
        self,
    ):
        options = dict(
            seed=73, per_split={"development": 1, "held_out": 1}, no_target_per_split=1
        )
        first = generate_targets(self.catalogue, **options)
        second = generate_targets(self.catalogue, **options)
        self.assertEqual(first, second)
        scenarios, truths, manifest = first
        self.assertEqual(len(scenarios), 4)
        self.assertEqual(manifest["evaluation_mode"], "target_item")
        families = {}
        for scenario, truth in zip(scenarios, truths, strict=True):
            self.assertEqual(
                families.setdefault(scenario.family, scenario.split), scenario.split
            )
            serialized = json.dumps(scenario.model_dump())
            self.assertNotIn("target_id", serialized)
            self.assertNotIn("target_title", serialized)
            self.assertNotIn("compatible_count", serialized)
            self.assertEqual(
                truth.profile_sha256,
                hashlib.sha256(
                    json.dumps(
                        scenario.profile.model_dump(),
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
            )
            if truth.target_id is None:
                self.assertEqual(truth.compatible_count, 0)
                continue
            self.assertNotIn(truth.target_id, serialized)
            self.assertNotIn(truth.target_title, serialized)
            row = next(r for r in self.rows if r["parent_asin"] == truth.target_id)
            for fact in scenario.profile.facts:
                if fact.field == "product_type":
                    self.assertEqual(fact.value.lower(), row["categories"][-1].lower())
                elif fact.field == "price":
                    self.assertGreater(fact.value, row["price"])
                    self.assertEqual(fact.value % 10, 0)
                else:
                    key = {
                        "department": "Department",
                        "brand": "Brand",
                        "color": "Color",
                        "material": "Material",
                        "size": "Size",
                    }[fact.field]
                    self.assertEqual(fact.value.lower(), row["details"][key].lower())

    def test_optional_identity_or_exact_title_fields_are_not_disclosed(self):
        row = copy.deepcopy(self.rows[0])
        row["parent_asin"] = "B012345678"
        row["details"]["Brand"] = "B012345678"
        row["details"]["Color"] = row["title"]
        source = self.root / "identity-details.jsonl"
        source.write_text(json.dumps(row) + "\n")
        profile = TargetPool(source).profiles[row["parent_asin"]]
        payload = json.dumps([f.model_dump() for f in profile])
        self.assertNotIn(row["parent_asin"], payload)
        self.assertNotIn(row["title"], payload)

    def test_ambiguous_targets_stay_ambiguous_without_identifying_hints(self):
        scenarios, truths, _ = generate_targets(
            self.catalogue,
            seed=73,
            per_split={"development": 1, "held_out": 1},
            group="ambiguous",
        )
        self.assertEqual(len(truths), 2)
        for scenario, truth in zip(scenarios, truths, strict=True):
            self.assertEqual(truth.ambiguity, "ambiguous")
            self.assertEqual(truth.compatible_count, 2)
            self.assertEqual(len(scenario.profile.facts), 6)
            self.assertNotIn(truth.target_id, json.dumps(scenario.model_dump()))
            self.assertNotIn(truth.target_title, json.dumps(scenario.model_dump()))

    def test_insufficient_targets_raise_instead_of_inventing_hints_or_shrinking(self):
        with self.assertRaisesRegex(ValueError, "eligible"):
            generate_targets(
                self.catalogue, seed=73, per_split={"development": 10, "held_out": 1}
            )

    def test_identity_like_category_cannot_leak_target_through_type_or_opening(self):
        row = copy.deepcopy(self.rows[0])
        row["parent_asin"] = "B012345678"
        row["categories"] = ["Fashion", "B012345678"]
        row["title"] = "Unique title"
        source = self.root / "identity-category.jsonl"
        source.write_text(json.dumps(row) + "\n")
        pool = TargetPool(source)
        self.assertEqual(pool.groups[row["parent_asin"]], "insufficient_evidence")
        self.assertNotIn(row["parent_asin"], pool.profiles)


if __name__ == "__main__":
    unittest.main()
