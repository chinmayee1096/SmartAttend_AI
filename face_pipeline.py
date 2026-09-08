"""Shared face preparation and conservative face detection."""
import cv2
import numpy as np
from functools import lru_cache

@lru_cache(maxsize=1)
def eye_detector():
    return cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

def valid_sample(gray):
    if gray is None or min(gray.shape[:2]) < 60:
        return False
    gray = cv2.resize(gray, (200, 200))
    return (cv2.Laplacian(gray, cv2.CV_64F).var() >= 40
            and 25 <= gray.mean() <= 230
            and len(eye_detector().detectMultiScale(gray[:130], 1.1, 4, minSize=(12, 12))) > 0)

def prepare_face(gray):
    gray = cv2.resize(gray, (200, 200))
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

def detect_faces(gray, detector):
    boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=8, minSize=(80, 80))
    return [(x,y,w,h) for x,y,w,h in boxes if valid_sample(gray[y:y+h,x:x+w])]
