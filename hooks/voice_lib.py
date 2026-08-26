"""Shared helpers for the Claude Code voice/notification hooks (Windows, stdlib only)."""

import ctypes
from ctypes import wintypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape as xml_escape

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HOOKS_DIR, "voice-config.json")
STATE_DIR = os.path.join(tempfile.gettempdir(), "claude_voice")
LOCK_PATH = os.path.join(STATE_DIR, "speak.lock")

DEFAULTS = {
    "speak": True,
    "toast": True,
    "idle_seconds": 45,
    "long_turn_seconds": 60,
    "rate": 1,
    "voice": None,
}

_CREATE_NO_WINDOW = 0x08000000


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)
    return STATE_DIR


ERROR_LOG = os.path.join(HOOKS_DIR, "voice-errors.log")


SPOKEN_LOG = os.path.join(HOOKS_DIR, "voice-spoken.log")


def log_spoken(what, text):
    """Record what was said and when, so 'did it speak over me?' is answerable."""
    try:
        with open(SPOKEN_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %-9s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                        what, (text or "")[:90]))
    except Exception:
        pass


def log_problem(message):
    """Record why speech did not happen. Silence should always be explainable."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (stamp, message))
    except Exception:
        pass


def safe_id(value):
    """Reduce a session id to something safe to use as a filename."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:100] or "default"


def turn_stamp_path(session_id):
    return os.path.join(state_dir(), "turn-" + safe_id(session_id))


def powershell():
    root = os.environ.get("SystemRoot", r"C:\Windows")
    exe = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return exe if os.path.isfile(exe) else "powershell"


