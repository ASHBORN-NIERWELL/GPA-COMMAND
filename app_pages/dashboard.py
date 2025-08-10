from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
import streamlit as st
from core.metrics import compute_metrics, weighted_readiness

def render(subjects_df, logs_df, tests_df, settings):
    st.title(f"GPA Command Center — {settings.get('semester','Sem')}")
    metrics = compute_metrics(subjects_df, logs_df, tests_df)

    c1, c2, c3 = st.columns(3)
    with c1:
        if not metrics.empty:
            focus_row = metrics.sort_values("priority_gap", ascending=False).iloc[0]
            st.metric("Focus today on", focus_row["name"], delta=f"Gap {focus_row['priority_gap']:.2f}")
        else:
            st.info("Add subjects to get a focus suggestion.")
    with c2:
        ready = weighted_readiness(metrics)
        st.metric("Overall readiness (weighted)", f"{round(ready*100):d}%")
    with c3:
        st.metric("Study momentum", f"{len(logs_df)} logs • {len(tests_df)} tests")

    focus_n = int(settings.get("focus_n", 3))
    st.subheader(f"Top {focus_n} focus areas (by priority gap)")
    if len(metrics):
        topn = metrics.sort_values("priority_gap", ascending=False).head(focus_n)[
            ["name","priority_gap","avg_score","hours","days_left"]
        ]
        st.dataframe(topn.set_index("name"), use_container_width=True)

    st.subheader("Hours by subject")
    hb = metrics[["name","hours"]].set_index("name")
    st.bar_chart(hb)

    momentum_days = int(settings.get("momentum_days", 7))
    st.subheader(f"Study momentum (last {momentum_days} days)")
    if len(logs_df):
        logs = logs_df.copy()
        logs["date"] = pd.to_datetime(logs["date"], errors="coerce").dt.date
        logs = logs.dropna(subset=["date"])
        cutoff = date.today() - timedelta(days=momentum_days - 1)
        recent = logs[logs["date"] >= cutoff]
        daily = recent.groupby("date")["hours"].sum().reset_index().set_index("date")
        st.line_chart(daily)
    else:
        st.caption("No logs yet.")

    st.subheader("Knowledge curve (tests average by date)")
    if len(tests_df):
        curve = tests_df.copy()
        curve["date"] = pd.to_datetime(curve["date"], errors="coerce").dt.date
        curve = curve.dropna(subset=["date"]).groupby("date")["score"].mean().reset_index().set_index("date")
        st.line_chart(curve)
    else:
        st.caption("No test scores yet.")
