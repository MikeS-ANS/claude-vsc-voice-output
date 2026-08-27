#!/usr/bin/env python
"""Synthesize speech to WAV with Kokoro. Runs inside .venv, not the system Python.

  --list                       print available voice names, one per line
  --text-file F --wav O        synthesize F to O, then exit
  --server                     stay alive and synthesize on request

Server mode exists because loading the model costs a few seconds and the model is
the whole reason speech is slow to start. One-shot mode pays that cost per call,
so speaking a summary sentence by sentence paid it once per sentence -- slower in
total than not chunking at all. In server mode it is paid once, and each sentence
then takes about a second, which is short enough to hide behind the previous
sentence still playing.

Protocol: one JSON object per line on stdin, one per line on stdout.
  in : {"text": "...", "wav": "C:/path/out.wav", "voice": "af_heart", "speed": 1.0}
  out: {"ok": true}  or  {"ok": false, "error": "..."}
  in : {"quit": true}
"""

import argparse
import io
import json
import os
import sys
import wave

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "kokoro-onnx")
MODEL = os.path.join(CACHE, "kokoro-v1.0.onnx")
VOICES = os.path.join(CACHE, "voices-v1.0.bin")


def load():
    from kokoro_onnx import Kokoro
    return Kokoro(MODEL, VOICES)


def write_wav(path, samples, sample_rate):
    import numpy as np
    audio = np.asarray(samples, dtype=np.float32).flatten()
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.0:
        audio = audio / peak
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm.tobytes())


def synthesize(kokoro, text, wav, voice, speed, lang):
    samples, rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)
    write_wav(wav, samples, rate)


def serve(default_voice, default_speed, lang):
    """Read requests until stdin closes. The model is loaded once, here."""
    kokoro = load()
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            sys.stdout.write(json.dumps({"ok": False, "error": "bad json: %s" % exc}) + "\n")
            sys.stdout.flush()
            continue

        if request.get("quit"):
            return 0

        try:
            synthesize(kokoro,
                       request["text"],
                       request["wav"],
                       request.get("voice") or default_voice,
                       float(request.get("speed") or default_speed),
                       request.get("lang") or lang)
            reply = {"ok": True}
        except Exception as exc:
            reply = {"ok": False, "error": "%s: %s" % (exc.__class__.__name__, exc)}

        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--server", action="store_true")
    ap.add_argument("--text-file")
    ap.add_argument("--wav")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--lang", default="en-us")
    a = ap.parse_args()

    for path in (MODEL, VOICES):
        if not os.path.isfile(path):
            sys.stderr.write("missing model file: %s\n" % path)
            return 2

    if a.list:
        kokoro = load()
        names = kokoro.get_voices() if hasattr(kokoro, "get_voices") else sorted(kokoro.voices.keys())
        print("\n".join(sorted(names)))
        return 0

    if a.server:
        return serve(a.voice, a.speed, a.lang)

    if not (a.text_file and a.wav):
        sys.stderr.write("need --text-file and --wav, or --server\n")
        return 2

    text = io.open(a.text_file, encoding="utf-8").read().strip()
    if not text:
        return 0
    synthesize(load(), text, a.wav, a.voice, a.speed, a.lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
