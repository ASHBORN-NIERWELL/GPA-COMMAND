# pages/self_tests.py
from __future__ import annotations

import uuid
import pandas as pd
import streamlit as st

from core.config import TESTS_CSV
from core.storage import save_df


def render(subjects_df, tests_df, tests_df_all):
    st.title("Self-Test Tracker")

    with st.form("add_test"):
        c1, c2, c3 = st.columns(3)
        with c1:
            test_date = st.date_input("Date", value=pd.Timestamp.today().date(), key="test_date")
        with c2:
            subj_opts = {row["name"]: row["id"] for _, row in subjects_df.iterrows()}
            subj_name = st.selectbox("Subject", list(subj_opts.keys()) or ["— no subjects —"], key="test_subject")
            subj_id = subj_opts.get(subj_name, "")
        with c3:
            score = st.number_input("Score (%)", min_value=0, max_value=100, step=1, value=60)
        d1, d2 = st.columns(2)
        with d1:
            difficulty = st.slider("Difficulty (1–5)", min_value=1, max_value=5, value=3)
        with d2:
            notes = st.text_input("Notes", value="")

        submitted = st.form_submit_button("Add test")
        if submitted:
            if not st.session_state.user:
                st.warning("Please sign in to add tests.")
            else:
                new_row = {
                    "id": str(uuid.uuid4()),
                    "date": pd.to_datetime(test_date).strftime("%Y-%m-%d"),
                    "subject_id": subj_id,
                    "score": int(score),
                    "difficulty": int(difficulty),
                    "notes": notes,
                    "user_id": st.session_state.user["id"],
                }
                updated = pd.concat([tests_df_all, pd.DataFrame([new_row])], ignore_index=True)
                save_df(updated, TESTS_CSV)
                st.success("Test added.")
                st.rerun()

    st.subheader("Your test history")
    st.dataframe(tests_df.sort_values("date", ascending=False), use_container_width=True)
