#!/usr/bin/env python
"""Speak text aloud. Also the background worker that drains the queued utterance.

  python voice-say.py "some text"          speak immediately
  python voice-say.py --file F             speak the contents of a file
  python voice-say.py --drain              worker mode, used by the hooks
  python voice-say.py --mic                report what is holding the microphone
  python voice-say.py --diagnose           check the whole audio path out loud
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl


def main():
    args = sys.argv[1:]

    if "--mic" in args:
        users = vl.microphone_users()
        print("microphone in use by: %s" % (", ".join(users) if users else "nothing"))
        return 0

    if "--drain" in args:
        vl.drain_pending()
        return 0

    if "--diagnose" in args:
        # Errors are printed here rather than swallowed: showing what is wrong is
        # the entire point of this mode, and __main__ deliberately exits 0 on any
        # exception so that a voice bug can never wedge a turn.
        try:
            return vl.diagnose()
        except Exception:
            import traceback
            traceback.print_exc()
            return 1

    delete_after = "--delete-after" in args
    args = [a for a in args if a != "--delete-after"]

    path = None
    if args and args[0] == "--file":
        if len(args) < 2:
            return 2
        path = args[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return 2
    else:
        text = " ".join(args)

    try:
        vl.speak(text)
    finally:
        if delete_after and path:
            try:
                os.unlink(path)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
