import streamlit as st

from portal import actions, ui

account = ui.account()
st.title("To verify")
st.caption("Work recorded as completed by the field teams. Verify it, or reopen it with a reason.")
ui.action_table(actions.list_actions(ui.connection(), account["UserId"], "verify"), "verify",
                region=account["RoleCode"] == "ADM")
