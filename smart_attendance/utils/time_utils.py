"""One institutional clock for local and hosted attendance processing."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Kolkata"


def system_now() -> datetime:
    """Return the configured institutional time as a naive local datetime.

    Existing SQLite and CSV records use naive ISO timestamps. Keeping that
    representation avoids a destructive migration while preventing a hosted
    server's UTC clock from selecting the wrong classroom period.
    """
    timezone_name = os.environ.get("SMARTATTEND_TIMEZONE", DEFAULT_TIMEZONE).strip()
    try:
        return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)
    except ZoneInfoNotFoundError:
        return datetime.now()


def system_today() -> date:
    return system_now().date()
