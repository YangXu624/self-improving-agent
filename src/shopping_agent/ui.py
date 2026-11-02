"""Minimal local Streamlit presentation over persisted agent conversations."""

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import streamlit as st

from .cards import PROFILES
from .dev_console import (
    render_evaluation_runner_section,
    render_execution_trace_section,
    render_parameters_section,
)
from .memory_views import FORMATS
from .provider import DeepSeekPolicy, ProviderError
from .runtime_config import PRESETS, RuntimeConfig
from .sessions import SessionError
from .ui_service import DEFAULT_MANUAL_USER_ID, ChatService

SAFE_ERRORS = (SessionError, PermissionError, ValueError, OSError, sqlite3.Error)
OPERATORS = {
    "lt": "<",
    "lte": "≤",
    "gt": ">",
    "gte": "≥",
    "eq": "=",
    "neq": "is not",
    "contains": "includes",
    "not_contains": "excludes",
    "in": "in",
    "not_in": "not in",
}
CSS = """
<style>
.block-container {max-width: 980px; padding-top: 2rem; padding-bottom: 5rem;}
h1 {letter-spacing: -.045em; font-weight: 650 !important;}
[data-testid="stSidebar"] {border-right: 1px solid #e5e5dd;}
[data-testid="stChatMessage"] {background: transparent; padding: 1rem 0;}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background: #f0f1eb; padding: 1rem; border-radius: 14px;}
[data-testid="stText"] {font-family: inherit; white-space: pre-wrap;}
[data-testid="stCaptionContainer"] {color: #69736e;}
[data-testid="stImage"] img {height: 160px; object-fit: contain; border-radius: 8px; background: white;}
footer {visibility: hidden;}
.memory-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-right: 0.5rem;
    background: #eef2f6;
    color: #1e293b;
}
.memory-pill {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 12px;
    font-size: 0.75rem;
    background: #e0f2fe;
    color: #0369a1;
    margin-right: 0.3rem;
}
</style>
"""


def requirement_label(requirement: dict) -> str:
    """Plain-text summary; product/user text is never inserted into raw HTML."""
    field = requirement["field"].replace("_", " ").capitalize()
    value = requirement["value"]
    if isinstance(value, list):
        value = ", ".join(value)
    elif isinstance(value, float):
        value = f"{value:g}"
    if requirement["field"] == "price":
        value = f"USD {value}"
    return f"{field} {OPERATORS[requirement['op']]} {value}"


