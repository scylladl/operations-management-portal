import json
from itertools import groupby

import pandas as pd
import streamlit as st

from portal import actions, db, ui, users

account = ui.account()
conn = ui.connection()
me = account["UserId"]
types, _ = ui.reference()

wanted = st.number_input("Open action number", min_value=1, step=1, value=st.session_state.get("action_id"),
                         placeholder="Type an action number", width=220)
if not wanted:
    st.stop()
try:
    detail = actions.get_action(conn, me, int(wanted))
except db.NotFound as error:
    st.error(str(error))
    st.stop()
st.session_state["action_id"] = int(wanted)
action = detail["action"]
action_id = action["ActionId"]

st.title(f"{action['ActionTypeName']} on {action['CircuitId']}")
st.caption(ui.status_badge(action["Status"], action["StatusName"]) + " &nbsp; " + " · ".join(filter(None, [
    f"Action {action_id}", action["CustomerName"], action["Province"], action["RegionName"] or "no region",
    f"requested by {action['RequesterName']}" if action["RequesterName"] else "requester not recorded",
    f"version {action['VersionNo']}" if action["VersionNo"] else None])))
if action["IsHistorical"]:
    st.info("Recorded before the portal (NorthGrid history): read only. A field coordinator of the region can "
            "record the completion of one still in progress.", icon=":material/history:")

# The reason behind the current status (returned, rejected, cancelled, reopened), while it still applies
status_changes = [e for e in detail["events"] if e["FieldName"] == "Status"]
last = status_changes[-1] if status_changes else None
if last and last["Reason"] and last["EventType"] != "IMPORT":
    st.warning(f"**{ui.EVENT_LABELS[last['EventType']]}** by {last['ActorName']}, {ui.moment(last['EventAt'])}: "
               f"{last['Reason']}", icon=":material/comment:")

content, side = st.columns([3, 2], gap="large")

with side:
    with st.container(border=True):
        st.markdown("**What you can do**")
        if not detail["transitions"]:
            st.caption("Nothing for you at this step.")
        for t in detail["transitions"]:
            code = t["TransitionCode"]
            if t["RequiresReason"] or code in ("START", "COMPLETE"):
                with st.popover(t["ActionLabel"], width="stretch"):
                    with st.form(f"form_{code}"):
                        reason = st.text_area("Reason (the requester sees it)") if t["RequiresReason"] else None
                        event_date = (st.date_input("Start date" if code == "START" else "Completion date",
                                                    format="DD/MM/YYYY")
                                      if code in ("START", "COMPLETE") else None)
                        if st.form_submit_button(f"Confirm: {t['ActionLabel'].lower()}", type="primary"):
                            ui.run(lambda: actions.transition(conn, me, action_id, action["RowVer"], code,
                                                              reason=reason, event_date=event_date),
                                   ui.EVENT_LABELS[code])
            else:
                if st.button(t["ActionLabel"], key=f"do_{code}", type="primary", width="stretch"):
                    ui.run(lambda: actions.transition(conn, me, action_id, action["RowVer"], code),
                           ui.EVENT_LABELS[code])
        if action["RequesterId"] == me and action["Status"] in ("Draft", "Returned"):
            if st.button("Edit request", icon=":material/edit:", width="stretch"):
                ui.edit_request(action_id)
        if account["RoleCode"] == "FLD" and action["Status"] == "InProgress":
            with st.popover("Add a work note", width="stretch"):
                with st.form("note", clear_on_submit=True):
                    note = st.text_area("Note")
                    if st.form_submit_button("Add note", type="primary"):
                        ui.run(lambda: actions.add_work_note(conn, me, action_id, note), "Note added")
        if account["RoleCode"] == "ADM" and not action["IsHistorical"] and action["Status"] not in (
                "Rejected", "Verified", "Cancelled"):
            with st.popover("Change owner", width="stretch"):
                candidates = [u for u in users.list_accounts(conn, me)
                              if u["IsActive"] and (u["RoleCode"] == "ADM" or (
                                  u["RoleCode"] in ("REQ", "APR") and u["RegionCode"] == action["RegionCode"]))
                              and u["UserId"] != action["RequesterId"]]
                with st.form("owner"):
                    new_owner = st.selectbox("New owner", candidates, format_func=lambda u: u["DisplayName"])
                    reason = st.text_area("Reason")
                    if st.form_submit_button("Change owner", type="primary"):
                        ui.run(lambda: actions.change_owner(conn, me, action_id, action["RowVer"],
                                                            new_owner["UserId"], reason), "Owner changed")

    with st.container(border=True):
        st.markdown("**Dates**")
        st.markdown(f"Last submitted: {ui.moment(action['LastSubmittedAt']) or '–'}  \n"
                    f"Work started: {ui.day(action['StartDate']) or '–'}  \n"
                    f"Completed: {ui.day(action['CompletionDate']) or '–'}")

