"""Verify the per-session queue: lossless across sessions, collapsing within one."""
import os
import shutil
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
from _isolate import isolate, set_config, stub_synthesis

isolate(vl)          # private state dir; no cross-suite leakage
stub_synthesis(vl)   # instant, silent synthesis

# These suites test queue/mic logic, not lock handling, and may run on a
# locked machine -- pin the lock signal off.
vl.workstation_locked = lambda: False

spoken = []
# **kw so adding a parameter to speak() cannot silently break the suite
vl.speak = lambda text, cfg=None, **kw: spoken.append(text)


def enq(text, sid, cwd):
    """Queue exactly as say_detached does, minus spawning a competing worker."""
    return vl.enqueue(text, sid, vl.session_label(sid, cwd))

HUB = r"c:\Dev\Anchor-Hub"
STEW = r"c:\Dev\Stewart-HQ"


def reset(live=()):
    del spoken[:]
    shutil.rmtree(vl.QUEUE_DIR, ignore_errors=True)
    for p in (vl.SPEAKER_LOCK, vl.LABELS_PATH):
        try:
            os.unlink(p)
        except OSError:
            pass
    for name in list(os.listdir(vl.STATE_DIR)):
        if name.startswith("turn-"):
            try:
                os.unlink(os.path.join(vl.STATE_DIR, name))
            except OSError:
                pass
    for sid in live:
        with open(vl.turn_stamp_path(sid), "w", encoding="utf-8") as f:
            f.write(str(time.time()))


CFG = {"respect_microphone": False, "max_defer_seconds": 30,
       "max_stale_seconds": 0, "announce_session": "auto"}
checks = []

# 1. two windows -> both heard, oldest first, each named
reset(live=["A", "B"])
enq("The payroll report is done.", "A", HUB)
time.sleep(0.05)
enq("The chore list is updated.", "B", STEW)
vl.drain_pending(CFG)
checks.append(("two windows: both summaries are heard", len(spoken) == 2))
checks.append(("...in arrival order", spoken[0].endswith("payroll report is done.")))
checks.append(("...each named by its project", spoken[0].startswith("Anchor Hub")
               and spoken[1].startswith("Stewart HQ")))

# 2. same window, three quick turns -> ALL are heard, oldest first.
# Each turn's summary describes different work, so collapsing loses information.
reset(live=["A"])
for t in ("first pass", "second pass", "third pass"):
    enq(t, "A", HUB)
    time.sleep(0.01)
vl.drain_pending(CFG)
checks.append(("one window: every turn is heard, none collapsed",
               len(spoken) == 3))
checks.append(("...in the order they happened",
               "first pass" in spoken[0] and "third pass" in spoken[2]))

# 3. single window -> no name announced (nothing to disambiguate)
reset(live=["A"])
enq("Only one window here.", "A", HUB)
vl.drain_pending(CFG)
checks.append(("single window: no project name spoken",
               spoken == ["Only one window here."]))

# 4. two windows on the SAME folder get distinct names
reset(live=["A", "B"])
enq("from the first window", "A", HUB)
time.sleep(0.05)
enq("from the second window", "B", HUB)
vl.drain_pending(CFG)
labels = [s.split(".")[0] for s in spoken]
checks.append(("same folder twice: names are distinguishable",
               len(set(labels)) == 2 and "Anchor Hub" in labels[0]))

# 5. labels stay put across turns
reset(live=["A", "B"])
first = vl.session_label("A", HUB)
vl.session_label("B", HUB)
checks.append(("a window keeps its name across turns",
               vl.session_label("A", HUB) == first))

# 6. mixed windows: everything is heard, interleaved by arrival time
reset(live=["A", "B"])
enq("A first", "A", HUB)
time.sleep(0.01)
enq("B only", "B", STEW)
time.sleep(0.01)
enq("A second", "A", HUB)
vl.drain_pending(CFG)
joined = " | ".join(spoken)
checks.append(("two windows interleaved: all three heard",
               len(spoken) == 3 and "A first" in joined and "B only" in joined
               and "A second" in joined))
checks.append(("...in arrival order across windows",
               "A first" in spoken[0] and "B only" in spoken[1]
               and "A second" in spoken[2]))

# 6b. the per-session cap stops a runaway window narrating without limit
reset(live=["A"])
set_config(vl, max_queued_per_session=3)      # enqueue trims as it writes
for n in range(6):
    enq("summary %d" % n, "A", HUB)
    time.sleep(0.01)
vl.drain_pending(CFG)
set_config(vl, max_queued_per_session=10)
checks.append(("a runaway window is capped", len(spoken) == 3))
checks.append(("...keeping the most recent, dropping the oldest",
               "summary 5" in spoken[-1] and not any("summary 0" in x for x in spoken)))

# 7. on a call -> summaries stay queued, none lost
reset(live=["A", "B"])
vl.microphone_in_use = lambda cfg=None: True
enq("held one", "A", HUB)
enq("held two", "B", STEW)
vl.drain_pending({"respect_microphone": True, "max_defer_seconds": 6,
                  "max_stale_seconds": 0, "announce_session": "auto"})
checks.append(("on a call: nothing spoken, nothing lost",
               spoken == [] and vl.queue_depth() == 2))

# 8. call ends -> the backlog plays
vl.microphone_in_use = lambda cfg=None: False
vl.drain_pending(CFG)
checks.append(("call ends: the whole backlog is spoken", len(spoken) == 2))

reset()
print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
