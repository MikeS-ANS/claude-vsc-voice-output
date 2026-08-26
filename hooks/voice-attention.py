#!/usr/bin/env python
"""Notification hook: chime plus a persistent Windows toast when Claude needs input.

Deliberately silent -- this fires during calls and with people nearby.

Subscribes to ALL notification types and filters here, because matcher semantics for
this event are not worth guessing at. Every payload is logged so the filter can be
tightened against real data rather than assumptions.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl

DEBUG_LOG = os.path.join(vl.HOOKS_DIR, "voice-notify-debug.log")
FALLBACK = "Claude Code is waiting on you."

# Types that are informational, not a request for the user's attention.
IGNORE = ("auth_success", "quota_auto_resume_fired", "quota_auto_resume_stale",
          "quota_auto_resume_disabled", "elicitation_complete", "elicitation_response")


def log_payload(data, decision):
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                      decision, json.dumps(data, default=str)[:1200]))
    except Exception:
        pass


def notification_type(data):
    """The type field's name is not documented clearly, so check the likely candidates."""
    for key in ("notification_type", "notificationType", "type", "matcher", "reason",
                "hook_event_type", "event"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def main():
    cfg = vl.load_config()
    data = vl.read_hook_input()
    ntype = notification_type(data)

    if ntype and any(ntype.startswith(i) for i in IGNORE):
        log_payload(data, "SKIPPED type=%s" % ntype)
        return

    log_payload(data, "ALERTED type=%s" % (ntype or "<unknown>"))

    vl.chime()

    if not cfg.get("toast", True):
        return

    body = vl.clean_for_speech(data.get("message") or "") or FALLBACK
    if len(body) > 200:
        body = body[:197].rstrip() + "..."

    cwd = data.get("cwd") or ""
    project = os.path.basename(cwd.rstrip(r"\/")) if cwd else ""
    title = "Claude Code" + (" - " + project if project else "")

    if not vl.toast(title, body):
        vl.log_problem("toast failed to display (type=%s)" % (ntype or "unknown"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        vl.log_problem("voice-attention crashed: %r" % (exc,))
    sys.exit(0)
