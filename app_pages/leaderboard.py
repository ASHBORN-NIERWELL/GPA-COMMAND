# pages/leaderboard.py
from __future__ import annotations
from pathlib import Path
import streamlit as st
import pandas as pd

from core.auth import load_users, get_user_avatar_path
from core.gamify import compute_leaderboard, recent_highlights

def render(logs_df_all, tests_df_all):
    st.title("🏆 Leaderboard & Highlights")

    users = load_users()

    lb = compute_leaderboard(logs_df_all, tests_df_all, users)
    if len(lb) == 0:
        st.info("No data yet. Add logs and tests to see the leaderboard.")
        return

    st.subheader("Leaderboard")
    # Show avatar + name + score in a compact table
    for _, row in lb.iterrows():
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([0.6, 2, 1.5, 1.5, 2])
            # Avatar
            avatar = get_user_avatar_path(row["user_id"])
            if avatar and Path(avatar).exists():
                c1.image(avatar, width=48)
            else:
                c1.markdown("🧑‍🎓")
            c2.markdown(f"**#{int(row['rank'])} {row['username']}**")
            c3.metric("Score", f"{int(row['score']):,}")
            c4.metric("Hours", f"{row['hours']:.1f}")
            c5.markdown(f"**Tests avg:** {row['tests_avg']:.0f}%  \n"
                        f"**Streak:** {int(row['streak_cur'])}🔥 / {int(row['streak_best'])}🏅")

    st.divider()
    st.subheader("Recent highlights (last 7 days)")
    hi = recent_highlights(logs_df_all, tests_df_all, days=7)
    if len(hi) == 0:
        st.caption("No highlights yet.")
    else:
        user_map = dict(zip(users["id"].astype(str), users["username"]))
        hi["user"] = hi["user_id"].map(user_map).fillna("Unknown")
        hi = hi[["when","user","type","detail"]].sort_values("when", ascending=False)
        st.dataframe(hi, hide_index=True, use_container_width=True)
