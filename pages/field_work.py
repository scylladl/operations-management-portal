import streamlit as st

from portal import actions, ui

account = ui.account()
st.title("Field work")
st.caption("Approved actions to start and actions in progress in your region, including historical actions "
           "still open (you can record their completion).")
rows = actions.list_actions(ui.connection(), account["UserId"], "work")
to_start = [r for r in rows if r["Status"] == "Approved"]
in_progress = [r for r in rows if r["Status"] == "InProgress"]
st.subheader(f"To start ({len(to_start)})")
ui.action_table(to_start, "to_start", region=False)
st.subheader(f"In progress ({len(in_progress)})")
ui.action_table(in_progress, "in_progress", region=False)
