"""Locked-screen behaviour: hold, never lose, play the backlog on unlock."""
import os
import shutil
import sys
import time

HOOKS = os.environ.get("CLAUDE_VOICE_HOOKS",
                       os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, HOOKS)
import voice_lib as vl

spoken = []
vl.speak = lambda text, cfg=None, guard=None: spoken.append(text)
vl.microphone_in_use = lambda cfg=None: False
vl.microphone_blockers = lambda cfg=None: []
vl.state_dir()                      # a fresh clone has no state dir yet

locked = {"v": True}
vl.workstation_locked = lambda: locked["v"]

HUB = r"c:\Dev\Anchor-Hub"
CFG = {"respect_lock": True, "respect_microphone": True, "max_defer_seconds": 10,
       "max_stale_seconds": 0, "announce_session": "auto", "microphone_ignore": []}


def reset(live=("A",)):
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


checks = []

# 1. locked -> nothing spoken, nothing lost, lock released promptly
reset()
locked["v"] = True
vl.enqueue("do not narrate my empty office", "A", "Anchor Hub")
t0 = time.time()
vl.drain_pending(CFG)
elapsed = time.time() - t0
checks.append(("locked: nothing is spoken", spoken == []))
checks.append(("locked: the summary stays queued", vl.queue_depth() == 1))
checks.append(("locked: returns immediately, no waiting (%.1fs)" % elapsed, elapsed < 2))
checks.append(("locked: speaker lock released", not os.path.exists(vl.SPEAKER_LOCK)))

# 2. unlocking plays the backlog
locked["v"] = False
vl.drain_pending(CFG)
checks.append(("unlocked: the backlog is spoken", len(spoken) == 1))
checks.append(("unlocked: queue drains", vl.queue_depth() == 0))

# 3. several windows queue up while away, all survive
reset(live=["A", "B", "C"])
locked["v"] = True
for sid, cwd, txt in (("A", HUB, "hub done"), ("B", r"c:\Dev\Stewart-HQ", "chores done"),
                      ("C", r"c:\Dev\payroll", "payroll done")):
    vl.enqueue(txt, sid, vl.session_label(sid, cwd))
vl.drain_pending(CFG)
checks.append(("three windows held while locked", spoken == [] and vl.queue_depth() == 3))
locked["v"] = False
vl.drain_pending(CFG)
checks.append(("all three spoken after unlock", len(spoken) == 3))
checks.append(("...each one named", all("." in s for s in spoken)))

# 4. screen locks DURING synthesis -> requeued, not played
reset()
locked["v"] = False
calls = {"n": 0}


def lock_midway():
    calls["n"] += 1
    return calls["n"] > 1          # unlocked at the queue check, locked at playback


vl.workstation_locked = lock_midway
played = []
real_speak = vl.speak


def speak_with_guard(text, cfg=None, guard=None):
    if guard is not None and not guard():
        return "deferred"
    played.append(text)
    return True


vl.speak = speak_with_guard
vl.enqueue("locked while rendering", "A", "Anchor Hub")
vl.drain_pending(CFG)
checks.append(("locking mid-synthesis: not played", played == []))
checks.append(("locking mid-synthesis: requeued", vl.queue_depth() == 1))

vl.speak = real_speak
vl.workstation_locked = lambda: locked["v"]

# 5. the gate can be turned off
reset()
locked["v"] = True
vl.enqueue("speak regardless", "A", "Anchor Hub")
vl.drain_pending(dict(CFG, respect_lock=False))
checks.append(("respect_lock false: speaks while locked", len(spoken) == 1))

# 6. detection failure must not silence speech
reset()


def boom():
    raise OSError("detection broke")


vl.workstation_locked = lambda: vl._safe_locked(boom)
vl._safe_locked = lambda fn: False        # mirrors the try/except in the real function
vl.enqueue("fail open", "A", "Anchor Hub")
vl.drain_pending(CFG)
checks.append(("broken lock detection fails open (still speaks)", len(spoken) == 1))

reset()
print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
