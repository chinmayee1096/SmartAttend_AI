"""Local challenge-response liveness checks for webcam attendance.

The default provider requires an open/closed/open eye transition plus natural
frame variation. It is intentionally isolated so a trained anti-spoof model can
replace it later without changing attendance logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time

import cv2
import numpy as np


class LivenessStatus(str, Enum):
    VERIFYING = "VERIFYING..."
    LIVE = "LIVE"
    SPOOF = "SPOOF DETECTED"


@dataclass
class LivenessResult:
    status: LivenessStatus
    prompt: str
    score: float = 0.0


@dataclass
class _Track:
    created_at: float
    last_seen: float
    previous: np.ndarray | None = None
    saw_open: bool = False
    saw_closed_after_open: bool = False
    blink_count: int = 0
    motion_samples: int = 0
    quality_samples: int = 0
    frames: int = 0
    status: LivenessStatus = LivenessStatus.VERIFYING


class BlinkChallengeProvider:
    """Active blink challenge backed by Haar eyes and temporal motion checks."""

    def __init__(self, timeout_seconds: float = 12.0, minimum_motion_samples: int = 3):
        self.timeout_seconds = float(timeout_seconds)
        self.minimum_motion_samples = int(minimum_motion_samples)
        self._tracks: dict[int, _Track] = {}
        self._eye_detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml"
        )
        if self._eye_detector.empty():
            raise RuntimeError("OpenCV eye detector is unavailable.")

    def update(self, track_id: int, face_gray: np.ndarray, now: float | None = None) -> LivenessResult:
        now = time.monotonic() if now is None else float(now)
        track = self._tracks.setdefault(track_id, _Track(now, now))
        track.last_seen = now
        track.frames += 1

        if face_gray is None or face_gray.size == 0:
            return LivenessResult(LivenessStatus.VERIFYING, "Keep your face inside the frame")

        face = cv2.resize(face_gray, (160, 160))
        brightness = float(face.mean())
        sharpness = float(cv2.Laplacian(face, cv2.CV_64F).var())
        quality_ok = 25.0 <= brightness <= 230.0 and sharpness >= 35.0
        if quality_ok:
            track.quality_samples += 1

        if track.previous is not None:
            difference = float(cv2.absdiff(face, track.previous).mean())
            if 1.0 <= difference <= 45.0:
                track.motion_samples += 1
        track.previous = face

        upper = face[:105]
        eyes = self._eye_detector.detectMultiScale(
            upper, scaleFactor=1.1, minNeighbors=5, minSize=(16, 16)
        )
        eyes_open = len(eyes) >= 1
        if eyes_open:
            if track.saw_closed_after_open:
                track.blink_count += 1
                track.saw_closed_after_open = False
            track.saw_open = True
        elif track.saw_open:
            track.saw_closed_after_open = True

        quality_ratio = track.quality_samples / max(track.frames, 1)
        enough_motion = track.motion_samples >= self.minimum_motion_samples
        if track.blink_count >= 1 and enough_motion and quality_ratio >= 0.55:
            track.status = LivenessStatus.LIVE
            return LivenessResult(track.status, "Liveness verified", min(1.0, 0.65 + quality_ratio * 0.35))

        if now - track.created_at >= self.timeout_seconds:
            track.status = LivenessStatus.SPOOF
            reason = "Blink challenge not completed"
            if quality_ratio < 0.55:
                reason = "Face quality too low for liveness verification"
            return LivenessResult(track.status, reason, 0.0)

        prompt = "Blink once naturally"
        if track.saw_closed_after_open:
            prompt = "Open your eyes"
        elif track.blink_count and not enough_motion:
            prompt = "Move naturally and face the camera"
        return LivenessResult(LivenessStatus.VERIFYING, prompt, min(0.6, quality_ratio * 0.4))

    def expire(self, active_track_ids: set[int], now: float | None = None, max_age: float = 3.0) -> None:
        now = time.monotonic() if now is None else float(now)
        for track_id, track in list(self._tracks.items()):
            if track_id not in active_track_ids and now - track.last_seen > max_age:
                del self._tracks[track_id]

    def reset(self) -> None:
        self._tracks.clear()


class FaceTracker:
    """Associates liveness history with moving face boxes without using identity."""

    def __init__(self, maximum_distance: float = 110.0, max_age_seconds: float = 2.0):
        self.maximum_distance = maximum_distance
        self.max_age_seconds = max_age_seconds
        self._next = 1
        self._tracks: dict[int, tuple[float, float, float]] = {}

    def assign(self, boxes: list[tuple[int, int, int, int]], now: float | None = None) -> list[int]:
        now = time.monotonic() if now is None else float(now)
        self._tracks = {key: value for key, value in self._tracks.items() if now - value[2] <= self.max_age_seconds}
        available = set(self._tracks)
        assigned: list[int] = []
        for x, y, width, height in boxes:
            center = (x + width / 2.0, y + height / 2.0)
            nearest = None
            nearest_distance = self.maximum_distance
            for key in available:
                old_x, old_y, _ = self._tracks[key]
                distance = ((center[0] - old_x) ** 2 + (center[1] - old_y) ** 2) ** 0.5
                if distance < nearest_distance:
                    nearest, nearest_distance = key, distance
            if nearest is None:
                nearest = self._next
                self._next += 1
            else:
                available.remove(nearest)
            self._tracks[nearest] = (center[0], center[1], now)
            assigned.append(nearest)
        return assigned
