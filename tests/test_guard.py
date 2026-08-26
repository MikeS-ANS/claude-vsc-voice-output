"""The exact reported case: mic clear when checked, busy by the time audio is ready."""
import os
import shutil
import sys
import time

HOOKS = os.environ.get("CLAUDE_VOICE_HOOKS",
                       os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, HOOKS)
import voice_lib as vl

# These suites test queue/mic logic, not lock handling, and may run on a
# locked machine -- pin the lock signal off.
vl.workstation_locked = lambda: False

HUB = r"c:\Dev\Anchor-Hub"
CFG = {"respect_microphone": True, "max_defer_seconds": 10, "max_stale_seconds": 0,
       "announce_session": "auto", "microphone_ignore": []}

played = []
real_play = vl._play_wav
vl._play_wav = lambda wav: (played.append(wav) or True)

# Pretend synthesis succeeded instantly, so the test does not need real audio.
vl._synth_kokoro = lambda txt, wav, voice, rate: (open(wav, "wb").write(b"x") or True)


def reset(live=("A",)):
    del played[:]
    shutil.rmtree(vl.QUEUE_DIR, ignore_errors=True)
    for p in (vl.SPEAKER_LOCK, vl.LABELS_PATH, vl.LOCK_PATH + ".lck"):
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

# THE BUG: clear when the queue is checked, busy once audio is ready.
reset()
calls = {"n": 0}


def flaky_mic(cfg=None):
    calls["n"] += 1
    return calls["n"] > 1          # clear on the first check, busy afterwards


vl.microphone_in_use = flaky_mic
vl.enqueue("dictation started while this was rendering", "A", "Anchor Hub")
vl.drain_pending(CFG)
checks.append(("audio is NOT played when the mic goes busy mid-synthesis", played == []))
checks.append(("...and the summary is requeued, not lost", vl.queue_depth() == 1))
item = vl.queue_items()[0]
checks.append(("...requeued without the session name doubled up",
               item.get("text") == "dictation started while this was rendering"))

# Once the mic frees up, it plays.
reset()
vl.microphone_in_use = lambda cfg=None: False
vl.enqueue("spoken normally", "A", "Anchor Hub")
vl.drain_pending(CFG)
checks.append(("plays normally when the mic stays clear", len(played) == 1))

# A deferred summary must not be announced twice on the retry.
reset()
calls["n"] = 0
vl.microphone_in_use = flaky_mic
vl.enqueue("first try", "A", "Anchor Hub")
vl.drain_pending(CFG)
requeued = vl.queue_items()[0]
vl.microphone_in_use = lambda cfg=None: False
vl.drain_pending(CFG)
checks.append(("a requeued summary plays on the next attempt", len(played) == 1))
checks.append(("...and is not double-labelled",
               requeued.get("text", "").count("Anchor Hub") == 0))

# The guard is skipped entirely when the mic gate is off.
reset()
calls["n"] = 0
vl.microphone_in_use = flaky_mic
vl.enqueue("gate disabled", "A", "Anchor Hub")
vl.drain_pending({"respect_microphone": False, "max_defer_seconds": 10,
                  "max_stale_seconds": 0, "announce_session": "auto"})
checks.append(("mic gate off: plays regardless", len(played) == 1))

vl._play_wav = real_play
reset()
print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
