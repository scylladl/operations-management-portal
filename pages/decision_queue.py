import streamlit as st

from portal import actions, ui

account = ui.account()
rows = actions.list_actions(ui.connection(), account["UserId"], "decide")
late = sum(r["WaitingWorkingDays"] > 5 for r in rows)
ui.header("Decide", "Decision queue",
          "Submitted requests waiting for your decision, oldest first. Your own requests go to another approver of "
          "the region. The target is a decision within 5 working days.")
tiles = st.columns(4)
tiles[0].metric("Waiting", len(rows), border=True)
tiles[1].metric("Over 5 working days", late, border=True)
ui.action_cards(rows, "decide", waiting=True, empty="No request is waiting for a decision.")
