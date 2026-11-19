# JARVIS

A voice assistant for a Mac that runs mostly on your own machine. You say "Hey Jarvis", it listens, thinks with a local language model, uses tools to act, and answers out loud in a British voice.

I built it to learn how a tool-using language model agent fits together with speech in and speech out. It runs on macOS only, because it uses AppleScript for some actions and Apple's MLX for speech recognition.

## What it does

- **Hears you.** A wake word ("Hey Jarvis") starts listening, then Whisper turns speech into text.
- **Thinks.** A local model served by Ollama (default `gpt-oss:20b`) decides what to do and calls tools. Hard questions can be passed to Claude, using an API key if you set one.
- **Acts.** Tools open and quit apps, set the volume, control music, make notes, read the calendar, search the web, check the weather and journey times, control smart lights, and run scenes.
- **Keeps a household log.** To-dos, daily habits, reminders and a diary, stored as plain JSON.
- **Remembers.** A simple list of facts saved between sessions.
- **Speaks.** Replies stream sentence by sentence through a local text-to-speech model (Kokoro).
- **Sees the screen.** A local vision model can answer questions about a screenshot.
- **Shows a HUD.** A small window shows what it is doing.

## How the parts fit

| Part | File | Job |
|---|---|---|
| Entry point | `main.py` | Voice plus HUD, or `--text` for typing in the terminal |
| Fast lane | `jarvis/fastlane.py` | Instant answers for simple commands without calling the model |
| Brain | `jarvis/brain.py` | Local model with tool calling, optional Claude escalation |
| Tools | `jarvis/tools.py` | Every action it can take, each exposed to the model as a tool |
| Voice | `jarvis/voice.py` | Wake word, speech to text, text to speech |
| Household | `jarvis/household.py`, `jarvis/memory.py` | To-dos, habits, reminders, memory |
| Timing | `jarvis/timing.py` | Logs how long each step takes, to find slow parts |
| MCP server | `jarvis/mcp_server.py` | Exposes five key skills to a voice model over MCP |

## Setup

Requires macOS on Apple silicon, Python 3 and [Ollama](https://ollama.com).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env     # then edit .env
ollama pull gpt-oss:20b
```

Download the Kokoro text-to-speech files (`kokoro-v1.0.onnx` and `voices-v1.0.bin`) from the kokoro-onnx project and put them in a `models/` folder. These are not included in this repository.

Run it:

```bash
.venv/bin/python main.py          # voice and HUD
.venv/bin/python main.py --text   # type instead of speak
```

## Settings

Everything is set in `.env`. See `.env.example`. Free-form notes about you can go in `about me.txt`, which is git-ignored. API keys and smart-home logins stay in `.env`, which is git-ignored.

## Limits

- Mac only.
- It needs a machine that can run a 20-billion-parameter model locally, or you can set a smaller `OLLAMA_MODEL`.
- Tests cover the instant-command router and the reminder time parser only (`python -m unittest discover -s tests -v`). The language model's behaviour, speech recognition and the tools that touch your Mac or smart home are not tested, and I have not measured accuracy. Speed is logged in `data/timing.log`.
- If `CITY` is not set in `.env`, the code looks up your city from your IP address through ipinfo.io when it starts. Set `CITY` to avoid that network call.
- Some tools (smart lights, journey times) assume a home setup you configure yourself.
