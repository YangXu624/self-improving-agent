"""Multi-turn dialogue between a simulated shopper and ASTRA, with a per-turn trace.

The runner owns the loop; it never scores. ASTRA receives only the shopper's messages. The
shopper receives only ASTRA's visible words and product cards. Ground truth is used here
for one thing only: an audit that the shopper did not leak a product identifier or title.
"""

import time
from dataclasses import dataclass, field

from shopping_agent.sessions import SessionError

from .consistency import ConsistencyConfig, check_reply, errors
from .memory import AssistantView, ContextBudgetError, ShopperMemory, Transcript
from .simulators import SimulatorError

BUDGET_ERRORS = {"decision_budget_exhausted", "search_budget_exhausted"}
PROVIDER_PREFIX = "provider_"


class SimulatorFailure(RuntimeError):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass
class AgentTurn:
    turn: int
    request_id: str
    status: str
    action: str
    message: str
    recommended_ids: list = field(default_factory=list)
    candidates_seen: list = field(default_factory=list)
    counts: list = field(default_factory=list)
    model_calls: int = 0
    searches: int = 0
    error: str | None = None
    closure: str | None = None
    rejected_decisions: int = 0
    usage: dict = field(default_factory=dict)
    model_seconds: float = 0.0
    wall_ms: float = 0.0


@dataclass
class SessionRecord:
    scenario_id: str
    condition: str
    astra_session_id: str
    termination: str = "running"
    turns: list = field(default_factory=list)
    final_requirements: list = field(default_factory=list)
    simulator: dict = field(default_factory=dict)
    transcript: tuple = ()
    ledger: dict = field(default_factory=dict)
    repeated_questions: int = 0
    unmatched_questions: int = 0
    error: str | None = None


def card(product):
    facts = product.get("facts") or {}
    return {
        "id": product.get("id"),
        "title": product.get("title", ""),
        "price": facts.get("price"),
    }


def extract_turn(events, request_id, response, turn, wall_ms):
    """Summarise one agent turn from ASTRA's own authoritative event log."""
    mine = [e for e in events if e.turn_id == request_id]
    usage, seconds, seen, counts, recommended = {}, 0.0, [], [], []
    rejected, failure = 0, None
    for event in mine:
        payload = event.payload
        if event.type == "model_response":
            seconds += float(payload.get("duration_seconds") or 0)
            for key, value in (payload.get("metadata", {}).get("usage") or {}).items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
        elif event.type == "search_result":
            seen.append([c["id"] for c in payload.get("candidates", [])])
            counts.append(payload.get("counts", {}))
        elif event.type == "recommendation":
            recommended = list(payload.get("product_ids", []))
        elif event.type == "decision_rejected":
            rejected += 1
        elif event.type == "turn_failed":
            failure = payload.get("code")
    budget = response.get("budget_used", {})
    return AgentTurn(
        turn=turn,
        request_id=request_id,
        status=response.get("status", "error"),
        action=response.get("action", ""),
        message=response.get("message", ""),
        recommended_ids=recommended,
        candidates_seen=seen,
        counts=counts,
        model_calls=budget.get("model_calls", 0),
        searches=budget.get("searches", 0),
        error=response.get("error") or failure,
        closure=response.get("closure"),
        rejected_decisions=rejected,
        usage=usage,
        model_seconds=seconds,
        wall_ms=wall_ms,
    )


