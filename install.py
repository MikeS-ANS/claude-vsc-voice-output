#!/usr/bin/env python
"""Install Claude Code voice summaries and notifications (Windows).

    python install.py                 install or update
    python install.py --dry-run       show what would change, touch nothing
    python install.py --no-model      skip the ~354MB Kokoro download
    python install.py --uninstall     remove the hooks (leaves files in place)

What it does:
  1. copies the hook scripts into %USERPROFILE%\\.claude\\hooks
  2. creates a virtual environment there and installs Kokoro (local neural TTS)
  3. downloads the Kokoro model into %USERPROFILE%\\.cache\\kokoro-onnx
  4. copies the Claude icon out of your installed VS Code extension
  5. registers a toast identity so notifications say "Claude VSC Notice"
  6. checks for apps that hold the microphone permanently, which would
     otherwise silence speech for good, and offers to ignore them
  7. registers three hooks in %USERPROFILE%\\.claude\\settings.json
  8. speaks a line so you know it works

It never overwrites an existing voice-config.json, and it leaves any hooks it
did not create alone.
"""

import argparse
import collections
import glob
import io
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SRC_HOOKS = os.path.join(REPO, "hooks")

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
DEST = os.path.join(CLAUDE_DIR, "hooks")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
VENV_PY = os.path.join(DEST, ".venv", "Scripts", "python.exe")
MODEL_DIR = os.path.join(HOME, ".cache", "kokoro-onnx")

SCRIPTS = ["voice_lib.py", "voice-turn-start.py", "voice-stop.py", "voice-attention.py",
           "voice-say.py", "voice-voices.py", "voice-toggle.py", "voice-setup-toast.py",
           "kokoro_synth.py"]

MODEL_BASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
              "model-files-v1.0")
MODEL_FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]

# event -> (script, synchronous?, timeout, matcher)
HOOKS = [
    ("UserPromptSubmit", "voice-turn-start.py", True, 10, None),
    ("Stop", "voice-stop.py", True, 15, None),
    ("Notification", "voice-attention.py", False, 30, ""),
]

DRY = False


def say(step, detail=""):
    print(("  " if step.startswith(" ") else "") + step + (("  " + detail) if detail else ""))


def act(description):
    if DRY:
        print("  [dry-run] would " + description)
        return False
    return True


# --- checks -----------------------------------------------------------------

def preflight():
    problems = []
    if sys.platform != "win32":
        problems.append("This is Windows-only: it uses Windows speech, toasts, and winsound.")
    if sys.version_info < (3, 12):
        problems.append("Python 3.12+ required for Kokoro; found %d.%d"
                        % sys.version_info[:2])
    if not os.path.isdir(CLAUDE_DIR):
        problems.append("No %s -- run Claude Code once before installing." % CLAUDE_DIR)
    if not os.path.isdir(SRC_HOOKS):
        problems.append("Cannot find the hooks folder next to install.py.")
    return problems


# --- steps ------------------------------------------------------------------

def copy_scripts():
    say("Copying hook scripts ->", DEST)
    if act("copy %d scripts into %s" % (len(SCRIPTS), DEST)):
        os.makedirs(DEST, exist_ok=True)
        for name in SCRIPTS:
            shutil.copy2(os.path.join(SRC_HOOKS, name), os.path.join(DEST, name))
        say(" copied", "%d scripts" % len(SCRIPTS))

    live = os.path.join(DEST, "voice-config.json")
    default = os.path.join(SRC_HOOKS, "voice-config.default.json")
    if os.path.isfile(live):
        say(" keeping your existing voice-config.json", "(settings preserved)")
    elif act("create voice-config.json from the default"):
        shutil.copy2(default, live)
        say(" created", "voice-config.json")


