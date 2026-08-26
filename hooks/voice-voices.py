#!/usr/bin/env python
"""List, audition, and choose the voice used for spoken summaries.

  python voice-voices.py                  list voices (Kokoro first, then Windows)
  python voice-voices.py --audition       hear the recommended English Kokoro voices
  python voice-voices.py --audition all   hear every English voice, Kokoro and Windows
  python voice-voices.py --say am_puck    hear one voice
  python voice-voices.py --set am_puck    save it as your voice
  python voice-voices.py --rate 1.1       save a speaking-rate multiplier
"""

import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl

SAMPLE = ("I finished reviewing the payroll export and found two entries that do not match "
          "the timesheet. I left the rest alone so you can check my work.")

# Kokoro codes: a=American b=British, f=female m=male. Everything else is another language.
ENGLISH = ("af_", "am_", "bf_", "bm_")

# A short, opinionated starting set so the first audition isn't 20 voices long.
SHORTLIST = ["am_michael", "am_puck", "am_fenrir", "am_adam",
             "af_heart", "af_bella", "af_nicole",
             "bm_george", "bm_lewis", "bf_emma"]


def label(name):
    if not name.startswith(ENGLISH):
        return name
    region = "British" if name[0] == "b" else "American"
    gender = "female" if name[1] == "f" else "male"
    return "%s (%s %s)" % (name, region, gender)


def kokoro_english():
    return [v for v in vl.kokoro_voices() if v.startswith(ENGLISH)]


def show():
    cfg = vl.load_config()
    current = (cfg.get("voice") or "").strip()
    fallback = (cfg.get("fallback_voice") or "").strip()

    kv = vl.kokoro_voices()
    if kv:
        print("KOKORO -- local neural, %d voices (%d English). This is what you hear."
              % (len(kv), len(kokoro_english())))
        for v in kokoro_english():
            mark = "  <- in use" if v == current else ""
            star = " *" if v in SHORTLIST else "  "
            print("   %s%-34s%s" % (star, label(v), mark))
        print("\n   (* = in the default audition set; %d non-English voices hidden)"
              % (len(kv) - len(kokoro_english())))
    else:
        print("KOKORO -- not installed. Falling back to Windows voices.")

    print("\nWINDOWS -- fallback only, used if Kokoro fails")
    for eng, name, lang in vl.list_voices():
        mark = "  <- fallback" if fallback and fallback.lower() in name.lower() else ""
        print("   %-7s %-34s %s%s" % (eng, name, lang, mark))

    print("\nrate: %s   engine: %s" % (cfg.get("rate"), cfg.get("engine")))


def audition(which):
    cfg = vl.load_config()
    rate = cfg.get("rate", 1.0)

    if which == "all":
        targets = [("kokoro", v) for v in kokoro_english()]
        targets += [("winrt", n) for e, n, _ in vl.list_voices() if e == "winrt"]
    else:
        available = set(vl.kokoro_voices())
        targets = [("kokoro", v) for v in SHORTLIST if v in available]

    if not targets:
        print("Nothing to audition.")
        return

    print("Auditioning %d voices. Ctrl+C to stop.\n" % len(targets))
    for engine, name in targets:
        print("   %s" % label(name))
        spoken = name.split("_")[-1] if engine == "kokoro" else name.replace("Microsoft ", "")
        opts = {"engine": engine, "rate": rate}
        opts["voice" if engine == "kokoro" else "fallback_voice"] = name
        vl.speak("This is %s. %s" % (spoken, SAMPLE), opts)
        time.sleep(0.3)

    print("\nPick one:  python voice-voices.py --set am_puck")


def save(**changes):
    cfg = json.load(io.open(vl.CONFIG_PATH, encoding="utf-8"))
    cfg.update(changes)
    io.open(vl.CONFIG_PATH, "w", encoding="utf-8", newline="\n").write(
        json.dumps(cfg, indent=2) + "\n")
    print("saved:", ", ".join("%s=%s" % kv for kv in changes.items()))


def arg_after(flag, default=None):
    a = sys.argv[1:]
    i = a.index(flag)
    return a[i + 1] if i + 1 < len(a) else default


def main():
    args = sys.argv[1:]

    if "--set" in args:
        name = arg_after("--set")
        kv = vl.kokoro_voices()
        if name in kv:
            save(voice=name)
        else:
            win = [n for _, n, _ in vl.list_voices() if name and name.lower() in n.lower()]
            if not win:
                print("No voice matches %r. Run with no arguments to see the list." % name)
                return 1
            save(fallback_voice=win[0], engine="winrt")
            print("note: that is a Windows voice, so the engine was switched to winrt.")
        vl.speak("Voice set. %s" % SAMPLE)
        return 0

    if "--rate" in args:
        save(rate=float(arg_after("--rate", "1.0")))
        vl.speak(SAMPLE)
        return 0

    if "--say" in args:
        name = arg_after("--say")
        cfg = vl.load_config()
        opts = {"rate": cfg.get("rate", 1.0)}
        if name in vl.kokoro_voices():
            opts.update(engine="kokoro", voice=name)
        else:
            opts.update(engine="winrt", fallback_voice=name)
        print("speaking as %s ..." % label(name))
        vl.speak("This is %s. %s" % (name.split("_")[-1], SAMPLE), opts)
        return 0

    if "--audition" in args:
        audition((arg_after("--audition") or "short").lower())
        return 0

    show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