def run_powershell(script, env_extra=None, timeout=120):
    """Run a fixed PowerShell script. Data is passed via env vars, never interpolated."""
    env = dict(os.environ)
    if env_extra:
        env.update({k: ("" if v is None else str(v)) for k, v in env_extra.items()})
    try:
        return subprocess.run(
            [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            env=env,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW,
        ).returncode == 0
    except Exception:
        return False


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def os_idle_seconds():
    """Seconds since the last keyboard/mouse input anywhere on the machine."""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # dwTime is a 32-bit tick count; mask so the 49.7-day wrap works out.
        now = ctypes.windll.kernel32.GetTickCount64() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0


def acquire_lock(timeout=90, stale_after=300):
    os.makedirs(STATE_DIR, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            os.close(os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCK_PATH) > stale_after:
                    os.unlink(LOCK_PATH)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                return False
            time.sleep(0.1)
        except Exception:
            return False


def release_lock():
    try:
        os.unlink(LOCK_PATH)
    except OSError:
        pass


# --- Speech -----------------------------------------------------------------
# Two engines. WinRT (Windows.Media.SpeechSynthesis) reaches the modern
# natural/neural voices; SAPI (System.Speech) only sees the legacy "Desktop"
# voices but is far simpler. We prefer WinRT and fall back to SAPI, so a
# failure in the newer engine degrades to a worse voice rather than silence.

_AWAIT_PRELUDE = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
  $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
  $t.Wait(-1) | Out-Null
  $t.Result
}
"""

_WINRT_SPEAK_PS = """
$ErrorActionPreference = 'Stop'
""" + _AWAIT_PRELUDE + """
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
if ($env:CV_VOICE) {
  $want = $env:CV_VOICE
  $v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
       Where-Object { $_.DisplayName -like "*$want*" } | Select-Object -First 1
  if ($v) { $synth.Voice = $v }
}
if ($env:CV_RATE) { $synth.Options.SpeakingRate = [double]$env:CV_RATE }

$text = [System.IO.File]::ReadAllText($env:CV_TEXT_FILE, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }

$stream = Await ($synth.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$reader = New-Object Windows.Storage.Streams.DataReader($stream)
Await ($reader.LoadAsync([uint32]$stream.Size)) ([uint32]) | Out-Null
$bytes = New-Object byte[] ([int]$stream.Size)
$reader.ReadBytes($bytes)
[System.IO.File]::WriteAllBytes($env:CV_WAV_FILE, $bytes)
$synth.Dispose()
"""

_SAPI_SPEAK_PS = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($env:CV_TEXT_FILE, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  if ($env:CV_SAPI_RATE) { $synth.Rate = [int]$env:CV_SAPI_RATE }
  if ($env:CV_VOICE) {
    $want = $env:CV_VOICE
    $match = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -like "*$want*" } |
             Select-Object -First 1
    if ($match) { $synth.SelectVoice($match.VoiceInfo.Name) }
  }
  $synth.Speak($text)
} finally { $synth.Dispose() }
"""

_LIST_PS = """
$ErrorActionPreference = 'SilentlyContinue'
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
  ForEach-Object { 'winrt|' + $_.DisplayName + '|' + $_.Language }
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | ForEach-Object { 'sapi|' + $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture }
$s.Dispose()
"""


def clean_for_speech(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_#>|\[\]{}\\^~]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def list_voices():
    """Return [(engine, name, language)] for every voice both engines can see."""
    out = []
    try:
        r = subprocess.run(
            [powershell(), "-NoProfile", "-NonInteractive", "-Command", _LIST_PS],
            capture_output=True, text=True, timeout=60,
            creationflags=_CREATE_NO_WINDOW,
        )
        for line in r.stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) == 3 and parts[0] in ("winrt", "sapi"):
                out.append(tuple(parts))
    except Exception:
        pass
    return out


def _sapi_rate(multiplier):
    """SAPI wants -10..10; our config uses a speed multiplier around 1.0."""
    return max(-10, min(10, int(round((float(multiplier) - 1.0) * 10))))


# --- Kokoro (local neural, preferred) ---------------------------------------

KOKORO_PY = os.path.join(HOOKS_DIR, ".venv", "Scripts", "python.exe")
KOKORO_SYNTH = os.path.join(HOOKS_DIR, "kokoro_synth.py")

_PLAY_WAV_PS = """
$ErrorActionPreference = 'Stop'
$p = New-Object System.Media.SoundPlayer $env:CV_WAV_FILE
$p.PlaySync()
$p.Dispose()
"""


def kokoro_available():
    return os.path.isfile(KOKORO_PY) and os.path.isfile(KOKORO_SYNTH)


def kokoro_voices():
    """Voice names Kokoro offers, or [] if it is not installed."""
    if not kokoro_available():
        return []
    try:
        r = subprocess.run([KOKORO_PY, KOKORO_SYNTH, "--list"],
                           capture_output=True, text=True, timeout=180,
                           creationflags=_CREATE_NO_WINDOW)
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def _synth_kokoro(text_file, wav, voice, rate):
    """Synthesise to a WAV file. Playback is separate so the mic can be re-checked."""
    if not kokoro_available():
        return False
    try:
        r = subprocess.run(
            [KOKORO_PY, KOKORO_SYNTH, "--text-file", text_file, "--wav", wav,
             "--voice", voice or "am_michael", "--speed", str(rate)],
            capture_output=True, text=True, timeout=300,
            creationflags=_CREATE_NO_WINDOW,
        )
        if r.returncode != 0 or not os.path.isfile(wav):
            log_problem("kokoro synth rc=%s voice=%r: %s"
                        % (r.returncode, voice, (r.stderr or "").strip()[:400]))
            return False
    except Exception as exc:
        log_problem("kokoro synth raised: %r" % (exc,))
        return False
    return True


def _play_wav(wav):
    return run_powershell(_PLAY_WAV_PS, {"CV_WAV_FILE": wav})


def speak(text, cfg=None, guard=None):
    """Speak text aloud.

    Engine order: Kokoro (local neural) -> WinRT -> SAPI. Each fallback is a
    downgrade in voice quality, never a drop to silence.

    guard, if given, is called after synthesis and immediately before playback.
    Returning False aborts playback and makes this return the string "deferred",
    so the caller can requeue instead of talking over the user. Synthesis takes
    several seconds, which is long enough for a call or dictation to start.
    """
    cfg = cfg or load_config()
    text = clean_for_speech(text)
    if not text:
        return False

    rate = float(cfg.get("rate", 1.0) or 1.0)
    engine = (cfg.get("engine") or "auto").lower()
    kokoro_voice = (cfg.get("voice") or "").strip()
    win_voice = (cfg.get("fallback_voice") or "").strip()

    order = {"kokoro": ["kokoro"], "winrt": ["winrt"], "sapi": ["sapi"]}.get(
        engine, ["kokoro", "winrt", "sapi"])

    d = state_dir()
    fd, txt = tempfile.mkstemp(prefix="cv-", suffix=".txt", dir=d)
    wav = os.path.join(d, "cv-speak-%d.wav" % os.getpid())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if not acquire_lock():
            log_problem("gave up waiting for the audio lock")
            return False
        try:
            for eng in order:
                if eng == "kokoro":
                    synthesised = _synth_kokoro(txt, wav, kokoro_voice, rate)
                elif eng == "winrt":
                    synthesised = run_powershell(_WINRT_SPEAK_PS, {
                        "CV_TEXT_FILE": txt, "CV_WAV_FILE": wav,
                        "CV_VOICE": win_voice, "CV_RATE": rate,
                    }) and os.path.isfile(wav)
                else:
                    # SAPI synthesises and plays in one call, so the guard can
                    # only be honoured up front for this last-resort engine.
                    if guard is not None and not guard():
                        log_spoken("deferred", text)
                        return "deferred"
                    synthesised = None

                if eng == "sapi":
                    ok = run_powershell(_SAPI_SPEAK_PS, {
                        "CV_TEXT_FILE": txt, "CV_VOICE": win_voice,
                        "CV_SAPI_RATE": _sapi_rate(rate),
                    })
                    if ok:
                        log_spoken("spoke", text)
                        return True
                    log_problem("engine 'sapi' failed to speak")
                    continue

                if not synthesised:
                    log_problem("engine %r failed to synthesise" % eng)
                    continue

                if guard is not None and not guard():
                    log_spoken("deferred", text)
                    return "deferred"

                if _play_wav(wav):
                    if eng != order[0]:
                        log_problem("engine %r failed; fell back to %r" % (order[0], eng))
                    log_spoken("spoke", text)
                    return True
                log_problem("playback failed on engine %r" % eng)
            log_problem("all engines failed; nothing was spoken")
            return False
        finally:
            release_lock()
    finally:
        for path in (txt, wav):
            try:
                os.unlink(path)
            except OSError:
                pass


APP_ID = "ClaudeCode.VSC.Notice"
APP_DISPLAY_NAME = "Claude VSC Notice"
ICON_PATH = os.path.join(HOOKS_DIR, "claude-logo.png")


def icon_uri():
    return "file:///" + ICON_PATH.replace(os.sep, "/")


_TOAST_PS = """
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml([System.IO.File]::ReadAllText($env:CV_TOAST_FILE, [System.Text.Encoding]::UTF8))
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CV_APP_ID).Show($toast)
"""


def toast(title, body):
    """Show a Windows toast attributed to Claude VSC Notice. Returns False if unavailable."""
    parts = ['<toast scenario="reminder" duration="long">',
             '<visual><binding template="ToastGeneric">']
    if os.path.isfile(ICON_PATH):
        parts.append('<image placement="appLogoOverride" src="%s"/>' % xml_escape(icon_uri()))
    parts.append("<text>%s</text><text>%s</text>" % (xml_escape(title), xml_escape(body)))
    parts.append('</binding></visual><audio silent="true"/>')
    parts.append('<actions><action content="Dismiss" arguments="dismiss"'
                 ' activationType="background"/></actions></toast>')
    xml = "".join(parts)

    fd, path = tempfile.mkstemp(prefix="cv-toast-", suffix=".xml", dir=state_dir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(xml)
        return run_powershell(_TOAST_PS, {"CV_TOAST_FILE": path, "CV_APP_ID": APP_ID}, timeout=20)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def chime():
    """Short attention sound. Falls back to the system beep if the wav is missing."""
    try:
        import winsound
        wav = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "Media", "Windows Notify System Generic.wav")
        if os.path.isfile(wav):
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return True
    except Exception:
        return False


def nudge_path(session_id):
    return os.path.join(state_dir(), "nudge-" + safe_id(session_id))


def nudge_count(session_id):
    try:
        with open(nudge_path(session_id), "r", encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def set_nudge_count(session_id, n):
    try:
        with open(nudge_path(session_id), "w", encoding="utf-8") as f:
            f.write(str(n))
    except OSError:
        pass


def clear_nudge(session_id):
    try:
        os.unlink(nudge_path(session_id))
    except OSError:
        pass


SESSION_STALE = 1800          # ignore stamps from sessions idle longer than this


def turn_started_at(session_id):
    """Raw timestamp of when this turn's prompt was submitted, or None."""
    try:
        with open(turn_stamp_path(session_id), "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def turn_elapsed(session_id):
    started = turn_started_at(session_id)
    return None if started is None else max(0.0, time.time() - started)


def prompted_elsewhere_since(session_id, since_ts):
    """True if a different live session got a prompt after since_ts.

    With several windows open, machine-wide idle time is the wrong signal: the user
    can be typing furiously in window A while window B finishes unnoticed. A newer
    stamp on another session is direct evidence their attention is elsewhere.
    """
    d = state_dir()
    mine = "turn-" + safe_id(session_id)
    now = time.time()
    for name in os.listdir(d):
        if not name.startswith("turn-") or name == mine:
            continue
        try:
            mtime = os.path.getmtime(os.path.join(d, name))
        except OSError:
            continue
        if now - mtime > SESSION_STALE:
            continue                      # dead session, not competing for attention
        if mtime > since_ts:
            return True
    return False


def worth_interrupting(cfg, session_id):
    """True when the summary should be spoken.

    With always_speak on (the default), every turn is spoken -- the summary is meant
    to replace reading the screen, not just to catch the user when they wander off.
    The attention heuristics below only matter when always_speak is turned off.
    """
    if cfg.get("always_speak", True):
        return True

    started = turn_started_at(session_id)
    elapsed = None if started is None else max(0.0, time.time() - started)

    if elapsed is not None and elapsed >= float(cfg.get("long_turn_seconds", 60)):
        return True
    if os_idle_seconds() >= float(cfg.get("idle_seconds", 45)):
        return True

    # Working in another window. Require a minimum turn length so trivial
    # back-and-forth in a background session does not chatter.
    if started is not None and prompted_elsewhere_since(session_id, started):
        if elapsed is None or elapsed >= float(cfg.get("min_turn_seconds", 10)):
            return True
    return False


def sweep_stale_state():
    """Delete turn/nudge stamps left by sessions that are long gone."""
    d = state_dir()
    now = time.time()
    for name in os.listdir(d):
        if not (name.startswith("turn-") or name.startswith("nudge-")):
            continue
        fp = os.path.join(d, name)
        try:
            if now - os.path.getmtime(fp) > SESSION_STALE * 4:
                os.unlink(fp)
        except OSError:
            pass


# --- Workstation lock -------------------------------------------------------
# Windows keeps playing audio through the lock screen, so without this a locked
# machine gets narrated to an empty room. Detected by the presence of LogonUI,
# which is the process that draws the lock screen.
#
# OpenInputDesktop is the usual trick for this and is WRONG here: the hook runs
# in the user's own session, so it still gets a handle while locked. Verified
# against a genuinely locked machine.

_TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def _process_running(exe_name):
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return False
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        target = exe_name.lower().encode()
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == target:
                return True
            ok = k32.Process32Next(snap, ctypes.byref(entry))
        return False
    finally:
        k32.CloseHandle(snap)


def workstation_locked():
    """True when the lock screen is up. Roughly 13ms, no subprocess."""
    try:
        return _process_running("LogonUI.exe")
    except Exception:
        return False          # never suppress speech because detection broke


# --- Microphone / call awareness ---------------------------------------------
# Windows records per-app microphone use here; an app with a start time but no
# stop time holds the mic right now. This is the same data behind the privacy
# indicator in the taskbar, so it covers Teams, Zoom, browsers -- anything.
_MIC_KEY_PARTS = ("SOFTWARE", "Microsoft", "Windows", "CurrentVersion",
                  "CapabilityAccessManager", "ConsentStore", "microphone")
MIC_KEY = chr(92).join(_MIC_KEY_PARTS)


def _mic_scan(root, path, out, depth=0):
    import winreg
    if depth > 2:
        return
    try:
        key = winreg.OpenKey(root, path)
    except OSError:
        return
    with key:
        n_sub, n_val, _ = winreg.QueryInfoKey(key)
        start = stop = None
        for i in range(n_val):
            try:
                name, val, _ = winreg.EnumValue(key, i)
            except OSError:
                continue
            if name == "LastUsedTimeStart":
                start = val
            elif name == "LastUsedTimeStop":
                stop = val
        if start and not stop:
            out.append(path.split(chr(92))[-1])
        for i in range(n_sub):
            try:
                _mic_scan(root, path + chr(92) + winreg.EnumKey(key, i), out, depth + 1)
            except OSError:
                pass


def microphone_users():
    """Names of apps currently holding the microphone (empty when nothing is)."""
    import winreg
    found = []
    try:
        _mic_scan(winreg.HKEY_CURRENT_USER, MIC_KEY, found)
    except Exception:
        pass
    return found


# Apps that hold the microphone continuously rather than only during a call.
# A softphone or dictation tool keeps the device open all day, so treating any
# mic use as "on a call" would silence speech permanently.
ALWAYS_ON_MIC_APPS = ("cytracom", "wisprflow", "nvidia", "voicemeeter", "obs")


def microphone_blockers(cfg=None):
    """Mic users that should actually suppress speech."""
    cfg = cfg or load_config()
    ignore = [str(x).lower() for x in cfg.get("microphone_ignore", ALWAYS_ON_MIC_APPS)]
    out = []
    for name in microphone_users():
        low = name.lower()
        if any(pat in low for pat in ignore):
            continue
        out.append(name)
    return out


def microphone_in_use(cfg=None):
    return bool(microphone_blockers(cfg))


# --- When to hold speech ----------------------------------------------------


def locked_now(cfg):
    return bool(cfg.get("respect_lock", True)) and workstation_locked()


def mic_busy(cfg):
    return bool(cfg.get("respect_microphone", True)) and microphone_in_use(cfg)


def probably_away(cfg=None):
    """True when the user is likely not at this machine.

    Locked is definitive. Otherwise a long stretch with no keyboard or mouse
    means they have walked away or are driving the session from a phone, since
    Remote Control input never touches this machine's input devices.
    """
    cfg = cfg or load_config()
    if workstation_locked():
        return True
    return os_idle_seconds() >= float(cfg.get("away_seconds", 120))


def hold_reason(cfg=None):
    """Why speech should not play right now, or None if it may."""
    cfg = cfg or load_config()
    if locked_now(cfg):
        return "the screen is locked"
    blockers = microphone_blockers(cfg) if cfg.get("respect_microphone", True) else []
    if blockers:
        return "the microphone is in use"
    return None


# --- Utterance queue --------------------------------------------------------
# One slot PER SESSION. Two quick turns in the same window are the same work
# superseding itself, so the newer summary replaces the older. Two summaries
# from different windows are independent work, so both are kept and played in
# arrival order -- nothing you have not heard is thrown away.

QUEUE_DIR = os.path.join(STATE_DIR, "queue")
LABELS_PATH = os.path.join(STATE_DIR, "labels.json")
SPEAKER_LOCK = os.path.join(STATE_DIR, "speaker.lck")

_ORDINALS = ("", "", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def queue_dir():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    return QUEUE_DIR


def live_sessions():
    """Session ids that have submitted a prompt recently."""
    out = []
    try:
        names = os.listdir(state_dir())
    except OSError:
        return out
    for name in names:
        if not name.startswith("turn-"):
            continue
        try:
            if time.time() - os.path.getmtime(os.path.join(STATE_DIR, name)) <= SESSION_STALE:
                out.append(name[len("turn-"):])
        except OSError:
            pass
    return out


def _pretty(name):
    return " ".join(name.replace("-", " ").replace("_", " ").split())


def session_label(session_id, cwd=""):
    """A short spoken name for a session, taken from its project folder.

    Stable for the life of the session, and disambiguated when two windows are
    open on the same folder ("Anchor Hub" / "Anchor Hub two").
    """
    sid = safe_id(session_id)
    try:
        with open(LABELS_PATH, "r", encoding="utf-8") as f:
            labels = json.load(f)
    except (OSError, ValueError):
        labels = {}

    live = set(safe_id(x) for x in live_sessions())
    labels = dict((k, v) for k, v in labels.items() if k in live or k == sid)

    if sid not in labels:
        base = _pretty(os.path.basename((cwd or "").rstrip("/" + chr(92)))) or "Claude"
        taken = [v for k, v in labels.items() if k != sid and v.startswith(base)]
        if taken:
            n = min(len(taken) + 2, len(_ORDINALS) - 1)
            base = base + " " + _ORDINALS[n]
        labels[sid] = base
        try:
            with open(LABELS_PATH, "w", encoding="utf-8") as f:
                json.dump(labels, f)
        except OSError:
            pass
    return labels[sid]


def _slot(session_id):
    return os.path.join(queue_dir(), "q-" + safe_id(session_id) + ".json")


def enqueue(text, session_id="default", label=""):
    """Add or replace this session's queued summary."""
    d = queue_dir()
    payload = json.dumps({"text": text, "created": time.time(),
                          "label": label, "session": safe_id(session_id)})
    fd, tmp = tempfile.mkstemp(prefix="stage-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        # Unique staging name per process: several hooks can fire milliseconds
        # apart, and a shared temp name makes the rename fail on Windows.
        for _ in range(6):
            try:
                os.replace(tmp, _slot(session_id))
                return True
            except PermissionError:
                time.sleep(0.05)
        log_problem("could not queue utterance: slot stayed locked")
        return False
    except Exception as exc:
        log_problem("could not queue utterance: %r" % (exc,))
        return False
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def queue_items():
    """Queued summaries, oldest first, without removing them."""
    out = []
    try:
        names = os.listdir(QUEUE_DIR)
    except OSError:
        return out
    for name in names:
        if not (name.startswith("q-") and name.endswith(".json")):
            continue
        fp = os.path.join(QUEUE_DIR, name)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                item = json.load(f)
        except (OSError, ValueError):
            continue
        item["_path"] = fp
        out.append(item)
    out.sort(key=lambda i: i.get("created", 0))
    return out


def queue_depth():
    return len(queue_items())


def dequeue_oldest():
    """Take the longest-waiting summary, so sessions are heard in arrival order."""
    items = queue_items()
    if not items:
        return None
    item = items[0]
    try:
        os.unlink(item["_path"])
    except OSError:
        pass
    return item


def become_speaker():
    """Claim the sole draining role. False means someone else already has it."""
    state_dir()
    try:
        os.close(os.open(SPEAKER_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        try:
            if time.time() - os.path.getmtime(SPEAKER_LOCK) > 3600:
                os.unlink(SPEAKER_LOCK)
                return become_speaker()
        except OSError:
            pass
        return False
    except Exception:
        return False


def release_speaker():
    try:
        os.unlink(SPEAKER_LOCK)
    except OSError:
        pass


def say_detached(text, session_id="default", cwd=""):
    """Queue text for this session and ensure something is draining the queue."""
    if not text.strip():
        return False
    if not enqueue(text, session_id, session_label(session_id, cwd)):
        return False
    flags = 0x00000008 | _CREATE_NO_WINDOW      # DETACHED_PROCESS | CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(HOOKS_DIR, "voice-say.py"), "--drain"],
            creationflags=flags, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        log_problem("could not start the speech worker: %r" % (exc,))
        return False


def _should_announce(cfg, label, heard_labels):
    """Name the window only when it is genuinely ambiguous which one is talking."""
    mode = str(cfg.get("announce_session", "auto")).lower()
    if not label or mode == "never":
        return False
    if mode == "always":
        return True
    return len(live_sessions()) > 1 or len(heard_labels) > 1


def drain_pending(cfg=None):
    """Speak every queued summary in order. Nothing is ever discarded.

    The microphone is checked BEFORE taking an item off the queue, so a worker
    that dies while waiting cannot swallow a summary. If the wait times out the
    worker exits with the queue intact; the next turn in any window starts a
    fresh worker that tries again.
    """
    cfg = cfg or load_config()
    if not become_speaker():
        return

    respect_mic = cfg.get("respect_microphone", True)
    max_defer = float(cfg.get("max_defer_seconds", 120))
    max_stale = float(cfg.get("max_stale_seconds", 0))      # 0 = never discard
    heard_labels = set()

    try:
        while True:
            if not queue_depth():
                return

            # A locked screen can last hours, so do not sit here waiting on it --
            # leave the queue alone and let a later turn pick it up. A call, by
            # contrast, is minutes, so that one is worth waiting out.
            if locked_now(cfg):
                log_problem("screen locked; %d summary(s) waiting for unlock"
                            % queue_depth())
                return

            waited = 0.0
            while mic_busy(cfg) and waited < max_defer:
                time.sleep(5)
                waited += 5
                if locked_now(cfg):
                    log_problem("screen locked while waiting; %d summary(s) queued"
                                % queue_depth())
                    return

            if mic_busy(cfg):
                log_problem("microphone busy (%s) after %.0fs; %d summary(s) still queued"
                            % (", ".join(microphone_blockers(cfg))[:60], waited,
                               queue_depth()))
                return                       # queue untouched; a later turn retries

            item = dequeue_oldest()
            if not item:
                return

            age = time.time() - (item.get("created") or time.time())
            if max_stale and age > max_stale:
                log_problem("discarded a summary %.0fs old (max_stale_seconds)" % age)
                continue

            label = item.get("label") or ""
            text = item.get("text", "")
            announced = text
            if _should_announce(cfg, label, heard_labels | {label}):
                announced = label + ". " + text

            # Synthesis takes seconds -- long enough to lock the screen or start
            # talking, so re-check both right before the audio plays.
            guard = lambda: hold_reason(cfg) is None

            result = speak(announced, cfg, guard=guard)
            if result == "deferred":
                # The mic went busy during synthesis. Put it back untouched.
                enqueue(text, item.get("session", "default"), label)
                log_problem("held mid-synthesis (%s); requeued a summary"
                            % (hold_reason(cfg) or "unknown"))
                return
            heard_labels.add(label)
    finally:
        release_speaker()


def read_hook_input():
    try:
        raw = sys.stdin.read().strip()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}
