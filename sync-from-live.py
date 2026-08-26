#!/usr/bin/env python
"""Copy the live hooks back into this repo, showing what changed first.

The live copy at %USERPROFILE%\\.claude\\hooks is what actually runs. This repo is
what gets shared. Editing the live copy is the fast way to iterate, which means
the repo silently goes stale -- this makes that drift visible.

    python sync-from-live.py            report differences, change nothing
    python sync-from-live.py --diff     show the actual line-by-line changes
    python sync-from-live.py --apply    copy live -> repo

Deliberately one-directional. Going the other way (repo -> live) is install.py,
so there is never a question about which command overwrote what.

Never copied: logs (they contain real session content), voice-config.json (it is
your personal settings), claude-logo.png (Anthropic's mark), .venv.
"""

import argparse
import difflib
import filecmp
import io
import os
import shutil
import sys

REPO_HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks")
LIVE = os.environ.get("CLAUDE_VOICE_HOOKS",
                      os.path.join(os.path.expanduser("~"), ".claude", "hooks"))

TRACKED = ["voice_lib.py", "voice-turn-start.py", "voice-stop.py", "voice-attention.py",
           "voice-say.py", "voice-voices.py", "voice-toggle.py", "voice-setup-toast.py",
           "kokoro_synth.py"]


def read(path):
    try:
        return io.open(path, encoding="utf-8").read().splitlines(keepends=True)
    except OSError:
        return None


def classify():
    """Return (changed, only_live, only_repo, identical)."""
    changed, only_live, only_repo, same = [], [], [], []
    for name in TRACKED:
        live = os.path.join(LIVE, name)
        repo = os.path.join(REPO_HOOKS, name)
        if not os.path.isfile(live) and os.path.isfile(repo):
            only_repo.append(name)
        elif os.path.isfile(live) and not os.path.isfile(repo):
            only_live.append(name)
        elif not os.path.isfile(live):
            continue
        elif filecmp.cmp(live, repo, shallow=False):
            same.append(name)
        else:
            changed.append(name)
    return changed, only_live, only_repo, same


def line_delta(name):
    live = read(os.path.join(LIVE, name)) or []
    repo = read(os.path.join(REPO_HOOKS, name)) or []
    added = removed = 0
    for line in difflib.ndiff(repo, live):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--diff", action="store_true", help="show line-by-line changes")
    ap.add_argument("--apply", action="store_true", help="copy live -> repo")
    args = ap.parse_args()

    if not os.path.isdir(LIVE):
        print("No live hooks folder at %s" % LIVE)
        return 1

    print("live: %s" % LIVE)
    print("repo: %s\n" % REPO_HOOKS)

    changed, only_live, only_repo, same = classify()

    if not (changed or only_live or only_repo):
        print("In sync -- all %d tracked scripts match." % len(same))
        return 0

    for name in changed:
        added, removed = line_delta(name)
        print("  changed   %-26s +%d -%d" % (name, added, removed))
    for name in only_live:
        print("  new       %-26s (in live, not yet in the repo)" % name)
    for name in only_repo:
        print("  MISSING   %-26s (in the repo, not in live)" % name)
    if same:
        print("\n  %d script(s) already match." % len(same))

    if args.diff:
        for name in changed:
            print("\n" + "=" * 70)
            print(name)
            print("=" * 70)
            sys.stdout.writelines(difflib.unified_diff(
                read(os.path.join(REPO_HOOKS, name)) or [],
                read(os.path.join(LIVE, name)) or [],
                fromfile="repo/" + name, tofile="live/" + name))

    if not args.apply:
        print("\nNothing copied. Re-run with --apply to update the repo,"
              " or --diff to see the changes.")
        return 0

    for name in changed + only_live:
        shutil.copy2(os.path.join(LIVE, name), os.path.join(REPO_HOOKS, name))
    print("\nCopied %d file(s) into the repo." % len(changed + only_live))
    if only_repo:
        print("Left alone: %s -- present here but not in live, so possibly deleted"
              " on purpose. Remove by hand if that was intended."
              % ", ".join(only_repo))
    print("\nReview with `git diff`, then commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
