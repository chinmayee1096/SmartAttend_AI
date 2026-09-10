from datetime import datetime, timezone

from smart_attendance.utils.time_utils import system_now


def test_default_institutional_clock_is_india_time(monkeypatch):
    monkeypatch.delenv("SMARTATTEND_TIMEZONE", raising=False)
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    offset_hours = (system_now() - utc_now).total_seconds() / 3600
    assert 5.49 <= offset_hours <= 5.51