class DialogueRunner:
    def __init__(
        self,
        agent,
        store,
        simulator,
        *,
        run_id,
        user_id="eval-shopper",
        consistency=None,
        consistency_retries=1,
        budget=None,
    ):
        self.agent, self.store, self.simulator = agent, store, simulator
        self.run_id, self.user_id = run_id, user_id
        self.consistency = consistency or ConsistencyConfig()
        self.consistency_retries = consistency_retries
        self.budget = budget

    def shopper_reply(self, memory, view, forbidden, stats):
        feedback, last = [], []
        for attempt in range(1 + self.consistency_retries):
            try:
                result = self.simulator.respond(memory, view, tuple(feedback))
            except SimulatorError as exc:
                raise SimulatorFailure(exc.code) from None
            except ContextBudgetError:
                raise SimulatorFailure("simulator_context_overflow") from None
            stats["calls"] += 1
            stats["attempts"] += result.attempts
            stats["context_entries_dropped"] += result.prompt_info.get(
                "dialogue_entries_dropped_for_budget", 0
            )
            for key in ("prompt_tokens", "completion_tokens", "latency_ms"):
                value = result.usage.get(key)
                if isinstance(value, (int, float)):
                    stats["usage"][key] = stats["usage"].get(key, 0) + value
            violations = check_reply(
                result.reply,
                memory.profile,
                shown_text=view.text
                + " "
                + " ".join(p.get("title", "") for p in view.products),
                shown_prices=[
                    p["price"]
                    for p in view.products
                    if isinstance(p.get("price"), (int, float))
                ],
                has_products=bool(view.products),
                forbidden=forbidden,
                config=self.consistency,
            )
            for v in violations:
                stats["violations"][v.code] = stats["violations"].get(v.code, 0) + 1
            hard = errors(violations)
            if not hard:
                return result.reply, [v.code for v in violations]
            stats["consistency_retries"] += 1
            feedback = [f"{v.code}: {v.detail}".strip(": ") for v in hard]
            last = [v.code for v in hard]
        raise SimulatorFailure("simulator_inconsistent", ",".join(last))

    def run(
        self, scenario, *, condition="memory_off", transcript_path=None, forbidden=()
    ):
        sid = self.store.create(self.user_id)
        record = SessionRecord(scenario.id, condition, sid)
        memory = ShopperMemory(
            scenario.profile,
            window_turns=self.simulator.config.window_turns,
            transcript=Transcript(transcript_path),
        )
        stats = {
            "calls": 0,
            "attempts": 0,
            "consistency_retries": 0,
            "context_entries_dropped": 0,
            "violations": {},
            "usage": {},
        }
        message = scenario.opening
        memory.record_shopper(1, message, scenario.profile.opening_keys)
        consecutive_errors = 0
        for turn in range(1, scenario.max_user_turns + 1):
            if self.budget is not None and not self.budget.allow(self.agent.max_calls):
                record.termination = "run_budget_exhausted"
                break
            started = time.perf_counter()
            try:
                response = self.agent.turn(
                    self.user_id,
                    sid,
                    message,
                    request_id=f"{self.run_id}-{scenario.id}-{condition}-{turn}",
                )
            except (SessionError, ValueError) as exc:
                record.termination, record.error = "agent_exception", type(exc).__name__
                break
            wall_ms = (time.perf_counter() - started) * 1000
            with self.store.open(self.user_id, sid) as session:
                agent_turn = extract_turn(
                    session.events, response["request_id"], response, turn, wall_ms
                )
            record.turns.append(agent_turn)
            if self.budget is not None:
                self.budget.charge(agent_turn.model_calls)
            view = AssistantView(
                text=agent_turn.message,
                products=tuple(card(p) for p in response.get("products", [])),
                turn=turn,
                turns_left=scenario.max_user_turns - turn,
            )
            memory.record_assistant(
                view,
                extra={
                    "status": agent_turn.status,
                    "action": agent_turn.action,
                    "searches": agent_turn.searches,
                    "recommended": agent_turn.recommended_ids,
                    "error": agent_turn.error,
                },
            )
            if agent_turn.status != "ok":
                consecutive_errors += 1
                if str(agent_turn.error).startswith(PROVIDER_PREFIX):
                    record.termination, record.error = (
                        "provider_error",
                        agent_turn.error,
                    )
                    break
                if consecutive_errors >= 2:
                    record.termination = "agent_error"
                    break
            else:
                consecutive_errors = 0
            if turn == scenario.max_user_turns:
                record.termination = "max_turns"
                break
            try:
                reply, flags = self.shopper_reply(memory, view, forbidden, stats)
            except SimulatorFailure as failure:
                record.termination, record.error = (
                    "simulator_failure",
                    failure.code + (f":{failure.detail}" if failure.detail else ""),
                )
                memory.transcript.append(
                    {
                        "role": "simulator_audit",
                        "turn": turn + 1,
                        "failure": failure.code,
                        "detail": failure.detail,
                    }
                )
                break
            memory.apply(turn + 1, reply, flags)
            if reply.action == "accept":
                record.termination = "accepted"
                break
            if reply.action == "give_up":
                record.termination = "gave_up"
                break
            message = reply.message
        else:  # pragma: no cover - loop always breaks at max_turns
            record.termination = "max_turns"
        with self.store.open(self.user_id, sid) as session:
            record.final_requirements = [
                {"field": r.field, "op": r.op, "value": r.value, "strength": r.strength}
                for r in session.state.requirements
                if r.status == "active"
            ]
        record.simulator = stats
        record.transcript = memory.transcript.entries
        record.ledger = memory.ledger()
        record.repeated_questions = sum(memory.repeat_counts.values())
        record.unmatched_questions = memory.unmatched_questions
        return record
