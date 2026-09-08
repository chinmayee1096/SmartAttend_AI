"""Low-attendance prediction UI."""
import pandas as pd
import streamlit as st

from smart_attendance import ui_theme as ui
from smart_attendance.services import prediction_service
from smart_attendance.utils.security import AccessDenied


def show(token):
    ui.heading("RISK ANALYSIS", "Early attendance warning.",
               "Use real attendance history to identify students who may fall below the configured threshold.")
    if not token:
        st.warning("Sign in through Staff access to view student risk information.")
        return
    try:
        result = prediction_service.predict(token)
    except AccessDenied as exc:
        st.error(str(exc))
        return
    readiness = result["readiness"]
    if result["status"] == "insufficient":
        st.info(result["message"])
        metric_a, metric_b, metric_c, metric_d = st.columns(4)
        metric_a.metric("Eligible student-periods", readiness["eligible_periods"])
        metric_b.metric("Students with 5 periods", readiness["students_with_5_records"])
        metric_c.metric("Training windows", f"{result['training_samples']} / {readiness['required_training_windows']}")
        metric_d.metric("Threshold", f"{result['threshold']:.0f}%")
        classes = readiness["class_counts"]
        st.caption(
            "ML prediction starts only after the history provides at least 30 chronological training windows, "
            f"including both outcomes. Current windows: {classes['below_threshold']} below threshold and "
            f"{classes['at_or_above_threshold']} at or above threshold."
        )
    else:
        metric_a, metric_b, metric_c = st.columns(3)
        metric_a.metric("Model", "Logistic Regression")
        metric_b.metric("Training windows", result["training_samples"])
        metric_c.metric("Attendance threshold", f"{result['threshold']:.0f}%")
        st.caption(f"Historical training accuracy: {result['training_accuracy'] * 100:.1f}%. This describes the available historical windows, not future certainty.")
    rows = result["rows"]
    if not rows:
        st.info("No eligible attendance history is available for your access scope.")
        return
    data = pd.DataFrame(rows)
    departments = ["All"] + sorted(data["department"].dropna().unique().tolist())
    filter_a, filter_b, filter_c = st.columns([1, 1, 1])
    department = filter_a.selectbox("Department", departments, key="risk_department")
    scoped = data if department == "All" else data[data["department"] == department]
    sections = ["All"] + sorted(scoped["section"].dropna().unique().tolist())
    section = filter_b.selectbox("Section", sections, key="risk_section")
    if section != "All":
        scoped = scoped[scoped["section"] == section]
    levels = ["All", "HIGH", "MEDIUM", "LOW", "INSUFFICIENT DATA"]
    level = filter_c.selectbox("Current indicator", levels, key="risk_level")
    if level != "All":
        scoped = scoped[scoped["current_indicator"] == level]

    if result["status"] == "insufficient":
        st.subheader("Current attendance indicators")
        st.caption("These indicators summarize recorded attendance. They are not ML predictions.")
        columns = ["roll", "name", "department", "section", "classes", "current_attendance", "current_indicator", "observed_reason"]
    else:
        st.subheader("Predicted low-attendance risk")
        columns = ["roll", "name", "department", "section", "classes", "current_attendance", "risk_probability", "risk", "reason"]

    display = scoped[columns].rename(columns={
        "roll": "Roll", "name": "Student", "department": "Department", "section": "Section",
        "classes": "Eligible classes", "current_attendance": "Current attendance %",
        "risk_probability": "Predicted risk %", "risk": "Risk", "reason": "Reason",
        "current_indicator": "Current indicator", "observed_reason": "Reason",
    })
    st.dataframe(display, hide_index=True, width="stretch")