def make_venv():
    if os.path.isfile(VENV_PY):
        say("Virtual environment already present", VENV_PY)
    elif act("create a virtual environment in %s" % os.path.join(DEST, ".venv")):
        say("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", os.path.join(DEST, ".venv")], check=True)

    if not act("pip install kokoro-onnx numpy"):
        return
    say("Installing Kokoro (this takes a minute)...")
    subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False)
    r = subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet", "kokoro-onnx", "numpy"])
    if r.returncode != 0:
        say(" WARNING", "Kokoro install failed; Windows voices will be used instead.")
    else:
        say(" installed", "kokoro-onnx")


def fetch_model():
    if not act("download the Kokoro model (~354MB) into %s" % MODEL_DIR):
        return
    import urllib.request
    os.makedirs(MODEL_DIR, exist_ok=True)
    for name in MODEL_FILES:
        dest = os.path.join(MODEL_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            say(" already have", "%s (%.0f MB)" % (name, os.path.getsize(dest) / 1e6))
            continue
        say("Downloading %s ..." % name)
        urllib.request.urlretrieve(MODEL_BASE + "/" + name, dest)
        say(" downloaded", "%.0f MB" % (os.path.getsize(dest) / 1e6))


def copy_icon():
    """Take the Claude logo from the locally installed extension.

    Deliberately not committed to this repo -- it is Anthropic's mark, and the
    extension folder name changes with every update, so it must be found rather
    than hardcoded.
    """
    pattern = os.path.join(HOME, ".vscode", "extensions",
                           "anthropic.claude-code-*", "resources", "claude-logo.png")
    found = sorted(glob.glob(pattern))
    if not found:
        say("Claude icon not found", "(toasts will show without an icon)")
        return
    src = found[-1]
    if act("copy the Claude icon from %s" % os.path.basename(os.path.dirname(os.path.dirname(src)))):
        shutil.copy2(src, os.path.join(DEST, "claude-logo.png"))
        say(" icon copied", "from the installed extension")


ALWAYS_ON_MIC_HOURS = 2


def _duration(seconds):
    hours = seconds / 3600.0
    return "%.0f hours" % hours if hours < 48 else "%.0f days" % (hours / 24.0)


def check_microphone():
    """Offer to ignore apps that hold the microphone permanently.

    Speech is held while an app holds the mic, so an app that never releases it
    silences speech FOREVER -- and the only clue is a line in voice-errors.log,
    which nobody reads until they wonder why it went quiet. A real call lasts
    minutes; anything holding the device for hours is a companion app (headset,
    mouse, softphone, virtual audio device). Much cheaper to ask here than to
    debug silence later.
    """
    # SRC_HOOKS, not DEST: this installer ships alongside the voice_lib it was
    # written against. An older installed copy may predate microphone_holders().
    sys.path.insert(0, SRC_HOOKS)
    try:
        import voice_lib as vl
        holders = vl.microphone_holders()
    except Exception as exc:
        say("Microphone check", "skipped (%s)" % exc.__class__.__name__)
        return                                  # never block an install on this

    stuck = [(n, h) for n, h in holders if h >= ALWAYS_ON_MIC_HOURS * 3600]
    if not stuck:
        say("Microphone check", "nothing is holding the mic open")
        return

    cfg_path = os.path.join(DEST, "voice-config.json")
    try:
        cfg = json.load(io.open(cfg_path, encoding="utf-8"))
    except Exception:
        return
    ignore = list(cfg.get("microphone_ignore") or [])

    fresh = []
    say("Microphone check")
    for name, held in stuck:
        label = vl.mic_app_label(name)
        known = any(str(pat).lower() in label.lower() for pat in ignore)
        say(" %s has held the microphone for %s%s"
            % (label, _duration(held), "  (already ignored)" if known else ""))
        if not known:
            fresh.append(label)

    if not fresh:
        return

    print("\n  Speech is suppressed while an app holds the microphone, so it would stay"
          "\n  silent indefinitely. Say no if any of these holds the mic ONLY during real"
          "\n  calls -- ignoring such an app means speech will talk over them.\n")

    if not act("add %s to microphone_ignore" % ", ".join(fresh)):
        return
    try:
        answer = input("  Add %s to microphone_ignore? [Y/n] " % ", ".join(fresh)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        answer = "n"
    if answer and not answer.startswith("y"):
        say(" left alone", "edit microphone_ignore in %s if it goes quiet" % cfg_path)
        return

    cfg["microphone_ignore"] = ignore + fresh
    io.open(cfg_path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(cfg, indent=2) + "\n")
    say(" microphone_ignore", "now %s" % cfg["microphone_ignore"])


def register_toast():
    script = os.path.join(DEST, "voice-setup-toast.py")
    if not os.path.isfile(script):
        return
    if act("register the 'Claude VSC Notice' toast identity (HKCU, no admin)"):
        r = subprocess.run([sys.executable, script], capture_output=True, text=True)
        say(" toast identity", "registered" if r.returncode == 0 else "FAILED")


def hook_entry(script, synchronous, timeout, matcher):
    hook = collections.OrderedDict()
    hook["type"] = "command"
    hook["command"] = 'python "$HOME/.claude/hooks/%s"' % script
    if not synchronous:
        hook["async"] = True
    hook["timeout"] = timeout
    block = collections.OrderedDict()
    if matcher is not None:
        block["matcher"] = matcher
    block["hooks"] = [hook]
    return block


def register_hooks(remove=False):
    if not os.path.isfile(SETTINGS):
        settings = collections.OrderedDict()
    else:
        settings = json.load(io.open(SETTINGS, encoding="utf-8"),
                             object_pairs_hook=collections.OrderedDict)

    hooks = settings.setdefault("hooks", collections.OrderedDict())
    changed = []
    for event, script, sync, timeout, matcher in HOOKS:
        existing = hooks.setdefault(event, [])
        before = len(existing)
        # drop any earlier registration of this script so re-running is safe
        existing[:] = [b for b in existing
                       if not any(script in h.get("command", "")
                                  for h in b.get("hooks", []))]
        removed = before - len(existing)
        if not remove:
            existing.append(hook_entry(script, sync, timeout, matcher))
            changed.append("%s -> %s%s" % (event, script, " (replaced)" if removed else ""))
        else:
            changed.append("%s: removed %s" % (event, script) if removed
                           else "%s: %s was not registered" % (event, script))
        if not existing:
            del hooks[event]

    verb = "remove" if remove else "register"
    if act("%s %d hooks in %s" % (verb, len(HOOKS), SETTINGS)):
        io.open(SETTINGS, "w", encoding="utf-8", newline="\n").write(
            json.dumps(settings, indent=2) + "\n")
    for line in changed:
        say(" " + line)


def verify():
    if not act("speak a test line"):
        return
    script = os.path.join(DEST, "voice-say.py")
    say("Speaking a test line (first run loads the model, so allow ~10s)...")
    subprocess.run([sys.executable, script,
                    "Voice is installed. You will hear a short summary after each turn."],
                   check=False)


# --- main -------------------------------------------------------------------

def main():
    global DRY
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    DRY = args.dry_run

    problems = preflight()
    if problems:
        print("Cannot install:")
        for p in problems:
            print("  - " + p)
        return 1

    if args.uninstall:
        print("Removing voice hooks\n")
        register_hooks(remove=True)
        print("\nDone. Scripts and the model are still on disk; delete "
              "%s and %s to remove them." % (DEST, MODEL_DIR))
        return 0

    print("Installing Claude Code voice%s\n" % ("  [DRY RUN]" if DRY else ""))
    copy_scripts()
    make_venv()
    if not args.no_model:
        fetch_model()
    else:
        say("Skipping the model download", "(--no-model)")
    copy_icon()
    check_microphone()
    register_toast()
    register_hooks()
    verify()

    print("""
Done. The hooks usually start working straight away. If nothing happens on your
next turn, start a new Claude Code session.

  python %s\\voice-toggle.py          see what is on
  python %s\\voice-voices.py --audition   pick a voice
""" % (DEST, DEST))
    return 0


if __name__ == "__main__":
    sys.exit(main())
