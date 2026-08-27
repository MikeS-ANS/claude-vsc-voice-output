"""Stopping speech that is already playing: pause keeps it, stop discards it."""
import os
import subprocess
import sys
import time

# Prefer the hooks in this checkout, so the suite exercises the code you are
# looking at rather than whatever happens to be installed. Falls back to the
# installed copy, and CLAUDE_VOICE_HOOKS overrides both.
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

isolate(vl)                         # private state dir; no cross-suite leakage

vl.workstation_locked = lambda: False
vl.microphone_in_use = lambda cfg=None: False
vl.microphone_blockers = lambda cfg=None: []

checks = []


def reset():
    vl.clear_inflight()
    try:
        os.unlink(vl.SPEAKER_LOCK)
    except OSError:
        pass
    for item in vl.queue_items():
        try:
            os.unlink(item["_path"])
        except OSError:
            pass


# --- a pause must keep the summary that was cut off ------------------------
reset()
vl.enqueue("the one that was playing", "A", "My Project")
item = vl.queue_items()[0]
vl.set_inflight(item)                      # simulate: dequeued and playing
try:
    os.unlink(item["_path"])
except OSError:
    pass
assert vl.queue_depth() == 0

stopped, discarded = vl.stop_speaking(discard=False)
checks.append(("pause: nothing discarded", discarded == 0))
checks.append(("pause: the interrupted summary is back in the queue",
               vl.queue_depth() == 1))
checks.append(("pause: it is the same summary",
               "the one that was playing" in (vl.queue_items()[0].get("text") or "")))
checks.append(("pause: it keeps its original arrival time",
               abs((vl.queue_items()[0].get("created") or 0)
                   - (item.get("created") or 0)) < 0.001))
checks.append(("pause: the in-flight record is cleared",
               not os.path.exists(vl.INFLIGHT_PATH)))

# --- stop must clear the lot ----------------------------------------------
reset()
for n in range(3):
    vl.enqueue("queued %d" % n, "A", "My Project")
    time.sleep(0.01)
playing = vl.queue_items()[0]
vl.set_inflight(playing)
try:
    os.unlink(playing["_path"])
except OSError:
    pass

stopped, discarded = vl.stop_speaking(discard=True)
checks.append(("stop: the queue is emptied", vl.queue_depth() == 0))
checks.append(("stop: counts what it threw away (2 queued + 1 playing)",
               discarded == 3))
checks.append(("stop: the in-flight record is cleared",
               not os.path.exists(vl.INFLIGHT_PATH)))

# --- stopping when nothing is playing must be harmless -------------------
reset()
stopped, discarded = vl.stop_speaking(discard=False)
checks.append(("stopping with nothing playing is a no-op",
               stopped is False and discarded == 0))
checks.append(("...and does not invent a queue entry", vl.queue_depth() == 0))

# --- the speaker lock records a real PID so it can be targeted ------------
reset()
checks.append(("no speaker, no pid", vl.speaking_pid() is None))
assert vl.become_speaker()
checks.append(("the speaker lock holds this process's pid",
               vl.speaking_pid() == os.getpid()))
vl.release_speaker()
checks.append(("released", vl.speaking_pid() is None))

# --- stop_speaking must never kill the process calling it ----------------
reset()
assert vl.become_speaker()                 # lock now holds OUR pid
still_here = True
vl.stop_speaking(discard=False)
checks.append(("stop_speaking refuses to kill its own caller", still_here))

# --- playback interruption is surfaced, not swallowed --------------------
reset()
calls = {"n": 0}


def fake_play(wav, interrupt_check=None, poll=0.5, **kw):
    """Stand in for the player: report an interruption on the first poll."""
    calls["n"] += 1
    if interrupt_check is not None:
        return interrupt_check() or True
    return True


real_play = vl._play_wav
vl._play_wav = fake_play
vl._synth_kokoro = lambda txt, wav, voice, rate: (open(wav, "wb").write(b"x") or True)

