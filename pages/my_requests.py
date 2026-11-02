import streamlit as st

from portal import actions, components, ui

account = ui.account()
rows = actions.list_actions(ui.connection(), account["UserId"], "mine")
attention = [r for r in rows if r["Status"] in ("Draft", "Returned")]
underway = [r for r in rows if r["Status"] in ("Submitted", "Approved", "InProgress", "Completed")]
closed = [r for r in rows if r["Status"] in ("Verified", "Rejected", "Cancelled")]

title, button = st.columns([5, 1], vertical_alignment="bottom")
with title:
    ui.header("Request", "My requests", "Drafts and returned requests need you; the rest shows where your requests are.")
if button.button("New request", icon=":material/add:", type="primary", width="stretch"):
    ui.edit_request()
st.html(components.section(f"Needs you · {len(attention)}"))
ui.action_cards(attention, "attention", empty="Nothing needs you right now.")
st.html(components.section(f"Under way · {len(underway)}"))
ui.action_cards(underway, "underway", empty="No request under way.")
with st.expander(f"Closed · {len(closed)}"):
    ui.action_table(closed, "closed", region=False)
