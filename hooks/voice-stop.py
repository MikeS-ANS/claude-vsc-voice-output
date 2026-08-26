#!/usr/bin/env python
"""Stop hook: decide, fast, what should happen at the end of a turn.

Runs synchronously so it can block the stop, so it must not do anything slow --
actual speech is handed to a detached process.

  summary present + user away  -> speak it
  summary missing + user away  -> exit 2 once, making Claude write one
  still missing after that     -> speak a generic "I'm done" so silence is never ambiguous
  user at the keyboard         -> do nothing
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl

SPEAK_RE = re.compile(r"<!--\s*SPEAK\s*(.*?)\s*SPEAK\s*-->", re.DOTALL)

DEMAND_SUMMARY = (
    "the user will hear nothing from this turn. Add the spoken summary block:\n"
    "<!-- SPEAK\nTwo to four plain sentences, first person, saying what you did or what "
    "you need from them.\nSPEAK -->\n"
    "No file paths, code, URLs, or special characters - it is read aloud."
)

DEMAND_PUSH = (
    "the user is away from this machine, so speech will not reach them. Call the "
    "PushNotification tool with one line under 200 characters, then add the marker "
    "<!-- PUSHED --> on its own line. If a push is genuinely not warranted, add "
    "<!-- PUSHED: skipped --> instead."
)

PUSH_MARKER = "<!-- PUSHED"

FLOOR = "I have finished over here and I am waiting on you."
MAX_NUDGES = 1


def main():
    cfg = vl.load_config()
    if not cfg.get("speak", True):
        return 0

    data = vl.read_hook_input()
    session = data.get("session_id")
    message = data.get("last_assistant_message") or ""
    cwd = data.get("cwd") or ""

    found = SPEAK_RE.findall(message)
    summary = found[-1].strip() if found else None

    if not vl.worth_interrupting(cfg, session):
        vl.clear_nudge(session)
        return 0

    # Away means speech is queued rather than heard, so a phone push is the only
    # channel that actually reaches them -- and the marker is how this hook can
    # tell whether Claude sent one.
    push_expected = (cfg.get("push_when_away", True) and vl.probably_away(cfg))
    pushed = PUSH_MARKER in message

    missing = []
    if not summary:
        missing.append(DEMAND_SUMMARY)
    if push_expected and not pushed:
        missing.append(DEMAND_PUSH)

    if missing and vl.nudge_count(session) < MAX_NUDGES:
        vl.set_nudge_count(session, vl.nudge_count(session) + 1)
        sys.stderr.write("Voice mode: " + " Also, ".join(missing))
        return 2                      # blocks the stop; Claude gets the message above

    vl.clear_nudge(session)

    if summary:
        vl.say_detached(summary, session, cwd)
        return 0

    vl.say_detached(cfg.get("floor_message") or FLOOR, session, cwd)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)                   # never wedge a turn because voice broke
