import streamlit as st

from portal import actions, ui

account = ui.account()
st.title("Decision queue")
st.caption("Submitted requests waiting for a decision, oldest first. Your own requests go to another approver "
           "of the region. Requests waiting more than 5 working days are highlighted.")
rows = actions.list_actions(ui.connection(), account["UserId"], "decide")
late = sum(r["WaitingWorkingDays"] > 5 for r in rows)
left, right, _ = st.columns([1, 1, 3])
left.metric("Waiting", len(rows), border=True)
right.metric("Over 5 working days", late, border=True)
ui.action_table(rows, "decide", waiting=True, region=account["RoleCode"] == "ADM")
