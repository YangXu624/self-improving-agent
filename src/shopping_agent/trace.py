"""Structured execution trace extraction, stage profiling, and error diagnosis.

Transforms raw session event logs into an observable 13-stage execution trace:
1. Receive customer message
2. Retrieve user memories
3. Retrieve procedural memories
4. Build agent context
5. Call DeepSeek (LLM)
6. Parse and validate model output
7. Execute product search
8. Filter hard-ineligible candidates
9. Apply soft preference ranking
10. Generate recommendations or clarifying questions
11. Finalize session
12. Consolidate user memories
13. Distill/store procedural lessons (when enabled)

Includes automated root-cause failure diagnosis for transparent debugging.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

StageStatus = Literal["pending", "running", "completed", "skipped", "blocked", "failed"]


@dataclass
class StageRecord:
    stage_id: str
    name: str
    status: StageStatus = "pending"
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: float = 0.0
    summary: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    diagnostic_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STAGE_DEFINITIONS = [
    ("receive_message", "1. Receive Customer Message"),
    ("retrieve_user_memory", "2. Retrieve User Memories"),
    ("retrieve_procedural_memory", "3. Retrieve Procedural Memories"),
    ("build_context", "4. Build Agent Context"),
    ("call_llm", "5. Call Model Policy"),
    ("parse_validate_output", "6. Parse & Validate Model Output"),
    ("execute_search", "7. Execute Product Search"),
    ("filter_hard_constraints", "8. Filter Hard Constraints"),
    ("apply_soft_preferences", "9. Apply Soft Preferences"),
    ("generate_response", "10. Generate Recommendation / Clarification"),
    ("finalize_session", "11. Finalize Session"),
    ("consolidate_user_memory", "12. Consolidate User Memories"),
    ("distill_procedural_memory", "13. Distill Procedural Lessons"),
]


def diagnose_turn_failure(events: list[dict], result: dict | None = None) -> str | None:
    """Analyze turn events to produce a clear, human-understandable failure diagnosis."""
    # Check for turn completion / closure events
    failed_event = next(
        (
            e
            for e in events
            if e.get("type") in {"turn_failed", "turn_closed_safely", "model_error"}
        ),
        None,
    )
    rejections = [e for e in events if e.get("type") == "decision_rejected"]
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    search_results = [e for e in events if e.get("type") == "search_result"]
    responses = [e for e in events if e.get("type") == "model_response"]

    # 1. Budget limits reached
    if failed_event:
        payload = failed_event.get("payload", {})
        code = payload.get("code") or payload.get("closure") or payload.get("reason")
        if code == "decision_budget_exhausted":
            return f"Decision call limit reached: {len(responses)}/{len(responses)} model calls used this turn without reaching a valid terminal action."
        if code == "search_budget_exhausted":
            return f"Search limit reached: {len(tool_calls)} searches used this turn. No further searches allowed."
        if code == "search_requires_a_remaining_decision_call":
            return "Search blocked on final call: executing a search requires at least one remaining decision call to view and verify candidate products."
        if code == "repeated_empty_search":
            return "Search blocked: the model repeated an identical search query that already returned 0 eligible products earlier in this turn."
        if code == "no_match":
            return "NO_MATCH: 0 eligible products in catalogue after fallback. Customer prompted to relax constraints."
        if code == "provider_network_failure":
            return "LLM API network failure: unable to connect to model endpoint or socket timed out."
        if str(code).startswith("provider_http_"):
            return f"LLM API HTTP error ({code}): upstream provider rejected or failed the request."

    completed_events = [e for e in events if e.get("type") == "turn_completed"]
    if completed_events:
        comp_payload = completed_events[-1].get("payload", {})
        if (
            comp_payload.get("action") == "NO_MATCH"
            or comp_payload.get("status") == "no_match"
        ):
            return "NO_MATCH: 0 eligible products in catalogue after fallback. Customer prompted to relax constraints."

    # 2. Check search result candidate emptiness
    for sr in search_results:
        counts = sr.get("payload", {}).get("counts", {})
        lex = counts.get("lexical_matches", 0)
        elig = counts.get("verified_eligible", 0)
        if lex > 0 and elig == 0:
            fb = sr.get("payload", {}).get("fallback_triggered", False)
            fb_str = " (fallback attempted)" if fb else ""
            return f"Catalogue constraint conflict: FTS matched {lex:,} products, but 0 passed hard constraint verification{fb_str}."
        if lex == 0:
            return "Search returned 0 lexical matches: no products in the 50k catalogue matched the query terms."

    # 3. Check decision schema validation rejections
    if rejections:
        last_rej = rejections[-1].get("payload", {})
        reason = last_rej.get("code") or last_rej.get("reason")
        if reason:
            return f"Model output rejected by Python validator: {reason}"

    # 4. Check user memory rejections
    um_rejections = [
        e for e in events if e.get("type") == "user_memory_update_rejected"
    ]
    if um_rejections:
        code = um_rejections[-1].get("payload", {}).get("code", "unknown")
        return f"User memory proposal rejected: {code}"

    # 5. Check result error string
    if result and result.get("error"):
        return f"Turn error: {result['error']}"

    return None


class TraceExtractor:
    """Extracts organized 13-stage execution traces from authoritative session events."""

    @classmethod
    def extract_turn_trace(
        cls,
        events: list[dict],
        request_id: str | None = None,
        turn_result: dict | None = None,
    ) -> list[StageRecord]:
        """Build stage records for a specific turn request ID (or full session)."""
        turn_events = (
            [e for e in events if e.get("turn_id") == request_id]
            if request_id
            else events
        )

        stages: dict[str, StageRecord] = {
            sid: StageRecord(stage_id=sid, name=sname)
            for sid, sname in STAGE_DEFINITIONS
        }

        # 1. Receive Customer Message
        user_ev = next(
            (e for e in turn_events if e.get("type") == "user_message"), None
        )
        if user_ev:
            stages["receive_message"].status = "completed"
            stages[
                "receive_message"
            ].summary = (
                f'Customer: "{user_ev.get("payload", {}).get("message", "")[:100]}"'
            )
            stages["receive_message"].inputs = {
                "message": user_ev.get("payload", {}).get("message")
            }
            stages["receive_message"].outputs = {"event_id": user_ev.get("event_id")}

        # 2. Retrieve User Memories
        mem_sel = next(
            (e for e in turn_events if e.get("type") == "user_memory_selection"), None
        )
        mem_inj = next(
            (e for e in turn_events if e.get("type") == "user_memory_injection"), None
        )
        if mem_sel:
            retrieved = mem_sel.get("payload", {}).get("retrieved", [])
            injected = mem_inj.get("payload", {}).get("injected", []) if mem_inj else []
            stages["retrieve_user_memory"].status = "completed"
            stages[
                "retrieve_user_memory"
            ].summary = f"{len(retrieved)} retrieved · {len(injected)} injected (profile v{mem_sel.get('payload', {}).get('revision', 0)})"
            stages["retrieve_user_memory"].metrics = {
                "retrieved_count": len(retrieved),
                "injected_count": len(injected),
                "retrieved_ids": retrieved,
                "injected_ids": injected,
            }
        else:
            stages["retrieve_user_memory"].status = "skipped"
            stages[
                "retrieve_user_memory"
            ].summary = "User memory disabled or not retrieved."

        purch_ev = next(
            (e for e in turn_events if e.get("type") == "purchase_evidence_used"), None
        )
        if purch_ev:
            p_count = purch_ev.get("payload", {}).get("count", 0)
            if stages["retrieve_user_memory"].status == "skipped":
                stages["retrieve_user_memory"].status = "completed"
                stages[
                    "retrieve_user_memory"
                ].summary = f"{p_count} past purchase(s) retrieved as context"
            else:
                stages[
                    "retrieve_user_memory"
                ].summary += f" · {p_count} past purchase(s) retrieved"
            stages["retrieve_user_memory"].metrics["purchases_retrieved"] = p_count

        # 3. Retrieve Procedural Memories
        exp_sel = next(
            (e for e in turn_events if e.get("type") == "experience_selection"), None
        )
        if exp_sel:
            selected = exp_sel.get("payload", {}).get("selected", [])
            stages["retrieve_procedural_memory"].status = (
                "completed" if selected else "skipped"
            )
            stages[
                "retrieve_procedural_memory"
            ].summary = f"{len(selected)} procedural lesson(s) active"
            stages["retrieve_procedural_memory"].metrics = {"selected_ids": selected}
        else:
            stages["retrieve_procedural_memory"].status = "skipped"
            stages[
                "retrieve_procedural_memory"
            ].summary = "Procedural memory disabled or 0 lessons matched."

        # 4. Build Agent Context
        model_req = next(
            (e for e in turn_events if e.get("type") == "model_request"), None
        )
        if model_req:
            stages["build_context"].status = "completed"
            payload = model_req.get("payload", {})
            msgs = payload.get("messages", [])
            msg_len = sum(len(m.get("content", "")) for m in msgs)
            stages[
                "build_context"
            ].summary = f"{len(msgs)} messages assembled (~{msg_len:,} chars, {payload.get('cards_profile', 'baseline')} profile)"
            stages["build_context"].metrics = {
                "message_count": len(msgs),
                "total_chars": msg_len,
                "prompt_version": payload.get("prompt_version"),
            }

        # 5. Call Model Policy
        model_resps = [e for e in turn_events if e.get("type") == "model_response"]
        model_errors = [e for e in turn_events if e.get("type") == "model_error"]
        if model_resps:
            total_prompt_tok = sum(
                e.get("payload", {})
                .get("metadata", {})
                .get("usage", {})
                .get("prompt_tokens", 0)
                for e in model_resps
            )
            total_compl_tok = sum(
                e.get("payload", {})
                .get("metadata", {})
                .get("usage", {})
                .get("completion_tokens", 0)
                for e in model_resps
            )
            total_dur = sum(
                e.get("payload", {}).get("duration_seconds", 0.0) for e in model_resps
            )
            stages["call_llm"].status = "completed"
            stages["call_llm"].duration_ms = round(total_dur * 1000, 1)
            stages[
                "call_llm"
            ].summary = f"{len(model_resps)} API call(s) · {total_prompt_tok:,} in / {total_compl_tok:,} out · {total_dur:.2f}s"
            stages["call_llm"].metrics = {
                "calls": len(model_resps),
                "prompt_tokens": total_prompt_tok,
                "completion_tokens": total_compl_tok,
                "total_tokens": total_prompt_tok + total_compl_tok,
                "duration_seconds": round(total_dur, 2),
            }
        elif model_errors:
            stages["call_llm"].status = "failed"
            stages["call_llm"].failure_reason = (
                model_errors[0].get("payload", {}).get("code")
            )
            stages[
                "call_llm"
            ].summary = f"API error: {stages['call_llm'].failure_reason}"

        # 6. Parse & Validate Model Output
        decisions = [e for e in turn_events if e.get("type") == "decision_validated"]
        rejections = [e for e in turn_events if e.get("type") == "decision_rejected"]
        if decisions:
            last_dec = decisions[-1].get("payload", {})
            stages["parse_validate_output"].status = "completed"
            stages[
                "parse_validate_output"
            ].summary = f"Valid {last_dec.get('action', {}).get('type', 'UNKNOWN')} action validated ({len(decisions)} decision(s) parsed)"
            stages["parse_validate_output"].outputs = {
                "action_type": last_dec.get("action", {}).get("type"),
                "reason": last_dec.get("reason", "")[:120],
            }
        elif rejections:
            stages["parse_validate_output"].status = "failed"
            stages["parse_validate_output"].failure_reason = (
                rejections[-1].get("payload", {}).get("code")
            )
            stages[
                "parse_validate_output"
            ].summary = (
                f"Validation failed: {stages['parse_validate_output'].failure_reason}"
            )

        # 7. Execute Product Search
        searches = [e for e in turn_events if e.get("type") == "search_result"]
        tool_calls = [e for e in turn_events if e.get("type") == "tool_call"]
        if searches:
            last_s = searches[-1].get("payload", {})
            counts = last_s.get("counts", {})
            fb = last_s.get("fallback_triggered", False)
            fb_reason = last_s.get("fallback_reason")
            stages["execute_search"].status = "completed"
            stages[
                "execute_search"
            ].summary = f"{counts.get('lexical_matches', 0):,} matches · query '{tool_calls[-1].get('payload', {}).get('action', {}).get('query', '') if tool_calls else ''}'"
            if fb:
                stages["execute_search"].summary += f" [Fallback: {fb_reason}]"
            stages["execute_search"].metrics = {
                "lexical_matches": counts.get("lexical_matches", 0),
                "fallback_triggered": fb,
                "fallback_reason": fb_reason,
            }
        else:
            stages["execute_search"].status = "skipped"
            stages["execute_search"].summary = "No search required this turn."

        # 8. Filter Hard Constraints
        if searches:
            last_s = searches[-1].get("payload", {})
            counts = last_s.get("counts", {})
            elig = counts.get("verified_eligible", 0)
            excl = counts.get("products_excluded_by_hard_constraints", 0)
            unk = counts.get("products_with_unknown_required_attributes", 0)
            stages["filter_hard_constraints"].status = (
                "completed" if elig > 0 else "failed"
            )
            stages[
                "filter_hard_constraints"
            ].summary = f"{elig:,} verified eligible · {excl:,} failed constraints · {unk:,} missing attributes"
            stages["filter_hard_constraints"].metrics = {
                "verified_eligible": elig,
                "excluded": excl,
                "unknown_attributes": unk,
            }
            if elig == 0:
                stages[
                    "filter_hard_constraints"
                ].failure_reason = "zero_eligible_candidates"
        else:
            stages["filter_hard_constraints"].status = "skipped"
            stages[
                "filter_hard_constraints"
            ].summary = "No candidate filtering evaluated."

        # 9. Apply Soft Preferences
        if searches:
            last_s = searches[-1].get("payload", {})
            candidates = last_s.get("candidates", [])
            stages["apply_soft_preferences"].status = "completed"
            pref_matches = sum(len(c.get("matched_soft_ids", [])) for c in candidates)
            stages[
                "apply_soft_preferences"
            ].summary = f"{len(candidates)} candidates scored · {pref_matches} soft preference matches"
            stages["apply_soft_preferences"].metrics = {
                "candidates_ranked": len(candidates),
                "soft_matches": pref_matches,
            }
        else:
            stages["apply_soft_preferences"].status = "skipped"
            stages["apply_soft_preferences"].summary = "No candidate pool to rank."

        # 10. Generate Recommendation / Clarification
        recs = [e for e in turn_events if e.get("type") == "recommendation"]
        completed_ev = next(
            (e for e in turn_events if e.get("type") == "turn_completed"), None
        )
        if recs:
            stages["generate_response"].status = "completed"
            prod_ids = recs[-1].get("payload", {}).get("product_ids", [])
            q = recs[-1].get("payload", {}).get("follow_up_question", "")
            stages[
                "generate_response"
            ].summary = (
                f"RECOMMEND: {len(prod_ids)} verified product(s) + follow-up question"
            )
            stages["generate_response"].outputs = {
                "product_ids": prod_ids,
                "follow_up_question": q,
            }
        elif completed_ev:
            action = completed_ev.get("payload", {}).get("action", "RESPOND")
            status = completed_ev.get("payload", {}).get("status", "ok")
            if action == "NO_MATCH" or status == "no_match":
                stages["generate_response"].status = "failed"
                stages[
                    "generate_response"
                ].summary = "NO_MATCH: No products match all constraints; asked customer to relax criteria"
                stages["generate_response"].outputs = {"action": "NO_MATCH"}
            else:
                stages["generate_response"].status = "completed"
                stages["generate_response"].summary = f"{action}: Response generated"
                stages["generate_response"].outputs = {"action": action}
        elif any(
            e.get("type") in {"turn_failed", "turn_closed_safely"} for e in turn_events
        ):
            stages["generate_response"].status = "failed"
            stages[
                "generate_response"
            ].summary = "Turn terminated with closure message."

        # 11 & 12. Finalize Session & Consolidate User Memories
        fin_ev = next((e for e in events if e.get("type") == "session_finalized"), None)
        if fin_ev:
            payload = fin_ev.get("payload", {})
            stages["finalize_session"].status = "completed"
            stages[
                "finalize_session"
            ].summary = f"Status: {payload.get('status')} (Revision v{payload.get('revision', 0)})"

            stages["consolidate_user_memory"].status = (
                "completed"
                if payload.get("status") in {"success", "idempotent"}
                else "skipped"
            )
            applied = payload.get("operations_applied", [])
            stages[
                "consolidate_user_memory"
            ].summary = f"{len(applied)} preference(s) recorded: {payload.get('reason', '')[:80]}"
            reinf_ev = next(
                (
                    e
                    for e in events
                    if e.get("type") == "memory_reinforced_from_purchase"
                ),
                None,
            )
            if reinf_ev:
                reinf_ops = reinf_ev.get("payload", {}).get("operations", [])
                stages[
                    "consolidate_user_memory"
                ].summary += f" · {len(reinf_ops)} reinforced from purchase evidence"
                stages["consolidate_user_memory"].metrics[
                    "reinforced_from_purchase"
                ] = len(reinf_ops)
            stages["consolidate_user_memory"].outputs = {"operations": applied}
        else:
            stages["finalize_session"].status = "pending"
            stages[
                "finalize_session"
            ].summary = (
                "Session active (click 'Finish Session & Save Memory' to finalize)"
            )
            stages["consolidate_user_memory"].status = "pending"
            stages["consolidate_user_memory"].summary = "Awaiting session finalization"

        # 13. Distill Procedural Lessons
        distill_ev = next(
            (e for e in events if e.get("type") == "procedural_distillation"), None
        )
        if distill_ev:
            stages["distill_procedural_memory"].status = "completed"
            stages[
                "distill_procedural_memory"
            ].summary = f"Distillation: {distill_ev.get('payload', {}).get('outcome', 'complete')}"
        else:
            stages["distill_procedural_memory"].status = "skipped"
            stages[
                "distill_procedural_memory"
            ].summary = "Procedural distillation disabled or offline."

        # Diagnostic message enrichment
        diag = diagnose_turn_failure(turn_events, turn_result)
        for s in stages.values():
            if s.status == "failed" and not s.diagnostic_message:
                s.diagnostic_message = diag

        return list(stages.values())

    @classmethod
    def export_session_json(
        cls, session_id: str, events: list[dict], user_id: str
    ) -> str:
        """Export session activity log and structured execution trace as a clean JSON document."""

        trace = cls.extract_turn_trace(events)
        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "exported_at": datetime.now(UTC).isoformat(),
            "event_count": len(events),
            "stages": [s.to_dict() for s in trace],
            "events": events,
        }
        return json.dumps(doc, indent=2, ensure_ascii=False)
