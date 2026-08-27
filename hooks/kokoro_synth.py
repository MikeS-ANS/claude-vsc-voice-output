#!/usr/bin/env python
"""Synthesize speech to a WAV file with Kokoro. Runs inside .venv, not the system Python.

  --list                       print available voice names, one per line
  --text-file F --wav O        synthesize F to O
  --voice NAME --speed 1.0     voice and rate
"""

import argparse
import io
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--text-file")
    ap.add_argument("--wav")
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--lang", default="en-us")
    a = ap.parse_args()

    for p in (MODEL, VOICES):
        if not os.path.isfile(p):
            sys.stderr.write("missing model file: %s\n" % p)
            return 2

    k = load()

    if a.list:
        names = k.get_voices() if hasattr(k, "get_voices") else sorted(k.voices.keys())
        print("\n".join(sorted(names)))
        return 0

    if not (a.text_file and a.wav):
        sys.stderr.write("need --text-file and --wav\n")
        return 2

    text = io.open(a.text_file, encoding="utf-8").read().strip()
    if not text:
        return 0

    samples, rate = k.create(text, voice=a.voice, speed=a.speed, lang=a.lang)
    write_wav(a.wav, samples, rate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
