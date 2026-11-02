import pandas as pd
import streamlit as st

from portal import actions, ui

account = ui.account()
everything = account["RoleCode"] == "ADM"
st.title("All actions" if everything else f"Actions in {account['RegionName']}")
if account["RoleCode"] == "REQ":
    st.caption("Your own requests and the open actions of your region.")
rows = actions.list_actions(ui.connection(), account["UserId"], "all" if everything else "region")

types, regions = ui.reference()
filters = st.columns([2, 2, 2, 1] if everything else [2, 2, 1])
statuses = filters[0].multiselect("Status", sorted({r["StatusName"] for r in rows}))
chosen_types = filters[1].multiselect("Type", list(types.values()))
if everything:
    chosen_regions = filters[2].multiselect("Region", list(regions), format_func=regions.get)
history = filters[-1].toggle("History", help="Actions recorded before the portal (read only)")

frame = pd.DataFrame(rows)
if not frame.empty:
    keep = frame["IsHistorical"] == history
    if statuses:
        keep &= frame["StatusName"].isin(statuses)
    if chosen_types:
        keep &= frame["ActionTypeName"].isin(chosen_types)
    if everything and chosen_regions:
        keep &= frame["RegionCode"].isin(chosen_regions)
    rows = frame[keep].to_dict("records")
st.caption(f"{len(rows)} action(s)")
ui.action_table(rows, "region_list", region=everything)
