# Claude Code Voice & Notifications

Spoken summaries and desktop alerts for Claude Code in VS Code on Windows.

Instead of reading everything Claude produces, you hear a short spoken summary of each
turn. When Claude needs your input, you get a chime and a Windows toast. Subagent
chatter, tool output, file paths, and code are never read aloud.

Everything runs locally. No API keys, no cloud speech service, nothing leaves the machine.

---

## Quick start

All commands run from the hooks folder:

```powershell
cd $env:USERPROFILE\.claude\hooks
```

| I want to... | Command |
| --- | --- |
| See what's currently on | `python voice-toggle.py` |
| **Turn speech off** | `python voice-toggle.py off` |
| **Turn speech back on** | `python voice-toggle.py on` |
| Speak only when I step away | `python voice-toggle.py quiet` |
| Speak on every turn (default) | `python voice-toggle.py always` |
| Turn toasts off / on | `python voice-toggle.py toast off` |
| Speak even during calls | `python voice-toggle.py mic off` |
| See what's holding the mic | `python voice-say.py --mic` |
| Speak to a locked screen | `python voice-toggle.py lock off` |
| See what was actually spoken | `type voice-spoken.log` |
| Hear the available voices | `python voice-voices.py --audition` |
| Change voice | `python voice-voices.py --set am_puck` |
| Change speaking speed | `python voice-voices.py --rate 1.15` |
| Say something out loud right now | `python voice-say.py "build finished"` |
| Find out why it went quiet | `type voice-errors.log` |

> **Config changes apply instantly, in every open window.** No restart, no reload.

---

## What gets spoken

Claude appends a hidden summary block to each reply:

```html
<!-- SPEAK
I finished reviewing the payroll export and found two entries that don't match
the timesheet. I left the rest alone so you can check my work.
SPEAK -->
```

Only the text inside that block is spoken. This matters:

- **No file paths, code, URLs, or tool output.** A script reading Claude's raw output
  would read paths and code aloud, which defeats the purpose. Summarising requires
  judgement, so Claude writes the summary itself.
- **If the block is missing, nothing is spoken.** It fails to silence, never to noise.
- **Subagents are silent.** They fire a different event that nothing is wired to.

### The enforcement hook

Because the summary depends on Claude following an instruction, there's a backstop. If a
turn ends with no summary block, the hook **refuses to end the turn** and makes Claude
write one. If it still doesn't, you hear a generic *"I've finished and I'm waiting on
you"* — so silence is never ambiguous.

Capped at one retry per turn. If anything in the voice code errors, the hook exits
cleanly, so a voice bug can never wedge a turn.

---

## How it hangs together

Three hooks, registered in `~\.claude\settings.json`:

| Hook event | Script | Role |
| --- | --- | --- |
| `UserPromptSubmit` | `voice-turn-start.py` | Injects the summary instruction; timestamps the turn |
| `Stop` | `voice-stop.py` | Decides what happens at end of turn, hands speech to a background process |
| `Notification` | `voice-attention.py` | Chime + toast when Claude needs you |

The instruction is re-injected on **every** prompt rather than living in `CLAUDE.md`, so
context compaction can't lose it.

`voice-stop.py` runs synchronously so it's able to block a turn, which means it must be
fast — it decides in about 0.1s and spawns a detached process to do the talking. Turns
never stall waiting on audio.

### Two layers, different reload rules

This trips people up, so it's worth stating plainly:

| Layer | What's in it | When it's read |
| --- | --- | --- |
| `settings.json` | **Which hooks exist** | Once, at session start — needs a new session |
| `voice-config.json` + the `.py` files | **All behaviour**: voice, speed, on/off, logic | Fresh on every single invocation — instant, everywhere |

So changing your voice or muting speech is instant. Only adding or removing a hook
requires starting a new session.

---

## Speech engines

Three engines in a fallback chain. A failure costs you voice *quality*, never silence.

| Order | Engine | Voices | Notes |
| --- | --- | --- | --- |
| 1 | **Kokoro** (local neural) | 54, 28 English | What you normally hear. Fully offline |
| 2 | Windows WinRT | David, Zira, Mark | Modern Windows engine |
| 3 | Windows SAPI | David, Zira | Legacy fallback |

Kokoro runs in its own virtual environment at `.claude\hooks\.venv`, with the model
cached in `~\.cache\kokoro-onnx` (about 354 MB).

### Voices

