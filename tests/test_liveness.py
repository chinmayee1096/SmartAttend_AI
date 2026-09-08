import unittest
from unittest.mock import patch

import numpy as np

from smart_attendance.services.liveness_service import BlinkChallengeProvider, FaceTracker, LivenessStatus


class _Eyes:
    def __init__(self, values):
        self.values = iter(values)

    def empty(self):
        return False

    def detectMultiScale(self, *args, **kwargs):
        return [(1, 1, 10, 10)] if next(self.values) else []


class LivenessTests(unittest.TestCase):
    @patch("smart_attendance.services.liveness_service.cv2.Laplacian")
    def test_open_closed_open_challenge_passes(self, laplacian):
        laplacian.return_value = np.array([0.0, 200.0])
        provider = BlinkChallengeProvider(timeout_seconds=12, minimum_motion_samples=1)
        provider._eye_detector = _Eyes([True, False, True])
        base = np.full((160, 160), 100, dtype=np.uint8)
        provider.update(1, base, now=0)
        provider.update(1, base + 3, now=1)
        result = provider.update(1, base + 5, now=2)
        self.assertEqual(result.status, LivenessStatus.LIVE)

    @patch("smart_attendance.services.liveness_service.cv2.Laplacian")
    def test_static_face_times_out_as_spoof(self, laplacian):
        laplacian.return_value = np.array([0.0, 200.0])
        provider = BlinkChallengeProvider(timeout_seconds=2, minimum_motion_samples=1)
        provider._eye_detector = _Eyes([True, True])
        base = np.full((160, 160), 100, dtype=np.uint8)
        provider.update(1, base, now=0)
        result = provider.update(1, base, now=3)
        self.assertEqual(result.status, LivenessStatus.SPOOF)

    def test_tracker_keeps_nearby_face_id(self):
        tracker = FaceTracker()
        first = tracker.assign([(10, 10, 100, 100)], now=0)[0]
        second = tracker.assign([(15, 12, 100, 100)], now=1)[0]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
