import altair as alt
import pandas as pd
import streamlit as st

from portal import actions, ui

account = ui.account()
everything = account["RoleCode"] == "ADM"
data = actions.indicators(ui.connection(), account["UserId"])
_, regions = ui.reference()

st.title("Indicators")
st.caption(("All regions. " if everything else f"{account['RegionName']}. ")
           + "Portal requests only; the history recorded before the portal has no submissions or decisions. "
             "Working days are Monday to Friday, without holidays. Definitions in docs/01-business-requirements.md, "
             "section 7, and database/06_reporting.sql.")

waiting = pd.DataFrame(data["waiting"], columns=["RegionCode", "WaitingBucket", "Actions"])
decisions = pd.DataFrame(data["decisions"], columns=["RegionCode", "Decided", "Approved", "Rejected",
                                                      "ReturnedAtLeastOnce", "ReturnRate", "AvgWorkingDaysToDecision"])
completion = pd.DataFrame(data["completion"], columns=["RegionCode", "Completed", "AvgDaysToComplete"])
by_status = pd.DataFrame(data["by_status"], columns=["RegionCode", "ActionTypeCode", "Status", "Actions"])


def weighted(frame, value, weight):
    return (frame[value].astype(float) * frame[weight]).sum() / frame[weight].sum() if not frame.empty else None


over_five = int(waiting.loc[waiting["WaitingBucket"] == "Over 5", "Actions"].sum())
decided = int(decisions["Decided"].sum())
returned = int(decisions["ReturnedAtLeastOnce"].sum())
to_decision = weighted(decisions, "AvgWorkingDaysToDecision", "Decided")
to_complete = weighted(completion, "AvgDaysToComplete", "Completed")

tiles = st.columns(4)
tiles[0].metric("Waiting for a decision", int(waiting["Actions"].sum()), border=True,
                help="Submitted requests, now.")
tiles[0].caption(f"{over_five} over the 5-working-day target")
tiles[1].metric("Working days to decision", f"{to_decision:.1f}" if to_decision is not None else "–", border=True,
                help="Average, from the first submission to the approval or rejection.")
tiles[1].caption(f"{decided} requests decided")
tiles[2].metric("Return rate", f"{returned / decided:.0%}" if decided else "–", border=True,
                help="Decided requests that were returned at least once.")
tiles[2].caption(f"{returned} of {decided} decided")
tiles[3].metric("Days to complete", f"{to_complete:.1f}" if to_complete is not None else "–", border=True,
                help="Average calendar days from the approval to the completion date.")
tiles[3].caption(f"{int(completion['Completed'].sum())} completed or verified")

STATUS_ORDER = ["Submitted", "Returned", "Approved", "InProgress", "Completed", "Verified", "Rejected", "Cancelled"]
STATUS_NAMES = {"InProgress": "In progress"}
left, right = st.columns(2, gap="large")
with left:
    st.subheader("Waiting by age")
    ages = (waiting.groupby("WaitingBucket")["Actions"].sum()
            .reindex(["0-2", "3-5", "Over 5"], fill_value=0).rename_axis("Working days").reset_index())
    st.altair_chart(
        alt.Chart(ages).mark_bar(color="#0A7FA0", cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=48)
        .encode(x=alt.X("Working days:N", sort=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Actions:Q", axis=alt.Axis(tickMinStep=1, grid=True, gridOpacity=0.3), title="Requests"),
                tooltip=["Working days", "Actions"])
        .properties(height=260), width="stretch")
with right:
    st.subheader("Requests by status")
    statuses = (by_status.groupby("Status")["Actions"].sum().reindex(STATUS_ORDER, fill_value=0)
                .rename(index=STATUS_NAMES).rename_axis("Status").reset_index())
    st.altair_chart(
        alt.Chart(statuses).mark_bar(color="#0A7FA0", cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=18)
        .encode(y=alt.Y("Status:N", sort=None, title=None),
                x=alt.X("Actions:Q", axis=alt.Axis(tickMinStep=1, grid=True, gridOpacity=0.3), title="Requests"),
                tooltip=["Status", "Actions"])
        .properties(height=260), width="stretch")

st.subheader("By region" if everything else "Detail")
table = (decisions.merge(completion, on="RegionCode", how="outer")
         .merge(waiting.groupby("RegionCode")["Actions"].sum().rename("Waiting").reset_index(), on="RegionCode",
                how="outer"))
table.insert(0, "Region", table.pop("RegionCode").map(regions))
st.dataframe(table, hide_index=True, width="stretch", column_config={
    "Waiting": st.column_config.NumberColumn("Waiting now", format="%d"),
    "Decided": st.column_config.NumberColumn(format="%d"),
    "Approved": st.column_config.NumberColumn(format="%d"),
    "Rejected": st.column_config.NumberColumn(format="%d"),
    "ReturnedAtLeastOnce": st.column_config.NumberColumn("Returned at least once", format="%d"),
    "ReturnRate": st.column_config.NumberColumn("Return rate", format="percent"),
    "AvgWorkingDaysToDecision": st.column_config.NumberColumn("Working days to decision", format="%.1f"),
    "Completed": st.column_config.NumberColumn(format="%d"),
    "AvgDaysToComplete": st.column_config.NumberColumn("Days to complete", format="%.1f"),
})
