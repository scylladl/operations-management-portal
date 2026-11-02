import streamlit as st

from portal import auth, ui

account = ui.account()
st.title("My account")
st.markdown(f"**{ui.plain(account['DisplayName'])}** ({ui.plain(account['Login'])})  \n{account['RoleName']}"
            + (f", {account['RegionName']}" if account["RegionName"] else ", all regions"))
st.caption("Your role and region are set by an administrator.")

with st.form("password", clear_on_submit=True, width=420):
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
