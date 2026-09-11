"""Central attendance engine: roster, observations, duration and final status."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path

from smart_attendance.database.db import ROOT, connect, initialize
from smart_attendance.services.timetable_runtime import ClassContext
from smart_attendance.services.audit_service import record_system
from smart_attendance.utils.time_utils import system_now


DEFAULT_RULES = {
    "late_minutes": 10.0,
    "presence_ratio": 0.75,
    "observation_gap_seconds": 90.0,
    "lbph_distance": 55.0,
    "liveness_required": True,
}


def rules() -> dict:
    with connect() as db:
        values = {row["key"]: json.loads(row["value"]) for row in db.execute("SELECT key,value FROM settings")}
    result = DEFAULT_RULES | values
    result["presence_ratio"] = min(1.0, max(0.1, float(result["presence_ratio"])))
    return result


def _ids(db, context: ClassContext) -> tuple[int, int]:
    department = db.execute("SELECT id FROM departments WHERE name=?", (context.department,)).fetchone()
    section = db.execute("SELECT id FROM sections WHERE name=?", (context.section,)).fetchone()
    if not department or not section:
        raise ValueError("The selected department or section is not registered.")
    return department[0], section[0]


def start_class(context: ClassContext, allow_finalized: bool = False) -> int:
    """Create a class and snapshot its current active roster once.

    Scheduled catch-up scans may inspect an already finalized class.  They use
    ``allow_finalized`` so the scan stays idempotent; interactive attendance
    starts retain the guard against reopening a completed class.
    """
    initialize()
    with connect() as db:
        department_id, section_id = _ids(db, context)
        db.execute(
            """INSERT OR IGNORE INTO class_sessions(
               timetable_id,date,period,department_id,section_id,subject_id,faculty_id,
               semester,starts_at,ends_at,source
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (context.timetable_id, context.starts_at.date().isoformat(), context.period,
             department_id, section_id, context.subject_id, context.faculty_id, context.semester,
             context.starts_at.isoformat(timespec="seconds"), context.ends_at.isoformat(timespec="seconds"),
             context.source),
        )
        session = db.execute(
            """SELECT id,finalized FROM class_sessions WHERE date=? AND department_id=?
               AND section_id=? AND period=?""",
            (context.starts_at.date().isoformat(), department_id, section_id, context.period),
        ).fetchone()
        if session["finalized"] and not allow_finalized:
            raise ValueError("This class has already ended and is finalized.")
        if session["finalized"]:
            return int(session["id"])
        db.execute(
            """UPDATE class_sessions SET timetable_id=?,subject_id=?,faculty_id=?,semester=?,
               starts_at=?,ends_at=?,source=? WHERE id=?""",
            (context.timetable_id, context.subject_id, context.faculty_id, context.semester,
             context.starts_at.isoformat(timespec="seconds"), context.ends_at.isoformat(timespec="seconds"),
             context.source, session["id"]),
        )
        students = db.execute(
            """SELECT id FROM students WHERE active=1 AND department_id=? AND section_id=?
               AND semester=? AND date(enrolled_at)<=?""",
            (department_id, section_id, context.semester, context.starts_at.date().isoformat()),
        ).fetchall()
        if not students:
            raise ValueError(
                f"No active students are registered in {context.department}-{context.section}, "
                f"semester {context.semester}. Select the correct semester before starting attendance."
            )
        for student in students:
            db.execute(
                "INSERT OR IGNORE INTO attendance(session_id,student_id,status,source) VALUES (?,?,'INCOMPLETE',?)",
                (session["id"], student["id"], context.source),
            )
        return int(session["id"])


