"""Streamlit helpers shared by the pages: connection, the signed-in account, tables, badges and command feedback."""
import re

import pandas as pd
import streamlit as st

from portal import actions, config, db

DETAIL_PAGE = "pages/action_detail.py"
FORM_PAGE = "pages/request_form.py"

STATUS_COLORS = {"Draft": "gray", "Submitted": "blue", "Returned": "orange", "Rejected": "red",
                 "Approved": "violet", "InProgress": "blue", "Completed": "green", "Verified": "green",
                 "Cancelled": "gray"}
EVENT_LABELS = {"SAVE": "Saved", "SUBMIT": "Submitted", "RESUBMIT": "Resubmitted", "APPROVE": "Approved",
                "RETURN": "Returned for changes", "REJECT": "Rejected", "START": "Work started",
                "COMPLETE": "Completion recorded", "VERIFY": "Verified", "REOPEN": "Reopened", "CANCEL": "Cancelled",
                "OWNER": "Owner changed", "DISCARD": "Draft discarded", "IMPORT": "Imported from the NorthGrid history"}
FIELD_LABELS = {"Status": "Status", "CircuitId": "Circuit", "ActionTypeCode": "Action type", "RequesterId": "Requester",
                "Justification": "Justification", "ExpectedOutcome": "Expected outcome", "StartDate": "Start date",
                "CompletionDate": "Completion date", "Incident": "Incident"}


def connection():
    # pyodbc pools connections, so opening one per page run is cheap
    return db.connect(config.database_settings())


def account():
    return st.session_state["account"]


@st.cache_data(ttl=3600)
def reference():
    """Action types and regions: the same for every user."""
    types, regions = db.call(connection(), "app.usp_ListReference")
    return ({t["ActionTypeCode"]: t["ActionTypeName"] for t in types},
            {r["RegionCode"]: r["RegionName"] for r in regions})


@st.cache_data(ttl=600)
def circuits(region_code):
    """The circuit inventory is not private, so one cached copy per region serves every user."""
    return actions.list_circuits(connection(), region_code)


MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def plain(text):
    """Text typed by users, shown inside Markdown as written: no links, images, HTML or Streamlit directives."""
    return MARKDOWN.sub(r"\\\1", text) if text else text


def status_badge(status, name):
    """Markdown for a status badge; the status name is always written, colour only supports it."""
    return f":{STATUS_COLORS[status]}-badge[{name}]"


def day(value):
    return value.strftime("%d %b %Y").lstrip("0") if value else ""


def moment(value):
    return value.strftime("%d %b %Y, %H:%M").lstrip("0") if value else ""


def open_action(action_id):
    st.session_state["action_id"] = int(action_id)
    st.switch_page(DETAIL_PAGE)


def edit_request(action_id=None):
    st.session_state["edit_action_id"] = action_id
    st.switch_page(FORM_PAGE)


def action_table(rows, key, waiting=False, region=True):
    """Actions as a table; selecting a row opens the action."""
    if not rows:
        st.info("Nothing here.")
        return
    frame = pd.DataFrame(rows)
    columns = ["ActionId", "CircuitId", "ActionTypeName", "StatusName", "RequesterName"]
    if region:
        columns.insert(3, "RegionCode")
    if waiting:
        columns += ["LastSubmittedAt", "WaitingWorkingDays"]
    else:
        columns += ["StartDate", "CompletionDate"]
    frame = frame[columns].fillna({"RequesterName": "not recorded"})
    for column in ("LastSubmittedAt", "StartDate", "CompletionDate"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])   # missing dates show as empty cells, not "None"
    view = frame
    if waiting:
        # Q4: older than 5 working days is highlighted in the queue
        view = frame.style.apply(
            lambda row: ["background-color: #FFF4D6" if row["WaitingWorkingDays"] > 5 else ""] * len(row), axis=1)
    event = st.dataframe(
        view, key=key, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        column_config={
            "ActionId": st.column_config.NumberColumn("Action", format="%d", width="small"),
            "CircuitId": "Circuit", "ActionTypeName": "Type", "RegionCode": "Region", "StatusName": "Status",
            "RequesterName": "Requester",
            "LastSubmittedAt": st.column_config.DatetimeColumn("Submitted", format="D MMM YYYY, HH:mm"),
            "WaitingWorkingDays": st.column_config.NumberColumn("Waiting (working days)", format="%d"),
            "StartDate": st.column_config.DateColumn("Started", format="D MMM YYYY"),
            "CompletionDate": st.column_config.DateColumn("Completed", format="D MMM YYYY"),
        })
    st.caption("Select a row to open the action.")
    if event.selection.rows:
        open_action(frame.iloc[event.selection.rows[0]]["ActionId"])


def run(command, done, then=None):
    """Runs a command, then reruns the page (or calls then); shows the rule that refused it, if any."""
    try:
        command()
    except db.Changed as error:
        st.warning(f"{error} The page now shows the current state.")
        return
    except db.PortalError as error:
        st.error(str(error))
        return
    st.toast(done, icon=":material/check:")
    then() if then else st.rerun()
