import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta
import csv

from smart_attendance.services.timetable_runtime import ClassContext


class AttendanceEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("SMARTATTEND_DB")
        os.environ["SMARTATTEND_DB"] = str(Path(self.temp.name) / "test.sqlite3")
        from smart_attendance.database.db import initialize, connect
        initialize()
        with connect() as db:
            department = db.execute("SELECT id FROM departments WHERE name='AIML'").fetchone()[0]
            section = db.execute("SELECT id FROM sections WHERE name='A'").fetchone()[0]
            db.execute("INSERT INTO students(roll,name,department_id,section_id,enrolled_at) VALUES ('1','One',?,?,?)", (department, section, "2026-01-01"))
            db.execute("INSERT INTO students(roll,name,department_id,section_id,enrolled_at) VALUES ('2','Two',?,?,?)", (department, section, "2026-01-01"))
            db.execute("INSERT INTO settings VALUES ('presence_ratio','0.5')")
            db.execute("INSERT INTO settings VALUES ('observation_gap_seconds','120')")
        start = datetime(2026, 9, 8, 9, 0)
        self.context = ClassContext("AIML", "A", "P1", start, start + timedelta(minutes=10), subject="ML")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SMARTATTEND_DB", None)
        else:
            os.environ["SMARTATTEND_DB"] = self.old
        self.temp.cleanup()

    def test_duplicate_observations_accumulate_one_record(self):
        from smart_attendance.services.attendance_service import record_observation
        for minute in (0, 2, 4, 6):
            record_observation(self.context, "1", 25, True, self.context.starts_at + timedelta(minutes=minute), Path(self.temp.name))
        from smart_attendance.database.db import connect
        with connect() as db:
            rows = db.execute("SELECT * FROM attendance WHERE first_seen IS NOT NULL").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "PRESENT")

    def test_rejected_liveness_is_not_recorded(self):
        from smart_attendance.services.attendance_service import record_observation
        self.assertEqual(
            record_observation(self.context, "1", 25, False, self.context.starts_at),
            "VERIFYING",
        )
        from smart_attendance.database.db import connect
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM attendance").fetchone()[0], 0)

    def test_finalization_marks_absent_and_incomplete(self):
        from smart_attendance.services.attendance_service import start_class, record_observation, finalize_due
        start_class(self.context)
        record_observation(self.context, "1", 20, True, self.context.starts_at, Path(self.temp.name))
        finalize_due(self.context.ends_at + timedelta(seconds=1), Path(self.temp.name))
        from smart_attendance.database.db import connect
        with connect() as db:
            statuses = {r["roll"]: r["status"] for r in db.execute("SELECT s.roll,a.status FROM attendance a JOIN students s ON s.id=a.student_id")}
        self.assertEqual(statuses, {"1": "INCOMPLETE", "2": "ABSENT"})

    def test_finalized_class_is_safe_for_catch_up_but_not_reopened(self):
        from smart_attendance.services.attendance_service import start_class, finalize_due
        session_id = start_class(self.context)
        finalize_due(self.context.ends_at + timedelta(seconds=1), Path(self.temp.name))
        with self.assertRaises(ValueError):
            start_class(self.context)
        self.assertEqual(start_class(self.context, allow_finalized=True), session_id)
        from smart_attendance.database.db import connect
        with connect() as db:
            session = db.execute("SELECT finalized FROM class_sessions WHERE id=?", (session_id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM attendance WHERE session_id=?", (session_id,)).fetchone()[0]
        self.assertEqual(session["finalized"], 1)
        self.assertEqual(count, 2)

    def test_consecutive_periods_keep_separate_complete_rosters_and_report_rows(self):
        from smart_attendance.services.attendance_service import finalize_due, record_observation, start_class
        first = self.context
        second = ClassContext(
            "AIML", "A", "P2", first.ends_at, first.ends_at + timedelta(minutes=10), subject="DBMS"
        )
        for context in (first, second):
            start_class(context)
            for minute in (0, 2, 4, 6):
                record_observation(
                    context, "1", 20, True, context.starts_at + timedelta(minutes=minute), Path(self.temp.name)
                )
            finalize_due(context.ends_at + timedelta(seconds=1), Path(self.temp.name))

        from smart_attendance.database.db import connect
        with connect() as db:
            rows = db.execute(
                """SELECT cs.period,s.roll,a.status FROM attendance a
                   JOIN class_sessions cs ON cs.id=a.session_id JOIN students s ON s.id=a.student_id
                   ORDER BY cs.period,s.roll"""
            ).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(row["period"], row["roll"], row["status"]) for row in rows],
            [("P1", "1", "PRESENT"), ("P1", "2", "ABSENT"),
             ("P2", "1", "PRESENT"), ("P2", "2", "ABSENT")],
        )
        report = Path(self.temp.name) / "reports" / "AIML_2026-09-08_attendance.csv"
        with report.open(encoding="utf-8") as handle:
            exported = list(csv.DictReader(handle))
        self.assertEqual(len(exported), 4)
        self.assertEqual({row["period"] for row in exported}, {"P1", "P2"})
        self.assertEqual({row["status"] for row in exported}, {"PRESENT", "ABSENT"})

    def test_observation_after_period_end_is_rejected_and_finalized(self):
        from smart_attendance.services.attendance_service import record_observation, start_class
        start_class(self.context)
        result = record_observation(
            self.context, "1", 20, True, self.context.ends_at, Path(self.temp.name)
        )
        self.assertEqual(result, "CLASS ENDED")
        from smart_attendance.database.db import connect
        with connect() as db:
            finalized = db.execute("SELECT finalized FROM class_sessions").fetchone()[0]
            statuses = {row[0] for row in db.execute("SELECT status FROM attendance")}
        self.assertEqual(finalized, 1)
        self.assertEqual(statuses, {"ABSENT"})

    def test_unfinished_empty_session_is_repaired_before_roster_creation(self):
        from smart_attendance.database.db import connect
        with connect() as db:
            department = db.execute("SELECT id FROM departments WHERE name='AIML'").fetchone()[0]
            section = db.execute("SELECT id FROM sections WHERE name='A'").fetchone()[0]
            db.execute(
                """INSERT INTO class_sessions(date,period,department_id,section_id,semester,
                   starts_at,ends_at,source) VALUES ('2026-09-08','P1',?,?,5,?,?, 'fallback')""",
                (department, section, self.context.starts_at.isoformat(), self.context.ends_at.isoformat()),
            )
        from smart_attendance.services.attendance_service import start_class
        session_id = start_class(self.context)
        with connect() as db:
            session = db.execute("SELECT semester FROM class_sessions WHERE id=?", (session_id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM attendance WHERE session_id=?", (session_id,)).fetchone()[0]
        self.assertEqual(session["semester"], 1)
        self.assertEqual(count, 2)

    def test_finalized_period_repairs_a_missing_student_outcome_as_absent(self):
        from smart_attendance.services.attendance_service import complete_period_rosters, finalize_due, start_class
        session_id = start_class(self.context)
        finalize_due(self.context.ends_at + timedelta(seconds=1), Path(self.temp.name))
        from smart_attendance.database.db import connect
        with connect() as db:
            db.execute(
                "DELETE FROM attendance WHERE session_id=? AND student_id=(SELECT id FROM students WHERE roll='2')",
                (session_id,),
            )
        self.assertEqual(
            complete_period_rosters(self.context.ends_at + timedelta(seconds=2), Path(self.temp.name)),
            1,
        )
        with connect() as db:
            row = db.execute(
                """SELECT a.status FROM attendance a JOIN students s ON s.id=a.student_id
                   WHERE a.session_id=? AND s.roll='2'""",
                (session_id,),
            ).fetchone()
        self.assertEqual(row["status"], "ABSENT")


if __name__ == "__main__":
    unittest.main()
