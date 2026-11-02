"""Developer Console & Visual Evaluation Runner UI for Streamlit.

Organized into three cohesive sections:
A. Parameters: editable runtime operational limits, presets (Demo, Eval, Custom), JSON export/import.
B. Live Agent Execution Trace: 13-stage visual trace, duration, tokens, memory scores, error diagnosis.
C. Visual Synthetic Customer Evaluation: benchmark runner, paired OFF/ON comparison, history review.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import streamlit as st

from .runtime_config import (
    PARAMETER_METADATA,
    PRESETS,
    RuntimeConfig,
)
from .trace import TraceExtractor, diagnose_turn_failure
from .ui_service import ChatService


def render_parameters_section(
    service: ChatService,
    session_view: dict[str, Any],
    project_root: Path,
) -> None:
    """Render Section A: Operational limits, presets, and configuration inspection."""
    st.markdown("### ⚙️ Operational Parameters & Limits")
    st.caption(
        "Inspect and configure execution bounds. Operational settings update live; "
        "customer isolation, catalogue integrity, and hard constraints remain immutable."
    )

    # 1. Preset Selector & Import/Export Bar
    col_preset, col_exp, col_imp = st.columns([2, 1, 1])

    current_cfg: RuntimeConfig = st.session_state.get(
        "runtime_config", service.get_runtime_config()
    )

    with col_preset:
        preset_names = list(PRESETS.keys()) + ["Custom"]
        active_preset = st.session_state.get(
            "selected_preset", "Evaluation (Standard Benchmark)"
        )
        chosen_preset = st.selectbox(
            "Configuration Preset",
            preset_names,
            index=preset_names.index(active_preset)
            if active_preset in preset_names
            else 1,
            key="preset_selector",
            help="Select an operational profile. Demo is generous; Evaluation matches standard benchmark controls.",
        )
        if chosen_preset in PRESETS and chosen_preset != st.session_state.get(
            "selected_preset"
        ):
            st.session_state["selected_preset"] = chosen_preset
            current_cfg = PRESETS[chosen_preset]
            st.session_state["runtime_config"] = current_cfg
            service.set_runtime_config(current_cfg)
            st.rerun()

    with col_exp:
        st.download_button(
            "📥 Export Preset",
            data=current_cfg.to_json(),
            file_name="astra_runtime_config.json",
            mime="application/json",
            use_container_width=True,
            help="Export active parameters as a JSON configuration file.",
        )

    with col_imp:
        with st.popover("📤 Import Preset"):
            uploaded = st.file_uploader(
                "Upload JSON config", type=["json"], key="config_uploader"
            )
            if uploaded is not None:
                try:
                    loaded = RuntimeConfig.from_json(uploaded.read().decode("utf-8"))
                    st.session_state["runtime_config"] = loaded
                    st.session_state["selected_preset"] = "Custom"
                    service.set_runtime_config(loaded)
                    st.success("Configuration loaded!")
                    st.rerun()
                except Exception as err:
                    st.error(f"Invalid configuration file: {err}")

    # Session Snapshot Notice
    snap = session_view.get("config_snapshot")
    if snap:
        with st.expander("📌 Active Session Configuration Snapshot", expanded=False):
            st.caption(
                "Existing sessions retain an immutable configuration snapshot for reproducibility."
            )
            st.json(snap)

    st.divider()

    # 2. Configurable Parameter Controls (Grouped by Category)
    categories = [
        "LLM",
        "Shopping & Search",
        "User Memory",
        "Procedural Memory",
        "Evaluation",
    ]
    tabs = st.tabs([f"📌 {cat}" for cat in categories])

    updated_fields = {}

    for cat, tab in zip(categories, tabs):
        with tab:
            cat_params = [
                (k, meta)
                for k, meta in PARAMETER_METADATA.items()
                if meta["category"] == cat
            ]
            for param_key, meta in cat_params:
                c1, c2 = st.columns([1, 2])
                current_val = getattr(current_cfg, param_key)
                default_val = meta["default"]

                with c1:
                    st.markdown(f"**{meta['label']}**")
                    st.caption(meta["description"])
                    diff_tag = (
                        "*(default)*"
                        if current_val == default_val
                        else "**(modified)**"
                    )
                    st.caption(f"Default: `{default_val}` {diff_tag}")

                with c2:
                    val_type = meta.get("type", "int")
                    if val_type == "int":
                        low, high = meta["bounds"]
                        new_val = st.slider(
                            meta["label"],
                            min_value=low,
                            max_value=high,
                            value=int(current_val),
                            key=f"cfg_{param_key}",
                            label_visibility="collapsed",
                        )
                        updated_fields[param_key] = new_val
                    elif val_type == "float":
                        low, high = meta["bounds"]
                        step = 0.05 if high <= 2.0 else 0.5
                        new_val = st.slider(
                            meta["label"],
                            min_value=float(low),
                            max_value=float(high),
                            value=float(current_val),
                            step=step,
                            key=f"cfg_{param_key}",
                            label_visibility="collapsed",
                        )
                        updated_fields[param_key] = new_val
                    elif val_type == "bool":
                        new_val = st.checkbox(
                            f"Enable {meta['label']}",
                            value=bool(current_val),
                            key=f"cfg_{param_key}",
                        )
                        updated_fields[param_key] = new_val
                    elif val_type == "choice":
                        options = meta["options"]
                        idx = (
                            options.index(current_val) if current_val in options else 0
                        )
                        new_val = st.selectbox(
                            meta["label"],
                            options,
                            index=idx,
                            key=f"cfg_{param_key}",
                            label_visibility="collapsed",
                        )
                        updated_fields[param_key] = new_val
                st.divider()

    # Apply changes if modified
    if any(getattr(current_cfg, k) != v for k, v in updated_fields.items()):
        new_config = current_cfg.copy(**updated_fields)
        st.session_state["runtime_config"] = new_config
        st.session_state["selected_preset"] = "Custom"
        service.set_runtime_config(new_config)

    # Immutable Safeguards Overview
    with st.expander("🛡️ Immutable Security & Integrity Safeguards"):
        st.markdown("""
        The following operational integrity safeguards remain hardcoded and cannot be disabled:
        - **Customer Isolation:** Customer spaces and SQLite stores are strictly partitioned by validated user identity.
        - **Catalogue Verification:** All product searches and recommendations strictly verify cryptographic SHA-256 integrity against the 50,000-product catalogue.
        - **Provenance Integrity:** Memory consolidation strictly verifies quote evidence, ownership, and event origin.
        - **Hard Constraint Enforcement:** All recommendations strictly pass hard constraint eligibility via catalogue facts; soft preferences only break ties.
        - **Hidden Ground-Truth Isolation:** Evaluator target IDs and private descriptions are strictly shielded from agent context.
        """)


def render_execution_trace_section(
    session_view: dict[str, Any],
    service: ChatService,
) -> None:
    """Render Section B: Live Agent Execution Trace with 13-stage observability and error diagnosis."""
    st.markdown("### 🔍 Live Agent Execution Trace")
    st.caption(
        "Visual 13-stage timeline of ASTRA's reasoning, tool execution, memory retrieval, "
        "and consolidation lifecycle for the current session."
    )

    events = session_view.get("events", [])
    sid = session_view.get("session_id", "")
    owner = session_view.get("user_id", "")

    # Top Action Bar: Export JSON & Diagnosis
    c_diag, c_btn = st.columns([3, 1])

    # Automated Error Diagnosis
    diag_message = diagnose_turn_failure(events)
    with c_diag:
        if diag_message:
            st.error(f"🚨 **Execution Diagnosis:** {diag_message}")
        else:
            st.success(
                "🟢 **Operational Status:** Normal execution. All validation and budget checks passing."
            )

    with c_btn:
        trace_json = TraceExtractor.export_session_json(sid, events, owner)
        st.download_button(
            "📥 Export Trace JSON",
            data=trace_json,
            file_name=f"astra_trace_{sid[-8:]}.json",
            mime="application/json",
            use_container_width=True,
            help="Download full structured execution trace and events.",
        )

    st.divider()

    # Turn selector or full trace
    user_turns = [e for e in events if e.get("type") == "user_message"]
    if not user_turns:
        st.info(
            "No turns executed yet in this session. Send a shopping request to view live stage traces."
        )
        return

    turn_options = ["All Turns (Full Session)"] + [
        f'Turn {idx}: "{e.get("payload", {}).get("message", "")[:40]}…"'
        for idx, e in enumerate(user_turns, start=1)
    ]
    selected_turn_str = st.selectbox(
        "Select Turn to Inspect",
        turn_options,
        index=0,
        key="trace_turn_selector",
    )

    req_id = None
    if selected_turn_str != "All Turns (Full Session)":
        idx = turn_options.index(selected_turn_str) - 1
        req_id = user_turns[idx].get("turn_id")

    stages = TraceExtractor.extract_turn_trace(events, request_id=req_id)

    # Render Stages in Interactive Cards
    status_icons = {
        "completed": "✅",
        "running": "⏳",
        "pending": "⚪",
        "skipped": "⏭️",
        "blocked": "🚫",
        "failed": "❌",
    }

    for stage in stages:
        icon = status_icons.get(stage.status, "•")
        badge = f"**{stage.name}**"

        with st.container(border=True):
            col_icon, col_title, col_stat = st.columns([1, 8, 3])
            with col_icon:
                st.markdown(f"### {icon}")
            with col_title:
                st.markdown(badge)
                st.caption(stage.summary or "Awaiting execution")
            with col_stat:
                st.caption(f"Status: `{stage.status.upper()}`")
                if stage.duration_ms > 0:
                    st.caption(f"Duration: `{stage.duration_ms:.1f} ms`")

            # Expandable Details & Metrics
            if stage.metrics or stage.inputs or stage.outputs or stage.failure_reason:
                with st.expander("View Stage Data & Metrics"):
                    if stage.failure_reason:
                        st.error(f"Failure reason: `{stage.failure_reason}`")
                    if stage.metrics:
                        st.markdown("**Metrics:**")
                        st.json(stage.metrics)
                    if stage.inputs:
                        st.markdown("**Inputs:**")
                        st.json(stage.inputs)
                    if stage.outputs:
                        st.markdown("**Outputs:**")
                        st.json(stage.outputs)


def render_evaluation_runner_section(
    project_root: Path,
    service: ChatService,
) -> None:
    """Render Section C: Visual Synthetic Customer Evaluation Runner with Paired Comparison."""
    st.markdown("### 📊 Visual Synthetic Customer Evaluation Runner")
    st.caption(
        "Demonstrate and measure ASTRA's personalized memory benefits against frozen benchmark datasets. "
        "Runs chronologically; earlier visits consolidate memories that later visits retrieve."
    )

    try:
        vr = importlib.import_module(".".join(["astra", "eval", "visual_runner"]))
        execute_visual_evaluation = vr.execute_visual_evaluation
        find_datasets = vr.find_datasets
        list_saved_runs = vr.list_saved_runs
        load_dataset_customers = vr.load_dataset_customers
    except (ImportError, ModuleNotFoundError):
        st.info("Evaluation runner is unavailable.")
        return

    datasets = find_datasets(project_root)
    if not datasets:
        st.error("No customer datasets found in `experiments/longitudinal/`.")
        return

    # 1. Dataset & Customer Selection
    col_ds, col_cust = st.columns(2)

    with col_ds:
        ds_titles = [d["title"] for d in datasets]
        chosen_ds_title = st.selectbox(
            "Benchmark Dataset",
            ds_titles,
            index=0,
            key="eval_dataset_picker",
        )
        selected_ds_info = next(d for d in datasets if d["title"] == chosen_ds_title)
        dataset_path = Path(selected_ds_info["path"])

    customers = load_dataset_customers(dataset_path)

    with col_cust:
        cust_labels = [
            f"{c['user_id']} ({c['visit_count']} visits) — {c['personality'][:40]}…"
            for c in customers
        ]
        chosen_cust_label = st.selectbox(
            "Customer / Persona",
            cust_labels,
            index=0,
            key="eval_customer_picker",
        )
        chosen_cust_idx = cust_labels.index(chosen_cust_label)
        selected_customer = customers[chosen_cust_idx]

    # Customer Persona Details
    with st.expander(
        f"👤 Customer Profile: {selected_customer['user_id']}", expanded=False
    ):
        st.markdown(f"**Personality:** {selected_customer['personality']}")
        st.markdown(f"**Background:** {selected_customer['background']}")
        st.markdown(f"**Total Visits:** {selected_customer['visit_count']}")
        for v in selected_customer["visits"]:
            st.caption(
                f"- **Visit {v['sequence']}** [{v['category']}]: {v['goal']} *(Mode: {v['evaluation_mode']})*"
            )

    st.divider()

    # 2. Evaluation Setup: Mode, Visits, Runner Type
    col_mode, col_seq, col_runtype = st.columns(3)

    with col_mode:
        eval_mode_choice = st.radio(
            "Comparison Mode",
            ["Paired Comparison (OFF vs ON)", "Memory ON only", "Memory OFF only"],
            index=0,
            key="eval_mode_choice",
            help="Paired comparison runs Memory OFF and Memory ON under identical conditions and computes the delta.",
        )
        arm_mode = (
            "paired"
            if "Paired" in eval_mode_choice
            else ("user_memory_on" if "ON" in eval_mode_choice else "user_memory_off")
        )

    with col_seq:
        visit_options = ["All Visits (Complete Sequence)"] + [
            f"Visit {v['sequence']}: {v['goal'][:25]}…"
            for v in selected_customer["visits"]
        ]
        chosen_seq_str = st.selectbox(
            "Visits to Execute",
            visit_options,
            index=0,
            key="eval_visit_seq_picker",
        )
        visit_seq = (
            None
            if chosen_seq_str == "All Visits (Complete Sequence)"
            else [int(chosen_seq_str.split(":")[0].replace("Visit ", ""))]
        )

    with col_runtype:
        runner_choice = st.radio(
            "Runner Engine",
            [
                "Offline Mock / Deterministic (Free & Fast)",
                "Live Model (DeepSeek Flash)",
            ],
            index=0,
            key="eval_runner_type_choice",
            help="Offline mock uses deterministic ScriptedShopper; live mode calls DeepSeek Flash (requires API credits).",
        )
        is_live = "Live" in runner_choice

    if is_live:
        st.warning(
            "⚠️ Live mode will make API calls to DeepSeek Flash. Ensure you have spending allowance configured.",
            icon="⚠️",
        )

    # 3. Execution Control Bar
    col_run_btn, col_hist = st.columns([1, 1])

    with col_run_btn:
        start_eval = st.button(
            "▶ Run Evaluation",
            type="primary",
            use_container_width=True,
            key="start_eval_btn",
        )

    # 4. Review Past Runs
    runs_dir = project_root / "data/eval-ui"
    saved_runs = list_saved_runs(runs_dir)

    with col_hist:
        with st.popover("📂 Load Previous Run Results"):
            if not saved_runs:
                st.caption("No previous runs saved yet.")
            else:
                run_labels = [
                    f"{r['timestamp'][:16].replace('T', ' ')} · {r['customer_id']} ({r['mode']})"
                    for r in saved_runs
                ]
                selected_run_label = st.selectbox(
                    "Select saved run", run_labels, key="saved_run_selector"
                )
                if st.button(
                    "Load Run Result", key="load_run_btn", use_container_width=True
                ):
                    run_idx = run_labels.index(selected_run_label)
                    chosen_run_info = saved_runs[run_idx]
                    run_data = json.loads(Path(chosen_run_info["path"]).read_text())
                    st.session_state["eval_result"] = run_data
                    st.success(f"Loaded run {chosen_run_info['run_id']}!")
                    st.rerun()

    # Execution Action
    if start_eval:
        prog_bar = st.progress(0.0)
        status_text = st.empty()

        def on_prog(ratio: float, msg: str) -> None:
            prog_bar.progress(min(max(ratio, 0.0), 1.0))
            status_text.caption(f"⏳ {msg}")

        try:
            status_text.caption("Initializing evaluation runner…")
            policy = service.policy  # Uses DeepSeekPolicy or test mock
            active_cfg = st.session_state.get(
                "runtime_config", service.get_runtime_config()
            )

            res = execute_visual_evaluation(
                dataset_path=dataset_path,
                customer_id=selected_customer["user_id"],
                visit_sequence=visit_seq,
                mode=arm_mode,
                runner_type="live" if is_live else "offline",
                policy=policy,
                catalogue_path=Path("data/catalogue/catalog.jsonl"),
                index_path=Path("data/index/catalogue.sqlite"),
                config=active_cfg,
                progress_callback=on_prog,
            )
            prog_bar.progress(1.0)
            status_text.success("✓ Evaluation completed successfully!")
            st.session_state["eval_result"] = res.to_dict()
        except Exception as e:
            status_text.error(f"Evaluation failed: {e}")
            return

    # 5. Display Evaluation Results
    eval_res = st.session_state.get("eval_result")
    if eval_res:
        st.divider()
        st.markdown(f"#### 📈 Results for Customer `{eval_res['customer_id']}`")
        st.caption(
            f"Run ID: `{eval_res['run_id']}` · Mode: `{eval_res['mode']}` · Engine: `{eval_res['runner_type']}`"
        )

        # Side-by-side Paired Comparison Table
        comp = eval_res.get("comparison")
        if comp:
            st.markdown("##### ⚖️ Paired Comparison: Memory OFF vs Memory ON")
            c_m1, c_m2, c_m3, c_m4 = st.columns(4)
            with c_m1:
                st.metric(
                    "Target Success Rate",
                    comp.get("success_rate_on", "0%"),
                    delta=comp.get("success_rate_delta"),
                )
            with c_m2:
                st.metric(
                    "Mean Turns to Success",
                    comp.get("mean_turns_on", "N/A"),
                    delta=comp.get("mean_turns_delta"),
                    delta_color="inverse",
                )
            with c_m3:
                st.metric(
                    "Hard Constraint Violations",
                    comp.get("hard_violations_on", 0),
                    delta=comp.get("hard_violations_on", 0)
                    - comp.get("hard_violations_off", 0),
                    delta_color="inverse",
                )
            with c_m4:
                st.metric(
                    "Total Model Calls",
                    comp.get("model_calls_on", 0),
                    delta=comp.get("model_calls_on", 0)
                    - comp.get("model_calls_off", 0),
                    delta_color="inverse",
                )

        # Tabbed Drilldown by Arm
        off_data = eval_res.get("off_arm")
        on_data = eval_res.get("on_arm")

        tab_labels = []
        if on_data:
            tab_labels.append("🧠 Memory ON Arm")
        if off_data:
            tab_labels.append("⚪ Memory OFF Arm")

        arm_tabs = st.tabs(tab_labels)
        for t_label, a_tab in zip(tab_labels, arm_tabs):
            with a_tab:
                curr_arm = on_data if "ON" in t_label else off_data
                if not curr_arm:
                    continue

                col_a1, col_a2, col_a3, col_a4 = st.columns(4)
                with col_a1:
                    st.metric(
                        "Visits Completed",
                        f"{curr_arm['successful_visits']}/{curr_arm['total_visits']}",
                    )
                with col_a2:
                    st.metric(
                        "Target Success",
                        f"{curr_arm['target_success_rate'] * 100:.1f}%",
                    )
                with col_a3:
                    st.metric(
                        "Mean Turns",
                        f"{curr_arm['mean_turns_to_success']:.1f}"
                        if curr_arm["mean_turns_to_success"]
                        else "N/A",
                    )
                with col_a4:
                    st.metric("Total Searches", curr_arm["total_searches"])

                st.markdown("##### Visits Breakdown & Dialogue Transcripts")
                for v in curr_arm.get("visits", []):
                    hit_badge = (
                        "🎯 Target Found" if v["target_hit"] else "❌ Target Missed"
                    )
                    turn_info = (
                        f"in {v['turn_hit']} turns"
                        if v["target_hit"]
                        else f"({v['total_turns']} turns)"
                    )
                    with st.expander(
                        f"Visit {v['sequence']} [{hit_badge} {turn_info}]: {v['goal']}"
                    ):
                        st.caption(
                            f"Task ID: `{v['task_id']}` · Hard Violations: {v['hard_violations']} · Calls: {v['model_calls']}"
                        )

                        if v.get("retrieved_memories"):
                            st.markdown(
                                f"**Retrieved Memories Injected ({len(v['retrieved_memories'])}):**"
                            )
                            st.caption(
                                ", ".join(f"`{m}`" for m in v["retrieved_memories"])
                            )

                        if v.get("consolidated_memories"):
                            st.markdown(
                                f"**Consolidated at Session End ({len(v['consolidated_memories'])}):**"
                            )
                            for op in v["consolidated_memories"]:
                                st.caption(
                                    f"- `{op.get('op')}` {op.get('attribute')}: {op.get('value')} (Scope: {op.get('scope')})"
                                )

                        st.markdown("**Transcript:**")
                        for msg in v.get("transcript", []):
                            role = msg.get("role")
                            prefix = (
                                "👤 **Shopper:** "
                                if role == "user"
                                else "✦ **ASTRA:** "
                            )
                            st.markdown(prefix + msg.get("message", ""))
