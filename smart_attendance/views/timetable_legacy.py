from datetime import date, datetime, time
from html import escape

import pandas as pd
import streamlit as st

from smart_attendance.services import timetable_runtime as service
from smart_attendance.database.db import connect


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_SLOTS = [
    ("08:30", "09:30", None), ("09:30", "10:30", None),
    ("10:30", "11:00", "BREAK"), ("11:00", "12:00", None),
    ("12:00", "13:00", None), ("13:00", "13:40", "LUNCH"),
    ("13:40", "14:40", None), ("14:40", "15:40", None),
    ("15:40", "16:10", None),
]


def _clock(value):
    return time.fromisoformat(value)


def _weekly_grid(rows, schedule_label, now=None):
    now = now or datetime.now()
    headers = "".join(f"<th>{start}<br>{end}</th>" for start, end, _ in TIME_SLOTS)
    body = []
    active_label = None
    for weekday in range(5):
        day_rows = [row for row in rows if row["weekday"] == weekday and row["valid_from"] != row["valid_to"]]
        by_start = {row["start_time"][:5]: row for row in day_rows}
        cells = [f'<td class="sa-day">{DAY_NAMES[weekday].upper()}</td>']
        index = 0
        while index < len(TIME_SLOTS):
            slot_start, slot_end, pause = TIME_SLOTS[index]
            if pause:
                cells.append(f'<td class="sa-break">{pause}</td>')
                index += 1
                continue
            row = by_start.get(slot_start)
            if row is None:
                cells.append('<td class="sa-empty"></td>')
                index += 1
                continue
            span = 1
            while index + span < len(TIME_SLOTS):
                _, next_end, next_pause = TIME_SLOTS[index + span]
                if next_pause or _clock(next_end) > _clock(row["end_time"]):
                    break
                span += 1
            is_current = (
                now.weekday() == weekday
                and date.fromisoformat(row["valid_from"]) <= now.date() <= date.fromisoformat(row["valid_to"])
                and _clock(row["start_time"]) <= now.time() < _clock(row["end_time"])
            )
            if is_current:
                active_label = f'{row["subject_code"]} · {row["subject"]} · until {row["end_time"][:5]}'
            css_class = "sa-current" if is_current else ""
            now_badge = '<span class="sa-now-badge">LIVE NOW</span>' if is_current else ""
            cells.append(
                f'<td class="{css_class}" colspan="{span}">{now_badge}'
                f'<div class="sa-course-code">{escape(row["subject_code"])}</div>'
                f'<div class="sa-course-name">{escape(row["subject"])}</div>'
                f'<div class="sa-course-meta">{escape(row["faculty"])}<br>{escape(row["classroom"] or "Room not set")}</div></td>'
            )
            index += span
        body.append("<tr>" + "".join(cells) + "</tr>")
    status = active_label or "No scheduled class is active at this time"
    st.markdown(
        f'<div class="sa-schedule-toolbar"><strong>{escape(schedule_label)}</strong>'
        f'<span>{now:%A, %H:%M} · {escape(status)}</span></div>'
        f'<div class="sa-timetable-wrap"><table class="sa-timetable"><thead><tr><th>DAY</th>{headers}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _special_saturdays(rows):
    special_dates = sorted({row["valid_from"] for row in rows if row["weekday"] == 5 and row["valid_from"] == row["valid_to"]})
    if not special_dates:
        return
    labels = "".join(
        f'<span class="sa-special-day">{date.fromisoformat(value):%d %b %Y}</span>' for value in special_dates
    )
    st.markdown("**Special working Saturdays**")
    st.markdown(f'<div class="sa-special-days">{labels}</div>', unsafe_allow_html=True)


def _setting(key, default):
    import json
    with connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return default if row is None else json.loads(row[0])


def _save_settings(values):
    import json
    with connect() as db:
        for key, value in values.items():
            db.execute(
                "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )


def show():
    from smart_attendance import ui_theme as ui
    ui.heading("ACADEMIC SCHEDULE", "Classes, subjects and attendance rules.",
               "Configure the timetable used to resolve the active class and finalize attendance.")

    rows = service.entries()
    if rows:
        departments = sorted({row["department"] for row in rows})
        department_filter = st.selectbox("Timetable department", departments)
        section_options = sorted({row["section"] for row in rows if row["department"] == department_filter})
        section_filter = st.selectbox("Timetable section", section_options)
        semester_options = sorted({row["semester"] for row in rows if row["department"] == department_filter and row["section"] == section_filter})
        semester_filter = st.selectbox("Timetable semester", semester_options, index=len(semester_options) - 1)
        selected_rows = [
            row for row in rows if row["department"] == department_filter
            and row["section"] == section_filter and row["semester"] == semester_filter
        ]
        _weekly_grid(
            selected_rows,
            f"{department_filter} · SECTION {section_filter} · SEMESTER {semester_filter}",
        )
        _special_saturdays(selected_rows)
        display = pd.DataFrame(rows)
        display["day"] = display["weekday"].map(dict(enumerate(DAY_NAMES)))
        with st.expander("Detailed schedule records"):
            st.dataframe(
                display[["id", "department", "section", "semester", "subject_code", "subject", "faculty",
                         "day", "start_time", "end_time", "classroom", "period", "valid_from", "valid_to"]],
                width="stretch", hide_index=True,
            )
    else:
        st.info("No timetable entries yet. The existing period schedule remains active as fallback.")

    catalogue = service.list_catalogue()
    st.subheader("Subjects and faculty")
    left, right = st.columns(2)
    with left, st.form("new_subject"):
        subject_code = st.text_input("Subject code")
        subject_name = st.text_input("Subject name")
        if st.form_submit_button("Add subject", width="stretch"):
            try:
                service.add_subject(subject_code, subject_name)
                st.success("Subject added.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with right, st.form("new_faculty"):
        faculty_name = st.text_input("Faculty name")
        faculty_department = st.selectbox("Faculty department", catalogue["departments"], format_func=lambda row: row["name"])
        if st.form_submit_button("Add faculty", width="stretch"):
            try:
                service.add_faculty(faculty_name, faculty_department["id"])
                st.success("Faculty added.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    catalogue = service.list_catalogue()
    st.subheader("Add timetable entry")
    if not catalogue["subjects"] or not catalogue["faculty"]:
        st.warning("Add at least one subject and faculty member first.")
    else:
        with st.form("new_timetable"):
            col1, col2, col3 = st.columns(3)
            with col1:
                department = st.selectbox("Department", catalogue["departments"], format_func=lambda row: row["name"])
                section = st.selectbox("Section", catalogue["sections"], format_func=lambda row: row["name"])
                semester = st.number_input("Semester", 1, 12, 1)
            with col2:
                subject = st.selectbox("Subject", catalogue["subjects"], format_func=lambda row: f"{row['code']} · {row['name']}")
                faculty = st.selectbox("Faculty", catalogue["faculty"], format_func=lambda row: row["name"])
                weekday = st.selectbox("Day", range(7), format_func=lambda value: DAY_NAMES[value])
            with col3:
                start_at = st.time_input("Start time", time(9, 0))
                end_at = st.time_input("End time", time(10, 0))
                period = st.text_input("Period label", "Period1")
            classroom = st.text_input("Classroom")
            valid_from = st.date_input("Effective from", date.today())
            valid_to = st.date_input("Effective until", date(date.today().year + 1, 12, 31))
            if st.form_submit_button("Save timetable entry", type="primary", width="stretch"):
                try:
                    service.add_entry(
                        department["id"], section["id"], int(semester), subject["id"], faculty["id"],
                        int(weekday), start_at, end_at, classroom, period, valid_from, valid_to,
                    )
                    st.success("Timetable entry saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    st.subheader("Attendance decision rules")
    with st.form("attendance_rules"):
        late = st.number_input("Late after (minutes)", 0, 60, int(_setting("late_minutes", 10)))
        presence = st.slider("Minimum presence required", 10, 100, int(float(_setting("presence_ratio", 0.75)) * 100), format="%d%%")
        gap = st.number_input("Maximum credited gap between observations (seconds)", 5, 300, int(_setting("observation_gap_seconds", 90)))
        threshold = st.number_input("LBPH maximum distance", 1.0, 100.0, float(_setting("lbph_distance", 55.0)))
        require_liveness = st.checkbox("Require liveness before attendance", bool(_setting("liveness_required", True)))
        if st.form_submit_button("Save attendance rules"):
            _save_settings({"late_minutes": late, "presence_ratio": presence / 100.0,
                            "observation_gap_seconds": gap, "lbph_distance": threshold,
                            "liveness_required": require_liveness})
            st.success("Attendance rules saved.")

    if rows:
        selected = st.selectbox("Retire timetable entry", rows, format_func=lambda row: f"{row['id']} · {row['department']}-{row['section']} · {row['subject']}")
        if st.button("Retire selected entry"):
            service.deactivate(selected["id"])
            st.rerun()
