"""The Stop hook must block a turn that owes a summary, a push, or both."""
import io
import json
import os
import shutil
import subprocess
import sys
import time

HOOKS = os.environ.get("CLAUDE_VOICE_HOOKS",
                       os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, HOOKS)
import voice_lib as vl

CFG_PATH = os.path.join(HOOKS, "voice-config.json")
SID = "enforce-test"

SUMMARY = "<!-- SPEAK\nAll done here.\nSPEAK -->"
PUSHED = "<!-- PUSHED -->"


def write_cfg(**kw):
    base = json.load(io.open(CFG_PATH + ".orig", encoding="utf-8"))
    base.update(kw)
    io.open(CFG_PATH, "w", encoding="utf-8", newline="\n").write(json.dumps(base, indent=2) + "\n")


def stop(message):
    payload = {"session_id": SID, "hook_event_name": "Stop", "cwd": r"c:\Dev",
               "last_assistant_message": message}
    p = subprocess.run(["python", os.path.join(HOOKS, "voice-stop.py")],
                       input=json.dumps(payload).encode(), capture_output=True, cwd=HOOKS)
    return p.returncode, p.stderr.decode(errors="replace")


def fresh():
    vl.clear_nudge(SID)
    shutil.rmtree(vl.QUEUE_DIR, ignore_errors=True)
    with open(vl.turn_stamp_path(SID), "w", encoding="utf-8") as f:
        f.write(str(time.time() - 5))


shutil.copy(CFG_PATH, CFG_PATH + ".orig")
checks = []
try:
    # away_seconds 0 makes "away" always true; max_stale 0 keeps nothing discarded
    AWAY = dict(away_seconds=0, push_when_away=True, respect_lock=False,
                respect_microphone=False)
    HOME = dict(away_seconds=999999, push_when_away=True, respect_lock=False,
                respect_microphone=False)

    # --- away, has summary but no push -> blocked, asks for the push ---
    write_cfg(**AWAY); fresh()
    rc, err = stop("text " + SUMMARY)
    checks.append(("away without a push: turn is blocked", rc == 2))
    checks.append(("...and it asks for PushNotification", "PushNotification" in err))
    checks.append(("...and does not re-ask for the summary", "SPEAK -->" not in err))

    # --- away, summary + marker -> allowed ---
    write_cfg(**AWAY); fresh()
    rc, err = stop("text " + SUMMARY + "\n" + PUSHED)
    checks.append(("away with the marker: turn proceeds", rc == 0 and not err))

    # --- away, explicit skip marker is accepted ---
    write_cfg(**AWAY); fresh()
    rc, err = stop("text " + SUMMARY + "\n<!-- PUSHED: skipped -->")
    checks.append(("a deliberate skip is accepted", rc == 0 and not err))

    # --- away, missing BOTH -> asks for both in one message ---
    write_cfg(**AWAY); fresh()
    rc, err = stop("bare text with nothing")
    checks.append(("missing both: blocked once", rc == 2))
    checks.append(("...asks for the summary", "SPEAK" in err))
    checks.append(("...and the push, in the same message", "PushNotification" in err))

    # --- at the desk: a push is never demanded ---
    write_cfg(**HOME); fresh()
    rc, err = stop("text " + SUMMARY)
    checks.append(("at the desk: no push demanded", rc == 0 and not err))

    # --- push_when_away off: never demanded even when away ---
    write_cfg(**dict(AWAY, push_when_away=False)); fresh()
    rc, err = stop("text " + SUMMARY)
    checks.append(("push_when_away off: not demanded", rc == 0 and not err))

    # --- only one block per turn, so a turn can always finish ---
    write_cfg(**AWAY); fresh()
    rc1, _ = stop("bare text")
    rc2, _ = stop("bare text again")
    checks.append(("blocks at most once per turn", rc1 == 2 and rc2 == 0))

    # --- speak=false disables all of it ---
    write_cfg(**dict(AWAY, speak=False)); fresh()
    rc, err = stop("bare text")
    checks.append(("speak=false never blocks a turn", rc == 0 and not err))
finally:
    shutil.move(CFG_PATH + ".orig", CFG_PATH)
    vl.clear_nudge(SID)
    shutil.rmtree(vl.QUEUE_DIR, ignore_errors=True)

print()
ok = True
for name, passed in checks:
    print(("  PASS  " if passed else "  FAIL  ") + name)
    ok = ok and passed
print("\nconfig restored:", json.load(io.open(CFG_PATH, encoding="utf-8"))["away_seconds"],
      "away_seconds")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
