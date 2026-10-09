"""Verify the microphone gate against the REAL audio stack, not a mock.

Every other suite fakes microphone_users(), so none of them would notice the
detection itself going blind -- which is exactly what happened when Windows 11
26H2 stopped updating the registry key it used to read. This suite opens the
default microphone for a few seconds and checks the gate sees it.

Needs a working capture device; with none it reports SKIPPED and exits 0.
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

_REPO_HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "hooks")
HOOKS = os.environ.get(
    "CLAUDE_VOICE_HOOKS",
    _REPO_HOOKS if os.path.isfile(os.path.join(_REPO_HOOKS, "voice_lib.py"))
    else os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, HOOKS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl
from _isolate import isolate

isolate(vl)
vl.workstation_locked = lambda: False
CFG = {"respect_microphone": True, "respect_lock": True, "microphone_ignore": []}

winmm = ctypes.WinDLL("winmm")


class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class _WAVEHDR(ctypes.Structure):
    _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_void_p),
                ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
                ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]


class Recording(object):
    """Holds the default microphone open, recording into a throwaway buffer."""

    def __init__(self, seconds=8):
        self.handle = wintypes.HANDLE()
        fmt = _WAVEFORMATEX(1, 1, 16000, 32000, 2, 16, 0)
        rc = winmm.waveInOpen(ctypes.byref(self.handle), 0xFFFFFFFF, ctypes.byref(fmt),
                              None, None, 0)
        if rc:
            raise OSError("waveInOpen returned %d" % rc)
        self.buf = ctypes.create_string_buffer(32000 * seconds)
        self.hdr = _WAVEHDR(ctypes.cast(self.buf, ctypes.c_void_p), len(self.buf),
                            0, None, 0, 0, None, None)
        size = ctypes.sizeof(self.hdr)
        winmm.waveInPrepareHeader(self.handle, ctypes.byref(self.hdr), size)
        winmm.waveInAddBuffer(self.handle, ctypes.byref(self.hdr), size)
        winmm.waveInStart(self.handle)

    def close(self):
        winmm.waveInStop(self.handle)
        winmm.waveInReset(self.handle)
        winmm.waveInUnprepareHeader(self.handle, ctypes.byref(self.hdr),
                                    ctypes.sizeof(self.hdr))
        winmm.waveInClose(self.handle)


ME = os.path.basename(sys.executable).lower()       # python.exe or pythonw.exe


def me_listed():
    return any(vl.mic_app_label(n).lower() + ".exe" == ME for n in vl.microphone_users())


def wait_for(cond, seconds=4.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


checks = []
checks.append(("Core Audio can be queried (the registry is only a fallback)",
               vl._capture_sessions_active() is not None))
checks.append(("this process is not a mic user before recording", not me_listed()))

try:
    rec = Recording()
except OSError as exc:
    print("SKIPPED: no usable microphone (%s)" % exc)
    sys.exit(0)

try:
    checks.append(("recording is detected", wait_for(me_listed)))
    checks.append(("...and holds speech",
                   vl.hold_reason(CFG) == "the microphone is in use"))
    held = [h for n, h in vl.microphone_holders() if vl.mic_app_label(n).lower() + ".exe" == ME]
    checks.append(("...with a positive hold time for install.py", bool(held) and held[0] > 0))
    ignored = dict(CFG, microphone_ignore=[os.path.splitext(ME)[0]])
    checks.append(("microphone_ignore suppresses it",
                   not any(vl.mic_app_label(n).lower() + ".exe" == ME
                           for n in vl.microphone_blockers(ignored))))
    checks.append(("respect_microphone false: does not hold",
                   not vl.mic_busy(dict(CFG, respect_microphone=False))))
finally:
    rec.close()

checks.append(("releasing the mic clears it", wait_for(lambda: not me_listed())))

# If Core Audio cannot answer, the registry fallback must still return a list
# rather than raise -- a broken detector must never take speech down with it.
real = vl._capture_sessions_active
vl._capture_sessions_active = lambda: None
try:
    checks.append(("Core Audio failure falls back without raising",
                   isinstance(vl.microphone_users(), list)))
finally:
    vl._capture_sessions_active = real

print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
