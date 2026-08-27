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
| **Shut it up right now** | `python voice-toggle.py stop` |
| **Pause / resume** | **`Ctrl+Alt+P`** — or `python voice-toggle.py pause` |
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
| `settings.json` | **Which hooks exist** | Usually picked up immediately; start a new session if not |
| `voice-config.json` + the `.py` files | **All behaviour**: voice, speed, on/off, logic | Fresh on every single invocation — instant, everywhere |

So changing your voice or muting speech is instant.

Adding or removing a hook is the one change that might need a new session — the docs say
`settings.json` is read at startup, but on two machines so far the hooks began firing in
the very session that installed them. Claude Code also has a `ConfigChange` hook event,
which suggests it watches config files. Treat a restart as the fallback, not the rule.

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
> calls. It ships **empty on purpose**, and an entry in this list means speech will talk
> over that app's calls -- so only add an app you are sure never releases the mic on its own.
>
> Not every machine is so lucky, and the failure is silent: an app that holds the mic
> permanently suppresses speech forever, with the only clue a line in `voice-errors.log`.
> A Logitech G Hub install was found holding the microphone for **44 days straight**.
> `install.py` now checks for holders older than a couple of hours and offers to add them,
> so this is a question at install time rather than a mystery afterwards. To check by hand:
>
> ```powershell
> python voice-say.py --mic
> ```

### You're working in another window

**Every summary is kept and played in arrival order.** Two windows finishing together
means you hear both. Two turns in the *same* window means you hear both of those too.

Nothing is collapsed, and that is a deliberate reversal of an earlier design. Each turn's
summary describes that turn's work, so a newer one does not contain what an older one
said — discarding the older loses information rather than merely delaying it. The earlier
"newest wins within a window" behaviour was wrong for that reason.

The cost is honest: come back after an hour with several windows working and you will
hear a real backlog, one summary at a time. `max_queued_per_session` (10) bounds it, and
when a single window exceeds that the **oldest** of its summaries is dropped and logged —
if something has to go, it should be the least current thing.

Each summary is announced with its project name — *"My Project. The payroll report is
finished…"* — so you know which window is talking. Two windows on the same folder get
distinguished ("My Project" / "My Project two"). Names only get announced when more than
one window is live, and `announce_session` can force it `always` or `never`.

> The meeting problem is not something you notice until someone reviews it with fresh
> eyes — credit to Jamison West, who also found that an app can hold the microphone for
> weeks, which turns this gate from a courtesy into a permanent mute.

---

## Stopping speech that is already playing

### Ctrl+Alt+P

A phone ringing does not leave time to open a terminal, so `install.py` registers a global
shortcut. **Press `Ctrl+Alt+P` to pause, press it again to resume.** One key, both
directions — you should not have to remember which state you are in.

It works from any application, including while you are in a call, and flashes no console
window (it runs through `pythonw.exe`). A toast confirms which way it went, since a hotkey
has nowhere to print.

> **Why the toggle is guarded.** A Windows shortcut hotkey can fire several invocations for
> one press. Because the toggle reads the paused state and then writes it, unguarded
> duplicates cancelled out — pause, resume, pause — leaving it paused, so the key appeared
> dead and only worked after enough presses to hit a lucky interleaving. It now takes a
> non-blocking mutex (contention means a duplicate, so do nothing) plus a one-second stamp
> for a duplicate that lands after the first finished. Verified with up to eight concurrent
> invocations per press: exactly one acts, every time.
>
> The practical cost: two *deliberate* presses inside one second count as one. A real second
> press that fast is almost certainly the OS repeating itself.

```powershell
python install.py --hotkey "CTRL+ALT+M"   # a different combination
python install.py --no-hotkey             # skip it
```

> The shortcut is a `.lnk` in your Start Menu, because Windows only honours a shortcut's
> hotkey when it lives in the Start Menu or on the Desktop.

### What pause cannot do

It cannot resume where it stopped. A summary is synthesised as one audio file and handed to
a player that blocks until finished; nothing reads back how far it got, so a resume replays
the whole summary — and pays the synthesis cost again, which for 80 words is 15–20 seconds
before any sound.

Speaking sentence by sentence was tried, so that a resume could pick up at a sentence
boundary and the first word could arrive sooner. It was reverted: **the pauses between
sentences were worse than the problem being solved.** Synthesis is not fast enough to hide
in the gap even with the model held in memory and the next sentence built during playback.

