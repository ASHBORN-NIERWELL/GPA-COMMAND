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

    # ---------- Study momentum (last N days) ----------
    momentum_days = int(settings.get("momentum_days", 7))
    st.subheader(f"Study momentum (last {momentum_days} days)")

    if len(logs_df):
        logs = logs_df.copy()

        # Parse dates to datetime64[ns] at midnight; coerce hours
        logs["date"] = pd.to_datetime(logs["date"], errors="coerce").dt.normalize()
        logs["hours"] = pd.to_numeric(logs.get("hours"), errors="coerce").fillna(0.0)
        logs = logs.dropna(subset=["date"])

        if not logs.empty:
            min_d, max_d = logs["date"].min(), logs["date"].max()
            st.caption(f"Logs range: {min_d.date()} → {max_d.date()} • {len(logs)} rows")

        cutoff = pd.Timestamp.today().normalize() - timedelta(days=momentum_days - 1)
        recent = logs.loc[logs["date"] >= cutoff]

        # Fallbacks if the chosen window is empty
        if recent.empty:
            fallback_cut = pd.Timestamp.today().normalize() - timedelta(days=90)
            recent = logs.loc[logs["date"] >= fallback_cut]
            if recent.empty:
                recent = logs

        if not recent.empty:
            daily = recent.groupby("date", as_index=True)["hours"].sum()
            st.line_chart(daily)
        else:
            st.caption("No logs to plot.")
    else:
        st.caption("No logs yet.")

    # ---------- Knowledge curve (tests average by date) ----------
    st.subheader("Knowledge curve (tests average by date)")

    if len(tests_df):
        curve = tests_df.copy()

        # Dates as datetime64[ns] at midnight; numeric scores
        curve["date"] = pd.to_datetime(curve["date"], errors="coerce").dt.normalize()
        curve["score"] = pd.to_numeric(curve.get("score"), errors="coerce")
        curve = curve.dropna(subset=["date"])

        if not curve.empty:
            tmin, tmax = curve["date"].min(), curve["date"].max()
            st.caption(f"Tests range: {tmin.date()} → {tmax.date()} • {len(curve)} rows")

        if curve["score"].notna().any():
            series = curve.groupby("date", as_index=True)["score"].mean()
            if not series.empty:
                st.line_chart(series)
            else:
                st.caption("No test scores to plot after grouping.")
        else:
            st.caption("All test scores are missing/invalid.")
    else:
        st.caption("No test scores yet.")