Kokoro names encode region and gender: `am_michael` = **A**merican **m**ale,
`bf_emma` = **B**ritish **f**emale.

```powershell
python voice-voices.py                  # list everything, flag what's in use
python voice-voices.py --audition       # hear 10 shortlisted voices
python voice-voices.py --audition all   # hear all 28 English voices
python voice-voices.py --say bm_george  # hear just one
python voice-voices.py --set af_heart   # save your pick
```

> **Note:** Windows 11's Narrator "natural voices" *cannot* be used here. Microsoft
> restricts them to Narrator — they're invisible to every speech API, which is also why
> NVDA and JAWS can't use them. Kokoro exists to fill that gap.

**Expect a 4–8 second pause before speech starts.** The neural model loads fresh each
time. Speech also serialises behind a lock, so several quick turns in a row will queue.

---

## When it stays quiet

Three situations where narration would be wrong. In all of them the summary is **held,
never discarded** — you hear it when the moment passes.

### Your screen is locked

If the lock screen is up, nothing is spoken. Windows happily plays audio through a lock
screen, so without this a locked machine gets read aloud to an empty room — which is
exactly what happens when you're driving the session from your phone.

Locks can last hours, so it doesn't sit and wait: it leaves the queue alone and a later
turn picks it up. Unlock, carry on working, and the backlog plays.

```powershell
python voice-toggle.py lock off    # speak to a locked machine anyway
```

> Detected via the presence of `LogonUI.exe`. The usual trick for this,
> `OpenInputDesktop`, is **wrong here** — the hook runs in your own session, so it still
> gets a handle while locked. Verified against a genuinely locked machine.

### You're on a call

Before speaking it checks whether any app holds the microphone — Teams, Zoom, a browser,
a softphone, a dictation tool. If something does, the summary waits.

