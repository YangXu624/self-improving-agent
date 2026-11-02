"""Offline contract comparison using original ASTRA fixtures and real framework graphs."""

import importlib.util
import json
import socket
import unittest

if importlib.util.find_spec("langchain") is None:
    raise unittest.SkipTest("Install optional langchain extra for framework tests")
from unittest.mock import patch

import test_agent as fixtures
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from test_agent import decision, recommend, search
from test_user_memory import preference

from astra_eval.target_scoring import TargetRule
from astra_langchain.workflow import LangChainShoppingAgent
from shopping_agent.sessions import SessionError
from shopping_agent.user_memory import UserMemoryStore


class ScriptedChat(BaseChatModel):
    """Fixture model through real create_agent, not a mock of the orchestration."""

    steps: list = Field(default_factory=list)
    contexts: list = Field(default_factory=list)
    bound: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "offline-astra-fixture"

    def bind_tools(self, tools, **kwargs):
        self.bound[:] = [t.name for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        context = json.loads(messages[-1].content)
        self.contexts.append(context)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        value = step(context) if callable(step) else step
        if isinstance(value, AIMessage):
            message = value
        else:
            name = {
                "SEARCH": "search_products",
                "RECOMMEND": "recommend_products",
                "CLARIFY": "clarify",
                "RESPOND": "respond",
            }[value["action"]["type"]]
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": name,
                        "args": value,
                        "id": f"call-{len(self.contexts)}",
                        "type": "tool_call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


def respond(ctx):
    return decision(ctx, {"type": "RESPOND", "message": "Ready."})


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        fixtures.AgentTests.setUp(self)
        self.addCleanup(patch.stopall)
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        ).start()
        self.memory = UserMemoryStore(self.root / "memory")

    def agent(self, *steps, **options):
        self.model = ScriptedChat(steps=list(steps))
        return LangChainShoppingAgent(self.store, self.search, self.model, **options)

    def events(self):
        return fixtures.AgentTests.events(self)

    def test_search_recommend_and_target_scoring(self):
        result = self.agent(search, recommend).turn("alice", self.sid, "boots")
        self.assertEqual(result["action"], "RECOMMEND", result)
        self.assertEqual(result["budget_used"], {"model_calls": 2, "searches": 1})
        ids = [p["id"] for p in result["products"]]
        self.assertEqual(TargetRule(ids[0]).check(result, ids), 1)
        self.assertIn("search_products", self.model.bound)

    def test_clarify_then_constrain(self):
        self.agent(
            lambda c: decision(
                c,
                {"type": "CLARIFY", "attribute": "price", "question": "Budget in USD?"},
            )
        ).turn("alice", self.sid, "boots")
        from test_sessions import add

        result = self.agent(
            lambda c: search(c, [add(value=60.0, quote="under 60 USD").model_dump()]),
            recommend,
        ).turn("alice", self.sid, "under 60 USD")
        self.assertEqual([p["id"] for p in result["products"]], ["cheap"])

    def test_unseen_id_rejected_then_repaired(self):
        result = self.agent(
            search, lambda c: recommend(c, ["invented"]), recommend
        ).turn("alice", self.sid, "boots")
        self.assertEqual(result["action"], "RECOMMEND")
        self.assertEqual(result["budget_used"]["model_calls"], 3)
        self.assertIn(
            "recommendation_contains_unseen_product_id",
            json.dumps([e.payload for e in self.events()]),
        )

    def test_budget_no_final_search(self):
        result = self.agent(search, max_calls=1).turn("alice", self.sid, "boots")
        self.assertEqual(result["budget_used"], {"model_calls": 1, "searches": 0})
        self.assertEqual(result["closure"], "search_requires_a_remaining_decision_call")

    def test_empty_search_deduplicated(self):
        def empty(c):
            return decision(c, {"type": "SEARCH", "query": "nonexistent"})

        result = self.agent(empty, empty, empty).turn("alice", self.sid, "nonexistent")
        self.assertEqual(result["budget_used"], {"model_calls": 3, "searches": 1})
        self.assertEqual(result["closure"], "repeated_empty_search")

    def test_memory_staged_then_consolidated_and_cross_session(self):
        def remember(c):
            d = respond(c)
            d["user_memory_updates"] = [preference().model_dump()]
            return d

        self.agent(remember, user_memory=self.memory).turn(
            "alice", self.sid, preference().quote
        )
        self.assertEqual(self.memory.read("alice").records, [])
        self.agent(respond, user_memory=self.memory).turn(
            "alice", self.sid, "thanks", end_session=True
        )
        self.assertEqual(self.memory.read("alice").records[0].value, "blue")
        second = self.store.create("alice")
        self.agent(respond, user_memory=self.memory).turn("alice", second, "bags")
        self.assertEqual(
            self.model.contexts[0]["user_memory"]["records"][0]["value"], "blue"
        )
        with self.assertRaises(SessionError):
            self.agent(respond).turn("alice", self.sid, "reopen")

    def test_off_and_owner_isolation(self):
        self.agent(respond).turn("alice", self.sid, "bags")
        self.assertNotIn("user_memory", self.model.contexts[0])
        self.assertFalse(self.memory.directory("alice").exists())
        with self.assertRaises(PermissionError):
            self.agent(respond).turn("bob", self.sid, "bags")
        bob = self.store.create("bob")
        self.agent(respond, user_memory=self.memory).turn("bob", bob, "bags")
        self.assertEqual(self.model.contexts[0]["user_memory"]["records"], [])

    def test_request_replay_no_second_model_call(self):
        agent = self.agent(respond)
        first = agent.turn("alice", self.sid, "hello", request_id="same")
        self.assertEqual(
            first, agent.turn("alice", self.sid, "hello", request_id="same")
        )
        self.assertEqual(len(self.model.contexts), 1)
        with self.assertRaises(SessionError):
            agent.turn("alice", self.sid, "changed", request_id="same")

    def test_provider_failure_safe_no_retries(self):
        result = self.agent(RuntimeError("SECRET remote payload"), respond).turn(
            "alice", self.sid, "boots"
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self.model.contexts), 1)
        self.assertNotIn("SECRET", json.dumps([e.payload for e in self.events()]))

    def test_bare_or_parallel_outputs_fail_before_tools(self):
        for output in [
            AIMessage(content="fabricated products"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "respond", "args": {}, "id": "a", "type": "tool_call"},
                    {"name": "respond", "args": {}, "id": "b", "type": "tool_call"},
                ],
            ),
        ]:
            sid = self.store.create("alice")
            result = self.agent(output).turn("alice", sid, "boots")
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["budget_used"]["searches"], 0)

    def test_scoped_central_lessons_retrieved_injected_and_applied(self):
        from shopping_agent.experience.extractor import extract_candidate_lesson
        from shopping_agent.experience.store import ExperienceStore

        with ExperienceStore(self.root / "experience.sqlite") as experience:
            lesson = extract_candidate_lesson(
                {
                    "scenario_id": "synthetic",
                    "turns": [
                        {"action": "SEARCH", "counts": [{"verified_eligible": 0}]}
                    ],
                },
                {"termination": "synthetic"},
            )
            experience.add_candidate(lesson)
            experience.confirm(
                lesson.lesson_id, review_notes="Synthetic test fixture only"
            )
            for owner in ["alice", "bob"]:
                sid = self.store.create(owner)
                result = self.agent(search, recommend, experience=experience).turn(
                    owner, sid, "boots"
                )
                self.assertIn(lesson.lesson_id, result["experience"]["retrieved"])
                self.assertIn(lesson.lesson_id, result["experience"]["injected"])
                self.assertIn(lesson.lesson_id, result["experience"]["applied"])

    def test_end_session_procedural_candidate_requires_learning_opt_in(self):
        from shopping_agent.experience.store import ExperienceStore

        def empty(c):
            return decision(c, {"type": "SEARCH", "query": "nonexistent"})

        with ExperienceStore(self.root / "experience.sqlite") as experience:
            self.agent(empty, respond, experience=experience).turn(
                "alice", self.sid, "nonexistent", end_session=True
            )
            self.assertEqual(experience.list_lessons(), [])
            sid = self.store.create("alice")
            self.agent(empty, respond, experience=experience, learn=True).turn(
                "alice", sid, "nonexistent", end_session=True
            )
            lessons = experience.list_lessons()
            self.assertEqual(len(lessons), 1)
            self.assertEqual(lessons[0].status, "candidate")
            self.assertNotIn("alice", json.dumps(lessons[0].to_dict()))
            self.assertNotIn(sid, json.dumps(lessons[0].to_dict()))
            self.assertEqual(
                experience.retrieve("initial_query", context_cues={"is_initial": True}),
                [],
            )

    def test_sqlite_checkpoint_inspection_and_restart(self):
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = str(self.root / "checkpoints.sqlite")
        with SqliteSaver.from_conn_string(path) as saver:
            first = self.agent(search, recommend, checkpointer=saver).turn(
                "alice", self.sid, "boots", request_id="check"
            )
            checkpoints = list(saver.list(None))
            self.assertGreater(len(checkpoints), 5)
            self.assertEqual(
                checkpoints[0].checkpoint["channel_values"]["phase"], "persist"
            )
        with SqliteSaver.from_conn_string(path) as saver:
            model = self.agent(checkpointer=saver)
            self.assertEqual(
                first, model.turn("alice", self.sid, "boots", request_id="check")
            )
            self.assertEqual(self.model.contexts, [])

    def test_invalid_tool_schema_feedback_then_repair(self):
        invalid = AIMessage(
            content="",
            tool_calls=[
                {"name": "respond", "args": {}, "id": "bad", "type": "tool_call"}
            ],
        )
        result = self.agent(invalid, respond).turn("alice", self.sid, "hello")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            self.model.contexts[1]["validation_feedback"],
            [{"code": "invalid_tool_arguments"}],
        )

    def test_memory_off_rejects_proposals_in_schema(self):
        def bad(c):
            value = respond(c)
            value["user_memory_updates"] = [preference().model_dump()]
            return value

        result = self.agent(bad, respond).turn(
            "alice", self.sid, preference().quote, end_session=True
        )
        self.assertEqual(result["status"], "ok")
        self.assertFalse(
            any(e.type == "framework_memory_staged" for e in self.events())
        )
        self.assertFalse(self.memory.directory("alice").exists())

    def test_current_state_edit_invalidates_previous_visible_search(self):
        from test_sessions import add

        self.agent(search, recommend).turn("alice", self.sid, "boots")

        def bad(c):
            d = recommend(c)
            d["updates"] = [add(value=60.0, quote="under 60").model_dump()]
            return d

        result = self.agent(bad, search, recommend).turn("alice", self.sid, "under 60")
        self.assertEqual([p["id"] for p in result["products"]], ["cheap"])
        self.assertEqual(result["budget_used"]["model_calls"], 3)
        self.assertIsNone(self.model.contexts[1]["latest_search"])

    def test_conditional_color_hardening_rejected_and_repaired(self):
        from test_sessions import add

        def colored(c, strength):
            update = add("color", "eq", "Black", "Black").model_dump()
            update["requirement"]["strength"] = strength
            return decision(c, {"type": "RESPOND", "message": "Noted."}, [update])

        result = self.agent(
            lambda c: colored(c, "hard"), lambda c: colored(c, "soft")
        ).turn("alice", self.sid, "Black if you have it")
        self.assertEqual(result["status"], "ok")
        with self.store.open("alice", self.sid) as session:
            self.assertEqual(session.state.requirements[0].strength, "soft")

    def test_concurrent_profile_revision_is_not_overwritten_at_session_end(self):
        def remember(c):
            d = respond(c)
            d["user_memory_updates"] = [preference().model_dump()]
            return d

        self.agent(remember, user_memory=self.memory).turn(
            "alice", self.sid, preference().quote
        )
        other = self.store.create("alice")
        self.agent(remember, user_memory=self.memory).turn(
            "alice", other, preference().quote, end_session=True
        )
        result = self.agent(respond, user_memory=self.memory).turn(
            "alice", self.sid, "done", end_session=True
        )
        self.assertIn(
            "user_memory_revision_conflict", result["user_memory"]["rejected"]
        )
        self.assertEqual(self.memory.read("alice").revision, 1)

    def test_memory_write_failure_not_claimed_as_completed(self):
        def remember(c):
            d = respond(c)
            d["user_memory_updates"] = [preference().model_dump()]
            return d

        with patch.object(
            self.memory, "apply", side_effect=OSError("fixture disk failure")
        ):
            with self.assertRaises(OSError):
                self.agent(remember, user_memory=self.memory).turn(
                    "alice",
                    self.sid,
                    preference().quote,
                    end_session=True,
                    request_id="failed",
                )
        self.assertFalse(any(e.type == "turn_completed" for e in self.events()))
        with self.assertRaises(SessionError):
            self.agent(respond).turn(
                "alice",
                self.sid,
                preference().quote,
                end_session=True,
                request_id="failed",
            )

    def test_shared_fixtures_match_baseline_results_and_call_counts(self):
        from shopping_agent.agent import ShoppingAgent

        scenarios = [
            ("boots", [search, recommend]),
            ("hello", [respond]),
            ("boots", [search, lambda c: recommend(c, ["invented"]), recommend]),
        ]
        for message, steps in scenarios:
            with self.subTest(message=message, steps=len(steps)):
                original = ShoppingAgent(
                    self.store, self.search, fixtures.ScriptedPolicy(*steps)
                )
                baseline = original.turn(
                    "baseline", self.store.create("baseline"), message
                )
                alternative = self.agent(*steps).turn(
                    "alternative", self.store.create("alternative"), message
                )
                for key in ["status", "action", "budget_used", "state_version"]:
                    self.assertEqual(baseline[key], alternative[key])
                self.assertEqual(baseline["products"], alternative["products"])

    def test_unchanged_dialogue_runner_and_target_score(self):
        from test_target_qa import PatientShopper, TargetQATests

        from astra_eval.dialogue import DialogueRunner
        from astra_eval.target_scoring import TargetRule

        fixture = TargetQATests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        model = ScriptedChat(steps=[fixture.search, recommend])
        agent = LangChainShoppingAgent(fixture.store, fixture.tool, model)
        runner = DialogueRunner(
            agent, fixture.store, PatientShopper(), run_id="framework-test"
        )
        record = runner.run(fixture.scenario(), target_rule=TargetRule("Boots-0"))
        self.assertEqual(record.termination, "target_found")
        self.assertEqual(record.target_hit["rank"], 1)
        self.assertEqual(record.turns[0].model_calls, 2)
        from astra_eval.oracle import CatalogueOracle
        from astra_eval.target_scoring import target_score

        scored = target_score(
            record,
            fixture.truth(target="Boots-0"),
            CatalogueOracle(fixture.catalogue),
            max_turns=3,
        )
        self.assertEqual(scored["first_hit_mrr_at_k"], 1.0)
        self.assertNotIn('"target_id"', json.dumps(model.contexts))

    def test_currency_guard_preserved(self):
        from test_sessions import add

        def euros(c):
            return search(c, [add(value=60.0, quote="under 60 EUR").model_dump()])

        result = self.agent(euros, search, search).turn(
            "alice", self.sid, "under 60 EUR"
        )
        self.assertEqual(result["budget_used"]["searches"], 0)
        self.assertEqual(result["closure"], "budget_currency_not_supported")

    def test_conflicting_constraints_block_search(self):
        from test_sessions import add

        def conflicting(c):
            return search(
                c,
                [
                    add(value=40.0, quote="under 40").model_dump(),
                    add("price", "gt", 80.0, "over 80").model_dump(),
                ],
            )

        result = self.agent(conflicting, search, search).turn(
            "alice", self.sid, "under 40 and over 80"
        )
        self.assertEqual(result["budget_used"]["searches"], 0)
        self.assertEqual(result["status"], "error")

    def test_off_session_end_never_reads_or_writes_memory(self):
        with (
            patch.object(
                UserMemoryStore, "context", side_effect=AssertionError("OFF read")
            ),
            patch.object(
                UserMemoryStore, "apply", side_effect=AssertionError("OFF write")
            ),
        ):
            result = self.agent(respond).turn(
                "alice", self.sid, "hello", end_session=True
            )
        self.assertEqual(result["status"], "ok")

    def test_memory_consolidation_correction_across_sessions(self):
        def remember(c):
            value = respond(c)
            value["user_memory_updates"] = [preference().model_dump()]
            return value

        self.agent(remember, user_memory=self.memory).turn(
            "alice", self.sid, preference().quote, end_session=True
        )
        sid = self.store.create("alice")
        quote = "Actually I now generally prefer black bags instead of blue"

        def correct(c):
            value = respond(c)
            value["user_memory_updates"] = [
                preference(
                    value="black",
                    quote=quote,
                    op="REPLACE",
                    target_id=c["user_memory"]["records"][0]["id"],
                ).model_dump()
            ]
            return value

        self.agent(correct, user_memory=self.memory).turn(
            "alice", sid, quote, end_session=True
        )
        profile = self.memory.read("alice")
        self.assertEqual(
            [r.value for r in profile.records if r.status == "active"], ["black"]
        )
        self.assertEqual(profile.records[0].status, "superseded")
