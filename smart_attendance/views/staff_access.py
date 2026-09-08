"""Local staff authentication and initial account setup."""
import streamlit as st

from smart_attendance import ui_theme as ui
from smart_attendance.utils import security


def show():
    ui.heading("STAFF ACCESS", "Secure staff workspace.",
               "Sign in to use predictions, corrections, audit logs, and administration tools.")
    token = st.session_state.get("staff_token")
    if token:
        try:
            current = security.current_user(token)
        except security.AccessDenied:
            st.session_state.pop("staff_token", None)
            st.warning("Your staff session expired. Sign in again.")
            return
        st.success(f"Signed in as {current['username']} · {current['role']}")
        if st.button("Logout", type="primary"):
            security.logout(token)
            st.session_state.pop("staff_token", None)
            st.rerun()
        if current["role"] == "ADMIN":
            with st.expander("Account and system administration"):
                from smart_attendance.views.settings import show as show_settings
                show_settings(token)
        return

    if not security.has_users():
        st.info("Create the first administrator account. The password is stored only as a secure hash.")
        with st.form("initial_admin"):
            username = st.text_input("Administrator username")
            password = st.text_input("Administrator password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create administrator", type="primary"):
                if password != confirm:
                    st.error("Passwords do not match.")
                else:
                    try:
                        security.setup_admin(username, password)
                        st.session_state.staff_token = security.login(username, password)
                        st.rerun()
                    except (ValueError, security.AccessDenied) as exc:
                        st.error(str(exc))
        return

    with st.form("staff_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            try:
                st.session_state.staff_token = security.login(username, password)
                st.rerun()
            except security.AccessDenied as exc:
                st.error(str(exc))
