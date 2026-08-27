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
vl.state_dir()                      # a fresh clone has no state dir yet

HUB = r"c:\Dev\Anchor-Hub"
CFG = {"respect_microphone": True, "max_defer_seconds": 10, "max_stale_seconds": 0,
       "announce_session": "auto", "microphone_ignore": []}

played = []
real_play = vl._play_wav
vl._play_wav = lambda wav: (played.append(wav) or True)

# The mic is mocked at microphone_users: the ONE seam that both the queue gate
# (mic_busy -> microphone_in_use) and the pre-playback guard (hold_reason ->
# microphone_blockers) read through. Patching microphone_in_use instead reaches
# only the queue gate, leaving the guard to consult the real microphone -- which
# passes on a machine whose mic happens to be free and fails on one where an
# always-on app holds it. Neither outcome tests anything.
mic = {"busy": False, "arm": False}
vl.microphone_users = lambda: ["Teams.exe"] if mic["busy"] else []

synths = {"n": 0}


def synth(txt, wav, voice, rate):
    """Pretend synthesis succeeded instantly, so no real audio is needed.

    When armed, the mic goes busy DURING synthesis -- the reported bug. A
    call-counting mock cannot express this: drain_pending calls mic_busy twice
    before it dequeues, so a counter is spent on the pre-checks and the run
    bails out before the guard is ever reached.
    """
    synths["n"] += 1
    with open(wav, "wb") as f:
        f.write(b"x")
    if mic["arm"]:
        mic["busy"] = True
    return True


vl._synth_kokoro = synth


def reset(live=("A",), busy=False, arm=False):
    del played[:]
    synths["n"] = 0
    mic["busy"], mic["arm"] = busy, arm
    shutil.rmtree(vl.QUEUE_DIR, ignore_errors=True)
    for p in (vl.SPEAKER_LOCK, vl.LABELS_PATH, vl.LOCK_PATH):
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

# THE BUG: clear at both pre-checks, busy once the audio is ready.
reset(arm=True)
vl.enqueue("dictation started while this was rendering", "A", "Anchor Hub")
vl.drain_pending(CFG)
checks.append(("the guard was actually reached (synthesis ran)", synths["n"] == 1))
checks.append(("audio is NOT played when the mic goes busy mid-synthesis", played == []))
checks.append(("...and the summary is requeued, not lost", vl.queue_depth() == 1))
item = vl.queue_items()[0]
checks.append(("...requeued without the session name doubled up",
               item.get("text") == "dictation started while this was rendering"))

# Busy the whole time: it never even dequeues, and nothing is lost.
reset(busy=True)
vl.enqueue("wait for the call to end", "A", "Anchor Hub")
vl.drain_pending(dict(CFG, max_defer_seconds=0))
checks.append(("busy throughout: nothing played", played == []))
checks.append(("busy throughout: summary still queued", vl.queue_depth() == 1))

# Once the mic frees up, it plays.
reset()
vl.enqueue("spoken normally", "A", "Anchor Hub")
vl.drain_pending(CFG)
checks.append(("plays normally when the mic stays clear", len(played) == 1))

# A deferred summary must not be announced twice on the retry.
reset(arm=True)
vl.enqueue("first try", "A", "Anchor Hub")
vl.drain_pending(CFG)
requeued = vl.queue_items()[0] if vl.queue_depth() else {}
mic["busy"], mic["arm"] = False, False
vl.drain_pending(CFG)
checks.append(("a requeued summary plays on the next attempt", len(played) == 1))
checks.append(("...and is not double-labelled",
               requeued.get("text", "").count("Anchor Hub") == 0))

# The guard is skipped entirely when the mic gate is off.
reset(arm=True)
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
