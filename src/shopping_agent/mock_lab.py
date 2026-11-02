"""Mock Customer Lab for ASTRA Developer Console.

Provides interactive debugging and demonstration of synthetic customer profiles:
- Select synthetic customer profiles from actual benchmark fixtures (dev, dev-expanded, memory-sensitive)
- Detailed persona, persistent preferences, changes, and planned visit sequences
- Strict confidentiality boundary: Evaluator-visible hidden target IDs with developer toggle
- Visual conversation playback of completed evaluation runs with step controls (zero API calls)
- Live mock customer evaluation integration (Paired OFF/ON, offline or live mode)
- Longitudinal memory visualization across visits comparing ground truth vs stored memory
- Side-by-side OFF vs ON evaluation results with evidence-backed diagnostic analysis
- Recorded run explorer with multi-dimensional filtering
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import streamlit as st

from .retrieval import LexicalSearch
from .ui_service import ChatService


def load_mock_customer_fixtures(project_root: Path) -> list[dict[str, Any]]:
    """Load benchmark customer fixtures from experiments/longitudinal."""
    datasets_dir = project_root / "experiments/longitudinal"
    fixtures = [
        (
            "customers.memory-sensitive.json",
            "Memory-Sensitive Benchmark (Helpful / Neutral / Conflicting)",
            "30-customer benchmark testing memory influence under varying conditions",
        ),
        (
            "customers.dev-expanded.json",
            "Expanded Longitudinal Returning Customers (10 Personas)",
            "10 multi-visit customer personas with evolving preferences across visits",
        ),
        (
            "customers.dev.json",
            "Standard Longitudinal Dev Set (Alice / Bob / Carol / Dave)",
            "4 foundational test personas for longitudinal testing and regression",
        ),
    ]

    loaded_datasets: list[dict[str, Any]] = []
    for filename, title, description in fixtures:
        path = datasets_dir / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            customers = data.get("customers", [])
            loaded_datasets.append(
                {
                    "filename": filename,
                    "title": title,
                    "description": description,
                    "path": path,
                    "dataset_id": data.get("dataset_id", filename),
                    "customer_count": len(customers),
                    "customers": customers,
                    "provenance": data.get("provenance", "Not specified in fixture"),
                }
            )
        except Exception:
            pass

    return loaded_datasets


def get_target_title(project_root: Path, target_id: str) -> str | None:
    """Safely look up target product title from catalogue index without leaking to agent."""
    idx_path = project_root / "data/index/catalogue.sqlite"
    if not idx_path.exists():
        return None
    try:
        searcher = LexicalSearch(idx_path)
        row = searcher.get_product(target_id)
        if row:
            return row.get("title")
    except Exception:
        pass
    return None


def render_customer_profile_inspector(
    customer: dict[str, Any],
    project_root: Path,
) -> None:
    """Render customer profile, preferences, changes, and confidential evaluator targets."""
    st.markdown(f"### 👤 Profile: {customer.get('user_id')}")
    st.caption(customer.get("personality", "No personality specified"))

    col_meta1, col_meta2 = st.columns(2)
    with col_meta1:
        st.markdown(
            f"**Background:** {customer.get('background') or 'Not specified in fixture'}"
        )
        interests = customer.get("interests", [])
        if interests:
            st.markdown(f"**Interests:** {', '.join(f'`{i}`' for i in interests)}")
        else:
            st.caption("Interests: Not specified in fixture")
    with col_meta2:
        st.metric("Total Planned Visits", len(customer.get("visits", [])))
        changes = customer.get("changes", [])
        st.caption(f"Preference Evolution Events: {len(changes)} update(s) defined")

    # Persistent Preferences Defined in Fixture
    st.markdown("#### 📌 Ground-Truth Persistent Preferences")
    prefs = customer.get("preferences", [])
    if prefs:
        pref_rows = []
        for p in prefs:
            fact = p.get("fact", {})
            pref_rows.append(
                {
                    "Category": p.get("category", "preference"),
                    "Scope": p.get("scope", "global"),
                    "Attribute": fact.get("key", "N/A"),
                    "Operator": fact.get("op", "="),
                    "Value": str(fact.get("val", "N/A")),
                    "Statement": fact.get("statement") or "N/A",
                }
            )
        st.table(pref_rows)
    else:
        st.caption("No persistent preferences defined in fixture.")

    # Changes / Updates
    if changes:
        with st.expander(f"🔄 Preference Evolution Schedule ({len(changes)} changes)"):
            for ch in changes:
                st.markdown(f"**Before Visit Sequence {ch.get('before_sequence')}:**")
                if ch.get("background"):
                    st.caption(f"Background update: *{ch.get('background')}*")
                if ch.get("remove_keys"):
                    st.caption(
                        f"Retracted preferences: `{', '.join(ch.get('remove_keys'))}`"
                    )
                for u in ch.get("updates", []):
                    uf = u.get("fact", {})
                    st.caption(
                        f"- `{u.get('category')}`: {uf.get('key')} = {uf.get('val')} ({uf.get('statement')})"
                    )

    # Confidential Evaluator-Visible Ground-Truth Section
    st.divider()
    st.markdown("#### 🔒 Evaluator Ground Truth & Target Inspector")
    st.caption(
        "Strict Confidentiality Boundary: Evaluator UI inspects private ground truth to assess accuracy. "
        "ASTRA runtime NEVER sees target IDs, acceptable counts, or future visit plans."
    )

    reveal_targets = st.toggle(
        "👁️ Reveal Confidential Evaluator Data (Target Product IDs & Verification Sources)",
        value=False,
        key=f"reveal_toggle_{customer.get('user_id')}",
        help="When toggled off, confidential target product IDs and acceptable sets remain masked.",
    )

    visits = customer.get("visits", [])
    for v in visits:
        seq = v.get("sequence", 1)
        mode = v.get("evaluation_mode", "target_item")
        scen_group = v.get("scenario_group") or "Standard"
        with st.container(border=True):
            st.markdown(
                f"##### Visit {seq}: {v.get('goal')} `[{mode}]` · `{scen_group}`"
            )
            col_v1, col_v2 = st.columns([2, 1])
            with col_v1:
                st.markdown(f'**Opening Customer Message:** *"{v.get("opening")}"*')
                st.caption(
                    f"Category: `{v.get('category')}` · Recipient: `{v.get('recipient')}` · Max turns: {v.get('max_user_turns', 6)}"
                )

                # Requirements
                hard_facts = v.get("hard", [])
                soft_facts = v.get("soft", [])
                if hard_facts:
                    st.markdown(
                        f"**Hard Constraints ({len(hard_facts)}):** "
                        + ", ".join(
                            f"`{f.get('key')} {f.get('op')} {f.get('val')}`"
                            for f in hard_facts
                        )
                    )
                if soft_facts:
                    st.markdown(
                        f"**Soft Preferences ({len(soft_facts)}):** "
                        + ", ".join(
                            f"`{f.get('key')} {f.get('op')} {f.get('val')}`"
                            for f in soft_facts
                        )
                    )

            with col_v2:
                witness_id = v.get("witness_id")
                acceptable = v.get("acceptable_target_ids") or (
                    [witness_id] if witness_id else []
                )

                if reveal_targets:
                    st.markdown(f"🎯 **Target ID:** `{witness_id}`")
                    target_title = get_target_title(project_root, witness_id)
                    if target_title:
                        st.caption(f"*{target_title}*")
                    if len(acceptable) > 1:
                        st.caption(
                            f"Acceptable target pool ({len(acceptable)}): "
                            + ", ".join(f"`{a}`" for a in acceptable)
                        )
                    ev = v.get("evidence")
                    if ev:
                        st.caption(
                            f"Acceptable count in catalogue: `{ev.get('acceptable_count')}`"
                        )
                else:
                    st.markdown("🎯 **Target ID:** `•••••••• [Masked]`")
                    st.caption("🔒 *Target product ID hidden for confidentiality*")


def render_conversation_playback(
    project_root: Path,
) -> None:
    """Render step-by-step visual conversation playback with zero model calls."""
    st.markdown("### ⏪ Replay Completed Evaluation Conversations")
    st.caption(
        "Inspect saved evaluation runs step-by-step with interactive playback controls. "
        "Uses saved transcripts and events with **zero API calls**."
    )

    # Discover runs from eval-ui and data/eval/
    candidate_roots = [
        project_root / "data/eval-ui",
        project_root / "data/eval/canaries",
        project_root / "data/eval/runs",
    ]

    discovered_runs: list[dict[str, Any]] = []
    for root in candidate_roots:
        if not root.exists():
            continue
        for rfolder in sorted(root.iterdir(), reverse=True):
            if not rfolder.is_dir():
                continue
            res_file = rfolder / "eval_result.json"
            if res_file.exists():
                try:
                    data = json.loads(res_file.read_text(encoding="utf-8"))
                    discovered_runs.append(
                        {
                            "label": f"Run {rfolder.name} · {data.get('customer_id')} ({data.get('timestamp', '')[:16].replace('T', ' ')})",
                            "folder": rfolder,
                            "data": data,
                        }
                    )
                except Exception:
                    pass

    if not discovered_runs:
        st.info(
            "No evaluation run artifacts found with transcripts. "
            "Execute an evaluation in the 'Live Mock Customer Evaluation' section below to create one."
        )
        return

    run_labels = [r["label"] for r in discovered_runs]
    selected_label = st.selectbox(
        "Select Completed Evaluation Run", run_labels, index=0
    )
    selected_run = next(r for r in discovered_runs if r["label"] == selected_label)
    run_data = selected_run["data"]
    run_folder = selected_run["folder"]

    # Choose arm (user_memory_on vs user_memory_off)
    available_arms = []
    if run_data.get("on_arm"):
        available_arms.append("user_memory_on")
    if run_data.get("off_arm"):
        available_arms.append("user_memory_off")

    col_arm, col_vis = st.columns(2)
    with col_arm:
        chosen_arm = st.radio(
            "Evaluation Condition",
            available_arms,
            format_func=lambda a: "🧠 Memory ON" if "on" in a else "⚪ Memory OFF",
            horizontal=True,
        )

    arm_key = "on_arm" if chosen_arm == "user_memory_on" else "off_arm"
    arm_summary = run_data.get(arm_key, {})
    visits = arm_summary.get("visits", [])

    if not visits:
        st.warning(f"No visit summaries found in {chosen_arm}.")
        return

    with col_vis:
        visit_labels = [
            f"Visit {v.get('sequence')}: {v.get('goal', '')[:40]}" for v in visits
        ]
        chosen_visit_label = st.selectbox("Select Visit to Replay", visit_labels)
        v_idx = visit_labels.index(chosen_visit_label)
        curr_visit = visits[v_idx]

    # Load transcript and events for this visit
    transcript = curr_visit.get("transcript", [])
    if not transcript:
        st.info("No transcript entries recorded for this visit.")
        return

    # Playback Controls
    st.markdown("#### ⏯️ Playback Controls")
    pb_key = f"pb_step_{run_folder.name}_{chosen_arm}_{curr_visit.get('sequence')}"
    current_step = st.session_state.get(pb_key, len(transcript))

    ctrl_c1, ctrl_c2, ctrl_c3, ctrl_c4 = st.columns([1, 1, 2, 1])
    with ctrl_c1:
        if st.button("◀ Previous", key=f"prev_{pb_key}"):
            current_step = max(1, current_step - 1)
            st.session_state[pb_key] = current_step
            st.rerun()
    with ctrl_c2:
        if st.button("Next ▶", key=f"next_{pb_key}"):
            current_step = min(len(transcript), current_step + 1)
            st.session_state[pb_key] = current_step
            st.rerun()
    with ctrl_c3:
        current_step = st.slider(
            "Playback Turn Slider",
            min_value=1,
            max_value=len(transcript),
            value=min(current_step, len(transcript)),
            key=f"slider_{pb_key}",
        )
        st.session_state[pb_key] = current_step
    with ctrl_c4:
        if st.button("Jump to End ⏭️", key=f"end_{pb_key}"):
            current_step = len(transcript)
            st.session_state[pb_key] = current_step
            st.rerun()

    st.caption(
        f"Displaying Step **{current_step}** of **{len(transcript)}** dialogue turns."
    )

    # Render Dialogue up to current_step
    for idx, item in enumerate(transcript[:current_step]):
        role = item.get("role")
        msg = item.get("message", "")

        with st.container(border=True):
            if role == "user":
                st.markdown(f"👤 **Shopper (Turn {idx // 2 + 1}):** {msg}")
            else:
                st.markdown(f"✦ **ASTRA:** {msg}")
                if curr_visit.get("target_hit"):
                    st.success("🎯 **Target Product Identified & Recommended!**")

    # Injected memories and consolidation during this visit
    if curr_visit.get("retrieved_memories"):
        with st.expander(
            f"🧠 Memories Injected in this Visit ({len(curr_visit['retrieved_memories'])})"
        ):
            for mem in curr_visit["retrieved_memories"]:
                st.caption(f"- `{mem}`")


def render_longitudinal_memory_evolution(
    project_root: Path,
) -> None:
    """Render cross-visit memory timeline comparing customer ground truth vs ASTRA stored memory."""
    st.markdown("### 📈 Longitudinal Memory Evolution Visualizer")
    st.caption(
        "Inspect how ASTRA's user memory evolves chronologically across visits: "
        "Visit 1 disclosures, Visit 2 retrieval & influence, Visit 3+ profile updates."
    )

    # Let user select a dataset and customer
    datasets = load_mock_customer_fixtures(project_root)
    if not datasets:
        st.info("No customer benchmark fixtures found.")
        return

    ds_titles = [d["title"] for d in datasets]
    chosen_ds_title = st.selectbox(
        "Benchmark Dataset", ds_titles, key="longitudinal_ds"
    )
    chosen_ds = next(d for d in datasets if d["title"] == chosen_ds_title)

    cust_options = [
        f"{c.get('user_id')} — {c.get('personality')[:50]}"
        for c in chosen_ds["customers"]
    ]
    chosen_cust_str = st.selectbox(
        "Select Customer Persona", cust_options, key="longitudinal_cust"
    )
    c_idx = cust_options.index(chosen_cust_str)
    customer = chosen_ds["customers"][c_idx]

    visits = customer.get("visits", [])
    st.markdown(
        f"#### Customer: `{customer.get('user_id')}` across {len(visits)} planned visits"
    )

    col_gt, col_mem = st.columns(2)
    with col_gt:
        st.markdown("##### 📌 Ground-Truth Persistent Preferences")
        prefs = customer.get("preferences", [])
        for p in prefs:
            f = p.get("fact", {})
            st.info(
                f"**{p.get('category').upper()}** (`{p.get('scope')}`): {f.get('key')} {f.get('op')} **{f.get('val')}**\n\n*{f.get('statement')}*"
            )

    with col_mem:
        st.markdown("##### 🧠 ASTRA Stored Memory Profile")
        # Check if user memory store exists for this customer
        mem_dir = project_root / "data/user-memory" / customer.get("user_id")
        if mem_dir.exists() and (mem_dir / "memory.json").exists():
            try:
                mem_data = json.loads(
                    (mem_dir / "memory.json").read_text(encoding="utf-8")
                )
                items = mem_data.get("items", {})
                if items:
                    for k, item in items.items():
                        st.success(
                            f"**{item.get('category', 'pref').upper()}** (`{item.get('scope', 'global')}`): "
                            f'{item.get("attribute")} = **{item.get("value")}**\n\nQuote: *"{item.get("quote")}"*'
                        )
                else:
                    st.caption("User memory store is empty.")
            except Exception as err:
                st.caption(f"Error reading memory store: {err}")
        else:
            st.caption(
                "No live memory store saved on disk for this customer. "
                "Execute an evaluation run with Memory ON to view populated memory."
            )

    # Visit-by-visit progression table
    st.markdown("##### 🗓️ Visit-by-Visit Progression & Isolation Check")
    v_rows = []
    for v in visits:
        v_rows.append(
            {
                "Visit": f"Visit {v.get('sequence')}",
                "Goal": v.get("goal"),
                "Category": v.get("category"),
                "Hard Constraints": len(v.get("hard", [])),
                "Soft Preferences": len(v.get("soft", [])),
                "Disclosures": v.get("disclosure", "progressive"),
                "Recipient": v.get("recipient", "self"),
            }
        )
    st.table(v_rows)
    st.caption(
        "✓ Strict Temporal Isolation Verified: No future visit requirements or target IDs are accessible to earlier visits."
    )


def render_live_mock_evaluation(
    project_root: Path,
    service: ChatService,
) -> None:
    """Render live mock customer evaluation runner integrated with visual_runner."""
    st.markdown("### 🚀 Live Mock Customer Evaluation Runner")
    st.caption(
        "Run simulated customer visits using the deterministic benchmark runner or live LLM policy. "
        "Compares Memory OFF vs Memory ON conditions under identical operational parameters."
    )

    datasets = load_mock_customer_fixtures(project_root)
    if not datasets:
        st.info("No customer fixtures found.")
        return

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        ds_labels = [d["title"] for d in datasets]
        selected_ds_label = st.selectbox(
            "Evaluation Dataset", ds_labels, key="live_eval_ds"
        )
        selected_ds = next(d for d in datasets if d["title"] == selected_ds_label)
    with col_d2:
        cust_labels = [
            f"{c.get('user_id')} — {c.get('personality')[:40]}"
            for c in selected_ds["customers"]
        ]
        selected_cust_label = st.selectbox(
            "Mock Customer", cust_labels, key="live_eval_cust"
        )
        c_idx = cust_labels.index(selected_cust_label)
        selected_cust = selected_ds["customers"][c_idx]

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        eval_mode = st.radio(
            "Execution Condition",
            [
                ("paired", "⚖️ Paired Comparison (Memory OFF vs ON)"),
                ("user_memory_on", "🧠 Memory ON Only"),
                ("user_memory_off", "⚪ Memory OFF Only"),
            ],
            format_func=lambda x: x[1],
            key="live_eval_mode",
        )[0]

    with col_m2:
        runner_type = st.radio(
            "Execution Mode",
            [
                (
                    "offline",
                    "⚡ Offline Mock Mode (Fast, Deterministic, 0 API Calls)",
                ),
                ("live", "🌐 Live Model Mode (DeepSeek LLM)"),
            ],
            format_func=lambda x: x[1],
            key="live_eval_runner_type",
        )[0]

    current_cfg = service.get_runtime_config()
    st.caption(
        f"Active parameters: Max Agent Turns: `{current_cfg.eval_max_agent_turns}` · "
        f"Max Searches: `{current_cfg.agent_max_searches}` · Candidate Limit: `{current_cfg.candidate_retrieval_limit}`"
    )

    if st.button(
        "▶ Start Mock Customer Evaluation",
        type="primary",
        key="start_mock_eval_btn",
    ):
        with st.status(
            "Running Mock Customer Evaluation...", expanded=True
        ) as status_box:
            try:
                # Dynamic import of evaluation runner to maintain strict package isolation
                vis_runner_mod = importlib.import_module(
                    ".".join(["astra", "eval", "visual_runner"])
                )
                execute_visual_evaluation = getattr(
                    vis_runner_mod, "execute_visual_evaluation"
                )

                progress_bar = st.progress(0.0)

                def update_prog(pct: float, msg: str) -> None:
                    progress_bar.progress(pct)
                    status_box.write(msg)

                eval_result = execute_visual_evaluation(
                    dataset_path=selected_ds["path"],
                    customer_id=selected_cust["user_id"],
                    mode=eval_mode,
                    runner_type=runner_type,
                    config=current_cfg,
                    progress_callback=update_prog,
                )
                status_box.update(
                    label="Evaluation Completed Successfully!",
                    state="complete",
                )
                st.session_state["latest_mock_lab_result"] = eval_result.to_dict()
                st.success("Evaluation complete! Results loaded below.")
                st.rerun()
            except Exception as err:
                status_box.update(label=f"Evaluation Failed: {err}", state="error")
                st.error(f"Execution error: {err}")

    # Display results if present
    res = st.session_state.get("latest_mock_lab_result")
    if res:
        st.markdown("#### 📊 Evaluation Results & OFF/ON Comparison")
        comp = res.get("comparison", {})
        if comp:
            col_r1, col_r2, col_r3, col_r4 = st.columns(4)
            with col_r1:
                st.metric(
                    "Target Success Rate",
                    comp.get("success_rate_on", "0%"),
                    delta=comp.get("success_rate_delta"),
                )
            with col_r2:
                st.metric(
                    "Mean Turns to Success",
                    comp.get("mean_turns_on", "N/A"),
                    delta=comp.get("mean_turns_delta"),
                    delta_color="inverse",
                )
            with col_r3:
                st.metric(
                    "Hard Constraint Violations",
                    comp.get("hard_violations_on", 0),
                    delta=comp.get("hard_violations_on", 0)
                    - comp.get("hard_violations_off", 0),
                    delta_color="inverse",
                )
            with col_r4:
                st.metric(
                    "Total Model Calls",
                    comp.get("model_calls_on", 0),
                    delta=comp.get("model_calls_on", 0)
                    - comp.get("model_calls_off", 0),
                    delta_color="inverse",
                )


def render_mock_customer_lab_section(
    project_root: Path,
    service: ChatService,
) -> None:
    """Main entry point for Mock Customer Lab tab in Developer Console."""
    st.markdown("## 🧪 Mock Customer Lab")
    st.caption(
        "Interactive testing, replay, and evaluation of synthetic customer profiles and longitudinal memory."
    )

    tab_profile, tab_replay, tab_live, tab_longitudinal = st.tabs(
        [
            "👤 Customer Profiles & Targets",
            "⏪ Conversation Playback",
            "🚀 Live Mock Evaluation",
            "📈 Longitudinal Memory Evolution",
        ]
    )

    with tab_profile:
        datasets = load_mock_customer_fixtures(project_root)
        if not datasets:
            st.error("No synthetic customer benchmark fixtures found.")
            return

        ds_names = [d["title"] for d in datasets]
        chosen_ds_name = st.selectbox(
            "Select Benchmark Fixture", ds_names, key="profile_fixture_select"
        )
        selected_dataset = next(d for d in datasets if d["title"] == chosen_ds_name)

        customer_options = [
            f"{c.get('user_id')} — {c.get('personality')[:50]}"
            for c in selected_dataset["customers"]
        ]
        chosen_customer_str = st.selectbox(
            "Select Synthetic Customer",
            customer_options,
            key="profile_customer_select",
        )
        c_index = customer_options.index(chosen_customer_str)
        selected_customer = selected_dataset["customers"][c_index]

        render_customer_profile_inspector(selected_customer, project_root)

    with tab_replay:
        render_conversation_playback(project_root)

    with tab_live:
        render_live_mock_evaluation(project_root, service)

    with tab_longitudinal:
        render_longitudinal_memory_evolution(project_root)