Windows tracks this itself (it's the data behind the mic indicator in your taskbar), so
it needs no extra software and covers every app rather than a hardcoded list. A call is
minutes rather than hours, so this one *is* worth waiting out — up to
`max_defer_seconds`.

```powershell
python voice-say.py --mic          # what's holding the microphone right now
python voice-toggle.py mic off     # speak during calls anyway
```

**The check happens twice.** Synthesis takes 4–8 seconds, which is easily long enough to
answer a call or start dictating, so the microphone and lock state are re-checked
immediately before playback. If either changed, the audio is not played and the summary
goes back on the queue.

> `microphone_ignore` exists for apps that hold the mic all day rather than only during
> calls. It ships **empty on purpose**: every app tested here releases the mic properly,
> and an entry in this list means speech will talk over that app's calls.

### You're working in another window

Every session gets **its own queue slot**, and they play in arrival order. Two windows
finishing together means you hear both.

Within a single session, a newer summary *replaces* an older unspoken one — that's the
same work superseding itself, not new information. Across sessions nothing is ever
dropped.

Each summary is announced with its project name — *"My Project. The payroll report is
finished…"* — so you know which window is talking. Two windows on the same folder get
distinguished ("My Project" / "My Project two"). Names only get announced when more than
one window is live, and `announce_session` can force it `always` or `never`.

> The call and stacking problems were both spotted by
> Jamison West reviewing an earlier version — the kind
> of thing you don't notice until someone else looks.

---

## Toast notifications

When Claude needs your input you get a chime plus a Windows toast that stays until
dismissed. **Nothing is spoken** — this fires during calls and with people nearby.

Toasts are attributed to **"Claude VSC Notice"** with the Claude logo, via a registry
entry under `HKCU\SOFTWARE\Classes\AppUserModelId\ClaudeCode.VSC.Notice`. Without that,
Windows labels them "Windows PowerShell".

Because it has its own identity, it appears as a separate app under
**Settings → System → Notifications**, so you can give it its own quiet hours.

```powershell
python voice-setup-toast.py             # re-register (safe to re-run)
python voice-setup-toast.py --remove    # unregister
```

---

## Configuration

`voice-config.json`:

```json
{
  "speak": true,
  "always_speak": true,
  "toast": true,
  "idle_seconds": 45,
  "long_turn_seconds": 60,
  "engine": "auto",
  "voice": "af_heart",
  "fallback_voice": "Mark",
  "rate": 1.0,
  "min_turn_seconds": 10,
  "respect_microphone": true,
  "max_defer_seconds": 900,
  "max_stale_seconds": 180
}
```

| Key | Meaning |
| --- | --- |
| `speak` | Master switch. `false` also stops Claude writing summaries |
| `always_speak` | `true` = speak every turn. `false` = only when you're likely away |
| `toast` | Windows toast notifications on/off |
| `engine` | `auto`, `kokoro`, `winrt`, or `sapi` |
| `voice` | Kokoro voice name |
| `fallback_voice` | Windows voice, used only if Kokoro fails |
| `rate` | Speed multiplier. `1.0` normal, `1.15` brisker |
| `respect_lock` | Hold speech while the screen is locked. Keep this `true` |
| `respect_microphone` | Hold speech while any app holds the mic. Keep this `true` |
| `microphone_ignore` | Apps to ignore because they hold the mic all day. Empty by default |
| `announce_session` | `auto` (name windows only when several are live), `always`, `never` |
| `max_defer_seconds` | Give up waiting out a call after this long (1800) |
| `max_stale_seconds` | Discard summaries older than this. `0` means never discard |

### Only used when `always_speak` is `false`

| Key | Meaning |
| --- | --- |
| `idle_seconds` | No keyboard or mouse for this long = you've stepped away |
| `long_turn_seconds` | A turn this long means you almost certainly switched windows |
| `min_turn_seconds` | Floor for the multi-window rule, to stop trivial turns chattering |

In quiet mode it also detects **multiple VS Code windows**: if another session gets a
prompt after this turn started, you're demonstrably working elsewhere, so this window
speaks anyway. Machine-wide idle time alone gets that case wrong.

---

## Troubleshooting

### It went quiet

```powershell
python voice-toggle.py    # is it on? is something holding it?
type voice-spoken.log     # what was spoken, and when
type voice-errors.log     # why something was not spoken
```

`voice-toggle.py` shows the live state: whether the screen is locked, what holds the
microphone, and what is sitting in the queue. That answers most cases outright.

`voice-spoken.log` records every utterance as `spoke` or `deferred` with a timestamp, so
"did it talk over me?" is answerable rather than a guess. `voice-errors.log` records
every reason speech did not happen — a held summary, a failed engine, Kokoro's own error
output. **An empty error log means speech never failed; it was never triggered.**

### No toast notifications

```powershell
type voice-notify-debug.log
```

Every notification Claude Code emits is logged here with the decision made. If this file
is empty, the events aren't reaching the hook at all — most likely because in auto mode
Claude rarely needs to ask permission.

### Speech lags behind

Expected under rapid turns: synthesis takes 4–8 seconds and utterances queue. Options
are dropping stale audio when a newer summary arrives, or keeping a warm model process.

### Verify the whole chain

```powershell
python voice-say.py "testing one two three"    # speech
python voice-voices.py                         # engines and voices visible
python voice-toggle.py                         # current state
```

---

## Files

Everything lives in `%USERPROFILE%\.claude\hooks`:

| File | Purpose |
| --- | --- |
| `voice_lib.py` | Shared library: engines, gating, toasts, logging |
| `voice-config.json` | All settings |
| `voice-turn-start.py` | `UserPromptSubmit` hook |
| `voice-stop.py` | `Stop` hook |
| `voice-attention.py` | `Notification` hook |
| `voice-say.py` | Speech worker, also usable by hand |
| `voice-voices.py` | List / audition / choose voices |
| `voice-toggle.py` | On, off, and mode switching |
| `voice-setup-toast.py` | Registers the toast identity |
| `kokoro_synth.py` | Runs inside `.venv` to synthesise audio |
| `claude-logo.png` | Toast icon |
| `voice-errors.log` | Why speech didn't happen |
| `voice-spoken.log` | What was spoken or deferred, with timestamps |
| `voice-notify-debug.log` | Every notification received |

---

## Requirements

- **Windows** — uses Windows speech APIs, `winsound`, and Windows toasts throughout
- **Python 3.12+** on `PATH` as `python` (the Microsoft Store `python3` stub won't work)
- **Speakers or headphones**, obviously

No admin rights needed. The only machine-level change is one registry key under
`HKCU` for the toast identity.

## Privacy

Nothing leaves the machine. Kokoro and both Windows engines synthesise locally, and the
model was downloaded once at install. There is no cloud speech service and no API key.

The alternative worth knowing about and avoiding: cloud neural voices sound better but
send every spoken summary to a remote endpoint. For sessions that touch client data,
that's the wrong trade.
