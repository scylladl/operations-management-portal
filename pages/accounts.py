import pandas as pd
import streamlit as st

from portal import ui, users

account = ui.account()
conn = ui.connection()
me = account["UserId"]
_, regions = ui.reference()
ROLES = {"REQ": "Requester", "APR": "Approver", "FLD": "Field coordinator", "ADM": "Administrator"}

ui.header("Administration", "Accounts", "Create accounts, activate sign-up requests and set roles and regions.")
rows = users.list_accounts(conn, me)
waiting = [r for r in rows if r["RoleCode"] is None]
if waiting:
    st.warning(f"{len(waiting)} sign-up request(s) waiting for activation. Select one to give it a role and a region.",
               icon=":material/person_add:")

frame = pd.DataFrame(rows)
event = st.dataframe(frame[["Login", "DisplayName", "RoleName", "RegionCode", "AccountStatus", "CreatedAt"]]
                     .fillna({"RoleName": "–", "RegionCode": "–"}),
                     key="accounts", hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                     column_config={"DisplayName": "Name", "RoleName": "Role", "RegionCode": "Region",
                                    "AccountStatus": "Status",
                                    "CreatedAt": st.column_config.DatetimeColumn("Created", format="D MMM YYYY")})

left, right = st.columns(2, gap="large")
with left:
    if event.selection.rows:
        chosen = rows[event.selection.rows[0]]
        with st.container(border=True, key="panel-edit-account"), st.form("edit", border=False):
            st.subheader(f"{chosen['DisplayName']} ({chosen['Login']})")
            role_codes = list(ROLES)
            role = st.selectbox("Role", role_codes, format_func=ROLES.get,
                                index=role_codes.index(chosen["RoleCode"]) if chosen["RoleCode"] else 0)
            region_codes = list(regions)
            region = st.selectbox("Region (not for administrators)", region_codes, format_func=regions.get,
                                  index=region_codes.index(chosen["RegionCode"]) if chosen["RegionCode"] else 0)
            active = st.checkbox("Active (can sign in)", value=bool(chosen["IsActive"]) or chosen["RoleCode"] is None)
            if st.form_submit_button("Save", type="primary"):
                ui.run(lambda: users.update_account(conn, me, chosen["UserId"], role,
                                                    None if role == "ADM" else region, active, chosen["RowVer"]),
                       "Account saved")
        with st.popover("Reset password"):
            with st.form("reset", clear_on_submit=True):
                password = st.text_input("New password (12 characters or more)", type="password")
                if st.form_submit_button("Reset"):
                    if len(password) < 12:
                        st.error("Use 12 characters or more.")
                    else:
                        ui.run(lambda: users.reset_password(conn, me, chosen["UserId"], password), "Password reset")
    else:
        st.caption("Select an account to change its role, region or activation.")

with right:
    with st.container(border=True, key="panel-new-account"), st.form("create", clear_on_submit=True, border=False):
        st.subheader("New account")
        login = st.text_input("Login")
        name = st.text_input("Full name")
        role = st.selectbox("Role", list(ROLES), format_func=ROLES.get, key="new_role")
        region = st.selectbox("Region (not for administrators)", list(regions), format_func=regions.get,
                              key="new_region")
        password = st.text_input("Initial password (12 characters or more)", type="password")
        if st.form_submit_button("Create account", type="primary"):
            if len(password) < 12:
                st.error("Use 12 characters or more.")
            else:
                ui.run(lambda: users.create_account(conn, me, login, name, role, None if role == "ADM" else region,
                                                    password), "Account created")
