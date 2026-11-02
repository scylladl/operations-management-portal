import streamlit as st

from portal import auth, ui

account = ui.account()
ui.header("You", account["DisplayName"], f"{account['Login']} · {account['RoleName']}, "
          + (account["RegionName"] or "all regions") + ". Your role and region are set by an administrator.")

with st.container(border=True, key="panel-password", width=460), st.form("password", clear_on_submit=True, border=False):
    st.subheader("Change password")
    current = st.text_input("Current password", type="password")
    new = st.text_input("New password (12 characters or more)", type="password")
    repeat = st.text_input("New password again", type="password")
    if st.form_submit_button("Change password", type="primary"):
        if len(new) < 12 or new != repeat:
            st.error("The new password must have 12 characters or more and be typed the same twice.")
        else:
            try:
                auth.change_password(ui.connection(), account["UserId"], current, new)
                st.success("Password changed.")
            except auth.SignInFailed as error:
                st.error(str(error))
