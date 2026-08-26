# Claude Code Voice

**Spoken summaries and phone notifications for Claude Code — Windows only.**

Claude tells you what it did, out loud, so you can stop reading everything on screen. When
you walk away, the summary follows you to your phone instead.

Everything runs locally. No API keys, no cloud speech service, no audio leaves the machine.

> **Windows only.** This uses Windows speech APIs, Windows toast notifications, the Windows
> microphone privacy registry, and `winsound`. It will not work on macOS or Linux.

---

## The idea

The obvious way to build this is to run text-to-speech over Claude's output. That's useless
in practice — you get file paths, code blocks, and tool results read aloud.

So instead, **Claude writes a short spoken summary of each turn**, and only that is read:

```html
<!-- SPEAK
I finished reviewing the payroll export and found two entries that don't match
the timesheet. I left the rest alone so you can check my work.
SPEAK -->
```

Two or three sentences, plain language, no paths or code. Summarising takes judgement, so
the model does it rather than a regex.

And because a prompt instruction is only as reliable as the model's memory, **a hook
enforces it**: if a turn ends without a summary, the hook refuses to end the turn until
there is one.

---

## What it actually does

| | |
| --- | --- |
| **After every turn** | Speaks a 2–4 sentence summary in a local neural voice |
| **When Claude needs you** | Chime + a Windows toast that waits until you dismiss it |
| **While you're on a call** | Silent. Holds the summary and speaks it when you hang up |
| **While your screen is locked** | Silent. Holds it until you unlock |
| **When you've walked away** | Pushes a one-line version to your phone instead |
| **With several windows open** | Each summary is named by its project, played in order |
| **Subagents** | Silent |

Nothing is ever discarded. A summary you haven't heard waits its turn.

---

## Install

Requires **Windows**, **Python 3.12+** on `PATH` as `python`, and Claude Code run at least
once.

```powershell
git clone https://github.com/YOUR-USER/claude-code-voice-windows
cd claude-code-voice-windows
python install.py
```

That copies the hooks into `%USERPROFILE%\.claude\hooks`, builds a virtual environment,
downloads the Kokoro voice model (~354 MB, one time), registers a toast identity, and wires
three hooks into your `settings.json`. It leaves any other hooks you have alone, and never
overwrites an existing `voice-config.json`.

Then **start a new Claude Code session** — hook registration is read at startup.

```powershell
python install.py --dry-run     # show what it would change, touch nothing
python install.py --no-model    # skip the model download
python install.py --uninstall   # remove the hooks
```

---

## Using it

```powershell
cd $env:USERPROFILE\.claude\hooks

python voice-toggle.py                  # what's on, what's queued, what's blocking it
python voice-toggle.py off              # silence
python voice-toggle.py on               # back on
python voice-voices.py --audition       # hear the shortlist, then pick
python voice-voices.py --set am_puck    # 54 voices, 28 of them English
python voice-say.py "build finished"    # say something now
```

Config changes apply **instantly, in every open window** — no restart. Only adding or
removing a hook needs a new session.

Full reference, troubleshooting, and design notes: **[DOCS.md](DOCS.md)**

---

## Why Kokoro and not the Windows voices

The voices Windows exposes to applications are the old generation — David, Zira, Mark — and
they are hard to listen to repeatedly.

Windows 11's Narrator "natural voices" sound great and **cannot be used here**: Microsoft
restricts them to Narrator, so they're invisible to every speech API. That's also why NVDA
and JAWS can't use them. Don't spend an afternoon on it like I did.

So this ships [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), a local neural engine:
54 voices, fully offline, about 354 MB. Windows voices remain as an automatic fallback, so a
Kokoro failure costs you voice quality rather than silence.

Expect **4–8 seconds** before speech starts — the model loads per utterance.

---

## Privacy

Speech synthesis is local. The model is downloaded once from GitHub and never contacted
again. No speech audio or text is sent anywhere.

Two things to know if you work with sensitive data:

- **`voice-spoken.log` records every summary spoken.** By design those name whatever you
  were working on. It's gitignored here, but it's plaintext on your disk.
- **Phone notifications** travel through Anthropic's Remote Control, the same path your
  Claude Code conversation already takes. Turn it off with `push_when_away: false`.

---

## Contributing

Issues and PRs welcome. It's a handful of standalone Python scripts with no dependencies
beyond Kokoro — `voice_lib.py` holds the shared logic and each hook is a thin entry point.

There's a test suite that mocks the audio layer, so the queue, gating, and enforcement logic
can be exercised without listening to anything.

## Credits

Built with [Claude Code](https://claude.com/claude-code). The call-awareness and
queue-ordering behaviour came out of a code review by Jamison West, who spotted that it
would happily talk over a meeting.

## License

MIT — see [LICENSE](LICENSE).