result = vl.speak("cut me off", {"engine": "kokoro", "rate": 1.0},
                  guard=lambda: True, interrupt=lambda: "the microphone is in use")
checks.append(("an interrupted playback returns 'interrupted'", result == "interrupted"))

result = vl.speak("let me finish", {"engine": "kokoro", "rate": 1.0},
                  guard=lambda: True, interrupt=lambda: None)
checks.append(("an uninterrupted playback still returns True", result is True))
vl._play_wav = real_play

# --- pause HOLDS through later turns, resume lifts it ---------------------
reset()
vl.clear_paused()
checks.append(("not paused to begin with", not vl.is_paused()))

vl.enqueue("held while paused", "A", "My Project")
vl.stop_speaking(discard=False, hold=True)
checks.append(("pause sets the hold", vl.is_paused()))
checks.append(("pause keeps the queue", vl.queue_depth() == 1))
checks.append(("hold_reason says so", vl.hold_reason({}) == "speech is paused"))

# A later turn must NOT quietly undo the pause.
spoke = []
real_speak = vl.speak
vl.speak = lambda text, cfg=None, **kw: spoke.append(text)
vl.drain_pending({"respect_microphone": False, "respect_lock": False,
                  "max_stale_seconds": 0})
checks.append(("a later turn does not break the pause", spoke == []))
checks.append(("...and the summary is still waiting", vl.queue_depth() == 1))

# Resume speaks what was waiting.
depth = vl.resume_speaking()
checks.append(("resume reports what was waiting", depth == 1))
checks.append(("resume clears the hold", not vl.is_paused()))
vl.drain_pending({"respect_microphone": False, "respect_lock": False,
                  "max_stale_seconds": 0})
checks.append(("after resume it is spoken",
               len(spoke) == 1 and "held while paused" in spoke[0]))
vl.speak = real_speak

# --- stop must not leave a lingering hold --------------------------------
reset()
vl.set_paused()
vl.stop_speaking(discard=True, hold=False)
checks.append(("stop clears any hold", not vl.is_paused()))

# --- paused_since reports roughly how long ------------------------------
reset()
vl.clear_paused()
checks.append(("paused_since is None when running", vl.paused_since() is None))
vl.set_paused()
held = vl.paused_since()
checks.append(("paused_since is a small number just after pausing",
               held is not None and held < 5))
vl.clear_paused()

# --- a pause cuts off audio already playing -----------------------------
reset()
vl.set_paused()
real_play2 = vl._play_wav
vl._play_wav = lambda wav, interrupt_check=None, poll=0.5, **kw: (
    interrupt_check() if interrupt_check else True)
vl._synth_kokoro = lambda txt, wav, voice, rate: (open(wav, "wb").write(b"x") or True)
result = vl.speak("stop me", {"engine": "kokoro", "rate": 1.0},
                  guard=lambda: True, interrupt=lambda: vl.hold_reason({}))
checks.append(("pausing mid-sentence interrupts playback", result == "interrupted"))
vl._play_wav = real_play2
vl.clear_paused()

# --- one keypress must count once, even when the OS fires it twice --------
# A Windows shortcut hotkey can deliver several invocations per press. The toggle
# is a read-then-write, so duplicates used to interleave as pause -> resume ->
# pause and leave it paused: the key looked dead.
import threading

reset()
vl.clear_paused()
try:
    os.unlink(vl.TOGGLE_LOCK)
except OSError:
    pass


