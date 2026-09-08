"""Sanitized audit events and authorized audit-log queries."""
from __future__ import annotations

import json
from datetime import date

from smart_attendance.database.db import connect, initialize
from smart_attendance.utils.security import actor, audit


SENSITIVE_TERMS = ("password", "secret", "token", "embedding", "credential", "smtp", "api_key", "image")


def record_system(action: str, target: str = "", details: dict | None = None) -> None:
    """Record an application event without storing secrets or biometric data."""
    initialize()
    safe = {
        str(key): value for key, value in (details or {}).items()
        if not any(term in str(key).lower() for term in SENSITIVE_TERMS)
    }
    with connect() as db:
        db.execute(
            "INSERT INTO audit_logs(user_id,role,action,target,metadata) VALUES (NULL,'SYSTEM',?,?,?)",
            (action.strip().upper(), str(target), json.dumps(safe, default=str)),
        )


def query(token: str, user: str = "", action: str = "", day: date | None = None) -> list[dict]:
    """Return filtered logs to ADMIN/HOD, with HOD restricted to their department."""
    initialize()
    with connect() as db:
        current = actor(db, token, ["ADMIN", "HOD"])
        sql = """SELECT al.id,COALESCE(u.username,'System') user,COALESCE(al.role,'SYSTEM') role,
                 al.action,al.target,al.metadata details,al.created_at timestamp
                 FROM audit_logs al LEFT JOIN users u ON u.id=al.user_id WHERE 1=1"""
        params: list[object] = []
        if current["role"] == "HOD":
            sql += " AND (al.user_id=? OR json_extract(al.metadata,'$.department')=(SELECT name FROM departments WHERE id=?))"
            params.extend([current["id"], current["department_id"]])
        if user:
            sql += " AND COALESCE(u.username,'System')=?"
            params.append(user)
        if action:
            sql += " AND al.action=?"
            params.append(action)
        if day:
            sql += " AND date(al.created_at)=?"
            params.append(day.isoformat())
        sql += " ORDER BY al.created_at DESC,al.id DESC LIMIT 2000"
        return [dict(row) for row in db.execute(sql, params)]


def filter_options(token: str) -> dict[str, list[str]]:
    rows = query(token)
    return {
        "users": sorted({row["user"] for row in rows}),
        "actions": sorted({row["action"] for row in rows}),
    }
