"""Interpretable low-attendance prediction from real attendance history."""
from __future__ import annotations

import json
import math

import numpy as np

from smart_attendance.database.db import connect, initialize
from smart_attendance.utils.security import AccessDenied, actor


ATTENDED = {"PRESENT", "LATE"}
MISSED = {"ABSENT", "INCOMPLETE"}
ELIGIBLE = ATTENDED | MISSED
FEATURE_NAMES = (
    "current attendance", "recent absence rate", "consecutive absences",
    "late frequency", "recent attendance trend",
)


def _features(history: list[str]) -> np.ndarray:
    attended = np.array([1.0 if status in ATTENDED else 0.0 for status in history])
    recent = attended[-5:]
    previous = attended[-10:-5]
    consecutive = 0
    for status in reversed(history):
        if status not in MISSED:
            break
        consecutive += 1
    return np.array([
        100.0 * attended.mean(),
        1.0 - recent.mean(),
        float(consecutive),
        sum(status == "LATE" for status in history) / len(history),
        recent.mean() - (previous.mean() if len(previous) else attended.mean()),
    ], dtype=float)


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-9] = 1.0
    normalized = (x - mean) / scale
    design = np.column_stack([np.ones(len(normalized)), normalized])
    weights = np.zeros(design.shape[1], dtype=float)
    for _ in range(1800):
        logits = np.clip(design @ weights, -30, 30)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        gradient = design.T @ (probabilities - y) / len(y)
        gradient[1:] += 0.01 * weights[1:]
        weights -= 0.05 * gradient
    return weights, mean, scale


def _probability(features: np.ndarray, model) -> float:
    weights, mean, scale = model
    vector = np.r_[1.0, (features - mean) / scale]
    return float(1.0 / (1.0 + math.exp(-float(np.clip(vector @ weights, -30, 30)))))


def _reason(values: np.ndarray, threshold: float) -> str:
    current, recent_absence, consecutive, late_frequency, trend = values
    reasons = []
    if current < threshold:
        reasons.append(f"current attendance is below {threshold:.0f}%")
    if recent_absence >= 0.4:
        reasons.append("multiple recent missed classes")
    if consecutive >= 2:
        reasons.append(f"{int(consecutive)} consecutive missed classes")
    if late_frequency >= 0.25:
        reasons.append("frequent late arrivals")
    if trend <= -0.2:
        reasons.append("recent attendance is declining")
    return "; ".join(reasons[:3]) or "attendance history is currently stable"


def _scoped_rows(db, current) -> list:
    sql = """SELECT s.id student_id,s.roll,s.name,d.name department,se.name section,
             cs.date,COALESCE(cs.starts_at,cs.date || 'T00:00:00') occurred_at,
             COALESCE(a.status,'ABSENT') status
             FROM class_sessions cs JOIN students s
               ON s.department_id=cs.department_id AND s.section_id=cs.section_id
              AND s.semester=cs.semester AND date(s.enrolled_at)<=cs.date
             LEFT JOIN attendance a ON a.session_id=cs.id AND a.student_id=s.id
             JOIN departments d ON d.id=s.department_id JOIN sections se ON se.id=s.section_id
             WHERE s.active=1 AND cs.finalized=1
               AND COALESCE(a.status,'ABSENT') IN ('PRESENT','LATE','ABSENT','INCOMPLETE')"""
    params: list[object] = []
    if current["role"] == "HOD":
        sql += " AND s.department_id=?"
        params.append(current["department_id"])
    elif current["role"] == "FACULTY":
        sql += " AND EXISTS(SELECT 1 FROM timetables t JOIN faculty f ON f.id=t.faculty_id WHERE f.user_id=? AND t.department_id=s.department_id AND t.section_id=s.section_id AND t.semester=s.semester AND t.active=1)"
        params.append(current["id"])
    sql += " ORDER BY s.id,occurred_at,cs.period"
    return db.execute(sql, params).fetchall()


def _scoped_students(db, current) -> list:
    sql = """SELECT s.id student_id,s.roll,s.name,d.name department,se.name section
             FROM students s JOIN departments d ON d.id=s.department_id
             JOIN sections se ON se.id=s.section_id WHERE s.active=1"""
    params: list[object] = []
    if current["role"] == "HOD":
        sql += " AND s.department_id=?"
        params.append(current["department_id"])
    elif current["role"] == "FACULTY":
        sql += " AND EXISTS(SELECT 1 FROM timetables t JOIN faculty f ON f.id=t.faculty_id WHERE f.user_id=? AND t.department_id=s.department_id AND t.section_id=s.section_id AND t.semester=s.semester AND t.active=1)"
        params.append(current["id"])
    sql += " ORDER BY d.name,se.name,s.roll"
    return db.execute(sql, params).fetchall()


