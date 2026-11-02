"""Streamlit helpers shared by the pages: connection, the signed-in account, cards, tables and command feedback."""
import re

import pandas as pd
import streamlit as st

from portal import actions, components, config, db

DETAIL_PAGE = "pages/action_detail.py"
FORM_PAGE = "pages/request_form.py"

# Text and background of each status, as in assets/portal.css (all pairs above 4.5:1)
STATUS_STYLE = {"Draft": ("#475467", "#EEF1F5"), "Submitted": ("#1D4ED8", "#E7EFFE"),
                "Returned": ("#8A4B00", "#FFF1DB"), "Approved": ("#6D28D9", "#F1EAFE"),
                "InProgress": ("#065F76", "#E0F4F9"), "Completed": ("#17703D", "#E3F5EA"),
                "Verified": ("#0F5132", "#D3EFDF"), "Rejected": ("#B42318", "#FDEBEA"),
                "Cancelled": ("#525C6B", "#EEEFF2")}
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


def day(value):
    return value.strftime("%d %b %Y").lstrip("0") if value else ""


def moment(value):
    return value.strftime("%d %b %Y, %H:%M").lstrip("0") if value else ""


def header(kicker, title, subtitle=None):
    st.html(components.header(kicker, title, subtitle))


def open_action(action_id):
    st.session_state["action_id"] = int(action_id)
    st.switch_page(DETAIL_PAGE)


def edit_request(action_id=None):
    st.session_state["edit_action_id"] = action_id
    st.switch_page(FORM_PAGE)


def action_cards(rows, key, waiting=False, empty="Nothing waiting here."):
    """Queues as cards, one per action, each with a button that opens it."""
    if not rows:
        st.info(empty, icon=":material/check_circle:")
        return
    for row in rows:
        started = f"started {day(row['StartDate'])}" if row.get("StartDate") else None
        with st.container(border=True, key=f"card-{key}-{row['ActionId']}"):
            text, button = st.columns([7, 1], vertical_alignment="center")
            text.html(components.action_card({**row, "Started": started}, waiting))
            if button.button("Open", key=f"open-{key}-{row['ActionId']}", width="stretch"):
                open_action(row["ActionId"])


def action_table(rows, key, region=True):
    """Long lists as a table; selecting a row opens the action."""
    if not rows:
        st.info("No actions match.")
        return
    frame = pd.DataFrame(rows).fillna({"RequesterName": "not recorded"})
    for column in ("StartDate", "CompletionDate"):
        frame[column] = frame[column].map(day)   # as text, so a missing date is an empty cell, not "None"
    shown = ["ActionId", "CircuitId", "ActionTypeName"] + (["RegionCode"] if region else []) + \
            ["StatusName", "RequesterName", "StartDate", "CompletionDate"]

    def status_cell(row):
        ink, fill = STATUS_STYLE[row["Status"]]
        return [f"color: {ink}; background-color: {fill}; font-weight: 600" if column == "StatusName" else ""
                for column in row.index]

    event = st.dataframe(
        frame.style.apply(status_cell, axis=1), key=key, hide_index=True, width="stretch", column_order=shown,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "ActionId": st.column_config.NumberColumn("Action", format="%d", width="small"),
            "CircuitId": "Circuit", "ActionTypeName": "Type", "RegionCode": "Region", "StatusName": "Status",
            "RequesterName": "Requester", "StartDate": "Started", "CompletionDate": "Completed",
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
