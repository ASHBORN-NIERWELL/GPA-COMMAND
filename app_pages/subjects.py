# pages/subjects.py
from __future__ import annotations

import uuid
import pandas as pd
import streamlit as st

from core.config import DEFAULT_SETTINGS, SUBJECTS_CSV
from core.metrics import sanitize_subjects_for_editor, compute_metrics
from core.storage import save_df
from core.normalize import _align_columns


def render(subjects_df, subjects_df_all, logs_df, tests_df, settings):
    """
    Subjects & Priorities page.

    subjects_df      = filtered subjects for current user (or blanks if no login)
    subjects_df_all  = all subjects (all users)
    logs_df, tests_df = filtered logs/tests for current user (or blanks)
    settings         = current settings dict
    """
    st.title("Subjects & Priorities")
    st.caption("Keep credits accurate; adjust confidence weekly. Set exam date per subject.")

    # Make the dataframe editor-safe (especially exam_date -> datetime.date)
    subjects_editor_df = sanitize_subjects_for_editor(subjects_df, settings)

    edited = st.data_editor(
        subjects_editor_df,
        column_config={
            "id": st.column_config.TextColumn(disabled=True),
            "name": st.column_config.TextColumn(label="Subject"),
            "credits": st.column_config.NumberColumn(min_value=1, step=1),
            "confidence": st.column_config.NumberColumn(min_value=0, max_value=10, step=1),
            "exam_date": st.column_config.DateColumn(label="Exam date", format="YYYY-MM-DD"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="subjects_editor",
    )

    c1, c2 = st.columns([1, 1])

    # --- Add subject ---
    with c1:
        if st.button("➕ Add subject"):
            s = settings
            new = {
                "id": str(uuid.uuid4()),
                "name": "New subject",
                "credits": 2,
                "confidence": 5,
                "exam_date": s.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]),
                "user_id": st.session_state.user["id"] if st.session_state.user else "",
            }
            edited = pd.concat([edited, pd.DataFrame([new])], ignore_index=True)

            if "exam_date" in edited.columns:
                edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")

            if st.session_state.user:
                uid = st.session_state.user["id"]
                others = subjects_df_all[subjects_df_all.get("user_id", "") != uid]
                edited["user_id"] = uid
                save_df(pd.concat([others, edited], ignore_index=True), SUBJECTS_CSV)
            else:
                save_df(edited, SUBJECTS_CSV)

            st.rerun()

    # --- Save changes ---
    with c2:
        if st.button("💾 Save changes"):
            if "exam_date" in edited.columns:
                edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")

            if st.session_state.user:
                uid = st.session_state.user["id"]
                others = subjects_df_all[subjects_df_all.get("user_id", "") != uid]
                edited["user_id"] = uid
                save_df(pd.concat([others, edited], ignore_index=True), SUBJECTS_CSV)
            else:
                save_df(edited, SUBJECTS_CSV)

            st.success("Saved.")
            st.rerun()

    st.divider()

    # --- Computed metrics ---
    st.subheader("Computed metrics")
    metrics = compute_metrics(edited, logs_df, tests_df)
    st.dataframe(
        metrics[
            [
                "name",
                "credits",
                "confidence",
                "exam_date",
                "priority",
                "hours",
                "avg_score",
                "days_left",
                "priority_gap",
            ]
        ],
        use_container_width=True,
    )
