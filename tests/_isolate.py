"""Give a test run its own state directory.

Every suite reaches the same %TEMP%\\claude_voice by default, so leftovers from
one leak into the next: stale turn stamps change how many sessions look "live",
which changes whether session labels get announced. The result is order
dependence -- test_call passes alone, fails after test_queue, passes again.

Call isolate() straight after importing voice_lib. It sets CLAUDE_VOICE_STATE so
any subprocess the suite spawns lands in the same private directory, then
repoints the already-imported module's paths at it.
"""

import os
import shutil
import tempfile


def isolate(vl, keep=False):
    """Point all voice_lib state at a private directory. Returns its path."""
    root = tempfile.mkdtemp(prefix="voice-test-")

    # Subprocesses read this at import, so they land in the same place.
    os.environ["CLAUDE_VOICE_STATE"] = root

    vl.STATE_DIR = root
    vl.QUEUE_DIR = os.path.join(root, "queue")
    vl.LABELS_PATH = os.path.join(root, "labels.json")
    vl.SPEAKER_LOCK = os.path.join(root, "speaker.lck")
    vl.LOCK_PATH = os.path.join(root, "speak.lock")
    vl.ERROR_LOG = os.path.join(root, "voice-errors.log")
    vl.SPOKEN_LOG = os.path.join(root, "voice-spoken.log")
    vl.INFLIGHT_PATH = os.path.join(root, "inflight.json")
    vl.PAUSE_PATH = os.path.join(root, "paused")
    vl.TOGGLE_LOCK = os.path.join(root, "toggle.lck")
    vl.TOGGLE_STAMP = os.path.join(root, "toggle.stamp")

    os.makedirs(vl.QUEUE_DIR, exist_ok=True)

    # A private config too, so a suite can set thresholds without touching the
    # user's real settings, and so anything it spawns reads the same values.
    cfg_path = os.path.join(root, "voice-config.json")
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "hooks", "voice-config.default.json")
    try:
        shutil.copy2(default, cfg_path)
    except OSError:
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("{}")
    os.environ["CLAUDE_VOICE_CONFIG"] = cfg_path
    vl.CONFIG_PATH = cfg_path

    if not keep:
        import atexit
        atexit.register(lambda: shutil.rmtree(root, ignore_errors=True))
    return root


def set_config(vl, **values):
    """Change the isolated config, as the product code will read it."""
    import json
    try:
        with open(vl.CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    cfg.update(values)
    with open(vl.CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=2)
    return cfg

def stub_synthesis(vl, on_synth=None):
    """Make synthesis instant and audio-free.

    Centralised deliberately: suites used to patch voice_lib's synthesis
    internals directly, so each change to how synthesis works broke several at
    once -- and a broken suite reports zero assertions, which reads as "nothing
    ran" rather than "something failed". Point this at the current seam and the
    suites do not need to know what it is.
    """
    def _synth(text_file, wav, voice, rate):
        if on_synth is not None:
            try:
                with open(text_file, "r", encoding="utf-8") as f:
                    on_synth(f.read())
            except OSError:
                on_synth("")
        try:
            with open(wav, "wb") as f:
                f.write(b"x")
        except OSError:
            return False
        return True

    vl._synth_kokoro = _synth
