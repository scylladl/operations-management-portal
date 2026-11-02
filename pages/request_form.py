import pandas as pd
import streamlit as st

from portal import actions, db, ui

account = ui.account()
conn = ui.connection()
me = account["UserId"]
types, regions = ui.reference()

editing = None
action_id = st.session_state.get("edit_action_id")
if action_id:
    try:
        editing = actions.get_action(conn, me, action_id)
    except db.NotFound:
        editing = None
    if editing and (editing["action"]["RequesterId"] != me or editing["action"]["Status"] not in ("Draft", "Returned")):
        editing = None
if not editing:
    st.session_state["edit_action_id"] = None
current = editing["action"] if editing else {}

st.title(f"Edit request {current['ActionId']}" if editing else "New request")
if current.get("Status") == "Returned":
    reason = next((e for e in reversed(editing["events"]) if e["EventType"] == "RETURN" and e["Reason"]), None)
    if reason:
        st.warning(f"Returned by {reason['ActorName']}: {reason['Reason']}", icon=":material/undo:")

inventory = ui.circuits(None if account["RoleCode"] == "ADM" else account["RegionCode"])
labels = {c["CircuitId"]: f"{c['CircuitId']} · {c['CustomerName']} · {c['Province']} · {c['RecentIncidents']} recent incident(s)"
          for c in inventory}
options = list(labels)
if current and current["CircuitId"] not in labels:
    options.insert(0, current["CircuitId"])
circuit_id = st.selectbox("Circuit", options, format_func=lambda c: labels.get(c, c), placeholder="Search a circuit",
                          index=options.index(current["CircuitId"]) if current else None,
                          help="Circuits of your region in the inventory, most recent incidents first. Circuits "
                               "without a region or decommissioned cannot be requested.")
if not circuit_id:
    st.stop()

evidence = actions.circuit_evidence(conn, me, circuit_id)
circuit, incidents = evidence["circuit"], evidence["incidents"]
window = f"{ui.day(circuit['WindowStart'])} to {ui.day(circuit['WindowEnd'])}"

left, right = st.columns([3, 2], gap="large")
with left:
    st.markdown(f"**{circuit['CustomerName']}** ({circuit['Segment']}) · {circuit['TechnologyCode']} · "
                f"{circuit['Province']}, {circuit['RegionName'] or 'no region'} · installed {ui.day(circuit['InstallDate'])}")
    st.subheader(f"Incidents from {window}")
    st.caption("The 90 days up to the latest NorthGrid extraction. Cancelled and duplicate tickets are left out.")
    if incidents:
        st.dataframe(pd.DataFrame(incidents), hide_index=True, width="stretch", column_config={
            "TicketId": "Ticket", "OpenedAt": st.column_config.DatetimeColumn("Opened", format="D MMM YYYY, HH:mm"),
            "PriorityCode": "Priority", "RootCauseCode": "Root cause", "ResponsibleTeam": "Team", "Status": "Status"})
    else:
        st.info("No incidents in the window: a request needs at least one.")
    st.subheader("Actions on this circuit")
    if evidence["history"]:
        st.dataframe(pd.DataFrame(evidence["history"]), hide_index=True, width="stretch", column_config={
            "ActionId": st.column_config.NumberColumn("Action", format="%d"), "ActionTypeName": "Type",
            "StatusName": "Status", "StartDate": st.column_config.DateColumn("Started", format="D MMM YYYY"),
            "CompletionDate": st.column_config.DateColumn("Completed", format="D MMM YYYY"),
            "IsHistorical": st.column_config.CheckboxColumn("Before the portal")})
    else:
        st.caption("None.")

with right:
    linked = [i["TicketId"] for i in editing["incidents"]] if editing else []
    by_ticket = {i["TicketId"]: i for i in incidents}
    with st.form("request"):
        type_codes = list(types)
        action_type = st.selectbox("Action type", type_codes, format_func=types.get,
                                   index=type_codes.index(current["ActionTypeCode"]) if current else None)
        tickets = st.multiselect(
            "Incidents this action addresses", list(by_ticket), default=[t for t in linked if t in by_ticket],
            format_func=lambda t: f"{t} · {ui.day(by_ticket[t]['OpenedAt'])} · {by_ticket[t]['PriorityCode']}")
        justification = st.text_area("Justification", value=current.get("Justification") or "", height=160,
                                     help="Why this circuit and this action, based on the incidents.")
        outcome = st.text_area("Expected outcome", value=current.get("ExpectedOutcome") or "", height=90)
        save, submit = st.columns(2)
        saved = save.form_submit_button("Save draft", width="stretch")
        submitted = submit.form_submit_button("Save and submit", type="primary", width="stretch")

    if saved or submitted:
        def save_and_maybe_submit():
            new_id, row_ver = actions.save_request(conn, me, circuit_id, action_type, justification, outcome, tickets,
                                                   action_id=current.get("ActionId"), row_ver=current.get("RowVer"))
            st.session_state["edit_action_id"] = new_id
            if submitted:
                actions.transition(conn, me, new_id, row_ver,
                                   "RESUBMIT" if current.get("Status") == "Returned" else "SUBMIT")
                st.session_state["edit_action_id"] = None
                st.session_state["action_id"] = new_id
        if not action_type:
            st.error("Choose the action type.")
        else:
            ui.run(save_and_maybe_submit, "Request submitted" if submitted else "Draft saved",
                   then=(lambda: st.switch_page(ui.DETAIL_PAGE)) if submitted else None)

    if current.get("Status") == "Draft":
        if st.button("Discard draft", icon=":material/delete:"):
            ui.run(lambda: actions.discard_draft(conn, me, current["ActionId"], current["RowVer"]), "Draft discarded")
