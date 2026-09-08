import os
from pathlib import Path
import tempfile
import unittest


class CorrectionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("SMARTATTEND_DB")
        os.environ["SMARTATTEND_DB"] = str(Path(self.temp.name) / "test.sqlite3")
        from smart_attendance.database.db import initialize, connect
        from smart_attendance.utils.security import setup_admin, login
        from smart_attendance.services.admin_service import create_user
        initialize()
        setup_admin("admin", "SecureAdminPassword1!")
        self.admin_token = login("admin", "SecureAdminPassword1!")
        with connect() as db:
            department = db.execute("SELECT id FROM departments WHERE name='AIML'").fetchone()[0]
            section = db.execute("SELECT id FROM sections WHERE name='A'").fetchone()[0]
            student = db.execute(
                "INSERT INTO students(roll,name,department_id,section_id,semester,enrolled_at) VALUES ('1','One',?,?,5,'2026-01-01')",
                (department, section),
            ).lastrowid
            subject = db.execute("INSERT INTO subjects(code,name) VALUES ('ML101','Machine Learning')").lastrowid
            faculty = db.execute("INSERT INTO faculty(name,department_id) VALUES ('Dr Faculty',?)", (department,)).lastrowid
            session = db.execute(
                """INSERT INTO class_sessions(date,period,department_id,section_id,subject_id,faculty_id,semester,starts_at,ends_at,finalized)
                   VALUES ('2026-09-01','P1',?,?,?,?,5,'2026-09-01T09:00:00','2026-09-01T10:00:00',1)""",
                (department, section, subject, faculty),
            ).lastrowid
            self.attendance_id = db.execute(
                "INSERT INTO attendance(session_id,student_id,status) VALUES (?,?,'ABSENT')", (session, student)
            ).lastrowid
        create_user(self.admin_token, "faculty", "SecureFacultyPass1!", "FACULTY", department, faculty_id=faculty)
        create_user(self.admin_token, "student", "SecureStudentPass1!", "STUDENT", department, student_id=student)
        self.faculty_token = login("faculty", "SecureFacultyPass1!")
        self.student_token = login("student", "SecureStudentPass1!")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SMARTATTEND_DB", None)
        else:
            os.environ["SMARTATTEND_DB"] = self.old
        self.temp.cleanup()

    def test_assigned_faculty_correction_and_audit(self):
        from smart_attendance.services import correction_service, audit_service
        records = correction_service.records(self.faculty_token)
        self.assertEqual([row["attendance_id"] for row in records], [self.attendance_id])
        correction_service.correct(
            self.faculty_token, self.attendance_id, "PRESENT", "Verified against the signed class register.",
            Path(self.temp.name),
        )
        from smart_attendance.database.db import connect
        with connect() as db:
            status = db.execute("SELECT status FROM attendance WHERE id=?", (self.attendance_id,)).fetchone()[0]
            correction = db.execute("SELECT * FROM attendance_corrections").fetchone()
        self.assertEqual(status, "PRESENT")
        self.assertEqual(correction["original_status"], "ABSENT")
        self.assertEqual(correction["requested_status"], "PRESENT")
        logs = audit_service.query(self.admin_token, action="ATTENDANCE CORRECTED")
        self.assertEqual(len(logs), 1)
        self.assertNotIn("password", logs[0]["details"].lower())

    def test_student_cannot_correct_attendance(self):
        from smart_attendance.services import correction_service
        from smart_attendance.utils.security import AccessDenied
        with self.assertRaises(AccessDenied):
            correction_service.correct(
                self.student_token, self.attendance_id, "PRESENT", "Unauthorized change attempt.",
                Path(self.temp.name),
            )

    def test_reason_is_required(self):
        from smart_attendance.services import correction_service
        with self.assertRaises(ValueError):
            correction_service.correct(
                self.faculty_token, self.attendance_id, "PRESENT", "",
                Path(self.temp.name),
            )


if __name__ == "__main__":
    unittest.main()
