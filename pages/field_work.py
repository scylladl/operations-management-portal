import streamlit as st

from portal import actions, components, ui

account = ui.account()
rows = actions.list_actions(ui.connection(), account["UserId"], "work")
to_start = [r for r in rows if r["Status"] == "Approved"]
in_progress = [r for r in rows if r["Status"] == "InProgress"]
ui.header("Field work", f"Work in {account['RegionName']}",
          "Approved actions to start and actions in progress, including historical actions still open: you can "
          "record their completion.")
tiles = st.columns(4)
tiles[0].metric("To start", len(to_start), border=True)
tiles[1].metric("In progress", len(in_progress), border=True)
st.html(components.section(f"To start · {len(to_start)}"))
ui.action_cards(to_start, "to_start", empty="Nothing approved is waiting to start.")
st.html(components.section(f"In progress · {len(in_progress)}"))
ui.action_cards(in_progress, "in_progress", empty="No work in progress.")
