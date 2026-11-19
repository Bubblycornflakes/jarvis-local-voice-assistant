"""Start J.A.R.V.I.S.

  python main.py          voice + HUD window
  python main.py --text   type in the terminal, no voice or window
"""
import datetime as dt
import json
import random
import sys
import threading
import subprocess
import time

from jarvis import config
from jarvis.brain import Brain


def text_mode():
    brain = Brain(lambda kind, text: print(f"  [{text}]"))
    print("J.A.R.V.I.S. online. Type 'quit' to exit.")
    while (q := input("> ").strip()) not in ("quit", "exit"):
        if q:
            print(brain.think(q))


def hud_mode():
    import webview

    window = None
    lock = threading.Lock()  # one request at a time
    voice = None

    def js(fn, *args):
        try:
            window.evaluate_js(f"{fn}({', '.join(json.dumps(a) for a in args)})")
        except Exception:  # noqa: BLE001  window closed or not ready
            pass

    brain = Brain(lambda kind, text: js("add", "tool", text))

    def handle(text: str, show: bool = True) -> str | None:
        """Answer out loud, speaking each sentence as soon as it's ready.
        Returns a new command if the user talked over the reply ("" for "stop")."""
        with lock:
            if show:
                js("add", "you", text)
            js("setState", "thinking", "Processing")
            speech = voice.utterance() if voice else None
            from jarvis import timing
            t0, first = time.perf_counter(), []

            def on_sentence(s):
                if not first:
                    first.append(1)
                    timing.log(f"→ first words ready  ({text[:40]!r})", time.perf_counter() - t0)
                js("add", "jarvis", s)
                js("setState", "speaking", "Speaking")
                if speech:
                    speech.put(s)
            try:
                brain.think(text, on_sentence=on_sentence)
            except Exception as e:  # noqa: BLE001
                on_sentence(f"I'm afraid something went wrong. {e}")
            interrupted = None
            if speech:
                speech.finish()
                interrupted = speech.wait()
                if interrupted is not None:
                    js("add", "tool", "Interrupted")
            timing.log("→ whole request incl. speaking", time.perf_counter() - t0)
            js("setState", "idle", "Standing by · say “Jarvis”" if voice else "Standing by")
            return interrupted

    def announce(text: str):
        """JARVIS speaking up on his own (reminders, meetings)."""
        with lock:
            js("add", "jarvis", text)
            js("setState", "speaking", "Speaking")
            subprocess.run(["osascript", "-e", f'display notification {json.dumps(text)} with title "J.A.R.V.I.S."'])
            if voice:
                voice.ducker.duck()
                voice.say(text)
                voice.ducker.restore()
            js("setState", "idle", "Standing by · say “Jarvis”")

    def butler_duties():
        """Background loop: reminders on time, and a heads-up before calendar events."""
        from jarvis import household, tools
        warned: set[str] = set()
        last_cal = 0.0
        while True:
            for r in household.due_reminders():
                announce(random.choice(["Pardon the interruption, sir.", "A reminder, sir.", "If I may —"])
                         + f" You asked me to remind you: {r}.")
            if time.time() - last_cal > 300:  # check the calendar every five minutes
                last_cal = time.time()
                try:
                    now = dt.datetime.now()
                    for line in tools.calendar().splitlines():
                        when, _, title = line.partition(" - ")
                        start = dt.datetime.combine(now.date(), dt.datetime.strptime(when.strip(), "%H:%M:%S").time())
                        if 0 < (start - now).total_seconds() <= 15 * 60 and line not in warned:
                            warned.add(line)
                            mins = round((start - now).total_seconds() / 60)
                            announce(f"{title} starts in {mins} minutes, sir.")
                except Exception:  # noqa: BLE001  calendar unavailable or odd time format
                    pass
            time.sleep(20)

    class Api:
        def send(self, text):
            threading.Thread(target=handle, args=(text,), daemon=True).start()

    def voice_loop():
        nonlocal voice
        # load the brain into memory now, so the first question isn't a 20-second wait
        import ollama
        threading.Thread(target=lambda: ollama.generate(model=config.OLLAMA_MODEL, prompt="", keep_alive=-1),
                         daemon=True).start()
        window.events.loaded.wait()
        js("setState", "thinking", "Calibrating systems")
        try:
            from jarvis.voice import Voice
            voice = Voice()
        except Exception as e:  # noqa: BLE001
            js("add", "tool", f"Voice unavailable ({e}). Typing still works.")
            js("setState", "idle", "Standing by")
            return
        first_run = config.DATA / ".permissions_asked"
        if not first_run.exists():
            # ask for every macOS permission up front, once, instead of mid-conversation
            js("setState", "thinking", "One-time setup · click Allow on each prompt")
            from jarvis import tools
            tools.calendar()
            tools._osa('tell application "Notes" to count notes')
            first_run.touch()
        screen_flag = config.DATA / ".screen_asked"
        if not screen_flag.exists():  # one-time Screen Recording permission, for "look at my screen"
            js("setState", "thinking", "One-time setup · allow Screen Recording for Jarvis")
            subprocess.run(["screencapture", "-x", str(config.DATA / "probe.png")])
            (config.DATA / "probe.png").unlink(missing_ok=True)
            screen_flag.touch()
        threading.Thread(target=butler_duties, daemon=True).start()
        from jarvis import household
        hour = dt.datetime.now().hour
        if hour < 12 and household.flag("morning_briefing"):
            handle("Good morning. Give me my morning briefing: weather, rain, calendar, today's list, "
                   "and one observation from the household log. Keep it to about five sentences, warm and brisk.",
                   show=False)
        else:
            part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
            greeting = random.choice([f"Good {part}, sir. All systems are online.", f"Good {part}. At your service.",
                                      f"Ah, good {part}, sir. The household is in order."])
            js("add", "jarvis", greeting)
            js("setState", "speaking", "Speaking")
            voice.say(greeting)
        while True:
            js("setState", "idle", "Standing by · say “Jarvis”")
            heard = voice.wait_for_wake_word()
            voice.ducker.duck()  # music down while we talk
            if not heard:  # just "Jarvis" on its own: answer, then wait for the command
                voice.acknowledge()
                js("setState", "listening", "Listening")
                heard = voice.listen()
            # keep the conversation going: after each reply, listen for a follow-up
            # without needing the wake word, until there's silence
            while heard:
                interrupted = handle(heard)
                if interrupted:  # "Jarvis, <something else>" mid-reply
                    heard = interrupted
                    continue
                if brain.started_music:  # the music would be mistaken for a follow-up
                    break
                js("setState", "listening", "Listening for a follow-up")
                heard = voice.listen(wait_seconds=config.FOLLOW_UP_SECONDS)
            voice.ducker.restore()

    window = webview.create_window("J.A.R.V.I.S.", str(config.ROOT / "hud" / "index.html"),
                                   js_api=Api(), width=900, height=760, background_color="#02060c")
    webview.start(lambda: threading.Thread(target=voice_loop, daemon=True).start())


if __name__ == "__main__":
    text_mode() if "--text" in sys.argv else hud_mode()
