from __future__ import annotations
import pandas as pd
import streamlit as st
from datetime import timedelta
from core.metrics import compute_metrics, weighted_readiness


def render(subjects_df, logs_df, tests_df, settings):
    st.title(f"GPA Command Center — {settings.get('semester','Sem')}")

    # ---------- Metrics ----------
    metrics = compute_metrics(subjects_df, logs_df, tests_df)

    c1, c2, c3 = st.columns(3)
    with c1:
        if not metrics.empty:
            focus_row = metrics.sort_values("priority_gap", ascending=False).iloc[0]
            st.metric("Focus today on", focus_row["name"], delta=f"Gap {focus_row['priority_gap']:.2f}")
        else:
            st.info("Add subjects to get a focus suggestion.")
    with c2:
        ready = weighted_readiness(metrics) if not metrics.empty else 0.0
        st.metric("Overall readiness (weighted)", f"{round(ready*100):d}%")
    with c3:
        st.metric("Study momentum", f"{len(logs_df)} logs • {len(tests_df)} tests")

    focus_n = int(settings.get("focus_n", 3))
    st.subheader(f"Top {focus_n} focus areas (by priority gap)")
    if not metrics.empty:
        topn = metrics.sort_values("priority_gap", ascending=False).head(focus_n)[
            ["name", "priority_gap", "avg_score", "hours", "days_left"]
        ]
        st.dataframe(topn.set_index("name"), use_container_width=True)
    else:
        st.caption("No subjects yet.")

    st.subheader("Hours by subject")
    if not metrics.empty and "hours" in metrics:
        hb = metrics[["name", "hours"]].set_index("name")
        st.bar_chart(hb)
    else:
        st.caption("No study hours recorded yet.")

    # =======================
    # STUDY MOMENTUM — Optimized & Interactive
    # =======================
    st.subheader("Study momentum")

    if len(logs_df):
        logs = logs_df.copy()
        # Safe parsing
        logs["date"] = pd.to_datetime(logs["date"], errors="coerce").dt.normalize()
        logs["hours"] = pd.to_numeric(logs.get("hours"), errors="coerce").fillna(0.0)
        logs = logs.dropna(subset=["date"])

        if logs.empty:
            st.caption("No valid logs to plot.")
        else:
            # Controls
            c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
            with c1:
                range_mode = st.radio("Range", ["Last N days", "Custom"], horizontal=True, key="mom_range")
            with c2:
                agg = st.radio("Aggregate", ["Daily", "Weekly"], horizontal=True, key="mom_agg")
            with c3:
                chart_kind = st.radio("Chart", ["Line", "Bar"], horizontal=True, key="mom_kind")
            with c4:
                subj_map = {r["name"]: r["id"] for _, r in subjects_df.iterrows()} if len(subjects_df) else {}
                sel_subj = st.multiselect("Subjects (optional)", list(subj_map.keys()), key="mom_subj")

            if sel_subj:
                logs = logs[logs["subject_id"].isin([subj_map[n] for n in sel_subj])]

            # Pick window
            if range_mode == "Last N days":
                default_days = int(settings.get("momentum_days", 7))
                n_days = st.slider("Days", 3, 180, default_days, 1, key="mom_days")
                end = pd.Timestamp.today().normalize()
                start = end - pd.Timedelta(days=n_days - 1)
            else:
                min_d, max_d = logs["date"].min(), logs["date"].max()
                start_default = max(min_d, pd.Timestamp.today().normalize() - pd.Timedelta(days=30))
                end_default = max_d
                start_end = st.date_input(
                    "Pick a date range",
                    (start_default.date(), end_default.date()),
                    min_value=min_d.date(),
                    max_value=max_d.date(),
                    key="mom_custom_range",
                )
                if not isinstance(start_end, tuple) or len(start_end) != 2:
                    st.warning("Select a start and end date.")
                    return
                start = pd.to_datetime(start_end[0]).normalize()
                end = pd.to_datetime(start_end[1]).normalize()
                if start > end:
                    start, end = end, start

            window = logs[(logs["date"] >= start) & (logs["date"] <= end)]
            if window.empty:
                st.caption("No logs in the selected window. Expanding to last 90 days.")
                end = pd.Timestamp.today().normalize()
                start = end - pd.Timedelta(days=89)
                window = logs[(logs["date"] >= start) & (logs["date"] <= end)]

            # Aggregate & zero-fill
            if agg == "Weekly":
                window = window.groupby(pd.Grouper(key="date", freq="W-MON"), as_index=True)["hours"].sum().to_frame()
                idx = pd.date_range(start, end, freq="W-MON")
            else:
                window = window.groupby("date", as_index=True)["hours"].sum().to_frame()
                idx = pd.date_range(start, end, freq="D")
            window = window.reindex(idx, fill_value=0.0)
            window.index.name = "date"

            # Rolling average (causal, not centered)
            roll_on = st.checkbox("Show rolling average", value=True, key="mom_roll")
            if roll_on:
                win = 3 if agg == "Daily" else 2
                window["roll"] = window["hours"].rolling(win, min_periods=1).mean()

            # Diagnostics
            total_h = float(window["hours"].sum())
            active_bins = int((window["hours"] > 0).sum())
            span_text = f"{start.date()} → {end.date()}"
            st.caption(f"{agg} span: {span_text} • total {total_h:.1f} h • active {active_bins}/{len(window)} bins")

            # Plot
            if chart_kind == "Bar":
                st.bar_chart(window["hours"])
                if roll_on:
                    st.line_chart(window["roll"])
            else:
                to_plot = window[["hours"] + (["roll"] if roll_on else [])]
                st.line_chart(to_plot)
    else:
        st.caption("No logs yet.")

    # =======================
    # KNOWLEDGE CURVE — Optimized & Interactive
    # =======================
    st.subheader("Knowledge curve")

    if len(tests_df):
        curve = tests_df.copy()
        curve["date"] = pd.to_datetime(curve["date"], errors="coerce").dt.normalize()
        curve["score"] = pd.to_numeric(curve.get("score"), errors="coerce")
        curve = curve.dropna(subset=["date"])

        if curve.empty or not curve["score"].notna().any():
            st.caption("No valid test scores to plot.")
        else:
            c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
            with c1:
                kc_agg = st.radio("Aggregate", ["Daily", "Weekly"], horizontal=True, key="kc_agg")
            with c2:
                kc_stat = st.radio("Stat", ["Mean", "Median"], horizontal=True, key="kc_stat")
            with c3:
                kc_roll = st.checkbox("Rolling avg", value=True, key="kc_roll")
            with c4:
                subj_map = {r["name"]: r["id"] for _, r in subjects_df.iterrows()} if len(subjects_df) else {}
                kc_sel_subj = st.multiselect("Subjects (optional)", list(subj_map.keys()), key="kc_subj")

            if kc_sel_subj:
                curve = curve[curve["subject_id"].isin([subj_map[n] for n in kc_sel_subj])]

            # Window slider (days)
            kc_days = st.slider(
                "Window (days)", 7, 365,
                max(30, int(settings.get("momentum_days", 7) * 4)), 1, key="kc_days"
            )
            end = pd.Timestamp.today().normalize()
            start = end - pd.Timedelta(days=kc_days - 1)
            curw = curve[(curve["date"] >= start) & (curve["date"] <= end)]
            if curw.empty:
                st.caption("No tests in the selected window. Showing all available history.")
                curw = curve.copy()
                start, end = curw["date"].min(), curw["date"].max()

            g = curw.groupby(pd.Grouper(key="date", freq=("W-MON" if kc_agg == "Weekly" else "D")))
            series = (g["score"].median() if kc_stat == "Median" else g["score"].mean()).rename("score_avg")
            counts = g["score"].count().rename("attempts")

            out = pd.concat([series, counts], axis=1)
            idx = pd.date_range(out.index.min(), out.index.max(), freq=("W-MON" if kc_agg == "Weekly" else "D"))
            out = out.reindex(idx)
            out.index.name = "date"

            if kc_roll:
                win = 3 if kc_agg == "Daily" else 2
                out["roll"] = out["score_avg"].rolling(win, min_periods=1).mean()

            latest = out["score_avg"].dropna().iloc[-1] if out["score_avg"].notna().any() else float("nan")
            base = out["score_avg"].dropna().iloc[0] if out["score_avg"].notna().any() else float("nan")
            delta = (latest - base) if pd.notna(latest) and pd.notna(base) else None
            att_sum = int(counts.sum())
            st.caption(
                f"{kc_agg} span: {start.date()} → {end.date()} • "
                f"attempts {att_sum} • latest {latest:.0f}%"
                + (f" ({'+' if delta and delta>=0 else ''}{delta:.0f} vs start)" if delta is not None else "")
            )

            st.line_chart(out[["score_avg"] + (["roll"] if kc_roll else [])])
            st.bar_chart(out["attempts"].fillna(0))
    else:
        st.caption("No test scores yet.")