def _current_indicator(values: np.ndarray, history_size: int, threshold: float) -> tuple[str, str]:
    if history_size == 0:
        return "INSUFFICIENT DATA", "No eligible attendance records"
    current, recent_absence, consecutive, late_frequency, trend = values
    if current < threshold or consecutive >= 2 or recent_absence >= 0.6:
        level = "HIGH"
    elif current < threshold + 10 or recent_absence >= 0.2 or late_frequency >= 0.25 or trend <= -0.2:
        level = "MEDIUM"
    else:
        level = "LOW"
    reason = _reason(values, threshold)
    if history_size < 5:
        reason = f"{reason}; limited history ({history_size}/5 records)"
    return level, reason


def predict(token: str) -> dict:
    """Train on temporal snapshots and predict current student risk when valid."""
    initialize()
    with connect() as db:
        current = actor(db, token, ["ADMIN", "FACULTY", "HOD"])
        threshold_row = db.execute("SELECT value FROM settings WHERE key='minimum_percentage'").fetchone()
        threshold = float(json.loads(threshold_row[0])) if threshold_row else 75.0
        raw = _scoped_rows(db, current)
        roster = _scoped_students(db, current)

    students: dict[int, dict] = {
        row["student_id"]: {
            "student_id": row["student_id"], "roll": row["roll"], "name": row["name"],
            "department": row["department"], "section": row["section"], "history": [],
        }
        for row in roster
    }
    for row in raw:
        item = students.setdefault(row["student_id"], {
            "student_id": row["student_id"], "roll": row["roll"], "name": row["name"],
            "department": row["department"], "section": row["section"], "history": [],
        })
        item["history"].append(row["status"])

    training_x, training_y = [], []
    for item in students.values():
        history = item["history"]
        for cutoff in range(5, len(history) - 2):
            future = history[cutoff:cutoff + 3]
            training_x.append(_features(history[:cutoff]))
            future_percentage = 100.0 * sum(status in ATTENDED for status in future) / len(future)
            training_y.append(1.0 if future_percentage < threshold else 0.0)

    current_rows = []
    for item in students.values():
        history = item.pop("history")
        values = _features(history) if history else np.zeros(5)
        indicator, observed_reason = _current_indicator(values, len(history), threshold)
        current_rows.append({
            **item, "classes": len(history), "current_attendance": round(float(values[0]), 1),
            "risk_probability": None, "risk": "Insufficient data", "reason": "Fewer than 5 eligible attendance records"
            if len(history) < 5 else "A valid prediction model is not available yet",
            "current_indicator": indicator, "observed_reason": observed_reason,
            "_features": values,
        })

    labels = np.array(training_y, dtype=float)
    sufficient = len(training_x) >= 30 and len(set(training_y)) == 2 and min(np.bincount(labels.astype(int))) >= 5
    class_counts = {
        "below_threshold": int(sum(training_y)),
        "at_or_above_threshold": int(len(training_y) - sum(training_y)),
    }
    readiness = {
        "eligible_records": len(raw),
        "eligible_periods": len(raw),
        "students": len(students),
        "students_with_5_records": sum(row["classes"] >= 5 for row in current_rows),
        "required_training_windows": 30,
        "class_counts": class_counts,
    }
    if not sufficient:
        for row in current_rows:
            row.pop("_features", None)
        return {
            "status": "insufficient", "message": "Insufficient data for prediction",
            "training_samples": len(training_x), "threshold": threshold, "rows": current_rows,
            "readiness": readiness,
        }

    x = np.vstack(training_x)
    model = _fit_logistic(x, labels)
    probabilities = np.array([_probability(row, model) for row in x])
    accuracy = float(((probabilities >= 0.5) == labels).mean())
    for row in current_rows:
        if row["classes"] >= 5:
            probability = _probability(row["_features"], model)
            row["risk_probability"] = round(probability * 100.0, 1)
            row["risk"] = "HIGH" if probability >= 0.65 else "MEDIUM" if probability >= 0.35 else "LOW"
            row["reason"] = _reason(row["_features"], threshold)
        row.pop("_features", None)
    return {
        "status": "ready", "message": "Logistic Regression trained on historical attendance windows",
        "training_samples": len(training_x), "training_accuracy": round(accuracy, 3),
        "threshold": threshold, "features": FEATURE_NAMES, "rows": current_rows,
        "readiness": readiness,
    }
