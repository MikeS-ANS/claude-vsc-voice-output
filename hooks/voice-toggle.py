#!/usr/bin/env python
"""Turn spoken summaries on or off, and show current state.

  python voice-toggle.py            show what is on right now
  python voice-toggle.py stop       CUT OFF speech playing right now, drop the queue
  python voice-toggle.py pause      cut off what is playing, keep it for later
  python voice-toggle.py off        stop speaking (also stops Claude writing summaries)
  python voice-toggle.py on         start speaking again
  python voice-toggle.py quiet      speak only when you step away or a turn runs long
  python voice-toggle.py always     speak on every turn (the default)
  python voice-toggle.py toast off  turn Windows toast notifications on or off
  python voice-toggle.py mic off    speak even while you are on a call
  python voice-toggle.py lock off   speak even while the screen is locked
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl


def save(**changes):
    cfg = json.load(io.open(vl.CONFIG_PATH, encoding="utf-8"))
    cfg.update(changes)
    io.open(vl.CONFIG_PATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(cfg, indent=2) + "\n")
    return cfg


def status():
    cfg = vl.load_config()
    speak = cfg.get("speak", True)
    always = cfg.get("always_speak", True)

    print("Speech      : %s" % ("ON" if speak else "OFF"))
    if speak:
        print("When        : %s" % ("every turn" if always else
                                    "only when you step away (%ss) or a turn runs long (%ss)"
                                    % (cfg.get("idle_seconds"), cfg.get("long_turn_seconds"))))
        print("Voice       : %s at %sx" % (cfg.get("voice"), cfg.get("rate")))
        print("Engine      : %s%s" % (cfg.get("engine"),
                                      "" if vl.kokoro_available() else "  (Kokoro NOT installed)"))
    print("Toasts      : %s" % ("ON" if cfg.get("toast", True) else "OFF"))

    if cfg.get("respect_lock", True):
        print("Screen      : %s" % ("LOCKED -- speech is being held"
                                    if vl.workstation_locked() else "unlocked"))
    else:
        print("Screen      : ignored (will speak to a locked machine)")

    if cfg.get("respect_microphone", True):
        blockers = vl.microphone_blockers(cfg)
        if blockers:
            print("Microphone  : IN USE by %s -- speech is being held"
                  % ", ".join(blockers[:2]))
        else:
            others = vl.microphone_users()
            note = "  (ignoring %d always-on app(s))" % len(others) if others else ""
            print("Microphone  : clear%s" % note)
    else:
        print("Microphone  : ignored (will speak during calls)")

    depth = vl.queue_depth()
    if depth:
        print("Queued      : %d summary(s) waiting" % depth)
        for item in vl.queue_items():
            print("              %-14s %s" % (item.get("label", "?"),
                                              (item.get("text") or "")[:52]))
    else:
        print("Queued      : nothing waiting")

    live = vl.live_sessions()
    print("Windows     : %d active%s" % (len(live),
          "  (each summary will be named)" if len(live) > 1 else ""))

    print("\nTakes effect immediately in every window -- no restart needed.")


def main():
    args = [a.lower() for a in sys.argv[1:]]

    if not args:
        status()
        return 0

    if args[0] in ("stop", "shutup", "quiet!"):
        stopped, discarded = vl.stop_speaking(discard=True)
        print("Stopped." if stopped else "Nothing was playing.")
        if discarded:
            print("Discarded %d queued summary(s) as well." % discarded)
        return 0

    if args[0] in ("pause", "hold", "later"):
        stopped, _ = vl.stop_speaking(discard=False)
        depth = vl.queue_depth()
        print("Paused." if stopped else "Nothing was playing.")
        print("%d summary(s) waiting -- they play on your next turn." % depth
              if depth else "Nothing left queued.")
        return 0

    if args[0] in ("lock", "locked", "screen"):
        want = args[1] if len(args) > 1 else "on"
        save(respect_lock=(want == "on"))
        print("Lock gate %s. %s" % (
            want.upper(),
            "Summaries wait while the screen is locked." if want == "on"
            else "Speech will play to a locked machine."))
        return 0

    if args[0] in ("mic", "microphone"):
        want = args[1] if len(args) > 1 else "on"
        save(respect_microphone=(want == "on"))
        print("Microphone gate %s. %s" % (
            want.upper(),
            "Speech waits while an app holds the mic." if want == "on"
            else "Speech will play during calls."))
        return 0

    if args[0] == "toast":
        want = args[1] if len(args) > 1 else "on"
        save(toast=(want == "on"))
        print("Toasts %s." % want.upper())
        return 0

    if args[0] in ("off", "0", "false", "mute"):
        save(speak=False)
        print("Speech OFF. Claude will also stop adding summary blocks to its replies.")
        return 0

    if args[0] in ("on", "1", "true"):
        cfg = save(speak=True)
        print("Speech ON (%s)." % ("every turn" if cfg.get("always_speak", True)
                                   else "only when you step away"))
        vl.say_detached("Speech is back on.")
        return 0

    if args[0] in ("always", "everytime", "every"):
        save(speak=True, always_speak=True)
        print("Speech ON, every turn.")
        vl.say_detached("I will speak after every turn now.")
        return 0

    if args[0] in ("quiet", "away", "idle"):
        save(speak=True, always_speak=False)
        print("Speech ON, but only when you step away or a turn runs long.")
        vl.say_detached("I will only speak when you step away.")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