with content:
    if len(detail["versions"]) >= 2:
        # R5: the approver sees what changed since the previous submitted version
        new, old = detail["versions"][0], detail["versions"][1]
        with st.expander(f"What changed from version {old['VersionNo']} to {new['VersionNo']}",
                         expanded=action["Status"] == "Submitted", icon=":material/difference:"):
            changed = False
            for field, label in (("CircuitId", "Circuit"), ("ActionTypeCode", "Action type"),
                                 ("Justification", "Justification"), ("ExpectedOutcome", "Expected outcome")):
                if new[field] != old[field]:
                    changed = True
                    show = types.get if field == "ActionTypeCode" else str
                    st.markdown(f"**{label}**")
                    before, after = st.columns(2)
                    before.caption(f"Version {old['VersionNo']}")
                    before.write(show(old[field]))
                    after.caption(f"Version {new['VersionNo']}")
                    after.write(show(new[field]))
            added = sorted(set(json.loads(new["TicketIds"])) - set(json.loads(old["TicketIds"])))
            removed = sorted(set(json.loads(old["TicketIds"])) - set(json.loads(new["TicketIds"])))
            if added or removed:
                changed = True
                st.markdown("**Incidents**  \n" + "  \n".join([f"added {t}" for t in added] + [f"removed {t}" for t in removed]))
            if not changed:
                st.caption("Resubmitted without changes.")
    if not action["IsHistorical"]:
        st.subheader("Justification")
        st.write(action["Justification"] or "_Not written yet._")
        st.subheader("Expected outcome")
        st.write(action["ExpectedOutcome"] or "_Not written yet._")
        st.subheader("Incidents it addresses")
        if detail["incidents"]:
            st.dataframe(pd.DataFrame(detail["incidents"]), hide_index=True, width="stretch", column_config={
                "TicketId": "Ticket", "OpenedAt": st.column_config.DatetimeColumn("Opened", format="D MMM YYYY, HH:mm"),
                "PriorityCode": "Priority", "RootCauseCode": "Root cause", "ResponsibleTeam": "Team", "Status": "Status"})
        else:
            st.caption("None linked yet.")

    versions, history, notes = st.tabs([f"Versions ({len(detail['versions'])})", "History",
                                        f"Work notes ({len(detail['notes'])})"])
    with versions:
        for v in detail["versions"]:
            st.markdown(f"**Version {v['VersionNo']}**, submitted by {v['SubmittedBy']} on {ui.moment(v['SubmittedAt'])}  \n"
                        f"Incidents: {', '.join(json.loads(v['TicketIds']))}")
        if not detail["versions"]:
            st.caption("Not submitted yet.")
    with history:
        if not detail["events"]:
            st.caption("No changes recorded.")
        for (at, actor, event_type), group in groupby(detail["events"],
                                                      key=lambda e: (e["EventAt"], e["ActorName"], e["EventType"])):
            changes = list(group)
            lines = []
            for change in changes:
                field, old, new = change["FieldName"], change["OldValue"], change["NewValue"]
                if field == "RequesterId" and old is None:
                    continue   # set on creation; the requester is named in the header
                if field in ("Justification", "ExpectedOutcome"):
                    lines.append(f"{ui.FIELD_LABELS[field]} {'written' if old is None else 'edited'}")
                elif field == "Incident":
                    lines.append(f"{'linked' if new else 'unlinked'} incident {new or old}")
                elif field == "RequesterId":
                    lines.append("requester changed")
                else:
                    if field == "ActionTypeCode":
                        old, new = types.get(old, old), types.get(new, new)
                    lines.append(f"{ui.FIELD_LABELS[field]}: {new}" if old is None
                                 else f"{ui.FIELD_LABELS[field]}: {old} → {new or '–'}")
            reason = next((c["Reason"] for c in changes if c["Reason"]), None)
            st.markdown(f"**{ui.EVENT_LABELS.get(event_type, event_type)}** · {actor} · {ui.moment(at)}  \n"
                        + "; ".join(lines)
                        + (f"  \n*Reason: {reason}*" if reason and event_type != "IMPORT" else ""))
        st.caption("The history is written by the database in the same transaction as each change and cannot be edited.")
    with notes:
        for n in detail["notes"]:
            st.markdown(f"**{n['CreatedBy']}** · {ui.moment(n['CreatedAt'])}  \n{n['NoteText']}")
        if not detail["notes"]:
            st.caption("No notes.")
