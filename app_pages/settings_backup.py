# pages/settings_backup.py
from __future__ import annotations

import io
from datetime import datetime
from zipfile import ZipFile

import pandas as pd
import streamlit as st

from core.config import (
    DATA_DIR,
    DEFAULT_SETTINGS,
    SUBJECTS_CSV,
    LOGS_CSV,
    TESTS_CSV,
)
from core.storage import (
    load_df,
    load_settings,
    save_settings,
    save_df,
    zip_backup,
)
from core.auth import (
    load_users,
    get_user_by_name,
    rename_user,
    set_user_password,
    delete_user,
    claim_legacy_rows_for_user,
)
from core.normalize import (
    normalize_subjects_df,
    normalize_logs_df,
    normalize_tests_df,
    _merge_replace_current_user,
    _append_current_user,
)


def render(settings, subjects_df_all, logs_df_all, tests_df_all):
    st.title("Settings & Backup")
    st.caption("Global options, weights, users, and import/export.")
    st.info(f"Data folder: {DATA_DIR}")

    tabs = st.tabs(["App settings", "Manage users", "Backup/Export/Import"])

    # ----------------
    # App settings tab
    # ----------------
    with tabs[0]:
        with st.form("settings"):
            colA, colB = st.columns([1, 1])
            with colA:
                semester = st.text_input(
                    "Semester label",
                    value=settings.get("semester", DEFAULT_SETTINGS["semester"]),
                )
                focus_n = st.number_input(
                    "Top N focus subjects on dashboard",
                    min_value=1, max_value=10,
                    value=int(settings.get("focus_n", 3)),
                )
                momentum_days = st.number_input(
                    "Momentum window (days)",
                    min_value=3, max_value=30,
                    value=int(settings.get("momentum_days", 7)),
                )
            with colB:
                default_exam = st.date_input(
                    "Default exam date (for new subjects & fallback)",
                    value=pd.to_datetime(
                        settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"]),
                        errors="coerce",
                    ).date(),
                )
                logs_weight = st.slider(
                    "Logs weight (avg score)",
                    min_value=0.0, max_value=1.0, step=0.05,
                    value=float(settings.get("logs_weight", 0.70)),
                )
                tests_weight = round(1.0 - logs_weight, 2)
                st.write(f"Tests weight auto-set to **{int(tests_weight*100)}%**")
                show_upcoming = st.checkbox(
                    "Show Upcoming exams",
                    value=bool(settings.get("show_upcoming_exams", True)),
                )
                show_recent = st.checkbox(
                    "Show Recent activity",
                    value=bool(settings.get("show_recent_activity", True)),
                )

            apply_to_empty = st.checkbox(
                "Apply default exam date to subjects with empty exam_date",
                value=False,
            )
            submitted = st.form_submit_button("💾 Save settings")

            if submitted:
                settings.update({
                    "semester": semester,
                    "default_exam_date": default_exam.strftime("%Y-%m-%d"),
                    "focus_n": int(focus_n),
                    "momentum_days": int(momentum_days),
                    "logs_weight": float(logs_weight),
                    "tests_weight": float(tests_weight),
                    "show_upcoming_exams": bool(show_upcoming),
                    "show_recent_activity": bool(show_recent),
                })
                save_settings(settings)

                if apply_to_empty:
                    s = load_df(SUBJECTS_CSV)
                    s["exam_date"] = pd.to_datetime(s.get("exam_date"), errors="coerce")
                    mask = s["exam_date"].isna()
                    s.loc[mask, "exam_date"] = pd.to_datetime(settings["default_exam_date"])
                    s["exam_date"] = pd.to_datetime(s["exam_date"]).dt.strftime("%Y-%m-%d")
                    save_df(s, SUBJECTS_CSV)

                st.success("Settings saved.")
                st.rerun()

    # ---------------
    # Manage users tab
    # ---------------
    with tabs[1]:
        st.subheader("Users")
        users = load_users().copy()
        if len(users) == 0:
            st.info("No users yet. Create one from the sidebar → Sign up.")
        else:
            st.dataframe(users[["id", "username", "created_at"]], hide_index=True, use_container_width=True)

        st.markdown("### Edit user")
        if len(users):
            user_labels = [f"{r['username']} ({r['id'][:8]})" for _, r in users.iterrows()]
            choice = st.selectbox("Select user", options=["— select —"] + user_labels, index=0)
            if choice != "— select —":
                idx = user_labels.index(choice)
                row = users.iloc[idx]
                target_id = str(row["id"])

                new_name = st.text_input("Rename (optional)", value=row["username"])
                new_pw   = st.text_input("Set/Reset password (optional)", type="password", help="Leave blank to keep existing/none.")
                colx, coly, colz = st.columns(3)

                with colx:
                    if st.button("Save user changes"):
                        ok = True
                        if new_name.strip() and new_name.strip().lower() != str(row["username"]).lower():
                            ok = rename_user(target_id, new_name.strip())
                            if not ok:
                                st.error("Username already exists.")
                        if ok and new_pw.strip():
                            set_user_password(target_id, new_pw.strip())
                        if ok:
                            st.success("User updated.")
                            st.rerun()

                with coly:
                    other_users = users[users["id"] != target_id]
                    reassign_to = None
                    if len(other_users):
                        lab = [f"{r['username']} ({r['id'][:8]})" for _, r in other_users.iterrows()]
                        sel = st.selectbox("Reassign data to (optional)", ["— none —"] + lab)
                        if sel != "— none —":
                            reassign_to = str(other_users.iloc[lab.index(sel)]["id"])
                    if st.button("Delete user"):
                        if st.session_state.user and st.session_state.user["id"] == target_id:
                            st.error("Can't delete the currently signed-in user.")
                        else:
                            delete_user(target_id, reassign_to)
                            st.success("User deleted.")
                            st.rerun()

                with colz:
                    if st.button("Claim legacy rows for this user"):
                        claim_legacy_rows_for_user(target_id)
                        st.success("Unowned rows assigned.")
                        st.rerun()

    # -------------------------
    # Backup / Export / Import
    # -------------------------
    with tabs[2]:
        st.subheader("Backups")
        colb1, colb2 = st.columns(2)

        with colb1:
            if st.button("Create backup ZIP"):
                z = zip_backup()
                st.success(f"Backup created: {z.name}")
                with open(z, "rb") as f:
                    st.download_button("Download latest backup", data=f.read(), file_name=z.name, key="dl_backup_zip")

        with colb2:
            uploaded_zip = st.file_uploader("Restore from backup (ZIP)", type=["zip"])
            if uploaded_zip is not None:
                with ZipFile(io.BytesIO(uploaded_zip.read())) as zf:
                    zf.extractall(DATA_DIR)
                load_df.clear()
                st.success("Backup restored.")
                st.rerun()

        st.divider()
        st.subheader("Export CSVs")

        export_scope = st.radio(
            "What to export?",
            ["Current user only", "All data (admin)"],
            horizontal=True,
            key="export_scope",
        )

        if export_scope == "Current user only" and st.session_state.user:
            uid = st.session_state.user["id"]
            subj_exp = subjects_df_all[subjects_df_all.get("user_id", "") == uid]
            logs_exp = logs_df_all[logs_df_all.get("user_id", "") == uid]
            tests_exp = tests_df_all[tests_df_all.get("user_id", "") == uid]
        else:
            subj_exp = subjects_df_all
            logs_exp = logs_df_all
            tests_exp = tests_df_all

        c1, c2, c3 = st.columns(3)
        with c1:
            st.download_button("Download subjects.csv", data=subj_exp.to_csv(index=False), file_name="subjects.csv", key="exp_sub")
        with c2:
            st.download_button("Download logs.csv", data=logs_exp.to_csv(index=False), file_name="logs.csv", key="exp_logs")
        with c3:
            st.download_button("Download tests.csv", data=tests_exp.to_csv(index=False), file_name="tests.csv", key="exp_tests")

        # -------- Import CSVs (stable, inside a form) --------
        st.divider()
        st.subheader("Import CSVs")
        st.caption("Choose how imported rows should be applied. Dates and IDs will be normalized automatically.")

        import_mode = st.selectbox(
            "Import mode",
            [
                "Append to current user (recommended)",
                "Replace current user's data",
                "Replace entire file (admin)",
            ],
            index=0,
            help="Append = keep existing rows and add/overwrite by id. Replace current user = only your rows are replaced. Replace entire file = admin-level overwrite.",
            key="import_mode_sel",
        )

        with st.form("import_form", clear_on_submit=False):
            ci1, ci2, ci3 = st.columns(3)
            with ci1:
                f1 = st.file_uploader("subjects.csv", type=["csv"], key="imp_sub")
            with ci2:
                f2 = st.file_uploader("logs.csv", type=["csv"], key="imp_logs")
            with ci3:
                f3 = st.file_uploader("tests.csv", type=["csv"], key="imp_tests")

            submitted = st.form_submit_button("Run import")

        if submitted:
            # guard: signed in unless admin mode
            if import_mode != "Replace entire file (admin)" and not st.session_state.user:
                st.warning("Sign in to import for a specific user.")
            else:
                uid = st.session_state.user["id"] if st.session_state.user else None
                default_exam = settings.get("default_exam_date", DEFAULT_SETTINGS["default_exam_date"])

                def _read_csv_uploaded(uploaded):
                    if uploaded is None:
                        return None
                    uploaded.seek(0)
                    data = uploaded.read()
                    bio = io.BytesIO(data)
                    try:
                        return pd.read_csv(bio, sep=None, engine="python", encoding="utf-8-sig")
                    except Exception:
                        bio.seek(0)
                        return pd.read_csv(bio, encoding_errors="ignore")

                any_ok = False
                with st.spinner("Importing..."):
                    # subjects
                    if f1 is not None:
                        try:
                            incoming = _read_csv_uploaded(f1)
                            if incoming is None or incoming.empty:
                                st.error("subjects.csv is empty or unreadable.")
                            else:
                                incoming = normalize_subjects_df(
                                    incoming,
                                    default_exam,
                                    uid if import_mode != "Replace entire file (admin)" else None,
                                )
                                if import_mode == "Replace entire file (admin)":
                                    save_df(incoming, SUBJECTS_CSV)
                                elif import_mode == "Replace current user's data":
                                    merged = _merge_replace_current_user(load_df(SUBJECTS_CSV), incoming, uid)
                                    save_df(merged, SUBJECTS_CSV)
                                else:
                                    merged = _append_current_user(load_df(SUBJECTS_CSV), incoming, uid)
                                    save_df(merged, SUBJECTS_CSV)
                                st.success(f"subjects.csv imported ({len(incoming)} rows).")
                                any_ok = True
                        except Exception as e:
                            st.error(f"subjects.csv import failed: {e}")

                    # logs
                    if f2 is not None:
                        try:
                            incoming = _read_csv_uploaded(f2)
                            if incoming is None or incoming.empty:
                                st.error("logs.csv is empty or unreadable.")
                            else:
                                incoming = normalize_logs_df(
                                    incoming,
                                    uid if import_mode != "Replace entire file (admin)" else None,
                                )
                                if import_mode == "Replace entire file (admin)":
                                    save_df(incoming, LOGS_CSV)
                                elif import_mode == "Replace current user's data":
                                    merged = _merge_replace_current_user(load_df(LOGS_CSV), incoming, uid)
                                    save_df(merged, LOGS_CSV)
                                else:
                                    merged = _append_current_user(load_df(LOGS_CSV), incoming, uid)
                                    save_df(merged, LOGS_CSV)
                                st.success(f"logs.csv imported ({len(incoming)} rows).")
                                any_ok = True
                        except Exception as e:
                            st.error(f"logs.csv import failed: {e}")

                    # tests
                    if f3 is not None:
                        try:
                            incoming = _read_csv_uploaded(f3)
                            if incoming is None or incoming.empty:
                                st.error("tests.csv is empty or unreadable.")
                            else:
                                incoming = normalize_tests_df(
                                    incoming,
                                    uid if import_mode != "Replace entire file (admin)" else None,
                                )
                                if import_mode == "Replace entire file (admin)":
                                    save_df(incoming, TESTS_CSV)
                                elif import_mode == "Replace current user's data":
                                    merged = _merge_replace_current_user(load_df(TESTS_CSV), incoming, uid)
                                    save_df(merged, TESTS_CSV)
                                else:
                                    merged = _append_current_user(load_df(TESTS_CSV), incoming, uid)
                                    save_df(merged, TESTS_CSV)
                                st.success(f"tests.csv imported ({len(incoming)} rows).")
                                any_ok = True
                        except Exception as e:
                            st.error(f"tests.csv import failed: {e}")

                # refresh caches without forcing a rerun (prevents flicker)
                load_df.clear()
                st.session_state["import_status"] = "✅ Import complete." if any_ok else "⚠️ No files imported."

        # show sticky status without rerunning
        if st.session_state.get("import_status"):
            st.info(st.session_state["import_status"])
