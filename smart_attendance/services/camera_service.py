"""One leased camera per server, with bounded subprocess startup and cleanup."""
import atexit
import multiprocessing as mp
import os
import queue
import threading
import time
import uuid
from pathlib import Path


def _capture(index, frames, status, stop):
    import cv2
    cap = None
    try:
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF] if os.name == 'nt' else [cv2.CAP_V4L2, cv2.CAP_ANY]
        for backend in backends:
            cap = cv2.VideoCapture(index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                for _ in range(10):
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        frames.put(frame)
                        status.put(('ready', backend))
                        break
                else:
                    cap.release()
                    continue
                break
            cap.release()
        else:
            status.put(('error', 'Camera unavailable. Close other camera apps and allow desktop camera access in Windows Settings.'))
            return
        while not stop.is_set():
            ok, frame = cap.read()
            if not ok:
                status.put(('error', 'Camera disconnected or stopped delivering frames.'))
                return
            try:
                frames.put(frame, timeout=.02)
            except queue.Full:
                pass
            stop.wait(.04)
    except Exception:
        status.put(('error', 'Camera driver failed. Try another camera index or restart the camera.'))
    finally:
        if cap is not None:
            cap.release()


class CameraError(RuntimeError):
    pass


class CameraManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.owner = None
        self.process = None
        self.last_touch = 0
        self._file = None
        self.backend = None
        threading.Thread(target=self._watchdog, daemon=True).start()
        atexit.register(self.close)

    def _watchdog(self):
        while True:
            time.sleep(2)
            with self._lock:
                if self.owner and time.monotonic() - self.last_touch > 15:
                    self.close()

    def _acquire_file(self):
        path = Path(__file__).resolve().parents[2] / 'data' / 'camera.lock'
        path.parent.mkdir(exist_ok=True)
        self._file = path.open('a+b')
        self._file.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                self._file.close(); self._file = None
                raise CameraError('Another SmartAttend process is using the camera.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._file.close(); self._file = None
                raise CameraError('Another SmartAttend process is using the camera.') from exc

    def start(self, owner, index=0, timeout=8):
        if not isinstance(index, int) or not 0 <= index <= 5:
            raise CameraError('Camera index must be from 0 to 5.')
        with self._lock:
            if self.owner:
                raise CameraError('Camera already in use. Stop the active session before switching.')
            self._acquire_file()
            self.owner = owner
            self.last_touch = time.monotonic()
            ctx = mp.get_context('spawn')
            self.frames, self.status = ctx.Queue(maxsize=2), ctx.Queue()
            self.stop_event = ctx.Event()
            self.process = ctx.Process(target=_capture, args=(index, self.frames, self.status, self.stop_event), daemon=True)
            try:
                self.process.start()
                kind, message = self.status.get(timeout=timeout)
                if kind != 'ready':
                    raise CameraError(message)
                self.backend = message
            except queue.Empty as exc:
                self.close()
                raise CameraError('Camera startup timed out. Check camera permissions or select another camera.') from exc
            except Exception:
                self.close()
                raise

    def read(self, owner):
        with self._lock:
            if owner != self.owner:
                raise CameraError('Camera session expired. Start it again.')
            self.last_touch = time.monotonic()
            try:
                kind, message = self.status.get_nowait()
                if kind == 'error':
                    self.close()
                    raise CameraError(message)
            except queue.Empty:
                pass
            if not self.process.is_alive():
                self.close()
                raise CameraError('Camera stopped. Please restart capture.')
            latest = None
            try:
                while True:
                    latest = self.frames.get_nowait()
            except queue.Empty:
                return latest

    def close(self, owner=None):
        with self._lock:
            if owner is not None and owner != self.owner:
                return
            if self.process:
                self.stop_event.set()
                self.process.join(timeout=.6)
                if self.process.is_alive():
                    self.process.terminate(); self.process.join(timeout=1)
                self.process = None
                for channel in (self.frames, self.status):
                    channel.cancel_join_thread(); channel.close()
            self.owner = None
            if self._file:
                self._file.close(); self._file = None

    def discover(self):
        found = []
        owner = 'scan-' + uuid.uuid4().hex
        with self._lock:
            if self.owner:
                raise CameraError('Stop capture before scanning cameras.')
            for index in range(6):
                try:
                    self.start(owner, index, timeout=4)
                    found.append(index)
                except CameraError:
                    pass  # An unavailable device is an expected scan result.
                finally:
                    self.close(owner)
        return found


manager = CameraManager()
