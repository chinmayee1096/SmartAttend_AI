"""Import the AIML Semester V, Section A timetable effective 31 August 2026.

The source sheet names several lab instructors by initials and does not assign
one named instructor to mentoring, club activity, or the open-elective block.
Those labels are retained as printed/coordinator labels instead of inventing
personal names. Running this script repeatedly is safe.
"""
from __future__ import annotations

from datetime import date, time

from smart_attendance.database.db import connect, initialize
from smart_attendance.services.timetable_runtime import add_entry


VALID_FROM = date(2026, 8, 31)
VALID_TO = date(2026, 12, 31)

SUBJECTS = {
    "24AML151": "Software Engineering, Project Management and Finance",
    "24AML152": "Automata Theory and Computations",
    "24AML153": "Computer Networks and Security",
    "24AML154": "Advanced Machine Learning",
    "24AML155": "Virtual Reality and Augmented Reality",
    "OPEN-ELECTIVE-I": "Open Elective-I",
    "EMPLOYABILITY-I": "Employability Skills-I",
    "24AML158": "Internship-II",
    "LIBRARY": "Library",
    "CLUB-ACTIVITY-I": "Club Activity-I",
    "MENTORING": "Mentoring",
}

FACULTY = {
    "MKN": "Prof. Manjunath K N (MKN)",
    "PN": "Prof. Poornima N (PN)",
    "DR-SR": "Dr. Sunitha R (Dr. SR)",
    "PHC": "Prof. Pavithra H C (PHC)",
    "KP": "Prof. Krithi P (KP)",
    "MBM": "Prof. Mahesh B M (MBM)",
    "AML-LAB-A": "PHC / PKD / PV (Advanced ML Lab A)",
    "ARVR-LAB-A": "KP / MBM / MKN (ARVR Lab A)",
    "CNS-LAB-A": "Dr. SR / Dr. HK / Dr. MU (CNS Lab A)",
    "OPEN-ELECTIVE": "Open Elective Faculty (course-specific)",
    "ACTIVITY": "Club Activity Coordinator",
    "MENTOR": "Class Mentor",
}

# Corrections to names that appeared in an earlier timetable transcription.
# This remains idempotent so existing local and deployed databases are repaired
# without replacing timetable or attendance records.
FACULTY_NAME_CORRECTIONS = {
    "Dr. Sruthir K (Dr. SR)": "Dr. Sunitha R (Dr. SR)",
    "Sunitha R": "Dr. Sunitha R (Dr. SR)",
    "Sunitha R / Dr. HK / Dr. MU (CNS Lab A)": "Dr. SR / Dr. HK / Dr. MU (CNS Lab A)",
}

# weekday, start, end, course code, faculty key, room, period label
SCHEDULE = [
    (0, time(8, 30), time(10, 30), "24AML154", "AML-LAB-A", "Advanced ML Lab A", "M1-M2"),
    (0, time(11, 0), time(13, 0), "24AML155", "ARVR-LAB-A", "ARVR Lab A", "M3-M4"),
    (0, time(13, 40), time(14, 40), "24AML154", "PHC", "S103", "M5"),
    (0, time(14, 40), time(15, 40), "24AML151", "MKN", "S103", "M6"),
    (0, time(15, 40), time(16, 10), "MENTORING", "MENTOR", "S103", "M7"),

    (1, time(8, 30), time(10, 30), "24AML155", "ARVR-LAB-A", "ARVR Lab A", "T1-T2"),
    (1, time(11, 0), time(12, 0), "24AML153", "DR-SR", "S103", "T3"),
    (1, time(12, 0), time(13, 0), "LIBRARY", "MBM", "Library", "T4"),
    (1, time(13, 40), time(15, 40), "OPEN-ELECTIVE-I", "OPEN-ELECTIVE", "Course-specific", "T5-T6"),
    (1, time(15, 40), time(16, 10), "24AML158", "MBM", "S103", "T7"),

    (2, time(8, 30), time(9, 30), "24AML152", "PN", "S103", "W1"),
    (2, time(9, 30), time(10, 30), "24AML151", "MKN", "S103", "W2"),
    (2, time(11, 0), time(12, 0), "24AML154", "PHC", "S103", "W3"),
    (2, time(12, 0), time(13, 0), "24AML153", "DR-SR", "S103", "W4"),
    (2, time(13, 40), time(16, 10), "CLUB-ACTIVITY-I", "ACTIVITY", "Activity venue", "W5-W7"),

    (3, time(8, 30), time(9, 30), "24AML153", "DR-SR", "S103", "Th1"),
    (3, time(9, 30), time(10, 30), "24AML152", "PN", "S103", "Th2"),
    (3, time(11, 0), time(12, 0), "24AML151", "MKN", "S103", "Th3"),
    (3, time(12, 0), time(13, 0), "24AML152", "PN", "S103", "Th4"),
    (3, time(13, 40), time(15, 40), "OPEN-ELECTIVE-I", "OPEN-ELECTIVE", "Course-specific", "Th5-Th6"),
    (3, time(15, 40), time(16, 10), "24AML158", "MBM", "S103", "Th7"),

    (4, time(8, 30), time(10, 30), "24AML153", "CNS-LAB-A", "CNS Lab A", "F1-F2"),
    (4, time(11, 0), time(12, 0), "24AML154", "PHC", "S103", "F3"),
    (4, time(13, 40), time(16, 10), "24AML158", "MBM", "S103", "F5-F7"),
]

