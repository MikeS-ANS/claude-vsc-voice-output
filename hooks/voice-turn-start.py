#!/usr/bin/env python
"""UserPromptSubmit hook: stamp the turn start time and tell Claude to append a spoken summary.

stdout from UserPromptSubmit is added to Claude's context, so this is what keeps the
SPEAK-block instruction alive across compaction.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl

INSTRUCTION = """Voice mode is on. End EVERY response with a spoken-summary block:
<!-- SPEAK
Two to four plain sentences, first person, conversational.
SPEAK -->
A text-to-speech engine reads this aloud, so write it the way you would say it: no file
paths, code, URLs, abbreviations, or special characters. This is meant to replace reading
the screen, so lead with the outcome and what it means, not the steps you took. For a
trivial reply or a plain question, one short sentence is enough - but always include the
block, every turn."""

AWAY_NOTE = """The user is away from this machine (screen locked, or no keyboard activity
for a while), so the spoken summary will NOT be heard - it is queued instead. Reach them
on their phone: call the PushNotification tool with one line under 200 characters, leading
with the outcome. Then add this marker on its own line so the hook can confirm you did:
<!-- PUSHED -->
If the tool reports the push was not sent, still add the marker - it records that you
tried. Skip both only for a trivial reply, and say so in the marker line as
<!-- PUSHED: skipped -->."""


def main():
    cfg = vl.load_config()
    data = vl.read_hook_input()

    session = data.get("session_id")
    try:
        with open(vl.turn_stamp_path(session), "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    # A fresh turn owes at most one nudge, so reset the counter from last turn.
    vl.clear_nudge(session)

    vl.sweep_stale_state()

    if cfg.get("speak", True):
        print(INSTRUCTION)

        # Speech is suppressed when they are away, and no hook can raise a phone
        # notification -- only Claude can, by calling the tool. So say so here.
        if cfg.get("push_when_away", True) and vl.probably_away(cfg):
            print(AWAY_NOTE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