def product_image_url(value: object) -> str | None:
    """Reject local/executable/malformed references without breaking a product card."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname else None
    except ValueError:
        return None


def render_products(products: list[dict], show_images: bool) -> None:
    """Render only persisted tool-backed cards, even when remote images are unavailable."""
    if not products:
        return
    for column, product in zip(st.columns(len(products)), products, strict=True):
        with column, st.container(border=True):
            url = product_image_url(product.get("image_url"))
            if show_images:
                if url:
                    st.image(
                        url,
                        width="stretch",
                        alt="Product image unavailable; details remain below",
                    )
                else:
                    st.caption("◇ Image unavailable")
            title = product["title"]
            st.text(title[:115] + ("…" if len(title) > 115 else ""))
            facts = product["facts"]
            price = facts.get("price")
            st.markdown(
                f"**USD {price:.2f}**" if price is not None else "**Price unknown**"
            )
            attributes = [
                f"{key.capitalize()}: {facts[key]}"
                for key in ["color", "material"]
                if facts.get(key)
            ]
            if attributes:
                st.caption(" · ".join(attributes))
            st.caption("Catalogue price · availability unverified")
            with st.expander("Product details"):
                st.text(title)
                st.text("Product ID: " + product["id"])
                st.json(
                    {
                        "facts": facts,
                        "evidence": product["evidence"],
                        "matched_hard_ids": product["matched_hard_ids"],
                        "matched_soft_ids": product["matched_soft_ids"],
                    }
                )


def render_activity(events: list[dict], request_id: str) -> None:
    """Present an actual per-turn trace, with raw events available on demand."""
    turn_events = [e for e in events if e.get("turn_id") == request_id]
    with st.expander("View activity"):
        for event in turn_events:
            payload = event["payload"]
            if event["type"] == "state_committed":
                st.caption(f"Shopping state updated → version {event['state_version']}")
                for update in payload["updates"]:
                    st.text(
                        update["op"]
                        + (
                            " · " + requirement_label(update["requirement"])
                            if update.get("requirement")
                            else ""
                        )
                    )
            elif event["type"] == "tool_call":
                st.text("Search → " + payload["action"]["query"])
            elif event["type"] == "search_result":
                counts = payload["counts"]
                st.caption(
                    f"{counts['lexical_matches']:,} lexical matches · {counts['verified_eligible']:,} verified eligible · {counts['products_with_unknown_required_attributes']:,} with unknown required attributes"
                )
            elif event["type"] == "recommendation":
                st.caption(
                    f"Recommended {len(payload['product_ids'])} verified candidate(s)"
                )
            elif event["type"] == "user_memory_selection":
                retrieved = payload.get("retrieved", [])
                st.caption(
                    f"User memory selection → {len(retrieved)} candidate record(s) retrieved (revision {payload.get('revision')})"
                )
            elif event["type"] == "user_memory_injection":
                injected = payload.get("injected", [])
                st.caption(
                    f"User memory injection → {len(injected)} record(s) injected into LLM context"
                )
            elif event["type"] in {
                "decision_rejected",
                "turn_failed",
                "turn_closed_safely",
                "model_error",
            }:
                st.text(event["type"].replace("_", " ").capitalize())
                st.json(payload)
        with st.expander("Full turn events"):
            st.json(turn_events)


def _sidebar(service: ChatService) -> tuple[str, str, bool, bool]:
    owner = st.session_state.setdefault(
        "owner", os.environ.get("ASTRA_DEV_USER", DEFAULT_MANUAL_USER_ID)
    )
    with st.sidebar:
        st.markdown("### ✦ ASTRA Shopping")
        st.caption("Conversational agent with persistent memory.")

        # Dedicated development identity
        st.markdown(f"**Shopper ID:** `{owner}`")
        with st.form("owner_form"):
            candidate = st.text_input(
                "Local shopper", value=owner, key="owner_input", max_chars=128
            )
            switch = st.form_submit_button("Switch shopper", width="stretch")
        if switch:
            if candidate.strip():
                try:
                    resolved = service.resolve_user_id(candidate.strip())
                    st.session_state["owner"] = owner = resolved
                    st.session_state.pop("conversation", None)
                    st.session_state.pop("conversation_picker", None)
                except SAFE_ERRORS as err:
                    st.error(str(err))
            else:
                st.error("Enter a shopper name.")

        st.divider()

        # Development-only Memory ON/OFF toggle
        st.session_state.setdefault("user_memory_enabled", True)
        memory_on = st.checkbox(
            "User Memory",
            key="user_memory_enabled",
            help="Memory ON: Retrieves and injects user memories into context and consolidates new memories at session end. Memory OFF: Disables memory retrieval, injection and consolidation while preserving existing stored records.",
        )
        service.set_user_memory_enabled(memory_on)

        if memory_on:
            st.caption("🟢 **Memory ON**: Context injection & consolidation enabled")
        else:
            st.caption("⚪ **Memory OFF**: Memory disabled (records preserved)")

        st.divider()

        if st.button("＋ New chat", key="new_chat", width="stretch"):
            st.session_state["conversation"] = service.create(owner)
            st.session_state["conversation_picker"] = st.session_state["conversation"]
            st.session_state.pop("last_finalization", None)

        with st.expander("Resume by session ID"):
            with st.form("resume_form"):
                requested = st.text_input("Session ID", key="resume_id")
                if st.form_submit_button("Resume chat", width="stretch"):
                    try:
                        st.session_state["conversation"] = service.resume(
                            owner, requested
                        )
                        st.session_state["conversation_picker"] = st.session_state[
                            "conversation"
                        ]
                        st.session_state.pop("last_finalization", None)
                    except SAFE_ERRORS:
                        st.error(
                            "Cannot open that session for this shopper. Check the ID and session files."
                        )

        options = service.sessions(owner)
        ids = [item["id"] for item in options]
        if not st.session_state.get("conversation"):
            sid = service.create(owner)
            st.session_state["conversation"] = sid
            options = service.sessions(owner)
            ids = [item["id"] for item in options]
        if st.session_state["conversation"] not in ids:
            st.error(
                "This session is unavailable. Resume another chat or start a new one."
            )
            st.stop()

        current = st.session_state["conversation"]
        if st.session_state.get("conversation_picker") not in ids:
            st.session_state["conversation_picker"] = current
        names = {
            item[
                "id"
            ]: f"Chat · {item['id'][-6:]}{' (Finalized)' if item.get('finalized') else ''}"
            for item in options
        }
        sid = (
            st.selectbox(
                "Conversations",
                ids,
                index=None,
                format_func=names.get,
                key="conversation_picker",
            )
            or current
        )
        st.session_state["conversation"] = sid
        st.caption("Session ID")
        st.code(sid, language=None)
        show_images = st.checkbox("Show product images", value=True, key="show_images")

        st.divider()
        with st.expander("🛠️ Developer Console", expanded=False):
            st.caption("Operational Limits & Presets")
            curr_cfg: RuntimeConfig = st.session_state.get(
                "runtime_config", service.get_runtime_config()
            )
            preset_options = list(PRESETS.keys()) + ["Custom"]
            current_preset = st.session_state.get(
                "selected_preset", "Evaluation (Standard Benchmark)"
            )
            chosen_p = st.selectbox(
                "Quick Preset",
                preset_options,
                index=preset_options.index(current_preset)
                if current_preset in preset_options
                else 1,
                key="sidebar_preset_select",
            )
            if chosen_p in PRESETS and chosen_p != current_preset:
                st.session_state["selected_preset"] = chosen_p
                new_cfg = PRESETS[chosen_p]
                st.session_state["runtime_config"] = new_cfg
                service.set_runtime_config(new_cfg)
                st.rerun()

            c_calls = st.slider(
                "Calls / Turn",
                1,
                6,
                int(curr_cfg.agent_max_calls),
                key="sb_max_calls",
            )
            c_searches = st.slider(
                "Searches / Turn",
                1,
                3,
                int(curr_cfg.agent_max_searches),
                key="sb_max_searches",
            )
            c_mem_thresh = st.slider(
                "Similarity Threshold",
                0.10,
                0.90,
                float(curr_cfg.user_memory_similarity_threshold),
                step=0.05,
                key="sb_mem_thresh",
            )
            if (
                c_calls != curr_cfg.agent_max_calls
                or c_searches != curr_cfg.agent_max_searches
                or abs(c_mem_thresh - curr_cfg.user_memory_similarity_threshold) > 0.01
            ):
                updated_cfg = curr_cfg.copy(
                    agent_max_calls=c_calls,
                    agent_max_searches=c_searches,
                    user_memory_similarity_threshold=c_mem_thresh,
                )
                st.session_state["runtime_config"] = updated_cfg
                st.session_state["selected_preset"] = "Custom"
                service.set_runtime_config(updated_cfg)

            st.caption(
                "Full controls, execution trace & eval runner in Developer Console tab."
            )

        st.caption(
            "Local app. Identity is server-isolated for development; no accounts or external auth."
        )

    return owner, sid, show_images, memory_on


def render_memory_inspector(service: ChatService, owner: str) -> None:
    """Render comprehensive memory inspection, export, and clearance panel."""
    st.markdown("### 🧠 User Memory Inspector")
    st.caption(f"Persistent memory store for **{owner}**")

    mem = service.inspect_memory(owner)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Memories", mem["total_active"])
    with col2:
        st.metric("Superseded Records", mem["total_superseded"])
    with col3:
        st.metric("Profile Revision", f"v{mem['revision']}")
    with col4:
        last_s = mem["last_consolidated_session_id"]
        st.metric("Last Consolidation", f"…{last_s[-6:]}" if last_s else "None")

    st.divider()

    st.markdown("#### Active Stored Memories")
    if not mem["active"]:
        st.info(
            f"No active memories recorded for **{owner}**. Complete a shopping session with Memory ON and click 'Finish Session & Save Memory' to consolidate durable preferences."
        )
    else:
        for idx, rec in enumerate(mem["active"], start=1):
            with st.container(border=True):
                cat = rec.get("category", "preference").upper()
                attr = rec.get("attribute", "")
                val = rec.get("value", "")
                scope = rec.get("scope", "general")
                st.markdown(
                    f"**{idx}. [{cat}] {attr.capitalize()}:** {val} &nbsp;*(Scope: {scope})*"
                )
                if rec.get("quote"):
                    st.caption(f'Evidence quote: "{rec["quote"]}"')
                created = rec.get("created_at", "")[:19].replace("T", " ")
                confirmed = rec.get("last_confirmed_at", "")[:19].replace("T", " ")
                meta_info = [f"ID: `{rec.get('id')}`", f"Created: {created}"]
                if confirmed and confirmed != created:
                    meta_info.append(f"Confirmed: {confirmed}")
                if rec.get("source_session_id"):
                    meta_info.append(f"Session: `…{rec['source_session_id'][-6:]}`")
                st.caption(" · ".join(meta_info))

    if mem["superseded"]:
        with st.expander(f"Superseded / Inactive Memories ({len(mem['superseded'])})"):
            for rec in mem["superseded"]:
                st.text(
                    f"[{rec.get('status').upper()}] {rec.get('category')}: {rec.get('attribute')} = {rec.get('value')} (ID: {rec.get('id')})"
                )
                if rec.get("superseded_by_id"):
                    st.caption(f"Superseded by: {rec.get('superseded_by_id')}")

    st.divider()

    st.markdown("#### Memory Management")
    c_exp, c_clr = st.columns([1, 1])
    with c_exp:
        export_data = service.export_memory(owner)
        st.download_button(
            "📥 Export Memory Profile (JSON)",
            data=export_data,
            file_name=f"astra_memory_{owner}.json",
            mime="application/json",
            use_container_width=True,
            key="export_memory_btn",
        )
    with c_clr:
        with st.expander("Clear User Memories"):
            st.warning(f"Reset all stored memories for {owner} to an empty profile.")
            confirm = st.checkbox(
                "Confirm clear memory", key="confirm_clear_memory_chk"
            )
            if st.button(
                "🗑️ Clear My Memories",
                disabled=not confirm,
                key="clear_memory_submit_btn",
                use_container_width=True,
            ):
                service.clear_memory(owner)
                st.success(f"All memories cleared for {owner}.")
                st.rerun()


def run_app(project_root: Path) -> None:
    """Live DeepSeek composition root; secrets stay server-side, no scripted fallback."""
    st.set_page_config(
        page_title="ASTRA · Interactive Personal Shopping",
        page_icon="✦",
        layout="centered",
    )
    st.html(CSS)
    try:
        policy = DeepSeekPolicy.from_env_file(
            Path(os.environ.get("ASTRA_ENV_FILE", project_root / ".env"))
        )
    except ProviderError as error:
        st.title("ASTRA")
        st.error("DeepSeek is not configured: " + str(error))
        st.caption(
            "Set DEEPSEEK_API_KEY in this project's .env file. Keep it local; no key belongs in chat."
        )
        st.chat_input("Configure DeepSeek to start chatting", disabled=True)
        return
    except (ValueError, OSError):
        st.title("ASTRA")
        st.error(
            "The local environment configuration could not be read. Check its syntax and file permissions."
        )
        st.chat_input("Configure DeepSeek to start chatting", disabled=True)
        return

    cards_profile = os.environ.get("ASTRA_CARDS_PROFILE", "baseline")
    memory_format = os.environ.get("ASTRA_MEMORY_FORMAT", "compact")
    if memory_format not in FORMATS:
        st.error("ASTRA_MEMORY_FORMAT must be compact or legacy.")
        return
    if cards_profile not in PROFILES:
        st.title("ASTRA")
        st.error("ASTRA_CARDS_PROFILE is not a known card profile.")
        st.caption("Valid values: " + ", ".join(PROFILES))
        st.chat_input("Fix the card profile to start chatting", disabled=True)
        return

    try:
        service = ChatService(
            Path(
                os.environ.get(
                    "ASTRA_CATALOGUE", project_root / "data/catalogue/catalog.jsonl"
                )
            ),
            Path(
                os.environ.get(
                    "ASTRA_INDEX", project_root / "data/index/catalogue.sqlite"
                )
            ),
            Path(
                os.environ.get(
                    "ASTRA_UI_SESSIONS", project_root / "data/ui-sessions/deepseek"
                )
            ),
            policy=policy,
            cards_profile=cards_profile,
            memory_format=memory_format,
            user_memory_enabled=st.session_state.get("user_memory_enabled", True),
            user_memory_root=Path(
                os.environ.get(
                    "ASTRA_USER_MEMORY_ROOT", project_root / "data/user-memory"
                )
            ),
        )
    except SAFE_ERRORS:
        st.title("ASTRA")
        st.error("The local catalogue index is missing, stale or unavailable.")
        st.code(".venv/bin/python -m shopping_agent index", language="bash")
        st.caption(
            "Source catalogue files must be present. Use --rebuild only to replace an existing index."
        )
        st.chat_input("Set up the catalogue to start chatting", disabled=True)
        return

    owner, sid, show_images, memory_on = _sidebar(service)
    try:
        view = service.view(owner, sid)
    except SAFE_ERRORS:
        st.error(
            "This chat could not be read. Its files have been preserved; try another session."
        )
        return

    st.caption("PERSONAL SHOPPING · INTERACTIVE MEMORY DEMO")
    st.title("ASTRA Personal Shopping")
    st.caption("DeepSeek · live decisions · catalogue-backed recommendations")

    # Mode indicator banner
    if memory_on:
        st.info(
            "🟢 **Memory Mode: ON** — ASTRA retrieves your past preferences, injects them before reasoning, and consolidates new preferences when you finish the session.",
            icon="🧠",
        )
    else:
        st.warning(
            "⚪ **Memory Mode: OFF** — ASTRA operates without long-term customer memory. Existing memories are preserved without modification.",
            icon="ℹ️",
        )

    # Main Tabs: Chat vs Memory Inspector vs Developer Console
    chat_tab, inspector_tab, dev_tab = st.tabs(
        ["💬 Shopping Chat", "🧠 Memory Inspector", "🛠️ Developer Console & Eval Runner"]
    )

    with dev_tab:
        sec_param, sec_trace, sec_eval = st.tabs(
            [
                "⚙️ Operational Parameters",
                "🔍 Live Execution Trace",
                "📊 Synthetic Evaluation Runner",
            ]
        )
        with sec_param:
            render_parameters_section(service, view, project_root)
        with sec_trace:
            render_execution_trace_section(view, service)
        with sec_eval:
            render_evaluation_runner_section(project_root, service)

    with inspector_tab:
        render_memory_inspector(service, owner)

    with chat_tab:
        if notice := st.session_state.pop("send_error", None):
            st.error(notice)

        # Prominent Finish Session & Save Memory Action Bar
        col_btn, col_info = st.columns([1, 2])
        with col_btn:
            finish_clicked = st.button(
                "🏁 Finish Session & Save Memory",
                key="finish_session_btn",
                type="primary",
                use_container_width=True,
                help="Finalize the current conversation and consolidate durable customer preferences into persistent memory.",
            )
        with col_info:
            if view.get("finalized"):
                st.caption("✓ This session has been finalized.")
            else:
                st.caption(
                    "When finished shopping, click to trigger end-of-session memory consolidation once."
                )

        if finish_clicked:
            try:
                with st.spinner("Consolidating dialogue into user memory…"):
                    res = service.finalize(owner, sid)
                    st.session_state["last_finalization"] = res
            except SAFE_ERRORS as e:
                st.session_state["last_finalization"] = {
                    "status": "error",
                    "error": str(e),
                }
            st.rerun()

        # Display last finalization result if available
        last_fin = st.session_state.get("last_finalization") or view.get(
            "finalization_details"
        )
        if last_fin:
            status = last_fin.get("status")
            if status == "success":
                st.success(
                    f"✓ Session finalized and memories saved! (Profile Revision v{last_fin.get('revision')})"
                )
                ops = last_fin.get("operations_applied", [])
                if ops:
                    st.markdown("**Learned Preferences:**")
                    for op in ops:
                        st.markdown(
                            f"- `{op.get('op')}` **{op.get('attribute').capitalize()}:** {op.get('value')} &nbsp;*(Scope: {op.get('scope')})*"
                        )
                        if op.get("quote"):
                            st.caption(f'  Quote: "{op.get("quote")}"')
                else:
                    st.info(
                        f"Outcome: {last_fin.get('reason', 'No new durable preferences.')}"
                    )
            elif status == "idempotent":
                st.info(
                    f"ℹ️ Session already finalized earlier ({last_fin.get('reason', 'no duplicate memory writes applied')})."
                )
            elif status == "memory_disabled":
                st.warning(
                    "Session finished with Memory OFF. No long-term memories were updated or saved."
                )
            elif status == "error":
                st.error(f"Finalization / consolidation error: {last_fin.get('error')}")

        st.divider()

        # Shopping State in Sidebar
        with st.sidebar:
            st.divider()
            st.markdown("#### Shopping state")
            active = [
                r for r in view["state"]["requirements"] if r["status"] == "active"
            ]
            if not active:
                st.caption("Your requirements will appear here as you chat.")
            for strength, label in [("hard", "Requirements"), ("soft", "Preferences")]:
                rows = [r for r in active if r["strength"] == strength]
                if rows:
                    st.caption(label)
                    for row in rows:
                        st.text(requirement_label(row))
            with st.expander("Shopping details"):
                st.json(view["shopping_state"])
            with st.expander("Audit history"):
                st.json(view["state"])

        # Starter buttons for empty sessions
        starter = None
        if not view["messages"]:
            st.write("Tell me what you're looking for. We can narrow it down together.")
            for column, text in zip(
                st.columns(3),
                ["Boots under $100", "A backpack", "A red dress"],
                strict=True,
            ):
                if column.button(text, width="stretch"):
                    starter = text
            st.caption(
                "Describe what matters to you. The agent can ask questions, search and recommend. Each turn allows up to 3 API attempts and 2 searches."
            )

        # Render conversation history
        for message in view["messages"]:
            with st.chat_message(message["role"]):
                st.text(message["message"])
                if message["role"] == "assistant":
                    if message.get("products"):
                        render_products(message["products"], show_images)

                    # Highlight memory injected during this turn
                    um_data = message.get("user_memory", {})
                    injected_records = um_data.get("injected_records", [])
                    if injected_records:
                        summary_pills = " · ".join(
                            f"**{r.get('attribute').capitalize()}:** {r.get('value')}"
                            for r in injected_records
                        )
                        st.caption(f"✦ Injected memory context: {summary_pills}")

                    budget = message.get("budget_used", {})
                    searches = budget.get("searches", 0)
                    st.caption(
                        f"{message['action'].capitalize()} · {budget.get('model_calls', 0)} API attempts · "
                        f"{searches} {'search' if searches == 1 else 'searches'}"
                    )
                    responses = [
                        e
                        for e in view["events"]
                        if e.get("turn_id") == message.get("request_id")
                        and e["type"] == "model_response"
                    ]
                    usages = [
                        e["payload"]["metadata"].get("usage", {}) for e in responses
                    ]
                    if usages:
                        input_tokens = sum(u.get("prompt_tokens", 0) for u in usages)
                        output_tokens = sum(
                            u.get("completion_tokens", 0) for u in usages
                        )
                        st.caption(
                            f"Reported tokens: {input_tokens:,} input / {output_tokens:,} output"
                        )
                    if len(
                        [
                            u
                            for u in usages
                            if "prompt_tokens" in u and "completion_tokens" in u
                        ]
                    ) < budget.get("model_calls", 0):
                        st.caption("Token usage is incomplete for this turn.")
                    if message.get("error"):
                        st.error("Turn error: " + message["error"])
                    if message.get("user_memory", {}).get("rejected"):
                        st.warning(
                            "A proposed profile update was not saved: "
                            + ", ".join(message["user_memory"]["rejected"])
                        )
                    render_activity(view["events"], message["request_id"])

        prompt = st.chat_input(
            "Describe an item, or change a requirement…",
            max_chars=8000,
            key="shopping_input",
        )
        if message := starter or prompt:
            if message.strip():
                try:
                    with st.spinner("The shop agent is working…"):
                        active_cfg = st.session_state.get("runtime_config")
                        service.send(
                            owner, sid, message, uuid4().hex, runtime_config=active_cfg
                        )
                except SAFE_ERRORS:
                    st.session_state["send_error"] = (
                        "The turn could not finish. Check the recorded state and activity before retrying; accepted changes may have been saved."
                    )
                st.rerun()
