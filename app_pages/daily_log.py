# pages/daily_log.py
from __future__ import annotations

import uuid
import numpy as np
import pandas as pd
import streamlit as st

from core.config import LOGS_CSV, TASK_TYPES
from core.storage import save_df
from core.utils import add_delete_flag, ensure_string_cols, ensure_numeric, coerce_date_col


def render(subjects_df, logs_df, logs_df_all):
    st.title("Daily Log")

    # ----- Active vs Completed subjects -----
    has_completed_col = "completed" in subjects_df.columns
    active_subjects = subjects_df[subjects_df["completed"] != True] if has_completed_col else subjects_df.copy()
    completed_subjects = subjects_df[subjects_df["completed"] == True] if has_completed_col else subjects_df.iloc[0:0]

    # Toggle to include completed subjects in the adder (off by default)
    include_completed = False
    if has_completed_col and len(completed_subjects):
        include_completed = st.toggle("Show completed subjects in picker", value=False, help="Completed subjects are hidden by default.")

    # Build subject name -> id map for the add form
    picker_df = subjects_df if include_completed else active_subjects
    subj_opts = {row["name"]: row["id"] for _, row in picker_df.iterrows()}
    no_subjects_msg = "— no subjects —" if len(subj_opts) == 0 else None

    # --- Add form ---
    with st.form("add_log"):
        c1, c2, c3 = st.columns(3)
        with c1:
            # ensure clean date (no time); always store as ISO string later
            log_date = pd.to_datetime(st.date_input("Date", value=pd.Timestamp.today().date())).date()
        with c2:
            subj_name = st.selectbox("Subject", list(subj_opts.keys()) or [no_subjects_msg])
            subj_id = subj_opts.get(subj_name, "")
        with c3:
            hours = st.number_input("Hours", min_value=0.0, step=0.25, value=1.5)

        t1, t2, t3 = st.columns(3)
        with t1:
            task = st.selectbox("Task type", TASK_TYPES)
        with t2:
            score = st.number_input("Quick self-test % (optional)", min_value=0, max_value=100, step=1, value=0)
        with t3:
            notes = st.text_input("Notes", value="")

        submitted = st.form_submit_button("Add entry")
        if submitted:
            if not st.session_state.user:
                st.warning("Please sign in to add logs.")
            elif not subj_id:
                st.warning("Please add a subject first.")
            else:
                new_row = {
                    "id": str(uuid.uuid4()),
                    # always store as ISO string (prevents NaT/missing after CSV round-trip)
                    "date": log_date.isoformat(),
                    "subject_id": subj_id,
                    "hours": float(hours),
                    "task": task,
                    "score": int(score) if score else np.nan,
                    "notes": notes,
                    "user_id": st.session_state.user["id"],
                }
                row_df = pd.DataFrame([new_row])

                # If logs_df_all is empty or None, skip concat to avoid dtype ambiguity warnings
                if logs_df_all is not None and len(logs_df_all):
                    updated = pd.concat([logs_df_all, row_df], ignore_index=True)
                else:
                    updated = row_df

                # 🔒 normalize date BEFORE saving (handles legacy/mixed rows too)
                updated["date"] = pd.to_datetime(updated["date"], errors="coerce").dt.strftime("%Y-%m-%d")

                save_df(updated, LOGS_CSV)
                st.success("Log added.")
                st.rerun()

    # --- Editor (edit/delete) ---
    st.subheader("Edit or delete logs")
    editable = logs_df.copy()
    editable = coerce_date_col(editable, "date", out="date")
    editable = add_delete_flag(editable, "delete")
    editable = ensure_string_cols(editable, ["subject_id", "task", "notes"])
    editable = ensure_numeric(editable, ["hours", "score"])

    # Subject options for the editor:
    # keep all ACTIVE subject ids, PLUS any ids already present in the logs (so old rows remain valid)
    active_ids = set(active_subjects["id"].astype(str).tolist())
    present_ids = set(editable["subject_id"].dropna().astype(str).tolist())
    editor_subject_ids = sorted(active_ids.union(present_ids))

    if has_completed_col:
        st.caption(
            f"Active subjects shown in pickers. Completed hidden by default. "
            f"(Active: {len(active_subjects)} | Completed: {len(completed_subjects)})"
        )

    edited_view = st.data_editor(
        editable,
        column_config={
            "id": st.column_config.TextColumn(help="Unique log ID", disabled=True),
            "date": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "subject_id": st.column_config.SelectboxColumn(label="Subject", options=editor_subject_ids),
            "hours": st.column_config.NumberColumn(step=0.25, min_value=0.0),
            "task": st.column_config.SelectboxColumn(options=TASK_TYPES),
            "score": st.column_config.NumberColumn(min_value=0, max_value=100, step=1),
            "notes": st.column_config.TextColumn(),
            "delete": st.column_config.CheckboxColumn(help="Tick to delete"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="logs_editor",
    )

    csave, cdel = st.columns([1, 1])

    with csave:
        if st.button("💾 Save edits"):
            if not st.session_state.user:
                st.warning("Please sign in to save.")
            else:
                edited_view["id"] = edited_view["id"].fillna("")
                mask_new = edited_view["id"] == ""
                edited_view.loc[mask_new, "id"] = [str(uuid.uuid4()) for _ in range(mask_new.sum())]
                edited_view["hours"] = pd.to_numeric(edited_view.get("hours"), errors="coerce").fillna(0.0)
                if "score" in edited_view.columns:
                    edited_view["score"] = pd.to_numeric(edited_view["score"], errors="coerce")
                for col in ["subject_id", "task", "notes"]:
                    if col in edited_view.columns:
                        edited_view[col] = edited_view[col].astype("string").fillna("")

                # 🔒 force date -> ISO string so CSV round-trips keep it intact
                edited_view["date"] = pd.to_datetime(edited_view["date"], errors="coerce").dt.strftime("%Y-%m-%d")

                edited_view["user_id"] = st.session_state.user["id"]

                uid = st.session_state.user["id"]
                others = logs_df_all[logs_df_all.get("user_id", "") != uid]
                to_save_all = pd.concat([others, edited_view.drop(columns=["delete"], errors="ignore")], ignore_index=True)

                # extra safety (handles any lingering mixed dtypes)
                to_save_all["date"] = pd.to_datetime(to_save_all["date"], errors="coerce").dt.strftime("%Y-%m-%d")

                save_df(to_save_all, LOGS_CSV)
                st.success("Edits saved.")
                st.rerun()

    with cdel:
        if st.button("🗑️ Delete checked rows"):
            if not st.session_state.user:
                st.warning("Please sign in to delete.")
            else:
                uid = st.session_state.user["id"]
                keep_current = edited_view[edited_view.get("delete", False) != True].drop(columns=["delete"], errors="ignore")

                # 🔒 keep dates normalized when saving after delete
                keep_current["date"] = pd.to_datetime(keep_current["date"], errors="coerce").dt.strftime("%Y-%m-%d")

                keep_current["user_id"] = uid
                others = logs_df_all[logs_df_all.get("user_id", "") != uid]
                remaining_all = pd.concat([others, keep_current], ignore_index=True)

                # final guard
                remaining_all["date"] = pd.to_datetime(remaining_all["date"], errors="coerce").dt.strftime("%Y-%m-%d")

                save_df(remaining_all, LOGS_CSV)
                st.success("Selected logs deleted.")
                st.rerun()

    st.caption("Subject ID → Name map:")
    if len(subjects_df):
        map_df = subjects_df[["id", "name"]].rename(columns={"id": "Subject ID", "name": "Subject name"})
        st.dataframe(map_df, use_container_width=True, hide_index=True)
