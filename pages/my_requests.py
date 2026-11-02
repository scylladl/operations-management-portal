import streamlit as st

from portal import actions, ui

account = ui.account()
st.title("My requests")
if st.button("New request", icon=":material/add:", type="primary"):
    ui.edit_request()
rows = actions.list_actions(ui.connection(), account["UserId"], "mine")
returned = [r for r in rows if r["Status"] == "Returned"]
if returned:
    st.warning(f"{len(returned)} request(s) returned to you for changes.", icon=":material/undo:")
ui.action_table(rows, "mine")
