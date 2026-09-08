"""Timetable operations used by the local Streamlit application."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from smart_attendance.database.db import connect, initialize
from smart_attendance.services.audit_service import record_system


@dataclass(frozen=True)
class ClassContext:
    department: str
    section: str
    period: str
    starts_at: datetime
    ends_at: datetime
    semester: int = 1
    timetable_id: int | None = None
    subject: str = "General"
    subject_code: str = ""
    faculty: str = ""
    subject_id: int | None = None
    faculty_id: int | None = None
    source: str = "fallback"

    @property
    def label(self) -> str:
        subject = f"{self.subject_code} · {self.subject}" if self.subject_code else self.subject
        return f"{self.department}-{self.section} · {subject} · {self.starts_at:%H:%M}–{self.ends_at:%H:%M}"


def list_catalogue() -> dict[str, list[dict]]:
    initialize()
    with connect() as db:
        return {
            "departments": [dict(row) for row in db.execute("SELECT * FROM departments ORDER BY name")],
            "sections": [dict(row) for row in db.execute("SELECT * FROM sections ORDER BY name")],
            "subjects": [dict(row) for row in db.execute("SELECT * FROM subjects ORDER BY code")],
            "faculty": [dict(row) for row in db.execute("SELECT * FROM faculty ORDER BY name")],
        }


def add_subject(code: str, name: str) -> None:
    code, name = code.strip().upper(), name.strip()
    if not code or len(code) > 24 or not name or len(name) > 100:
        raise ValueError("Enter a subject code and name within the allowed length.")
    with connect() as db:
        db.execute("INSERT INTO subjects(code,name) VALUES (?,?)", (code, name))


def add_faculty(name: str, department_id: int) -> None:
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError("Faculty name is required (maximum 100 characters).")
    with connect() as db:
        db.execute("INSERT INTO faculty(name,department_id) VALUES (?,?)", (name, int(department_id)))


def add_entry(
    department_id: int,
    section_id: int,
    semester: int,
    subject_id: int,
    faculty_id: int,
    weekday: int,
    start_time: time,
    end_time: time,
    classroom: str,
    period: str,
    valid_from: date,
    valid_to: date,
) -> None:
    if start_time >= end_time:
        raise ValueError("Class end time must be after its start time.")
    if not 0 <= int(weekday) <= 6 or not 1 <= int(semester) <= 12:
        raise ValueError("Invalid day or semester.")
    if valid_from > valid_to:
        raise ValueError("The effective end date must follow the start date.")
    if not period.strip() or len(classroom) > 80:
        raise ValueError("Period is required and classroom must be under 80 characters.")
    start_text, end_text = start_time.strftime("%H:%M:%S"), end_time.strftime("%H:%M:%S")
    with connect() as db:
        overlap = db.execute(
            """SELECT 1 FROM timetables WHERE active=1 AND weekday=?
               AND valid_from<=? AND valid_to>=? AND start_time<? AND end_time>?
               AND ((department_id=? AND section_id=? AND semester=?) OR faculty_id=?)""",
            (int(weekday), valid_to.isoformat(), valid_from.isoformat(), end_text, start_text,
             int(department_id), int(section_id), int(semester), int(faculty_id)),
        ).fetchone()
        if overlap:
            raise ValueError("This time overlaps an existing class or faculty assignment.")
        db.execute(
            """INSERT INTO timetables(
                department_id,section_id,semester,subject_id,faculty_id,weekday,
                start_time,end_time,classroom,period,valid_from,valid_to
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(department_id), int(section_id), int(semester), int(subject_id), int(faculty_id),
             int(weekday), start_text, end_text, classroom.strip(), period.strip(),
            valid_from.isoformat(), valid_to.isoformat()),
        )
    record_system(
        "TIMETABLE MODIFIED", f"{department_id}:{section_id}:{period}",
        {"department_id": int(department_id), "section_id": int(section_id), "semester": int(semester),
         "weekday": int(weekday), "start_time": start_text, "end_time": end_text},
    )


def entries() -> list[dict]:
    initialize()
    with connect() as db:
        rows = db.execute(
            """SELECT t.id,d.name department,c.name section,t.semester,s.code subject_code,
               s.name subject,f.name faculty,t.weekday,t.start_time,t.end_time,t.classroom,
               t.period,t.valid_from,t.valid_to
               FROM timetables t
               JOIN departments d ON d.id=t.department_id
               JOIN sections c ON c.id=t.section_id
               JOIN subjects s ON s.id=t.subject_id
               JOIN faculty f ON f.id=t.faculty_id
               WHERE t.active=1 ORDER BY t.weekday,t.start_time,d.name,c.name"""
        ).fetchall()
        return [dict(row) for row in rows]


def deactivate(entry_id: int) -> None:
    with connect() as db:
        db.execute("UPDATE timetables SET active=0 WHERE id=?", (int(entry_id),))
    record_system("TIMETABLE MODIFIED", f"timetable:{int(entry_id)}", {"operation": "retired"})


def current_classes(now: datetime | None = None) -> list[ClassContext]:
    now = now or datetime.now()
    day, current = now.date().isoformat(), now.time().strftime("%H:%M:%S")
    with connect() as db:
        rows = db.execute(
            """SELECT t.*,d.name department,c.name section,s.code subject_code,s.name subject,
               f.name faculty FROM timetables t
               JOIN departments d ON d.id=t.department_id
               JOIN sections c ON c.id=t.section_id
               JOIN subjects s ON s.id=t.subject_id JOIN faculty f ON f.id=t.faculty_id
               WHERE t.active=1 AND t.weekday=? AND t.valid_from<=? AND t.valid_to>=?
               AND t.start_time<=? AND t.end_time>? ORDER BY d.name,c.name""",
            (now.weekday(), day, day, current, current),
        ).fetchall()
    return [
        ClassContext(
            department=row["department"], section=row["section"], period=row["period"],
            starts_at=datetime.combine(now.date(), time.fromisoformat(row["start_time"])),
            ends_at=datetime.combine(now.date(), time.fromisoformat(row["end_time"])),
            semester=row["semester"], timetable_id=row["id"], subject=row["subject"],
            subject_code=row["subject_code"], faculty=row["faculty"], subject_id=row["subject_id"],
            faculty_id=row["faculty_id"], source="scheduled",
        )
        for row in rows
    ]


def student_semesters(department: str, section: str) -> list[int]:
    """Return semesters that currently have active students in a class scope."""
    initialize()
    with connect() as db:
        rows = db.execute(
            """SELECT DISTINCT s.semester FROM students s JOIN departments d ON d.id=s.department_id
               JOIN sections c ON c.id=s.section_id
               WHERE s.active=1 AND d.name=? AND c.name=? ORDER BY s.semester""",
            (department, section),
        ).fetchall()
    return [int(row[0]) for row in rows]


def fallback_context(
    department: str,
    section: str,
    schedule: list,
    now: datetime | None = None,
    semester: int = 1,
) -> ClassContext | None:
    now = now or datetime.now()
    for period, start_at, end_at in schedule:
        if "Break" not in period and start_at <= now.time() < end_at:
            return ClassContext(
                department=department, section=section, period=period,
                starts_at=datetime.combine(now.date(), start_at), ends_at=datetime.combine(now.date(), end_at),
                semester=int(semester), subject=period, source="fallback",
            )
    return None
