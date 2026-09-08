import os
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest


class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("SMARTATTEND_DB")
        os.environ["SMARTATTEND_DB"] = str(Path(self.temp.name) / "test.sqlite3")
        from smart_attendance.database.db import initialize
        from smart_attendance.utils.security import setup_admin, login
        initialize()
        setup_admin("admin", "SecureAdminPassword1!")
        self.token = login("admin", "SecureAdminPassword1!")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SMARTATTEND_DB", None)
        else:
            os.environ["SMARTATTEND_DB"] = self.old
        self.temp.cleanup()

    def _seed(self, students, classes):
        from smart_attendance.database.db import connect
        with connect() as db:
            department = db.execute("SELECT id FROM departments WHERE name='AIML'").fetchone()[0]
            section = db.execute("SELECT id FROM sections WHERE name='A'").fetchone()[0]
            student_ids = []
            for index in range(students):
                student_ids.append(db.execute(
                    "INSERT INTO students(roll,name,department_id,section_id,semester,enrolled_at) VALUES (?,?,?, ?,5,'2026-01-01')",
                    (str(index + 1), f"Student {index + 1}", department, section),
                ).lastrowid)
            sessions = []
            start = date(2026, 1, 1)
            for index in range(classes):
                day = (start + timedelta(days=index)).isoformat()
                sessions.append(db.execute(
                    "INSERT INTO class_sessions(date,period,department_id,section_id,semester,finalized) VALUES (?,?,?,?,5,1)",
                    (day, f"P{index + 1}", department, section),
                ).lastrowid)
            for student_index, student_id in enumerate(student_ids):
                status = "PRESENT" if student_index < students // 2 else "ABSENT"
                for session_id in sessions:
                    db.execute("INSERT INTO attendance(session_id,student_id,status) VALUES (?,?,?)", (session_id, student_id, status))

    def test_insufficient_history_does_not_predict(self):
        self._seed(2, 4)
        from smart_attendance.services.prediction_service import predict
        result = predict(self.token)
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["message"], "Insufficient data for prediction")
        self.assertTrue(all(row["risk_probability"] is None for row in result["rows"]))
        self.assertEqual(result["readiness"]["eligible_records"], 8)
        self.assertTrue(all("current_indicator" in row for row in result["rows"]))

    def test_students_without_attendance_are_included(self):
        self._seed(2, 0)
        from smart_attendance.services.prediction_service import predict
        result = predict(self.token)
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(row["current_indicator"] == "INSUFFICIENT DATA" for row in result["rows"]))

    def test_missing_event_in_finalized_period_counts_as_absent_period(self):
        self._seed(2, 4)
        from smart_attendance.database.db import connect
        with connect() as db:
            missing_student = db.execute("SELECT id FROM students WHERE roll='2'").fetchone()[0]
            db.execute("DELETE FROM attendance WHERE student_id=?", (missing_student,))
        from smart_attendance.services.prediction_service import predict
        result = predict(self.token)
        student = next(row for row in result["rows"] if row["roll"] == "2")
        self.assertEqual(student["classes"], 4)
        self.assertEqual(student["current_attendance"], 0.0)
        self.assertEqual(student["current_indicator"], "HIGH")

    def test_logistic_prediction_uses_real_temporal_windows(self):
        self._seed(10, 12)
        from smart_attendance.services.prediction_service import predict
        result = predict(self.token)
        self.assertEqual(result["status"], "ready")
        self.assertGreaterEqual(result["training_samples"], 30)
        good = next(row for row in result["rows"] if row["roll"] == "1")
        poor = next(row for row in result["rows"] if row["roll"] == "10")
        self.assertLess(good["risk_probability"], poor["risk_probability"])
        self.assertEqual(good["risk"], "LOW")
        self.assertEqual(poor["risk"], "HIGH")


if __name__ == "__main__":
    unittest.main()