# Working Saturdays printed beneath the weekly grid.  Each date follows the
# named weekday's timetable and is stored as a one-day Saturday schedule.
SPECIAL_SATURDAYS = {
    date(2026, 9, 12): 0,   # Monday timetable
    date(2026, 9, 26): 4,   # Friday timetable
    date(2026, 10, 10): 1,  # Tuesday timetable
    date(2026, 10, 24): 0,  # Monday timetable
    date(2026, 10, 31): 4,  # Friday timetable
    date(2026, 11, 14): 1,  # Tuesday timetable
    date(2026, 11, 28): 4,  # Friday timetable
    date(2026, 12, 12): 3,  # Thursday timetable
}


def correct_faculty_names() -> int:
    """Apply verified faculty-name corrections to an existing database."""
    initialize()
    changed = 0
    with connect() as db:
        for old_name, corrected_name in FACULTY_NAME_CORRECTIONS.items():
            cursor = db.execute(
                "UPDATE faculty SET name=? WHERE name=?",
                (corrected_name, old_name),
            )
            changed += cursor.rowcount
    return changed


def _catalogue_ids() -> tuple[int, int, dict[str, int], dict[str, int]]:
    with connect() as db:
        department_id = db.execute("SELECT id FROM departments WHERE name=?", ("AIML",)).fetchone()[0]
        section_id = db.execute("SELECT id FROM sections WHERE name=?", ("A",)).fetchone()[0]
        for code, name in SUBJECTS.items():
            db.execute(
                """INSERT INTO subjects(code,name) VALUES (?,?)
                   ON CONFLICT(code) DO UPDATE SET name=excluded.name""",
                (code, name),
            )
        for name in FACULTY.values():
            if not db.execute(
                "SELECT 1 FROM faculty WHERE name=? AND department_id=?", (name, department_id)
            ).fetchone():
                db.execute("INSERT INTO faculty(name,department_id) VALUES (?,?)", (name, department_id))
        subjects = {row["code"]: row["id"] for row in db.execute("SELECT id,code FROM subjects")}
        faculty = {
            key: db.execute(
                "SELECT id FROM faculty WHERE name=? AND department_id=?", (name, department_id)
            ).fetchone()[0]
            for key, name in FACULTY.items()
        }
    return department_id, section_id, subjects, faculty


def import_timetable() -> tuple[int, int]:
    initialize()
    correct_faculty_names()
    department_id, section_id, subjects, faculty = _catalogue_ids()
    added = skipped = 0
    entries_to_import = [
        (*entry, VALID_FROM, VALID_TO) for entry in SCHEDULE
    ]
    for special_day, source_weekday in SPECIAL_SATURDAYS.items():
        for _, starts, ends, code, faculty_key, room, period in SCHEDULE:
            if _ != source_weekday:
                continue
            special_period = f"SAT-{special_day:%Y%m%d}-{period}"
            entries_to_import.append(
                (5, starts, ends, code, faculty_key, room, special_period, special_day, special_day)
            )

    for weekday, starts, ends, code, faculty_key, room, period, valid_from, valid_to in entries_to_import:
        with connect() as db:
            exists = db.execute(
                """SELECT 1 FROM timetables WHERE department_id=? AND section_id=?
                   AND semester=5 AND weekday=? AND start_time=? AND end_time=?
                   AND subject_id=? AND valid_from=? AND valid_to=? AND active=1""",
                (department_id, section_id, weekday, starts.strftime("%H:%M:%S"),
                 ends.strftime("%H:%M:%S"), subjects[code], valid_from.isoformat(), valid_to.isoformat()),
            ).fetchone()
        if exists:
            skipped += 1
            continue
        add_entry(
            department_id, section_id, 5, subjects[code], faculty[faculty_key],
            weekday, starts, ends, room, period, valid_from, valid_to,
        )
        added += 1
    return added, skipped


if __name__ == "__main__":
    created, existing = import_timetable()
    print(f"AIML Semester V Section A: added {created}, already present {existing}")