def record_observation(
    context: ClassContext,
    roll: str,
    confidence: float,
    liveness_passed: bool,
    observed_at: datetime | None = None,
    base_dir: Path | None = None,
) -> str:
    """Record one verified observation without ever creating a duplicate row."""
    observed_at = observed_at or system_now()
    config = rules()
    if observed_at < context.starts_at:
        return "NOT STARTED"
    if observed_at >= context.ends_at:
        finalize_due(observed_at, base_dir)
        return "CLASS ENDED"
    if config["liveness_required"] and not liveness_passed:
        return "VERIFYING"
    if float(confidence) > float(config["lbph_distance"]):
        return "UNKNOWN"
    session_id = start_class(context)
    with connect() as db:
        department_id, section_id = _ids(db, context)
        student = db.execute(
            """SELECT id FROM students WHERE roll=? AND department_id=? AND section_id=?
               AND semester=? AND active=1""",
            (str(roll), department_id, section_id, context.semester),
        ).fetchone()
        if not student:
            return "UNKNOWN"
        row = db.execute(
            "SELECT * FROM attendance WHERE session_id=? AND student_id=?",
            (session_id, student["id"]),
        ).fetchone()
        previous = datetime.fromisoformat(row["last_seen"]) if row and row["last_seen"] else None
        increment = 0.0
        if previous:
            increment = max(0.0, min((observed_at - previous).total_seconds(), float(config["observation_gap_seconds"])))
        first_seen = row["first_seen"] if row and row["first_seen"] else observed_at.isoformat(timespec="seconds")
        presence = float(row["presence_seconds"] if row else 0.0) + increment
        duration = max(1.0, (context.ends_at - context.starts_at).total_seconds())
        if presence >= duration * float(config["presence_ratio"]):
            late_at = context.starts_at + timedelta(minutes=float(config["late_minutes"]))
            status = "LATE" if datetime.fromisoformat(first_seen) > late_at else "PRESENT"
        else:
            status = "INCOMPLETE"
        audit_change = not row or not row["first_seen"] or row["status"] != status
        db.execute(
            """INSERT INTO attendance(
               session_id,student_id,first_seen,last_seen,presence_seconds,status,confidence,provider,liveness,source
               ) VALUES (?,?,?,?,?,?,?,?,1,?)
               ON CONFLICT(session_id,student_id) DO UPDATE SET
               first_seen=COALESCE(attendance.first_seen,excluded.first_seen),last_seen=excluded.last_seen,
               presence_seconds=excluded.presence_seconds,status=excluded.status,
               confidence=excluded.confidence,provider=excluded.provider,liveness=1""",
            (session_id, student["id"], first_seen, observed_at.isoformat(timespec="seconds"),
             presence, status, float(confidence), "lbph", context.source),
        )
    if audit_change:
        record_system(
            "ATTENDANCE MARKED", f"{context.department}:{context.section}:{roll}",
            {"department": context.department, "section": context.section, "roll": str(roll),
             "subject": context.subject_code or context.subject, "status": status,
             "liveness": True, "recognition_distance": round(float(confidence), 2)},
        )
    sync_csv(context.starts_at.date(), context.department, base_dir)
    return status


def finalize_due(now: datetime | None = None, base_dir: Path | None = None) -> int:
    """Finalize every ended, known class. Missing roster members become ABSENT."""
    now = now or system_now()
    # Create rosters only for classes that can still be observed.  Importing a
    # timetable after a class has ended must not manufacture retroactive
    # absences for a period during which SmartAttend was not configured.
    materialize_scheduled(now.date(), active_after=now)
    complete_period_rosters(now, base_dir)
    config = rules()
    changed: list[tuple[date, str]] = []
    with connect() as db:
        sessions = db.execute(
            """SELECT cs.*,d.name department FROM class_sessions cs
               JOIN departments d ON d.id=cs.department_id
               WHERE cs.finalized=0 AND cs.ends_at IS NOT NULL AND cs.ends_at<=?""",
            (now.isoformat(timespec="seconds"),),
        ).fetchall()
        for session in sessions:
            duration = max(1.0, (datetime.fromisoformat(session["ends_at"]) - datetime.fromisoformat(session["starts_at"])).total_seconds())
            for row in db.execute("SELECT * FROM attendance WHERE session_id=?", (session["id"],)).fetchall():
                if not row["first_seen"]:
                    status = "ABSENT"
                elif float(row["presence_seconds"]) < duration * float(config["presence_ratio"]):
                    status = "INCOMPLETE"
                else:
                    late_at = datetime.fromisoformat(session["starts_at"]) + timedelta(minutes=float(config["late_minutes"]))
                    status = "LATE" if datetime.fromisoformat(row["first_seen"]) > late_at else "PRESENT"
                db.execute("UPDATE attendance SET status=? WHERE id=?", (status, row["id"]))
            db.execute("UPDATE class_sessions SET finalized=1 WHERE id=?", (session["id"],))
            changed.append((date.fromisoformat(session["date"]), session["department"]))
    for day, department in set(changed):
        sync_csv(day, department, base_dir)
    return len(changed)


