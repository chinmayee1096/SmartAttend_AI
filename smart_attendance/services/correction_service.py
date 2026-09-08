"""Faculty attendance corrections with service-level authorization."""
from __future__ import annotations

from datetime import date

from smart_attendance.database.db import connect, initialize
from smart_attendance.services.attendance_service import sync_csv
from smart_attendance.utils.security import AccessDenied, actor, audit


STATUSES = ("PRESENT", "LATE", "ABSENT", "INCOMPLETE", "EXCUSED")


def _scope(current) -> tuple[str, list[object]]:
    if current["role"] == "ADMIN":
        return "", []
    if current["role"] == "FACULTY":
        return " AND f.user_id=?", [current["id"]]
    raise AccessDenied("Only an administrator or assigned faculty member can correct attendance.")


def records(token: str, limit: int = 500) -> list[dict]:
    initialize()
    with connect() as db:
        current = actor(db, token, ["ADMIN", "FACULTY"])
        clause, params = _scope(current)
        rows = db.execute(
            """SELECT a.id attendance_id,cs.date,cs.period,COALESCE(sub.code,'') subject_code,
               COALESCE(sub.name,cs.period) subject,s.roll,s.name,d.name department,se.name section,
               a.status,a.first_seen,a.last_seen,COALESCE(f.name,'') faculty
               FROM attendance a JOIN class_sessions cs ON cs.id=a.session_id
               JOIN students s ON s.id=a.student_id JOIN departments d ON d.id=cs.department_id
               JOIN sections se ON se.id=cs.section_id LEFT JOIN subjects sub ON sub.id=cs.subject_id
               LEFT JOIN faculty f ON f.id=cs.faculty_id WHERE 1=1""" + clause +
            " ORDER BY cs.date DESC,cs.starts_at DESC,s.roll LIMIT ?",
            [*params, max(1, min(int(limit), 2000))],
        ).fetchall()
        return [dict(row) for row in rows]


def correct(token: str, attendance_id: int, new_status: str, reason: str, base_dir=None) -> int:
    new_status = new_status.strip().upper()
    reason = reason.strip()
    if new_status not in STATUSES:
        raise ValueError("Select a valid attendance status.")
    if len(reason) < 5 or len(reason) > 500:
        raise ValueError("Correction reason must contain 5–500 characters.")
    initialize()
    with connect() as db:
        current = actor(db, token, ["ADMIN", "FACULTY"])
        clause, params = _scope(current)
        row = db.execute(
            """SELECT a.*,cs.date,cs.period,s.roll,d.name department
               FROM attendance a JOIN class_sessions cs ON cs.id=a.session_id
               JOIN students s ON s.id=a.student_id JOIN departments d ON d.id=cs.department_id
               LEFT JOIN faculty f ON f.id=cs.faculty_id WHERE a.id=?""" + clause,
            [int(attendance_id), *params],
        ).fetchone()
        if row is None:
            raise AccessDenied("This attendance record is outside your assigned classes.")
        original = row["status"]
        if original == new_status:
            raise ValueError("Choose a status different from the recorded status.")
        correction_id = db.execute(
            """INSERT INTO attendance_corrections(
               attendance_id,requester,original_status,requested_status,reason,reviewer,
               decision,review_reason,reviewed_at
               ) VALUES (?,?,?,?,?,?,'APPROVED',?,CURRENT_TIMESTAMP)""",
            (row["id"], current["id"], original, new_status, reason, current["id"], reason),
        ).lastrowid
        db.execute("UPDATE attendance SET status=?,source='corrected' WHERE id=?", (new_status, row["id"]))
        audit(
            db, current, "ATTENDANCE CORRECTED", f"attendance:{row['id']}",
            {"roll": row["roll"], "department": row["department"], "date": row["date"],
             "period": row["period"], "original_status": original, "new_status": new_status,
             "reason": reason},
        )
        result = int(correction_id)
        report_day = date.fromisoformat(row["date"])
        report_department = row["department"]
    sync_csv(report_day, report_department, base_dir)
    return result


def history(token: str) -> list[dict]:
    initialize()
    with connect() as db:
        current = actor(db, token, ["ADMIN", "FACULTY"])
        clause, params = _scope(current)
        rows = db.execute(
            """SELECT ac.id,cs.date,s.roll,s.name,ac.original_status,ac.requested_status new_status,
               ac.reason,u.username corrected_by,ac.reviewed_at timestamp
               FROM attendance_corrections ac JOIN attendance a ON a.id=ac.attendance_id
               JOIN class_sessions cs ON cs.id=a.session_id JOIN students s ON s.id=a.student_id
               JOIN users u ON u.id=ac.reviewer LEFT JOIN faculty f ON f.id=cs.faculty_id
               WHERE ac.decision='APPROVED'""" + clause + " ORDER BY ac.reviewed_at DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
