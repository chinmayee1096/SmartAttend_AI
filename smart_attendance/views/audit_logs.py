"""ADMIN/HOD audit log viewer."""
from datetime import date

import pandas as pd
import streamlit as st

from smart_attendance import ui_theme as ui
from smart_attendance.services import audit_service
from smart_attendance.utils.security import AccessDenied
from smart_attendance.utils.time_utils import system_today


def show(token):
    ui.heading("AUDIT LOGS", "Accountable system activity.",
               "Review security and attendance operations without exposing passwords, credentials, or biometric data.")
    if not token:
        st.warning("Sign in through Staff access as an administrator or HOD.")
        return
    try:
        options = audit_service.filter_options(token)
        col1, col2, col3 = st.columns(3)
        user = col1.selectbox("Audit user", ["All", *options["users"]])
        action = col2.selectbox("Audit action", ["All", *options["actions"]])
        use_date = col3.checkbox("Filter by date")
        selected_date = st.date_input("Audit date", system_today(), disabled=not use_date)
        rows = audit_service.query(
            token, "" if user == "All" else user, "" if action == "All" else action,
            selected_date if use_date else None,
        )
    except AccessDenied as exc:
        st.error(str(exc))
        return
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No audit entries match the selected filters.")