def complete_period_rosters(now: datetime | None = None, base_dir: Path | None = None) -> int:
    """Ensure each started/finalized period has one outcome for every eligible student.

    Legacy CSVs often contain recognition events only. For a finalized period,
    an eligible student without an event is an ABSENT student-period, not a
    missing denominator.
    """
    now = now or system_now()
    initialize()
    inserted = 0
    changed: set[tuple[date, str]] = set()
    with connect() as db:
        sessions = db.execute(
            """SELECT cs.*,d.name department FROM class_sessions cs
               JOIN departments d ON d.id=cs.department_id
               WHERE cs.date<=? AND (cs.finalized=1 OR cs.starts_at IS NULL OR cs.starts_at<=?)
               ORDER BY cs.date,cs.id""",
            (now.date().isoformat(), now.isoformat(timespec="seconds")),
        ).fetchall()
        for session in sessions:
            semester = int(session["semester"])
            if session["source"] == "legacy":
                observed_semesters = db.execute(
                    """SELECT DISTINCT s.semester FROM attendance a
                       JOIN students s ON s.id=a.student_id WHERE a.session_id=?""",
                    (session["id"],),
                ).fetchall()
                if len(observed_semesters) == 1:
                    semester = int(observed_semesters[0][0])
                    db.execute("UPDATE class_sessions SET semester=? WHERE id=?", (semester, session["id"]))
            students = db.execute(
                """SELECT id FROM students WHERE active=1 AND department_id=? AND section_id=?
                   AND semester=? AND date(enrolled_at)<=?""",
                (session["department_id"], session["section_id"], semester, session["date"]),
            ).fetchall()
            status = "ABSENT" if session["finalized"] else "INCOMPLETE"
            for student in students:
                before = db.total_changes
                db.execute(
                    "INSERT OR IGNORE INTO attendance(session_id,student_id,status,source) VALUES (?,?,?,'period-roster')",
                    (session["id"], student["id"], status),
                )
                if db.total_changes > before:
                    inserted += 1
                    changed.add((date.fromisoformat(session["date"]), session["department"]))
    for day, department in changed:
        sync_csv(day, department, base_dir)
    if inserted:
        record_system(
            "PERIOD ROSTER COMPLETED", "attendance",
            {"student_periods_added": inserted, "reports_updated": len(changed)},
        )
    return inserted


