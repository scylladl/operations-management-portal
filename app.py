"""
NorthGrid Operations Portal (fictional company). Run with:  streamlit run app.py

Sign-in and navigation. The pages a role sees are a convenience: every command is checked again by the database.
"""
import pathlib

import streamlit as st

from portal import auth, components, db, ui, users

ASSETS = pathlib.Path(__file__).resolve().parent / "assets"


def sign_in_page():
    st.html(ASSETS / "portal.css")
    hero, _, form = st.columns([6, 1, 5], vertical_alignment="center")
    hero.html(components.sign_in_hero())
    with form:
        ui.header("Welcome back", "Sign in to the portal")
        with st.container(border=True, key="panel-sign-in"):
            with st.form("sign_in", border=False):
                login = st.text_input("Login")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in", type="primary", width="stretch"):
                    try:
                        st.session_state["user_id"] = auth.sign_in(ui.connection(), login.strip(), password)["UserId"]
                        st.rerun()
                    except auth.SignInFailed as error:
                        st.error(str(error))
        with st.expander("No account yet? Request one"):
            with st.form("sign_up", clear_on_submit=True, border=False):
                new_login = st.text_input("Login you would like")
                name = st.text_input("Full name")
                new_password = st.text_input("Password (12 characters or more)", type="password")
                if st.form_submit_button("Request account"):
                    if len(new_password) < 12:
                        st.error("Use a password of 12 characters or more.")
                    else:
                        try:
                            users.request_account(ui.connection(), new_login, name, new_password)
                            st.success("Request sent. An administrator assigns your role and region and activates it.")
                        except db.PortalError as error:
                            st.error(str(error))


conn = ui.connection()
user_id = st.session_state.get("user_id")
# Read on every run, so a disabled account or a new role takes effect on the next click
account = users.get_account(conn, user_id) if user_id else None
if not account or not account["IsActive"]:
    st.set_page_config(page_title="NorthGrid Operations Portal", page_icon=str(ASSETS / "mark.svg"), layout="wide",
                       initial_sidebar_state="collapsed")
    # Only the identity: clearing everything would also wipe the sign-in form being submitted
    for key in ("user_id", "account"):
        st.session_state.pop(key, None)
    st.navigation([st.Page(sign_in_page, title="Sign in", icon=":material/login:")], position="hidden").run()
    st.stop()

st.set_page_config(page_title="NorthGrid Operations Portal", page_icon=str(ASSETS / "mark.svg"), layout="wide",
                   initial_sidebar_state="expanded")
st.html(ASSETS / "portal.css")
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "mark.svg"), size="large")
st.session_state["account"] = account
role = account["RoleCode"]


def page(path, title, icon):
    return st.Page(path, title=title, icon=f":material/{icon}:")


sections = {}
if role in ("APR", "ADM"):
    sections["Decide"] = [page("pages/decision_queue.py", "Decision queue", "inbox"),
                          page("pages/verify.py", "To verify", "task_alt"),
                          page("pages/indicators.py", "Indicators", "monitoring")]
if role == "FLD":
    sections["Field work"] = [page("pages/field_work.py", "Field work", "engineering")]
if role in ("REQ", "APR", "ADM"):
    sections["Request"] = [page("pages/my_requests.py", "My requests", "assignment"),
                           page(ui.FORM_PAGE, "New request", "add_circle")]
sections["Look up"] = [page("pages/region_actions.py", "All actions" if role == "ADM" else "Actions in my region", "list"),
                       page(ui.DETAIL_PAGE, "Open an action", "search")]
if role == "ADM":
    sections["Administration"] = [page("pages/accounts.py", "Accounts", "group")]
sections["You"] = [page("pages/my_account.py", "My account", "person")]

with st.sidebar:
    st.html(components.user_chip(account["DisplayName"], f"{account['RoleName']} · "
                                 + (account["RegionName"] or "all regions")))
    if st.button("Sign out", icon=":material/logout:", width="stretch"):
        st.session_state.clear()
        st.rerun()
    st.caption("Simulated scenario. NorthGrid Telecom, its people and data are fictional.")

st.navigation(sections).run()