def double_fire():
    """Simulate one press delivered as two concurrent invocations."""
    out = []
    threads = [threading.Thread(target=lambda: out.append(vl.toggle_pause()))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    kinds = [o if isinstance(o, str) else o[0] for o in out]
    return kinds


kinds = double_fire()
checks.append(("a double-fired press acts exactly once",
               kinds.count("ignored") == 1 and
               (kinds.count("paused") + kinds.count("resumed")) == 1))
checks.append(("...and it paused", vl.is_paused()))

time.sleep(1.1)                              # a genuinely separate press
kinds = double_fire()
checks.append(("the next press acts exactly once too",
               kinds.count("ignored") == 1))
checks.append(("...and it resumed", not vl.is_paused()))

# Six presses must alternate, not stick.
states = []
for _ in range(6):
    time.sleep(1.1)
    double_fire()
    states.append(vl.is_paused())
checks.append(("six presses alternate cleanly",
               states == [True, False, True, False, True, False]))

vl.clear_paused()
try:
    os.unlink(vl.TOGGLE_LOCK)
except OSError:
    pass

# --- a killed worker must not wedge speech --------------------------------
# Stopping speech kills the worker, which cannot then run its own cleanup. The
# audio lock it held used to sit there until it aged out, so every later
# utterance spun and gave up: "resumed" said yes and nothing played.
AUDIO_LOCK = vl.audio_lock_path()


def clear_audio_lock():
    try:
        os.unlink(AUDIO_LOCK)
    except OSError:
        pass


reset()
clear_audio_lock()
dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
dead.kill()
dead.wait()
time.sleep(0.3)
checks.append(("a killed process reads as not alive", not vl.pid_alive(dead.pid)))
checks.append(("this process reads as alive", vl.pid_alive(os.getpid())))

with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(dead.pid))
t0 = time.time()
got = vl.acquire_lock()
took = time.time() - t0
checks.append(("a lock owned by a dead process is taken", got is True))
checks.append(("...immediately, not after a long spin (%.2fs)" % took, took < 3))
vl.release_lock()

holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
time.sleep(0.4)
with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(holder.pid))
checks.append(("a lock owned by a LIVE process is respected",
               vl.acquire_lock(timeout=1) is False))
holder.kill()
holder.wait()
clear_audio_lock()

# stop_speaking must release a lock whose owner is gone -- but only then.
# An earlier version released it unconditionally, which is how a survivor that
# had not actually been killed ended up talking under a freshly started worker.
reset()
gone = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
gone.kill()
gone.wait()
time.sleep(0.3)
with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(gone.pid))                 # owner is dead
with open(vl.SPEAKER_LOCK, "w", encoding="utf-8") as f:
    f.write(str(gone.pid))
vl.set_inflight({"text": "x", "session": "A", "label": "L", "created": time.time()})
vl.stop_speaking(discard=True)
checks.append(("a lock left by a dead worker is released",
               not os.path.exists(AUDIO_LOCK)))
checks.append(("...and so is its speaker lock",
               not os.path.exists(vl.SPEAKER_LOCK)))
clear_audio_lock()

# release_lock must delete the file acquire_lock created. These built the path
# separately and disagreed about the suffix, so the lock was never released and
# only its staleness timer ever freed it -- minutes of silence at a time.
reset()
clear_audio_lock()
got = vl.acquire_lock(timeout=2)
checks.append(("acquire_lock takes the lock", got is True and os.path.exists(AUDIO_LOCK)))
vl.release_lock()
checks.append(("release_lock actually releases it", not os.path.exists(AUDIO_LOCK)))
checks.append(("...so it can be taken again straight away",
               vl.acquire_lock(timeout=2) is True))
vl.release_lock()
clear_audio_lock()

# --- a worker launched as pythonw must still be killable -----------------
# The hotkey runs pythonw.exe, so workers it spawns inherit that. The kill used
# taskkill's IMAGENAME filter with a single name, so it silently failed on those
# while the caller believed speech had stopped -- the survivor kept talking, the
# locks were released anyway, and the next worker started over the top of it.
PYW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")

