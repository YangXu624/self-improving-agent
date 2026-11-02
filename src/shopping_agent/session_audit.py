"""Session Audit Explorer for ASTRA Developer Console.

Enables deep, comprehensive auditing of any shopping session:
- Complete conversation history distinguishing customer-visible from internal tool steps
- Full shopping-agent state inspector (requirements, constraints, candidate pool, budget)
- Turn-by-turn state transition history and before/after diffs (ADD, REPLACE, RETRACT, NEW_GOAL)
- User memory audit (eligible, selected, injected, consolidated, before/after profile diff)
- Tool execution, LLM metrics, token usage, latency, search filters, and raw JSON export
- Strict customer isolation ensuring authorized access only
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import streamlit as st

from .contracts import Event
from .sessions import MAX_EVENT_BYTES, SessionError
from .ui_service import ChatService


@dataclass
class TurnAuditRecord:
    turn_index: int
    request_id: str
    user_message: str | None = None
    assistant_message: str | None = None
    action_type: str | None = None
    recommended_product_ids: list[str] = field(default_factory=list)
    recommended_products: list[dict[str, Any]] = field(default_factory=list)
    follow_up_question: str | None = None
    internal_searches: list[dict[str, Any]] = field(default_factory=list)
    validation_rejections: list[dict[str, Any]] = field(default_factory=list)
    state_updates: list[dict[str, Any]] = field(default_factory=list)
    state_version_before: int = 0
    state_version_after: int = 0
    requirements_before: list[dict[str, Any]] = field(default_factory=list)
    requirements_after: list[dict[str, Any]] = field(default_factory=list)
    memories_selected: list[dict[str, Any]] = field(default_factory=list)
    memories_injected: list[dict[str, Any]] = field(default_factory=list)
    purchases: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class SessionAuditData:
    session_id: str
    user_id: str
    created_at: str
    finalized: bool
    finalization_details: dict[str, Any] | None = None
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    final_state: dict[str, Any] = field(default_factory=dict)
    total_turns: int = 0
    total_model_calls: int = 0
    total_searches: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0
    turns: list[TurnAuditRecord] = field(default_factory=list)
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    consolidation_audit: dict[str, Any] | None = None


def discover_available_sessions(
    service: ChatService,
    project_root: Path,
    current_owner: str,
) -> list[dict[str, Any]]:
    """Scan authorized sessions: manual sessions for current owner and eval runs."""
    results: list[dict[str, Any]] = []

    # 1. Manual Dev Sessions for current user
    try:
        manual_list = service.sessions(current_owner)
        for s in manual_list:
            results.append(
                {
                    "source": "Manual Dev Chat",
                    "customer_id": current_owner,
                    "session_id": s["id"],
                    "label": f"Manual Chat: {s['title']} ({s['created'][:16].replace('T', ' ')})",
                    "created": s["created"],
                    "finalized": s.get("finalized", False),
                    "store_root": service.store.root,
                }
            )
    except Exception:
        pass

    # 2. Synthetic Evaluation Runs Sessions in data/eval-ui/ and data/eval/
    candidate_roots = [
        project_root / "data/eval-ui",
        project_root / "data/eval/canaries",
        project_root / "data/eval/runs",
    ]
    for root in candidate_roots:
        if not root.exists():
            continue
        for run_folder in sorted(root.iterdir(), reverse=True):
            if not run_folder.is_dir():
                continue
            # Search for subdirectories ending in "sessions" or starting with "sessions"
            possible_sess_dirs = [
                run_folder / "user_memory_off" / "sessions",
                run_folder / "user_memory_on" / "sessions",
                run_folder / "sessions",
                run_folder / "sessions_visit1",
                run_folder / "sessions_visit2_off",
                run_folder / "sessions_visit2_on",
            ]
            for sess_dir in possible_sess_dirs:
                if sess_dir.exists() and sess_dir.is_dir():
                    for sfolder in sess_dir.iterdir():
                        if not sfolder.is_dir() or sfolder.is_symlink():
                            continue
                        events_file = sfolder / "events.jsonl"
                        if events_file.exists():
                            try:
                                with events_file.open("rb") as f:
                                    first_line = f.readline(MAX_EVENT_BYTES + 1)
                                first_ev = Event.model_validate_json(first_line)
                                cond_tag = (
                                    "Memory ON"
                                    if "on" in str(sess_dir).lower()
                                    else (
                                        "Memory OFF"
                                        if "off" in str(sess_dir).lower()
                                        else "Standard"
                                    )
                                )
                                results.append(
                                    {
                                        "source": f"Evaluation ({cond_tag})",
                                        "customer_id": first_ev.user_id,
                                        "session_id": sfolder.name,
                                        "label": f"[{cond_tag}] {first_ev.user_id} · {run_folder.name[:16]} ({first_ev.timestamp[:16].replace('T', ' ')})",
                                        "created": first_ev.timestamp,
                                        "finalized": True,
                                        "store_root": sess_dir,
                                    }
                                )
                            except Exception:
                                pass

    return results


def extract_session_audit(
    store_root: Path,
    user_id: str,
    session_id: str,
) -> SessionAuditData:
    """Read authoritative events.jsonl and build comprehensive audit records."""
    events_path = store_root / session_id / "events.jsonl"
    if not events_path.exists():
        raise SessionError(f"Session events not found: {session_id}")

    events: list[dict[str, Any]] = []
    with events_path.open("rb") as f:
        for line in f:
            if not line.strip():
                continue
            events.append(json.loads(line.decode("utf-8")))

    created_at = events[0].get("timestamp", "") if events else ""
    config_snapshot = {}
    finalized = False
    finalization_details = None
    consolidation_audit = None

    for ev in events:
        if ev.get("type") == "session_config_snapshot":
            config_snapshot = ev.get("payload", {}).get("runtime_config", {})
        elif ev.get("type") == "session_finalized":
            finalized = True
            finalization_details = ev.get("payload")
            if not consolidation_audit:
                consolidation_audit = ev.get("payload")
        elif ev.get("type") == "user_memory_consolidated":
            consolidation_audit = ev.get("payload")

    # Group events by turn request ID
    turns: list[TurnAuditRecord] = []
    current_turn: TurnAuditRecord | None = None
    turn_counter = 0

    running_requirements: list[dict[str, Any]] = []
    running_state_version = 0

    total_calls = 0
    total_searches = 0
    total_prompt_tok = 0
    total_compl_tok = 0
    total_dur = 0.0

    for ev in events:
        ev_type = ev.get("type")
        payload = ev.get("payload", {})
        req_id = ev.get("turn_id") or ""

        if ev_type == "turn_started":
            turn_counter += 1
            current_turn = TurnAuditRecord(
                turn_index=turn_counter,
                request_id=req_id,
                state_version_before=running_state_version,
                requirements_before=[dict(r) for r in running_requirements],
            )
            turns.append(current_turn)

        elif ev_type == "user_message":
            if not current_turn or current_turn.request_id != req_id:
                turn_counter += 1
                current_turn = TurnAuditRecord(
                    turn_index=turn_counter,
                    request_id=req_id,
                    state_version_before=running_state_version,
                    requirements_before=[dict(r) for r in running_requirements],
                )
                turns.append(current_turn)
            current_turn.user_message = payload.get("message", "")

        elif ev_type in {"state_committed", "state_updated"}:
            if current_turn:
                current_turn.state_version_after = (
                    ev.get("state_version")
                    or payload.get("version_after")
                    or (running_state_version + 1)
                )
                running_state_version = current_turn.state_version_after
                updates = payload.get("updates", [])
                current_turn.state_updates.extend(updates)

                # Reconstruct requirements
                if payload.get("requirements_after"):
                    running_requirements = list(payload.get("requirements_after", []))
                elif payload.get("state", {}).get("requirements"):
                    running_requirements = list(
                        payload.get("state", {}).get("requirements", [])
                    )
                else:
                    for u in updates:
                        op = u.get("op")
                        req = u.get("requirement")
                        if op == "ADD" and req:
                            running_requirements.append(req)
                        elif op == "REPLACE" and req:
                            old_id = u.get("target_id") or (
                                u.get("old_requirement") or {}
                            ).get("id")
                            running_requirements = [
                                r for r in running_requirements if r.get("id") != old_id
                            ]
                            running_requirements.append(req)
                        elif op == "RETRACT":
                            tgt_id = u.get("target_id")
                            running_requirements = [
                                r for r in running_requirements if r.get("id") != tgt_id
                            ]
                        elif op == "NEW_GOAL":
                            running_requirements = []

                current_turn.requirements_after = [
                    dict(r) for r in running_requirements
                ]

        elif ev_type == "user_memory_selection":
            if current_turn:
                current_turn.memories_selected = payload.get("retrieved", [])

        elif ev_type == "user_memory_injection":
            if current_turn:
                current_turn.memories_injected = payload.get("injected", [])

        elif ev_type in {"tool_call", "internal_search"}:
            if current_turn:
                current_turn.internal_searches.append(
                    {
                        "query": payload.get("action", {}).get("query")
                        or payload.get("query"),
                        "limit": payload.get("action", {}).get("limit")
                        or payload.get("limit"),
                        "counts": payload.get("counts", {}),
                        "timestamp": ev.get("timestamp"),
                    }
                )
                total_searches += 1

        elif ev_type == "search_result":
            if current_turn:
                if not current_turn.internal_searches:
                    current_turn.internal_searches.append(
                        {
                            "query": payload.get("query"),
                            "timestamp": ev.get("timestamp"),
                        }
                    )
                    total_searches += 1
                current_turn.internal_searches[-1]["counts"] = payload.get("counts", {})
                current_turn.internal_searches[-1]["candidates"] = payload.get(
                    "candidates", []
                )
                current_turn.internal_searches[-1]["fallback"] = payload.get(
                    "fallback_triggered", False
                )

        elif ev_type == "decision_rejected":
            if current_turn:
                current_turn.validation_rejections.append(
                    {
                        "ordinal": payload.get("ordinal"),
                        "feedback": payload.get("feedback", []),
                    }
                )

        elif ev_type == "model_response":
            if current_turn:
                current_turn.model_calls += 1
                meta = payload.get("metadata", {})
                usage = meta.get("usage", {})
                p_tok = usage.get("prompt_tokens", 0)
                c_tok = usage.get("completion_tokens", 0)
                dur = payload.get("duration_seconds", 0.0)

                current_turn.prompt_tokens += p_tok
                current_turn.completion_tokens += c_tok
                current_turn.total_tokens += p_tok + c_tok
                current_turn.duration_seconds += dur

                total_calls += 1
                total_prompt_tok += p_tok
                total_compl_tok += c_tok
                total_dur += dur

        elif ev_type in {"assistant_response", "assistant_message"}:
            if current_turn:
                current_turn.assistant_message = payload.get("message")
                current_turn.action_type = payload.get("action") or payload.get("type")
                prods = (
                    payload.get("products") or payload.get("recommended_products") or []
                )
                prod_ids = payload.get("recommended_product_ids") or [
                    p.get("id") if isinstance(p, dict) else str(p) for p in prods
                ]
                current_turn.recommended_product_ids = prod_ids
                current_turn.recommended_products = prods
                current_turn.follow_up_question = payload.get("follow_up_question")

        elif ev_type in {
            "purchase_recorded",
            "purchase_confirmed",
            "simulated_purchase",
        }:
            if current_turn:
                current_turn.purchases.append(payload)

        elif ev_type in {"turn_failed", "turn_closed_safely", "model_error"}:
            if current_turn:
                current_turn.errors.append(
                    payload.get("code") or payload.get("reason") or ev_type
                )

    total_tokens = total_prompt_tok + total_compl_tok

    # Build final state snapshot
    final_state = {
        "version": running_state_version,
        "requirements": running_requirements,
        "active_requirements_count": len(running_requirements),
    }

    return SessionAuditData(
        session_id=session_id,
        user_id=user_id,
        created_at=created_at,
        finalized=finalized,
        finalization_details=finalization_details,
        config_snapshot=config_snapshot,
        final_state=final_state,
        total_turns=len(turns),
        total_model_calls=total_calls,
        total_searches=total_searches,
        total_tokens=total_tokens,
        total_duration_seconds=round(total_dur, 2),
        turns=turns,
        raw_events=events,
        consolidation_audit=consolidation_audit,
    )


def render_state_diff(before: list[dict], after: list[dict]) -> None:
    """Render clean, colored before/after diff table of structured requirements."""
    b_map = {r.get("id", str(idx)): r for idx, r in enumerate(before)}
    a_map = {r.get("id", str(idx)): r for idx, r in enumerate(after)}

    all_ids = list(dict.fromkeys(list(b_map.keys()) + list(a_map.keys())))

    rows = []
    for rid in all_ids:
        b_item = b_map.get(rid)
        a_item = a_map.get(rid)

        if not b_item and a_item:
            # Added
            rows.append(
                {
                    "Change": "➕ ADD",
                    "Field": a_item.get("field", ""),
                    "Operator": a_item.get("op", ""),
                    "Value": str(a_item.get("value", "")),
                    "Strength": a_item.get("strength", "hard"),
                    "Quote Evidence": a_item.get("quote", ""),
                }
            )
        elif b_item and not a_item:
            # Retracted
            rows.append(
                {
                    "Change": "➖ RETRACT",
                    "Field": b_item.get("field", ""),
                    "Operator": b_item.get("op", ""),
                    "Value": str(b_item.get("value", "")),
                    "Strength": b_item.get("strength", "hard"),
                    "Quote Evidence": b_item.get("quote", ""),
                }
            )
        elif b_item != a_item and a_item and b_item:
            # Modified/Replaced
            rows.append(
                {
                    "Change": "🔄 REPLACE",
                    "Field": a_item.get("field", ""),
                    "Operator": f"{b_item.get('op')} → {a_item.get('op')}",
                    "Value": f"{b_item.get('value')} → {a_item.get('value')}",
                    "Strength": a_item.get("strength", "hard"),
                    "Quote Evidence": a_item.get("quote", ""),
                }
            )
        elif b_item:
            # Unchanged
            rows.append(
                {
                    "Change": "⏺ UNCHANGED",
                    "Field": b_item.get("field", ""),
                    "Operator": b_item.get("op", ""),
                    "Value": str(b_item.get("value", "")),
                    "Strength": b_item.get("strength", "hard"),
                    "Quote Evidence": b_item.get("quote", ""),
                }
            )

    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.caption("No structured requirements active in this state.")


def render_session_audit_section(
    service: ChatService,
    active_view: dict[str, Any] | Path,
    project_root: Path | None = None,
    owner_id: str | None = None,
) -> None:
    """Render Section: Complete Session Audit Explorer."""
    st.markdown("### 📋 Session Audit Explorer")
    st.caption(
        "Inspect the complete dialogue, state evolution, internal tool actions, memory operations, "
        "and resource metrics for any authorized session."
    )

    if isinstance(active_view, Path):
        root = active_view
        owner = owner_id or "manual-user-001"
    else:
        root = project_root or Path(".")
        owner = owner_id or active_view.get("user_id", "manual-user-001")

    available_sessions = discover_available_sessions(service, root, owner)

    if not available_sessions:
        st.info("No recorded sessions found to audit.")
        return

    # 1. Session Selector Bar
    c_cat, c_sess = st.columns([1, 2])

    with c_cat:
        sources = list(dict.fromkeys(s["source"] for s in available_sessions))
        chosen_source = st.selectbox(
            "Session Source", ["All Sources"] + sources, index=0
        )

    filtered = [
        s
        for s in available_sessions
        if chosen_source == "All Sources" or s["source"] == chosen_source
    ]

    session_labels = [f"{s['label']}" for s in filtered]
    with c_sess:
        selected_label = st.selectbox(
            "Select Session to Audit",
            session_labels,
            index=0,
            key="session_audit_selector",
        )

    chosen_info = filtered[session_labels.index(selected_label)]

    try:
        audit = extract_session_audit(
            chosen_info["store_root"],
            chosen_info["customer_id"],
            chosen_info["session_id"],
        )
    except Exception as exc:
        st.error(f"Could not load session audit: {exc}")
        return

    # 2. Executive Overview Bar
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Total Turns", audit.total_turns)
    with m2:
        st.metric("Model Calls", audit.total_model_calls)
    with m3:
        st.metric("Searches", audit.total_searches)
    with m4:
        st.metric("Total Tokens", f"{audit.total_tokens:,}")
    with m5:
        status_label = "✅ Finalized" if audit.finalized else "🟢 Active"
        st.metric("Status", status_label)

    # Export Button Bar
    col_meta, col_dl = st.columns([3, 1])
    with col_meta:
        st.caption(
            f"**Customer:** `{audit.user_id}` · **Session ID:** `{audit.session_id}` · **Created:** `{audit.created_at[:19].replace('T', ' ')}`"
        )
    with col_dl:
        st.download_button(
            "📥 Export Session JSON",
            data=json.dumps(audit.raw_events, indent=2),
            file_name=f"session_audit_{audit.session_id[:8]}.json",
            mime="application/json",
            use_container_width=True,
        )

    # 3. Sub-tabs for Audit Inspection
    tab_convo, tab_state, tab_mem, tab_tools, tab_raw = st.tabs(
        [
            "💬 Full Dialogue & Transcript",
            "📊 State Evolution & Diffs",
            "🧠 Memory & Consolidation Audit",
            "🛠️ Tools & Resource Metrics",
            "📜 Raw Event Ledger",
        ]
    )

    # TAB 1: FULL DIALOGUE & TRANSCRIPT
    with tab_convo:
        st.markdown("#### Complete Turn-by-Turn Conversation Transcript")
        st.caption(
            "Distinguishes user-facing responses from internal agent reasoning and search operations."
        )

        if not audit.turns:
            st.info("No messages exchanged in this session yet.")
        else:
            for turn in audit.turns:
                with st.container(border=True):
                    # Header
                    st.markdown(
                        f"**Turn {turn.turn_index}** · Request `{turn.request_id[:12]}`"
                    )

                    # User message
                    if turn.user_message:
                        st.markdown(
                            f"👤 **Customer (Turn {turn.turn_index}):** {turn.user_message}"
                        )

                    # Internal Agent Operations (Searches & Injections)
                    if turn.internal_searches or turn.validation_rejections:
                        with st.expander(
                            f"⚙️ Internal Operations ({len(turn.internal_searches)} searches, {len(turn.validation_rejections)} rejections)"
                        ):
                            for s_idx, search in enumerate(
                                turn.internal_searches, start=1
                            ):
                                st.caption(
                                    f"**Search {s_idx}:** `{search.get('query')}` (limit {search.get('limit')})"
                                )
                                counts = search.get("counts", {})
                                if counts:
                                    st.caption(
                                        f"Lexical: `{counts.get('lexical_matches', 0):,}` · "
                                        f"Eligible: `{counts.get('verified_eligible', 0):,}` · "
                                        f"Excluded by constraints: `{counts.get('products_excluded_by_hard_constraints', 0):,}`"
                                    )
                                if search.get("fallback"):
                                    st.caption("*(Fallback search triggered)*")
                            for rej in turn.validation_rejections:
                                st.warning(
                                    f"Validation Rejection (attempt {rej.get('ordinal')}): {rej.get('feedback')}"
                                )

                    # Assistant message
                    if turn.assistant_message:
                        st.markdown(f"✦ **ASTRA:** {turn.assistant_message}")
                        if turn.recommended_product_ids:
                            st.caption(
                                f"**Recommended Products ({len(turn.recommended_product_ids)}):** `{', '.join(turn.recommended_product_ids)}`"
                            )
                            if turn.recommended_products:
                                cols = st.columns(
                                    min(len(turn.recommended_products), 3)
                                )
                                for col, prod in zip(
                                    cols, turn.recommended_products[:3]
                                ):
                                    with col, st.container(border=True):
                                        st.caption(f"**{prod.get('title', '')[:45]}**")
                                        st.caption(f"ID: `{prod.get('id')}`")
                                        price = prod.get("facts", {}).get("price")
                                        if price:
                                            st.markdown(f"**USD {price:.2f}**")
                        if (
                            turn.follow_up_question
                            and turn.follow_up_question != turn.assistant_message
                        ):
                            st.markdown(
                                f"❓ **Follow-up:** *{turn.follow_up_question}*"
                            )

                    # Purchases made during this turn
                    if turn.purchases:
                        for p in turn.purchases:
                            st.success(
                                f"🛍️ Confirmed Simulated Purchase: **{p.get('title')}** (`{p.get('product_id')}`) — USD {p.get('price')}"
                            )

    # TAB 2: STATE EVOLUTION & DIFFS
    with tab_state:
        st.markdown("#### Shopping-Agent State History & Transition Diffs")
        st.caption(
            "Inspect exact before/after diffs of structured requirements across each committed turn."
        )

        turn_choices = [
            f"Turn {t.turn_index}: {t.user_message[:30] if t.user_message else 'Turn'}"
            for t in audit.turns
        ]
        if not turn_choices:
            st.info("No committed turns recorded in this session yet.")
        else:
            selected_turn_str = st.selectbox(
                "Inspect State at Turn", turn_choices, index=0
            )
            t_idx = turn_choices.index(selected_turn_str)
            t_record = audit.turns[t_idx]

            st.markdown(
                f"##### Turn {t_record.turn_index} State Diff (Version {t_record.state_version_before} → {t_record.state_version_after})"
            )
            render_state_diff(t_record.requirements_before, t_record.requirements_after)

        with st.expander("Final Persisted Shopping State (JSON)"):
            st.json(audit.final_state)

    # TAB 3: MEMORY & CONSOLIDATION AUDIT
    with tab_mem:
        st.markdown("#### Long-Term User Memory Audit")
        st.caption(
            "Distinguishes between memory eligibility, injection into context, and actual influence."
        )

        # Per-turn memory injection
        for t in audit.turns:
            if t.memories_selected or t.memories_injected:
                with st.expander(
                    f"Turn {t.turn_index} Memory Retrieval ({len(t.memories_injected)} injected)"
                ):
                    st.caption(
                        f"**Selected Memories ({len(t.memories_selected)}):** `{t.memories_selected}`"
                    )
                    st.caption(f"**Injected Memories ({len(t.memories_injected)}):**")
                    st.json(t.memories_injected)

        # End of session consolidation
        if audit.consolidation_audit:
            st.divider()
            st.markdown("##### End-of-Session Memory Consolidation Audit")
            c_aud = audit.consolidation_audit
            st.caption(
                f"**Reason:** {c_aud.get('reason', '')} · **New Revision:** `v{c_aud.get('new_revision', 1)}`"
            )

            col_app, col_rej = st.columns(2)
            with col_app:
                st.markdown(
                    f"**Applied Operations ({len(c_aud.get('operations_applied', []))}):**"
                )
                for op in c_aud.get("operations_applied", []):
                    st.success(
                        f'`{op.get("op")}` {op.get("category")}.{op.get("attribute")} = **{op.get("value")}** (Quote: *"{op.get("quote")}"*'
                    )
            with col_rej:
                st.markdown(
                    f"**Rejected Operations ({len(c_aud.get('operations_rejected', []))}):**"
                )
                for rej in c_aud.get("operations_rejected", []):
                    st.warning(
                        f"Rejection: {rej.get('rejection_reason')} — {rej.get('operation')}"
                    )
        else:
            st.info(
                "No end-of-session memory consolidation record found (session may be active or memory OFF)."
            )

    # TAB 4: TOOLS & RESOURCE METRICS
    with tab_tools:
        st.markdown("#### Tool Execution & DeepSeek LLM Resource Accounting")
        st.caption(
            "Complete breakdown of API attempts, tokens, latencies, and candidate counts."
        )

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("##### Resource Budget Used")
            st.text(f"Total Model Calls: {audit.total_model_calls}")
            st.text(f"Total Searches: {audit.total_searches}")
            st.text(f"Prompt Tokens: {sum(t.prompt_tokens for t in audit.turns):,}")
            st.text(
                f"Completion Tokens: {sum(t.completion_tokens for t in audit.turns):,}"
            )
            st.text(f"Total Tokens: {audit.total_tokens:,}")
            st.text(f"Total API Latency: {audit.total_duration_seconds:.2f}s")

        with col_t2:
            st.markdown("##### Session Configuration Snapshot")
            if audit.config_snapshot:
                st.json(audit.config_snapshot)
            else:
                st.caption("No runtime config snapshot found.")

    # TAB 5: RAW EVENT LEDGER
    with tab_raw:
        st.markdown(
            f"#### Authoritative Raw Event Log ({len(audit.raw_events)} events)"
        )
        st.caption("Immutable append-only events stored in `events.jsonl`.")
        st.json(audit.raw_events)
