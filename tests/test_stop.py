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

reset()
print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