def materialize_scheduled(day: date, active_after: datetime | None = None) -> int:
    """Create scheduled rosters, optionally excluding already-ended classes."""
    initialize()
    day_text = day.isoformat()
    with connect() as db:
        query = """SELECT t.*,d.name department,c.name section,s.code subject_code,s.name subject,
               f.name faculty FROM timetables t
               JOIN departments d ON d.id=t.department_id JOIN sections c ON c.id=t.section_id
               JOIN subjects s ON s.id=t.subject_id JOIN faculty f ON f.id=t.faculty_id
               WHERE t.active=1 AND t.weekday=? AND t.valid_from<=? AND t.valid_to>=?
               AND EXISTS (SELECT 1 FROM students roster
                   WHERE roster.active=1 AND roster.department_id=t.department_id
                   AND roster.section_id=t.section_id AND roster.semester=t.semester
                   AND date(roster.enrolled_at)<=?)"""
        params: list[object] = [day.weekday(), day_text, day_text, day_text]
        if active_after is not None and active_after.date() == day:
            query += " AND t.start_time<=? AND t.end_time>?"
            current_time = active_after.time().strftime("%H:%M:%S")
            params.extend([current_time, current_time])
        rows = db.execute(query, params).fetchall()
    count = 0
    for row in rows:
        context = ClassContext(
            department=row["department"], section=row["section"], period=row["period"],
            starts_at=datetime.fromisoformat(day_text + "T" + row["start_time"]),
            ends_at=datetime.fromisoformat(day_text + "T" + row["end_time"]),
            semester=row["semester"], timetable_id=row["id"], subject=row["subject"],
            subject_code=row["subject_code"], faculty=row["faculty"], subject_id=row["subject_id"],
            faculty_id=row["faculty_id"], source="scheduled",
        )
        start_class(context, allow_finalized=True)
        count += 1
    return count


def sync_csv(day: date, department: str, base_dir: Path | None = None) -> Path:
    base = Path(base_dir or ROOT / "dataset" / "college_faces")
    reports = base / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    destination = reports / f"{department}_{day.isoformat()}_attendance.csv"
    with connect() as db:
        rows = db.execute(
            """SELECT cs.date,s.roll roll_number,s.name,c.name section,cs.semester,cs.period,
               COALESCE(sub.name,cs.period) subject,COALESCE(sub.code,'') subject_code,
               COALESCE(f.name,'') faculty,cs.starts_at class_start,cs.ends_at class_end,
               a.first_seen sign_in_time,a.last_seen,
               ROUND(a.presence_seconds,1) presence_duration,a.status
               FROM attendance a JOIN class_sessions cs ON cs.id=a.session_id
               JOIN students s ON s.id=a.student_id JOIN departments d ON d.id=cs.department_id
               JOIN sections c ON c.id=cs.section_id LEFT JOIN subjects sub ON sub.id=cs.subject_id
               LEFT JOIN faculty f ON f.id=cs.faculty_id WHERE cs.date=? AND d.name=?
               ORDER BY cs.starts_at,cs.period,c.name,s.roll""",
            (day.isoformat(), department),
        ).fetchall()
    fields = ["date", "roll_number", "name", "section", "semester", "period", "subject", "subject_code",
              "faculty", "class_start", "class_end", "sign_in_time", "last_seen", "presence_duration", "status"]
    temporary = destination.with_suffix(".pending.csv")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)
    temporary.replace(destination)
    return destination


def refresh_report(day: date, department: str, base_dir: Path | None = None) -> Path | None:
    """Refresh a legacy-compatible CSV only when database attendance exists."""
    initialize()
    with connect() as db:
        count = db.execute(
            """SELECT COUNT(*) FROM attendance a JOIN class_sessions cs ON cs.id=a.session_id
               JOIN departments d ON d.id=cs.department_id WHERE cs.date=? AND d.name=?""",
            (day.isoformat(), department),
        ).fetchone()[0]
    if count:
        return sync_csv(day, department, base_dir)
    candidate = Path(base_dir or ROOT / "dataset" / "college_faces") / "reports" / f"{department}_{day.isoformat()}_attendance.csv"
    return candidate if candidate.exists() else None


def session_rows(session_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            """SELECT s.roll,s.name,a.first_seen,a.last_seen,ROUND(a.presence_seconds,1) presence_seconds,
               a.status,a.confidence FROM attendance a JOIN students s ON s.id=a.student_id
               WHERE a.session_id=? ORDER BY s.roll""",
            (int(session_id),),
        ).fetchall()
        return [dict(row) for row in rows]
