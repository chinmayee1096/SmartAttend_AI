import unittest
from pathlib import Path
import os
import tempfile

from streamlit.testing.v1 import AppTest


class StreamlitSmokeTests(unittest.TestCase):
    def test_every_workspace_page_renders_without_exception(self):
        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        app = AppTest.from_file(str(app_path), default_timeout=20).run()
        self.assertFalse(app.exception)

        for page in (
            "🎓 Training",
            "🗓 Timetable",
            "📈 Risk Analysis",
            "✏️ Corrections",
            "🛡 Audit Logs",
            "📧 Email Alerts",
            "🔐 Staff Access",
        ):
            app.sidebar.radio[0].set_value(page).run()
            self.assertFalse(app.exception, page)

    def test_authenticated_risk_page_renders_real_readiness_data(self):
        old_db = os.environ.get("SMARTATTEND_DB")
        with tempfile.TemporaryDirectory() as temp:
            os.environ["SMARTATTEND_DB"] = str(Path(temp) / "risk-ui.sqlite3")
            try:
                from smart_attendance.database.db import connect, initialize
                from smart_attendance.utils.security import login, setup_admin

                initialize()
                setup_admin("admin", "SecureAdminPassword1!")
                token = login("admin", "SecureAdminPassword1!")
                with connect() as db:
                    department = db.execute("SELECT id FROM departments WHERE name='AIML'").fetchone()[0]
                    section = db.execute("SELECT id FROM sections WHERE name='A'").fetchone()[0]
                    db.execute(
                        "INSERT INTO students(roll,name,department_id,section_id,semester,enrolled_at) VALUES ('1','Student One',?,?,5,'2026-01-01')",
                        (department, section),
                    )

                app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20)
                app.session_state["staff_token"] = token
                app.run()
                app.sidebar.radio[0].set_value("📈 Risk Analysis").run()
                self.assertFalse(app.exception)
                self.assertTrue(any("Insufficient data for prediction" in item.value for item in app.info))
                self.assertEqual(len(app.dataframe), 1)
            finally:
                if old_db is None:
                    os.environ.pop("SMARTATTEND_DB", None)
                else:
                    os.environ["SMARTATTEND_DB"] = old_db


if __name__ == "__main__":
    unittest.main()