So if you need silence immediately, mute your speakers — that is genuinely the better tool.
`stop` and `pause` are for deciding you do not want the backlog, not for a quick hush.

**The automatic microphone cut-off is the one that matters** and it works properly: pick up
a call or start dictating and the audio stops within about half a second, then resumes when
you are done. That covers most of what a manual pause was reaching for, without the
tradeoffs.

### Pause is a hold, not a one-off

Pausing stops the audio *and* holds everything afterwards: later turns keep queueing
summaries but none are spoken until you resume. That matters for the case it exists for —
a call lasts longer than one turn.

**Nothing is discarded.** The summary being spoken has already been taken off the queue,
and the code that would put it back lives in the worker being killed, so the worker records
what it is playing and pause restores that record at its original position. On resume you
hear it from the beginning — audio cannot be resumed mid-sentence, so it replays whole.

A pause has no timeout. `voice-toggle.py` reports it prominently for that reason, since a
forgotten pause otherwise looks exactly like a broken install:

```
Speech      : PAUSED 12 min ago -- run 'pause' again to resume
```

### Stop

```powershell
python voice-toggle.py stop      # silence now, throw away the queue, no hold
```

For when you want none of the backlog. Unlike pause it does not hold, so the next turn
speaks normally.

### It also cuts itself off

The microphone is polled *during* playback, not only before it. If a call starts
mid-sentence the audio is killed within about half a second and that summary goes back on
the queue whole — you hear it after the call rather than being talked over. Same for
locking the screen mid-sentence.

This is the one case the between-utterances check cannot catch, and it is why playback runs
as a polled subprocess rather than one blocking call.

---

## When you've walked away: the phone

Holding a summary is only half an answer. If you are away, speech is queued and reaches
nobody — so it goes to your phone instead.

This needs **Remote Control** connected: `/rc` in the Claude Code prompt box, or
`remoteControlAtStartup: true` in `settings.json` to connect every session automatically.
Without it there is nowhere for a notification to go.

### How it decides you're away

Locked screen is definitive. Otherwise `away_seconds` (120) of no keyboard or mouse — input
driven from a phone never touches this machine's input devices, so an idle desktop with an
active session is a good signal you are elsewhere.

### Why it needs enforcing

Speech is driven by a hook, so it happens whether or not the model cooperates. A phone push
is different: **no hook can send one.** Only Claude can, by calling its notification tool.
That makes it a request rather than a guarantee — and a request the model can quietly drop.

So it is enforced the same way the summary is. The `UserPromptSubmit` hook notices you are
away and asks for a push plus a marker:

```html
<!-- PUSHED -->
```

The `Stop` hook then refuses to end the turn if you are away and that marker is absent. A
deliberate `<!-- PUSHED: skipped -->` is accepted for a reply not worth a notification.
One block per turn, so a turn can always finish.

### What it will not do

Claude Code skips a push while you are actively at the terminal, on the reasoning that the
reply already reached you. That is not configurable, and it means the push channel is
reserved for genuine absence — you cannot opt into a notification for every turn.

```powershell
python voice-toggle.py            # includes whether you currently read as away
```

Turn it off with `push_when_away: false`. Note the notification travels through Anthropic's
Remote Control, the same path your conversation already takes — unlike speech, which never
leaves the machine.

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
| `push_when_away` | Send the summary to your phone when you are away from the machine |
| `away_seconds` | Idle time that counts as away, when the screen is unlocked (120) |
| `respect_microphone` | Hold speech while any app holds the mic. Keep this `true` |
| `microphone_ignore` | Apps to ignore because they hold the mic all day. Empty by default |
| `announce_session` | `auto` (name windows only when several are live), `always`, `never` |
| `max_defer_seconds` | Give up waiting out a call after this long (1800) |
| `max_stale_seconds` | Discard summaries older than this. `0` means never discard |
| `max_queued_per_session` | Cap on unheard summaries per window; oldest dropped past it (10) |

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

If it went quiet for minutes and then recovered on its own, that was the audio lock bug
fixed in this repo's history: `acquire_lock` and `release_lock` built the lock's path
separately and disagreed about the suffix, so releasing never deleted the file the acquirer
created and only the staleness timer ever freed it. The lock now records its owner's PID and
a dead owner releases it immediately, so a killed or crashed worker cannot wedge speech.

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
