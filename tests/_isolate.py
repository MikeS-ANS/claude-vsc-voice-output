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

    os.makedirs(vl.QUEUE_DIR, exist_ok=True)

    if not keep:
        import atexit
        atexit.register(lambda: shutil.rmtree(root, ignore_errors=True))
    return root
