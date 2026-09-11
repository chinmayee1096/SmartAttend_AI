import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime, time


class TimetableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("SMARTATTEND_DB")
        os.environ["SMARTATTEND_DB"] = str(Path(self.temp.name) / "test.sqlite3")
        from smart_attendance.database.db import initialize
        initialize()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SMARTATTEND_DB", None)
        else:
            os.environ["SMARTATTEND_DB"] = self.old
        self.temp.cleanup()

    def test_resolves_current_subject_and_rejects_overlap(self):
        from smart_attendance.services import timetable_runtime as service
        service.add_subject("ML101", "Machine Learning")
        catalogue = service.list_catalogue()
        department = next(row for row in catalogue["departments"] if row["name"] == "AIML")
        section = next(row for row in catalogue["sections"] if row["name"] == "A")
        service.add_faculty("Dr Faculty", department["id"])
        catalogue = service.list_catalogue()
        service.add_entry(
            department["id"], section["id"], 1, catalogue["subjects"][0]["id"],
            catalogue["faculty"][0]["id"], 1, time(9, 30), time(10, 30), "AI Lab", "P1",
            date(2026, 1, 1), date(2026, 12, 31),
        )
        current = service.current_classes(datetime(2026, 9, 8, 9, 45))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].subject, "Machine Learning")
        from smart_attendance.views.timetable_legacy import _weekly_grid
        with patch("smart_attendance.views.timetable_legacy.st.markdown") as markdown:
            _weekly_grid(service.entries(), "AIML · SECTION A · SEMESTER 1", datetime(2026, 9, 8, 9, 45))
        rendered = markdown.call_args.args[0]
        self.assertIn("sa-current", rendered)
        self.assertIn("LIVE NOW", rendered)
        from smart_attendance.services.attendance_service import materialize_scheduled
        # An active timetable with no enrolled roster must not crash startup.
        self.assertEqual(
            materialize_scheduled(date(2026, 9, 8), active_after=datetime(2026, 9, 8, 9, 45)),
            0,
        )
        from smart_attendance.services.attendance_service import start_class
        with self.assertRaisesRegex(ValueError, "No active students"):
            start_class(current[0])
        self.assertEqual(
            materialize_scheduled(date(2026, 9, 8), active_after=datetime(2026, 9, 8, 10, 31)),
            0,
        )
        with self.assertRaises(ValueError):
            service.add_entry(
                department["id"], section["id"], 1, catalogue["subjects"][0]["id"],
                catalogue["faculty"][0]["id"], 1, time(10), time(11), "AI Lab", "P2",
                date(2026, 1, 1), date(2026, 12, 31),
            )

    def test_fallback_uses_selected_semester_and_half_open_period_boundaries(self):
        from smart_attendance.services import timetable_runtime as service
        from smart_attendance.database.db import connect
        with connect() as db:
            department = db.execute("SELECT id FROM departments WHERE name='AIML'").fetchone()[0]
            section = db.execute("SELECT id FROM sections WHERE name='A'").fetchone()[0]
            db.execute(
                "INSERT INTO students(roll,name,department_id,section_id,semester,enrolled_at) "
                "VALUES ('5','Semester Five',?,?,5,'2026-01-01')",
                (department, section),
            )
        self.assertEqual(service.student_semesters("AIML", "A"), [5])
        schedule = [("P1", time(8, 30), time(9, 30)), ("P2", time(9, 30), time(10, 30))]
        context = service.fallback_context(
            "AIML", "A", schedule, datetime(2026, 9, 8, 9, 30), semester=5
        )
        self.assertEqual(context.period, "P2")
        self.assertEqual(context.semester, 5)


if __name__ == "__main__":
    unittest.main()
