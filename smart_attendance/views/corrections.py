"""Authorized direct attendance correction UI."""
import pandas as pd
import streamlit as st

from smart_attendance import ui_theme as ui
from smart_attendance.services import correction_service
from smart_attendance.utils.security import AccessDenied


def show(token):
    ui.heading("ATTENDANCE CORRECTIONS", "Review and correct a record.",
               "Every status change requires a reason and creates an immutable audit entry.")
    if not token:
        st.warning("Sign in through Staff access as assigned faculty or administrator.")
        return
    try:
        rows = correction_service.records(token)
    except AccessDenied as exc:
        st.error(str(exc))
        return
    if not rows:
        st.info("No attendance records are available within your assigned classes.")
        return
    selected = st.selectbox(
        "Attendance record", rows,
        format_func=lambda row: f"{row['date']} · {row['roll']} · {row['name']} · {row['subject']} · {row['status']}",
    )
    left, right = st.columns(2)
    left.metric("Recorded status", selected["status"])
    right.metric("Class", f"{selected['subject_code'] or selected['period']} · {selected['date']}")
    with st.form("attendance_correction"):
        new_status = st.selectbox("Corrected status", correction_service.STATUSES)
        reason = st.text_area("Correction reason", max_chars=500)
        if st.form_submit_button("Apply correction", type="primary"):
            try:
                correction_service.correct(token, selected["attendance_id"], new_status, reason)
                st.success("Attendance corrected and audit entry recorded.")
                st.rerun()
            except (ValueError, AccessDenied) as exc:
                st.error(str(exc))
    history = correction_service.history(token)
    if history:
        st.subheader("Correction history")
        st.dataframe(pd.DataFrame(history), hide_index=True, width="stretch")

