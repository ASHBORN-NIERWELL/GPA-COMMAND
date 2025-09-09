# pages/subjects.py
from __future__ import annotations

import uuid
import pandas as pd
import streamlit as st
from datetime import datetime

from core.config import DEFAULT_SETTINGS, SUBJECTS_CSV
from core.metrics import sanitize_subjects_for_editor, compute_metrics
from core.storage import save_df


REQUIRED_COLS = [
    "id", "name", "credits", "confidence", "exam_date",
    "user_id", "completed", "completed_at", "progress_snapshot"
]

def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add missing columns with sensible defaults, and align dtypes (keep exam_date as date for editor)."""
    df = df.copy()

    if "id" not in df.columns:
        df["id"] = ""
    if "name" not in df.columns:
        df["name"] = ""
    if "credits" not in df.columns:
        df["credits"] = 2
    if "confidence" not in df.columns:
        df["confidence"] = 5
    if "exam_date" not in df.columns:
        df["exam_date"] = DEFAULT_SETTINGS.get("default_exam_date", "")
    if "user_id" not in df.columns:
        df["user_id"] = ""

    # NEW fields
    if "completed" not in df.columns:
        df["completed"] = False
    else:
        df["completed"] = df["completed"].fillna(False).astype(bool)

    if "completed_at" not in df.columns:
        df["completed_at"] = ""
    else:
        df["completed_at"] = df["completed_at"].fillna("").astype(str)

    if "progress_snapshot" not in df.columns:
        df["progress_snapshot"] = 0.0
    else:
        df["progress_snapshot"] = pd.to_numeric(df["progress_snapshot"], errors="coerce").fillna(0.0)

    # Keep exam_date as Python date for the editor (do NOT stringify here)
    if "exam_date" in df.columns:
        df["exam_date"] = pd.to_datetime(df["exam_date"], errors="coerce").dt.date

    # Ensure required columns exist
    for col in REQUIRED_COLS:
        if col not in df.columns:
            if col == "completed":
                df[col] = False
            elif col in ("progress_snapshot", "credits", "confidence"):
                df[col] = 0
            elif col == "exam_date":
                df[col] = pd.to_datetime(DEFAULT_SETTINGS.get("default_exam_date", ""), errors="coerce").date()
            else:
                df[col] = ""
    return df


def _save_subjects(edited: pd.DataFrame, subjects_df_all: pd.DataFrame):
    """Persist edited subjects to disk, handling user scoping."""
    # Normalize exam_date to ISO string for storage
    if "exam_date" in edited.columns:
        edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")

    if st.session_state.user:
        uid = st.session_state.user["id"]
        others = subjects_df_all[subjects_df_all.get("user_id", "") != uid]
        edited["user_id"] = uid
        save_df(pd.concat([others, edited], ignore_index=True), SUBJECTS_CSV)
    else:
        save_df(edited, SUBJECTS_CSV)


def render(subjects_df, subjects_df_all, logs_df, tests_df, settings):
    """
    Subjects & Priorities page.

    subjects_df      = filtered subjects for current user (or blanks if no login)
    subjects_df_all  = all subjects (all users)
    logs_df, tests_df = filtered logs/tests for current user (or blanks)
    settings         = current settings dict
    """
    st.title("Subjects & Priorities")
    st.caption("Keep credits accurate; adjust confidence weekly. Set exam date per subject. Mark complete when done ✅.")

    # Ensure required columns exist (adds: completed, completed_at, progress_snapshot)
    subjects_df = _ensure_columns(subjects_df)
    subjects_df_all = _ensure_columns(subjects_df_all)

    # Keep a copy to detect completion flips after editing
    before = subjects_df.set_index("id", drop=False).copy()

    # Make the dataframe editor-safe (especially exam_date -> datetime.date)
    subjects_editor_df = sanitize_subjects_for_editor(subjects_df, settings)
    subjects_editor_df = _ensure_columns(subjects_editor_df)

    # Final guarantee for the editor: exam_date must be a date dtype (not string)
    subjects_editor_df["exam_date"] = pd.to_datetime(subjects_editor_df["exam_date"], errors="coerce").dt.date

    # ----- Summary strip -----
    active_count = int((~subjects_editor_df["completed"]).sum())
    done_count = int(subjects_editor_df["completed"].sum())
    st.markdown(
        f"**Active:** {active_count}  |  **Completed:** {done_count}  "
        + ("🏆" if done_count > 0 else "")
    )

    # ----- Editor -----
    edited = st.data_editor(
        subjects_editor_df,
        column_config={
            "id": st.column_config.TextColumn(disabled=True),
            "name": st.column_config.TextColumn(label="Subject"),
            "credits": st.column_config.NumberColumn(min_value=1, step=1),
            "confidence": st.column_config.NumberColumn(min_value=0, max_value=10, step=1),
            "exam_date": st.column_config.DateColumn(label="Exam date", format="YYYY-MM-DD"),
            # NEW: completion controls
            "completed": st.column_config.CheckboxColumn(help="When checked, this subject won't be prompted for practice again."),
            "completed_at": st.column_config.TextColumn(disabled=True, help="Auto-set when completed."),
            "progress_snapshot": st.column_config.NumberColumn(disabled=True, help="Hours snapshot when completed."),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="subjects_editor",
    )

    c1, c2, c3 = st.columns([1, 1, 1])

    # --- Add subject ---
    with c1:
        if st.button("➕ Add subject"):
            s = settings or {}
            new = {
                "id": str(uuid.uuid4()),
                "name": "New subject",
                "credits": 2,
                "confidence": 5,
                # Keep as date for the editor
                "exam_date": pd.to_datetime(
                    s.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]), errors="coerce"
                ).date(),
                "user_id": st.session_state.user["id"] if st.session_state.user else "",
                "completed": False,
                "completed_at": "",
                "progress_snapshot": 0.0,
            }
            edited = pd.concat([edited, pd.DataFrame([new])], ignore_index=True)
            _save_subjects(edited, subjects_df_all)
            st.rerun()

    # --- Mark/Undo selected row via buttons (optional QoL) ---
    with c2:
        with st.popover("⚙️ Quick actions"):
            st.caption("Type a subject ID to mark complete or undo.")
            target_id = st.text_input("Subject ID")
            cA, cB = st.columns(2)
            if cA.button("✅ Mark complete", disabled=(not target_id)):
                if target_id in edited["id"].values:
                    edited.loc[edited["id"] == target_id, "completed"] = True
                    _save_subjects(edited, subjects_df_all)
                    st.success("Marked complete.")
                    st.rerun()
            if cB.button("↩️ Undo", disabled=(not target_id)):
                if target_id in edited["id"].values:
                    edited.loc[edited["id"] == target_id, "completed"] = False
                    edited.loc[edited["id"] == target_id, "completed_at"] = ""
                    _save_subjects(edited, subjects_df_all)
                    st.info("Reopened.")
                    st.rerun()

    # --- Save changes (also stamps completion info & progress snapshot) ---
    with c3:
        if st.button("💾 Save changes"):
            # Normalize exam_date strings now so compute_metrics sees consistent dates after reload
            if "exam_date" in edited.columns:
                edited["exam_date"] = pd.to_datetime(edited["exam_date"], errors="coerce").dt.strftime("%Y-%m-%d")

            # Detect completion flips: False -> True
            after = edited.set_index("id", drop=False)
            flipped_ids = []
            for sid in after.index:
                was = bool(before.loc[sid, "completed"]) if sid in before.index else False
                now = bool(after.loc[sid, "completed"])
                if (not was) and now:
                    flipped_ids.append(sid)

            # Compute metrics on the *edited* frame to snapshot progress
            metrics_df = compute_metrics(edited, logs_df, tests_df).set_index("name", drop=False)

            today = datetime.now().strftime("%Y-%m-%d")
            for sid in flipped_ids:
                # Stamp completed_at
                edited.loc[edited["id"] == sid, "completed_at"] = today
                # Snapshot "progress" — take HOURS from metrics as proxy
                subj_name = after.loc[sid, "name"]
                hours_val = 0.0
                if subj_name in metrics_df.index:
                    try:
                        hours_val = float(metrics_df.loc[subj_name, "hours"])
                    except Exception:
                        hours_val = 0.0
                edited.loc[edited["id"] == sid, "progress_snapshot"] = round(hours_val, 2)

            _save_subjects(edited, subjects_df_all)
            st.success("Saved.")
            st.rerun()

    st.divider()

    # --- Computed metrics ---
    st.subheader("Computed metrics")
    metrics = compute_metrics(edited, logs_df, tests_df)

    # Tag completed status for readability in the table
    metrics = metrics.merge(
        edited[["id", "name", "completed"]],
        on=["name"],
        how="left",
        suffixes=("", "_x")
    )

    # Show Active first, then Completed (collapsed)
    active_tbl = metrics[metrics["completed"] != True]  # keep NaN/False as active
    done_tbl = metrics[metrics["completed"] == True]

    st.markdown("**Active subjects**")
    st.dataframe(
        active_tbl[
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
        ].sort_values(["priority"], ascending=False),
        use_container_width=True,
    )

    with st.expander(f"Completed subjects ({len(done_tbl)})", expanded=False):
        # Merge completion stamps; robust against missing cols in legacy data
        extra = edited[["name"]].copy()
        if "completed_at" in edited.columns:
            extra = extra.merge(edited[["name", "completed_at"]], on="name", how="left")
        else:
            extra["completed_at"] = ""
        if "progress_snapshot" in edited.columns:
            extra = extra.merge(edited[["name", "progress_snapshot"]], on="name", how="left")
        else:
            extra["progress_snapshot"] = 0.0

        view = done_tbl.merge(extra, on="name", how="left")

        # Ensure columns exist before selecting/sorting to avoid KeyError
        for c, default in [("completed_at", ""), ("progress_snapshot", 0.0)]:
            if c not in view.columns:
                view[c] = default

        cols = [
            "name",
            "credits",
            "confidence",
            "exam_date",
            "priority",
            "hours",
            "avg_score",
            "days_left",
            "priority_gap",
            "completed_at",
            "progress_snapshot",
        ]

        st.dataframe(
            view[cols].sort_values(["completed_at", "name"], ascending=[False, True]),
            use_container_width=True,
        )