if os.path.isfile(PYW):
    reset()
    worker = subprocess.Popen([PYW, "-c", "import time; time.sleep(60)"])
    time.sleep(0.7)
    checks.append(("a pythonw worker is recognised",
                   vl.process_image(worker.pid) == "pythonw.exe"))
    checks.append(("a pythonw worker is killed", vl._kill_tree(worker.pid) is True))
    checks.append(("...and is genuinely gone", not vl.pid_alive(worker.pid)))
    try:
        worker.kill()
    except Exception:
        pass

reset()
plain = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
time.sleep(0.6)
checks.append(("a python worker is killed too", vl._kill_tree(plain.pid) is True))
try:
    plain.kill()
except Exception:
    pass

# and a recycled PID belonging to something else is left alone
reset()
foreign = subprocess.Popen(["notepad.exe"])
time.sleep(0.8)
checks.append(("a process that is not ours is refused",
               vl._kill_tree(foreign.pid) is False))
checks.append(("...and survives", vl.pid_alive(foreign.pid)))
foreign.kill()
foreign.wait()

# --- locks must not be released while their owner is still speaking ------
reset()
clear_audio_lock()
survivor = subprocess.Popen(["notepad.exe"])          # unkillable by us, stands in
time.sleep(0.8)
with open(vl.SPEAKER_LOCK, "w", encoding="utf-8") as f:
    f.write(str(survivor.pid))
with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(survivor.pid))

vl.stop_speaking(discard=False)
checks.append(("a live un-killed worker keeps its speaker lock",
               os.path.exists(vl.SPEAKER_LOCK)))
checks.append(("...and keeps the audio lock, so nothing talks over it",
               os.path.exists(AUDIO_LOCK)))
survivor.kill()
survivor.wait()
try:
    os.unlink(vl.SPEAKER_LOCK)
except OSError:
    pass
clear_audio_lock()

# --- a long utterance must not have its lock stolen ---------------------
reset()
clear_audio_lock()
holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
time.sleep(0.5)
with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(holder.pid))
old_mtime = time.time() - 600                          # pretend it is 10 min old
os.utime(AUDIO_LOCK, (old_mtime, old_mtime))
checks.append(("a live owner is never stolen from, however old the lock",
               vl.acquire_lock(timeout=1) is False))
holder.kill()
holder.wait()
time.sleep(0.3)
checks.append(("...but once that owner dies the lock is free",
               vl.acquire_lock(timeout=2) is True))
vl.release_lock()
clear_audio_lock()

# --- the thing making sound must be stopped, even with no speaker lock ----
# A worker that lost its speaker lock while still playing left nothing to
# target: the press reported success, released the locks, and the audio carried
# on -- then the next worker took the free lock and played over the top of it.
reset()
clear_audio_lock()
player = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
time.sleep(0.6)
with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(player.pid))              # holds the device
# deliberately NO speaker lock: the state that broke it
try:
    os.unlink(vl.SPEAKER_LOCK)
except OSError:
    pass

stopped, _ = vl.stop_speaking(discard=False)
checks.append(("with no speaker lock, the audio holder is still killed",
               stopped is True))
checks.append(("...and it is genuinely gone", not vl.pid_alive(player.pid)))
checks.append(("...and the audio lock is freed", not os.path.exists(AUDIO_LOCK)))
try:
    player.kill()
except Exception:
    pass
clear_audio_lock()

# both owners get stopped when they differ
reset()
clear_audio_lock()
a = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
b = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
time.sleep(0.7)
with open(AUDIO_LOCK, "w", encoding="utf-8") as f:
    f.write(str(a.pid))
with open(vl.SPEAKER_LOCK, "w", encoding="utf-8") as f:
    f.write(str(b.pid))
vl.stop_speaking(discard=False)
checks.append(("a split audio/worker pair: both are stopped",
               not vl.pid_alive(a.pid) and not vl.pid_alive(b.pid)))
for proc in (a, b):
    try:
        proc.kill()
    except Exception:
        pass
clear_audio_lock()

reset()
print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
