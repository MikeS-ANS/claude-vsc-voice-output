#!/usr/bin/env python
"""Register the toast identity so notifications are attributed to Claude, not Windows PowerShell.

Writes one key under HKEY_CURRENT_USER (no admin required). Re-runnable and idempotent.
Undo with:  python voice-setup-toast.py --remove
"""

import os
import sys
import winreg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_lib as vl

KEY_PATH = r"SOFTWARE\Classes\AppUserModelId\{}".format(vl.APP_ID)


def register():
    if not os.path.isfile(vl.ICON_PATH):
        print("WARNING: icon missing at {} -- the toast will fall back to no icon."
              .format(vl.ICON_PATH))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY_PATH) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, vl.APP_DISPLAY_NAME)
        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, vl.ICON_PATH)
        winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ, "0")
    print("registered HKCU: {}".format(KEY_PATH))
    print("  DisplayName = {}".format(vl.APP_DISPLAY_NAME))
    print("  IconUri     = {}".format(vl.ICON_PATH))


def remove():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY_PATH)
        print("removed HKCU: {}".format(KEY_PATH))
    except FileNotFoundError:
        print("nothing to remove")


def verify():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH) as key:
            return {name: winreg.QueryValueEx(key, name)[0]
                    for name in ("DisplayName", "IconUri", "IconBackgroundColor")}
    except FileNotFoundError:
        return None


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        register()
        print("\nread back from registry: {}".format(verify()))
