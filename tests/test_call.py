"""Verify call handling: queue during a call, play the backlog when it ends."""
import os
import shutil
import sys
import threading
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
from _isolate import isolate, stub_synthesis

isolate(vl)          # private state dir; no cross-suite leakage
stub_synthesis(vl)   # instant, silent synthesis

# These suites test queue/mic logic, not lock handling, and may run on a
# locked machine -- pin the lock signal off.
vl.workstation_locked = lambda: False

spoken = []
# **kw so adding a parameter to speak() cannot silently break the suite
vl.speak = lambda text, cfg=None, **kw: spoken.append(text)

on_call = {"v": True}
vl.microphone_users = lambda: ["Cytracom Desktop.exe"] if on_call["v"] else []

HUB = r"c:\Dev\Anchor-Hub"
STEW = r"c:\Dev\Stewart-HQ"
CFG = {"respect_microphone": True, "max_defer_seconds": 60,
       "max_stale_seconds": 0, "announce_session": "auto", "microphone_ignore": []}


def reset(live=()):
    del spoken[:]
    shutil.rmtree(vl.QUEUE_DIR, ignore_errors=True)
    for p in (vl.SPEAKER_LOCK, vl.LABELS_PATH):
        try:
            os.unlink(p)
        except OSError:
            pass
    for n in list(os.listdir(vl.STATE_DIR)):
        if n.startswith("turn-"):
            try:
                os.unlink(os.path.join(vl.STATE_DIR, n))
            except OSError:
                pass
    for sid in live:
        with open(vl.turn_stamp_path(sid), "w", encoding="utf-8") as f:
            f.write(str(time.time()))


def enq(text, sid, cwd):
    return vl.enqueue(text, sid, vl.session_label(sid, cwd))


checks = []

# A worker starts waiting during a call; more summaries arrive mid-wait; the
# call ends; everything queued should be spoken, oldest first.
reset(live=["A", "B"])
on_call["v"] = True
enq("payroll is done", "A", HUB)

def add_more():
    time.sleep(6)
    enq("chores updated", "B", STEW)     # arrives while the worker is waiting
    time.sleep(4)
    enq("payroll revised", "A", HUB)     # a SECOND turn from the same window
    time.sleep(4)
    on_call["v"] = False                 # hang up

threading.Thread(target=add_more, daemon=True).start()

t0 = time.time()
vl.drain_pending(CFG)
elapsed = time.time() - t0

joined = " | ".join(spoken)
checks.append(("waited through the call (%.0fs)" % elapsed, elapsed >= 10))
checks.append(("spoke everything queued once the call ended", len(spoken) == 3))
checks.append(("kept the other window's summary", "chores updated" in joined))
checks.append(("kept BOTH turns from the same window",
               "payroll is done" in joined and "payroll revised" in joined))
checks.append(("...oldest first", spoken[0].endswith("payroll is done")))
checks.append(("named both windows", "Anchor Hub" in joined and "Stewart HQ" in joined))
checks.append(("queue is empty afterwards", vl.queue_depth() == 0))
checks.append(("speaker lock released", not os.path.exists(vl.SPEAKER_LOCK)))

# A second worker must not double-speak while the first is waiting on a call.
reset(live=["A"])
on_call["v"] = True
enq("held", "A", HUB)
assert vl.become_speaker()
vl.drain_pending(CFG)
checks.append(("a second worker stays out of the way while one waits",
               spoken == [] and vl.queue_depth() == 1))
vl.release_speaker()

reset()
print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
