"""Minimal local Streamlit presentation over persisted agent conversations."""

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import streamlit as st

from .provider import DeepSeekPolicy, ProviderError
from .sessions import SessionError
from .ui_service import ChatService

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
.block-container {max-width: 950px; padding-top: 2.3rem; padding-bottom: 5rem;}
h1 {letter-spacing: -.045em; font-weight: 650 !important;}
[data-testid="stSidebar"] {border-right: 1px solid #e5e5dd;}
[data-testid="stChatMessage"] {background: transparent; padding: 1rem 0;}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background: #f0f1eb; padding: 1rem; border-radius: 14px;}
[data-testid="stText"] {font-family: inherit; white-space: pre-wrap;}
[data-testid="stCaptionContainer"] {color: #69736e;}
[data-testid="stImage"] img {height: 160px; object-fit: contain; border-radius: 8px; background: white;}
footer {visibility: hidden;}
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
    turn_events = [e for e in events if e["turn_id"] == request_id]
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


def _sidebar(service: ChatService) -> tuple[str, str, bool]:
    owner = st.session_state.setdefault("owner", "local-shopper")
    with st.sidebar:
        st.markdown("### ✦ ASTRA")
        st.caption("A little help finding the right thing.")
        with st.form("owner_form"):
            candidate = st.text_input(
                "Local shopper", value=owner, key="owner_input", max_chars=128
            )
            switch = st.form_submit_button("Switch shopper", width="stretch")
        if switch:
            if candidate.strip():
                st.session_state["owner"] = owner = candidate.strip()
                st.session_state.pop("conversation", None)
                st.session_state.pop("conversation_picker", None)
            else:
                st.error("Enter a shopper name.")
        if st.button("＋ New chat", key="new_chat", width="stretch"):
            st.session_state["conversation"] = service.create(owner)
            st.session_state["conversation_picker"] = st.session_state["conversation"]
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
        # Keep durable selection separate from a widget's transient frontend value.
        # Labels are stable: first-message titles change after a send and can reset a
        # browser select widget even though the underlying UUID has not changed.
        current = st.session_state["conversation"]
        if st.session_state.get("conversation_picker") not in ids:
            st.session_state["conversation_picker"] = current
        names = {item["id"]: f"Chat · {item['id'][-6:]}" for item in options}
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
        st.caption(
            "Local app. Shopper names organise files; they are not accounts or authentication."
        )
    return owner, sid, show_images


def run_app(project_root: Path) -> None:
    """Live DeepSeek composition root; secrets stay server-side, no scripted fallback."""
    st.set_page_config(page_title="ASTRA · Shopping", page_icon="✦", layout="centered")
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
    owner, sid, show_images = _sidebar(service)
    try:
        view = service.view(owner, sid)
    except SAFE_ERRORS:
        st.error(
            "This chat could not be read. Its files have been preserved; try another session."
        )
        return
    st.caption("PERSONAL SHOPPING, ONE CONVERSATION AT A TIME")
    st.title("Find something that fits.")
    st.caption("DeepSeek · live decisions · catalogue-backed recommendations")
    if notice := st.session_state.pop("send_error", None):
        st.error(notice)
    with st.sidebar:
        st.divider()
        st.markdown("#### Shopping state")
        active = [r for r in view["state"]["requirements"] if r["status"] == "active"]
        if not active:
            st.caption("Your requirements will appear here as you chat.")
        for strength, label in [("hard", "Requirements"), ("soft", "Preferences")]:
            rows = [r for r in active if r["strength"] == strength]
            if rows:
                st.caption(label)
                for row in rows:
                    st.text(requirement_label(row))
        st.caption(f"State version {view['state']['version']}")
        with st.expander("State & correction history"):
            st.json(view["state"])
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
    for message in view["messages"]:
        with st.chat_message(message["role"]):
            st.text(message["message"])
            if message["role"] == "assistant":
                if message.get("products"):
                    render_products(message["products"], show_images)
                budget = message.get("budget_used", {})
                searches = budget.get("searches", 0)
                st.caption(
                    f"{message['action'].capitalize()} · {budget.get('model_calls', 0)} API attempts · "
                    f"{searches} {'search' if searches == 1 else 'searches'}"
                )
                responses = [
                    e
                    for e in view["events"]
                    if e["turn_id"] == message["request_id"]
                    and e["type"] == "model_response"
                ]
                usages = [e["payload"]["metadata"].get("usage", {}) for e in responses]
                if usages:
                    input_tokens = sum(u.get("prompt_tokens", 0) for u in usages)
                    output_tokens = sum(u.get("completion_tokens", 0) for u in usages)
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
                    service.send(owner, sid, message, uuid4().hex)
            except SAFE_ERRORS:
                st.session_state["send_error"] = (
                    "The turn could not finish. Check the recorded state and activity before retrying; accepted changes may have been saved."
                )
            st.rerun()
