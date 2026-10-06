"""
Face Unlock Windows Service
----------------------------
Wraps the recognition loop as an actual Windows Service, so it starts
at boot (before anyone logs in) rather than waiting for a first login
like a Task Scheduler "At log on" trigger would.

IMPORTANT - read before installing:

1. Credential Manager / keyring is scoped per Windows account. If this
   service runs as "Local System" (the default), it CANNOT see the
   password you stored via setup_credentials.py under your own user
   account - that's a separate credential vault. You have two options:
     a) Configure this service to "Log On As" your own user account
        (via services.msc → this service → Properties → Log On tab),
        entering your Windows password there. This keeps keyring
        working as-is.
     b) Switch password storage to something machine-wide instead of
        per-user (e.g. a DPAPI CRYPTPROTECT_LOCAL_MACHINE-protected
        file, similar to how match.bin itself is protected) - ask me
        if you want to go this route instead.
   This script assumes option (a) - update Windows Credential Manager
   lookup only works if the service runs as your own account.

2. Camera access under a Windows Service context (whether Local System
   or a real user account, but running non-interactively/no desktop
   session) is a less common configuration. Windows' camera privacy
   permissions sometimes behave differently for services than for a
   normal desktop app. TEST THIS - if the camera fails to open under
   the service, that's a real limitation we'd need to work around
   (e.g. falling back to the Task Scheduler approach, accepting that
   the very first login after boot needs a password).

Install dependencies (same as before, plus pywin32's service pieces
which come with pywin32 already):
    pip install opencv-python insightface numpy pywin32 keyring

One-time pywin32 setup (needed for the service framework to work):
    python <path-to-python>\\Scripts\\pywin32_postinstall.py -install
"""

import ctypes
import time
import logging
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil

import cv2
import numpy as np
from insightface.app import FaceAnalysis
import win32crypt
import win32cryptcon

BASE_DIR = Path(__file__).parent
TEMPLATE_PATH = BASE_DIR / "amrit_arcface_template.npy"
LOG_PATH = Path("C:/FaceCredentialProvider/face_service.log")

MATCH_DIR = Path("C:/ProgramData/FaceCredentialProvider")
MATCH_FILE = MATCH_DIR / "match.bin"

WINDOWS_USERNAME = "amrit"   # bare username - matches what Credential.cpp expects

SIMILARITY_THRESHOLD = 0.80
COOLDOWN_SECONDS = 3
POLL_INTERVAL_UNLOCKED = 1.0

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


CRED_FILE = Path("C:/ProgramData/FaceCredentialProvider/service_password.bin")


def get_password():
    if not CRED_FILE.exists():
        raise RuntimeError(
            "No stored password file found. Run setup_credentials_machine.py first."
        )
    with open(CRED_FILE, "rb") as f:
        encrypted = f.read()
    decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
    return decrypted[1].decode("utf-16-le")


from ctypes import wintypes
import threading
import win32gui
import win32con
import win32api

# --- Session lock detection via WTSRegisterSessionNotification ---
# Earlier approaches (OpenInputDesktop, then polling WTSQuerySessionInformation)
# both proved unreliable from a Windows Service context - the first had no
# desktop to check, the second never reflected real state changes on this
# machine. This uses the actual documented mechanism for this: registering
# a hidden window for session change notifications, with NOTIFY_FOR_ALL_SESSIONS
# so it works from Session 0 (where services run) while tracking the real
# interactive session's lock/unlock events. Windows pushes an event to us
# the moment it happens, rather than us guessing from a polled snapshot.

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_ALL_SESSIONS = 1

_session_locked = threading.Event()
_session_locked.set()  # default to "locked" until we get a real event, so
                        # we don't skip watching right after service start


def _wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_WTSSESSION_CHANGE:
        if wparam == WTS_SESSION_LOCK:
            logging.info(f"Session change: LOCK (session {lparam})")
            _session_locked.set()
        elif wparam == WTS_SESSION_UNLOCK:
            logging.info(f"Session change: UNLOCK (session {lparam})")
            _session_locked.clear()
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def _run_notification_window():
    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = _wndproc
    wc.lpszClassName = "FaceUnlockSessionNotifyWindow"
    wc.hInstance = win32api.GetModuleHandle(None)
    class_atom = win32gui.RegisterClass(wc)

    hwnd = win32gui.CreateWindow(
        class_atom, "FaceUnlockSessionNotifyWindow", 0, 0, 0, 0, 0,
        0, 0, wc.hInstance, None
    )

    wtsapi32 = ctypes.windll.wtsapi32
    registered = wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_ALL_SESSIONS)
    logging.info(f"WTSRegisterSessionNotification result: {registered}")

    win32gui.PumpMessages()  # blocks, delivering messages to _wndproc


def start_session_notification_thread():
    t = threading.Thread(target=_run_notification_window, daemon=True)
    t.start()
    return t


def is_locked():
    return _session_locked.is_set()


def write_match_proof(username: str, password: str):
    MATCH_DIR.mkdir(parents=True, exist_ok=True)
    password_bytes = password.encode("utf-16-le")
    encrypted = win32crypt.CryptProtectData(
        password_bytes, "face_unlock_match", None, None, None,
        win32cryptcon.CRYPTPROTECT_LOCAL_MACHINE
    )
    with open(MATCH_FILE, "wb") as f:
        f.write(username.encode("ascii") + b"\n" + encrypted)


def run_recognition_attempt(model, template):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        logging.warning("Could not read a frame from the camera.")
        return None

    faces = model.get(frame)
    if not faces:
        return None

    face = faces[0]
    embedding = face.embedding
    similarity = float(
        np.dot(embedding, template)
        / (np.linalg.norm(embedding) * np.linalg.norm(template))
    )
    logging.info(f"Similarity: {similarity:.3f}")
    return similarity


class FaceUnlockService(win32serviceutil.ServiceFramework):
    _svc_name_ = "FaceUnlockService"
    _svc_display_name_ = "Face Unlock Service"
    _svc_description_ = (
        "Runs face recognition at boot so the Face Unlock credential "
        "provider tile can authenticate before the first login."
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        self.running = False

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.main_loop()

    def main_loop(self):
        logging.info("Face Unlock service starting.")
        start_session_notification_thread()
        try:
            template = np.load(TEMPLATE_PATH)
            model = FaceAnalysis(name="buffalo_l")
            model.prepare(ctx_id=0, det_size=(640, 640))
        except Exception as e:
            logging.error(f"Failed to initialize model/template: {e}")
            return

        while self.running:
            # Let the service stop promptly if Windows asks it to.
            if win32event.WaitForSingleObject(self.stop_event, 0) == win32event.WAIT_OBJECT_0:
                break

            if not is_locked():
                time.sleep(POLL_INTERVAL_UNLOCKED)
                continue

            similarity = run_recognition_attempt(model, template)

            if similarity is not None and similarity > SIMILARITY_THRESHOLD:
                logging.info("Face matched. Writing match proof.")
                try:
                    password = get_password()
                    write_match_proof(WINDOWS_USERNAME, password)
                except Exception as e:
                    logging.error(f"Failed to write match proof: {e}")
                time.sleep(5)
            else:
                time.sleep(COOLDOWN_SECONDS)

        logging.info("Face Unlock service stopping.")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(FaceUnlockService)