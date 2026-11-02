import json
from itertools import groupby

import pandas as pd
import streamlit as st

from portal import actions, components, db, ui, users

account = ui.account()
conn = ui.connection()
me = account["UserId"]
types, _ = ui.reference()

top, find = st.columns([5, 1], vertical_alignment="bottom")
wanted = find.number_input("Go to action", min_value=1, step=1, value=st.session_state.get("action_id"),
                           placeholder="Number")
if not wanted:
    with top:
        ui.header("Look up", "Open an action", "Type an action number, or open one from a queue or a list.")
    st.stop()
try:
    detail = actions.get_action(conn, me, int(wanted))
except db.NotFound as error:
    with top:
        ui.header("Look up", "Open an action")
    st.error(str(error))
    st.stop()
st.session_state["action_id"] = int(wanted)
action = detail["action"]
action_id = action["ActionId"]

with top:
    st.html(components.header(f"Action {action_id} · {action['RegionName'] or 'no region'}",
                              f"{action['ActionTypeName']} on {action['CircuitId']}")
            + components.pill(action["Status"], action["StatusName"]))
if action["IsHistorical"]:
    st.info("Recorded before the portal (NorthGrid history): read only. A field coordinator of the region can "
            "record the completion of one still in progress.", icon=":material/history:")
else:
    st.html(components.stepper(action["Status"], action["StartDate"] is not None))

# The reason behind the current status (returned, rejected, cancelled, reopened), while it still applies
status_changes = [e for e in detail["events"] if e["FieldName"] == "Status"]
last = status_changes[-1] if status_changes else None
if last and last["Reason"] and last["EventType"] != "IMPORT":
    st.warning(f"**{ui.EVENT_LABELS[last['EventType']]}** by {ui.plain(last['ActorName'])}, "
               f"{ui.moment(last['EventAt'])}: {ui.plain(last['Reason'])}", icon=":material/comment:")

content, side = st.columns([3, 2], gap="large")

with side:
    with st.container(border=True, key="panel-actions"):
        st.html(components.section("What you can do"))
        if not detail["transitions"]:
            st.caption("Nothing for you at this step.")
        for t in detail["transitions"]:
            code = t["TransitionCode"]
            if t["RequiresReason"] or code in ("START", "COMPLETE"):
                with st.popover(t["ActionLabel"], width="stretch"):
                    with st.form(f"form_{code}", border=False):
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
                with st.form("note", clear_on_submit=True, border=False):
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
                with st.form("owner", border=False):
                    new_owner = st.selectbox("New owner", candidates, format_func=lambda u: u["DisplayName"])
                    reason = st.text_area("Reason")
                    if st.form_submit_button("Change owner", type="primary"):
                        ui.run(lambda: actions.change_owner(conn, me, action_id, action["RowVer"],
                                                            new_owner["UserId"], reason), "Owner changed")

    with st.container(border=True, key="panel-details"):
        st.html(components.section("Details")
                + components.facts([
                    ("Circuit", action["CircuitId"]), ("Customer", action["CustomerName"]),
                    ("Technology", action["TechnologyCode"]), ("Province", action["Province"]),
                    ("Region", action["RegionName"]),
                    ("Requester", action["RequesterName"] or "not recorded"),
                    ("Version", action["VersionNo"] or None), ("Last submitted", ui.moment(action["LastSubmittedAt"])),
                    ("Work started", ui.day(action["StartDate"])), ("Completed", ui.day(action["CompletionDate"]))]))

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
                    show = types.get if field == "ActionTypeCode" else ui.plain
                    st.markdown(f"**{label}**")
                    before, after = st.columns(2)
                    before.caption(f"Version {old['VersionNo']}")
                    before.markdown(show(old[field]))
                    after.caption(f"Version {new['VersionNo']}")
                    after.markdown(show(new[field]))
            added = sorted(set(json.loads(new["TicketIds"])) - set(json.loads(old["TicketIds"])))
            removed = sorted(set(json.loads(old["TicketIds"])) - set(json.loads(new["TicketIds"])))
            if added or removed:
                changed = True
                st.markdown("**Incidents**  \n" + "  \n".join([f"added {t}" for t in added] + [f"removed {t}" for t in removed]))
            if not changed:
                st.caption("Resubmitted without changes.")
    if not action["IsHistorical"]:
        with st.container(border=True, key="panel-request"):
            st.html(components.section("Justification"))
            st.markdown(ui.plain(action["Justification"]) or "_Not written yet._")
            st.html(components.section("Expected outcome"))
            st.markdown(ui.plain(action["ExpectedOutcome"]) or "_Not written yet._")
            st.html(components.section(f"Incidents it addresses · {len(detail['incidents'])}"))
            if detail["incidents"]:
                st.dataframe(pd.DataFrame(detail["incidents"]), hide_index=True, width="stretch", column_config={
                    "TicketId": "Ticket", "OpenedAt": st.column_config.DatetimeColumn("Opened", format="D MMM YYYY, HH:mm"),
                    "PriorityCode": "Priority", "RootCauseCode": "Root cause", "ResponsibleTeam": "Team",
                    "Status": "Status"})
            else:
                st.caption("None linked yet.")

    history, versions, notes = st.tabs(["History", f"Versions ({len(detail['versions'])})",
                                        f"Work notes ({len(detail['notes'])})"])
    with history:
        entries = []
        for (at, actor, event_type), group in groupby(detail["events"],
                                                      key=lambda e: (e["EventAt"], e["ActorName"], e["EventType"])):
            changes = list(group)
            lines = []
            for change in changes:
                field, old, new = change["FieldName"], change["OldValue"], change["NewValue"]
                if field == "RequesterId" and old is None:
                    continue   # set on creation; the requester is named in the details
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
            entries.append((actor, ui.EVENT_LABELS.get(event_type, event_type), ui.moment(at), lines,
                            reason if event_type != "IMPORT" else None))
        if entries:
            st.html(components.timeline(entries))
        st.caption("Written by the database in the same transaction as each change; it cannot be edited.")
    with versions:
        for v in detail["versions"]:
            st.markdown(f"**Version {v['VersionNo']}**, submitted by {ui.plain(v['SubmittedBy'])} on "
                        f"{ui.moment(v['SubmittedAt'])}  \nIncidents: {', '.join(json.loads(v['TicketIds']))}")
        if not detail["versions"]:
            st.caption("Not submitted yet.")
    with notes:
        if detail["notes"]:
            st.html(components.timeline([(n["CreatedBy"], "Work note", ui.moment(n["CreatedAt"]), [n["NoteText"]], None)
                                         for n in detail["notes"]]))
        else:
            st.caption("No notes.")
