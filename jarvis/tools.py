"""Everything JARVIS can actually do. Each function is exposed to the AI as a tool.
Replies are plain facts; the brain adds the butler's manner."""
import asyncio
import datetime as dt
import json
import re
import subprocess
import threading
import time

import httpx

from . import config, household, memory


class AppUnavailable(Exception):
    pass


def _osa(script: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AppUnavailable("no response") from None
    if r.returncode != 0:
        raise AppUnavailable(r.stderr.strip())
    return r.stdout.strip()


# ---------- Mac ----------

def get_time() -> str:
    """Get the current date and time."""
    now = dt.datetime.now()
    d = now.day
    suffix = "th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"It's {now.strftime('%-I:%M %p').replace('AM', 'a.m.').replace('PM', 'p.m.')} on {now:%A} the {d}{suffix} of {now:%B}."


def open_app(name: str) -> str:
    """Open a Mac application by name, e.g. 'Spotify' or 'Safari'."""
    r = subprocess.run(["open", "-a", name], capture_output=True, text=True)
    return f"{name} is open." if r.returncode == 0 else f"Couldn't find an app called {name}."


def quit_app(name: str) -> str:
    """Quit a running Mac application by name."""
    _osa(f'tell application "{name}" to quit')
    return f"{name} is closed."


def set_volume(level: int) -> str:
    """Set the Mac output volume from 0 to 100."""
    level = max(0, min(100, int(level)))
    _osa(f"set volume output volume {level}")
    return f"Volume at {level} percent."


def media_control(action: str) -> str:
    """Control Spotify or Music playback. action: play, pause, next, previous."""
    verb = {"play": "play", "pause": "pause", "next": "next track", "previous": "previous track"}.get(action)
    if not verb:
        return "Unknown action."
    for app in ("Spotify", "Music"):
        if subprocess.run(["pgrep", "-x", app], capture_output=True).returncode == 0:
            try:
                _osa(f'tell application "{app}" to {verb}', 8)
            except AppUnavailable:
                return f"{app} isn't responding. Jarvis may need permission to control it in System Settings, Automation."
            return {"play": "Music playing.", "pause": "Music paused.", "next": "Next track.",
                    "previous": "Previous track."}[action]
    if action != "play":
        return "Nothing is playing."
    from pathlib import Path

    app = "Spotify" if Path("/Applications/Spotify.app").exists() else "Music"
    subprocess.run(["open", "-g", "-a", app])  # open in the background, then play
    for _ in range(10):
        time.sleep(1)
        try:
            _osa(f'tell application "{app}" to play', 8)
            return "Music playing."
        except AppUnavailable:
            continue
    return f"I opened {app} but couldn't start playback. Jarvis may need permission to control it in System Settings, Automation."


def run_shortcut(name: str) -> str:
    """Run an Apple Shortcut by its exact name. Also controls Apple Home scenes."""
    r = subprocess.run(["shortcuts", "run", name], capture_output=True, text=True, timeout=60)
    return f"The {name} shortcut has run." if r.returncode == 0 else f"Shortcut failed: {r.stderr.strip()}"


def make_note(text: str) -> str:
    """Save a note into the Apple Notes app."""
    safe = text.replace('"', "'")
    _osa(f'tell application "Notes" to make new note with properties {{body:"{safe}"}}')
    return "It's in your Notes."


def look_at_screen(question: str = "Describe what's on the screen.") -> str:
    """Take a screenshot and look at it. Use for 'what am I looking at', 'explain this error',
    'summarise this page', 'what does this say'. Pass the user's question about the screen."""
    import ollama

    shot = config.DATA / "screen.png"
    r = subprocess.run(["screencapture", "-x", "-m", str(shot)], capture_output=True)  # main display, silent
    if r.returncode != 0 or not shot.exists():
        return "I couldn't take a screenshot; Jarvis may need Screen Recording permission."
    subprocess.run(["sips", "-Z", "1600", str(shot)], capture_output=True)  # smaller = faster to read
    try:
        # the vision model and the main brain don't fit in memory together, so the vision
        # model unloads straight after (keep_alive=0) and the brain reloads in the background
        resp = ollama.chat(model=config.VISION_MODEL, keep_alive=0, options={"num_predict": 300}, messages=[{
            "role": "user", "images": [str(shot)],
            "content": f"{question}\nIgnore any window titled J.A.R.V.I.S. Your answer will be read aloud: at most "
                       "four sentences, no markdown or bullet points. Quote key text such as an error message, "
                       "then explain it in plain words.",
        }])
    finally:
        shot.unlink(missing_ok=True)  # never keep screenshots around
        threading.Thread(target=lambda: ollama.generate(model=config.OLLAMA_MODEL, prompt="", keep_alive=-1),
                         daemon=True).start()
    return re.sub(r"[*_`#>]|^\s*[-•]\s*", "", resp.message.content, flags=re.M).strip()


# ---------- Calendar (read only) ----------

def calendar(day: str = "today") -> str:
    """List events from the Mac Calendar app. day: 'today' or 'tomorrow'."""
    offset = 1 if day.lower().startswith("tom") else 0
    script = f'''
    set out to ""
    set d0 to (current date) + {offset} * days
    set time of d0 to 0
    set d1 to d0 + 1 * days
    tell application "Calendar"
      repeat with c in calendars
        repeat with e in (every event of c whose start date >= d0 and start date < d1)
          set out to out & (time string of (start date of e)) & " - " & (summary of e) & linefeed
        end repeat
      end repeat
    end tell
    return out'''
    try:
        return _osa(script, 15) or f"Nothing on the calendar {day}."
    except AppUnavailable:
        return "The Calendar app isn't available right now."




# ---------- Web & info ----------

def web_search(query: str) -> str:
    """Search the web and return the top results. Use for news, films showing, reviews, facts."""
    from ddgs import DDGS

    results = DDGS().text(query, max_results=5)
    return "\n".join(f"- {r['title']}: {r['body']}" for r in results) or "No results."


def weather(city: str = "") -> str:
    """Get the current weather for a city (defaults to home)."""
    city = city or config.CITY
    r = httpx.get(f"https://wttr.in/{city}?format=%C,+%t,+feels+like+%f", timeout=10)
    household.log("Asked about the weather")
    # make it speakable: "+16°C" -> "16 degrees"
    text = re.sub(r"\+?(-?\d+)°C", r"\1 degrees", r.text.strip()).replace(" ,", ",")
    return f"{text[0].upper()}{text[1:].lower()} in {city.split(',')[0]}."


def rain_today() -> str:
    """Hourly chance of rain for the rest of today at home."""
    d = httpx.get(f"https://wttr.in/{config.CITY}?format=j1", timeout=10).json()
    now = dt.datetime.now().hour
    hours = [(int(h["time"]) // 100, int(h["chanceofrain"])) for h in d["weather"][0]["hourly"]]
    wet = [f"{hr}:00 ({p}%)" for hr, p in hours if hr >= now - 2 and p >= 50]
    return f"Rain likely around {', '.join(wet)}." if wet else "No rain expected today."


def travel_time(destination: str) -> str:
    """How long it takes to get from home to a place (airport, station, address, venue), by car and by public transport."""
    from . import places

    return places.journey(destination)


def find_nearby(kind: str = "restaurant", halal: bool = True) -> str:
    """Find places near home from the map. kind: restaurant, cafe, takeaway, gym, pharmacy, supermarket.
    halal: only halal-tagged places (map data can be incomplete, so a web_search can supplement)."""
    from . import places

    found = places.nearby(kind, halal=halal)
    if found:
        return found
    # map servers busy or places untagged: fall back to the web
    return web_search(f"best {'halal ' if halal else ''}{kind} near {config.HOME_POSTCODE} London")


# ---------- Tapo lights & plugs ----------

async def _tapo(name: str, action: str, brightness: int | None = None) -> str:
    from tapo import ApiClient

    if not (config.TAPO_EMAIL and config.TAPO_PASSWORD):
        return "Tapo isn't set up yet. Add your Tapo email and password to the .env file."
    targets = config.TAPO_DEVICES if name.lower() in ("all", "everything", "lights", "light") else {
        k: v for k, v in config.TAPO_DEVICES.items() if name.lower() in k or k in name.lower()
    } or (config.TAPO_DEVICES if len(config.TAPO_DEVICES) == 1 else {})
    if not targets:
        return f"I don't know a device called {name}. Known: {', '.join(config.TAPO_DEVICES) or 'none'}."
    client = ApiClient(config.TAPO_EMAIL, config.TAPO_PASSWORD)
    failed = []
    for dev_name, ip in targets.items():
        try:
            dev = await client.l530(ip)  # on/off is the same protocol for every Tapo bulb and plug
            if action == "on" or brightness:
                await dev.on()
                if brightness:
                    await dev.set_brightness(max(1, min(100, int(brightness))))
            else:
                await dev.off()
        except Exception as e:  # noqa: BLE001
            failed.append(f"{dev_name} failed: {e}")
    if failed:
        return "; ".join(failed)
    noun = "lights" if len(targets) > 1 else "light"
    return f"The {noun} {'are' if len(targets) > 1 else 'is'} " + (f"at {brightness} percent." if brightness else f"{action}.")


def control_device(name: str, action: str, brightness: int = 0) -> str:
    """Turn a Tapo light or smart plug on or off, optionally setting brightness 1-100.
    name: the device name, or 'all'. action: 'on' or 'off'."""
    return asyncio.run(_tapo(name, "on" if brightness else action, brightness or None))


def run_scene(name: str) -> str:
    """Run a scene: movie, goodnight, focus, relax (or any defined in data/scenes.json)."""
    scenes = json.loads((config.DATA / "scenes.json").read_text())
    key = next((k for k in scenes if k in name.lower() or name.lower() in k), None)
    if not key:
        return f"No scene called {name}. Scenes: {', '.join(scenes)}."
    s, out = scenes[key], []
    if "light" in s:
        control_device("all", "off" if s["light"] == "off" else "on", 0 if s["light"] == "off" else s["light"])
    if "volume" in s:
        set_volume(s["volume"])
    if s.get("music") in ("pause", "play"):
        media_control(s["music"])
    if s.get("open_url"):
        subprocess.run(["open", s["open_url"]])
    if s.get("say"):
        out.append(s["say"])
    if s.get("tomorrow"):
        out.append("Tomorrow: " + calendar("tomorrow"))
    return " ".join(out) or f"{key.title()} scene set."


# ---------- Routine: to-dos, habits, the household log ----------

def todays_tasks() -> str:
    """Today's to-do list including daily habits (gym, applications, study, reading, steps), with what's done."""
    tasks = household.tasks_for()
    done = [t["task"] for t in tasks if t["done"]]
    todo = [t["task"] for t in tasks if not t["done"]]
    return (f"Done: {', '.join(done) or 'nothing yet'}. Still to do: {', '.join(todo) or 'nothing, all clear'}. "
            f"Time now: {dt.datetime.now().strftime('%H:%M')}.")


def add_task(task: str, day: str = "today") -> str:
    """Add something to the to-do list. day: 'today' or 'tomorrow'."""
    when = dt.date.today() + dt.timedelta(days=1 if day.lower().startswith("tom") else 0)
    household.add_task(task, when.isoformat())
    return f"Added {task} to {day}'s list."


def complete_task(task: str) -> str:
    """Mark a to-do or habit as done (e.g. 'gym', 'job applications')."""
    t = household.complete_task(task)
    if not t:
        return f"Nothing on today's list matches {task}."
    left = [x["task"] for x in household.tasks_for() if not x["done"]]
    return f"{t} done. {len(left)} left: {', '.join(left)}." if left else f"{t} done. That's everything for today."


def remove_task(task: str) -> str:
    """Remove something from today's to-do list."""
    t = household.remove_task(task)
    return f"Took {t} off the list." if t else f"Nothing matches {task}."


def log_steps(steps: int) -> str:
    """Record today's step count (the user tells you, e.g. from their phone)."""
    household.log(f"Steps: {int(steps)}")
    if int(steps) >= 10000:
        household.complete_task("steps")
        return f"{int(steps)} steps logged. Target hit."
    return f"{int(steps)} steps logged, {10000 - int(steps)} to go for ten thousand."


def habit_report(days: int = 14) -> str:
    """How consistently the user has kept their daily habits recently, with missed days. Use for pattern remarks."""
    return household.habit_history(days)


def log_note(text: str) -> str:
    """Write something notable in the household log (moods, events, achievements, what the user did)."""
    household.log(text)
    return "Noted in the household log."


def read_log(days: int = 7) -> str:
    """Read recent household log entries."""
    return household.recent_log(days)


# ---------- Reminders ----------

def _parse_when(when: str) -> dt.datetime | None:
    now = dt.datetime.now()
    w = when.lower().strip()
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(second|sec|minute|min|hour|hr|day)", w):
        n, unit = float(m.group(1)), m.group(2)
        mult = {"sec": 1 / 60, "second": 1 / 60, "min": 1, "minute": 1, "hr": 60, "hour": 60, "day": 1440}[unit]
        return now + dt.timedelta(minutes=n * mult)
    if m := re.search(r"(\d{1,2})(?::|\.)?(\d{2})?\s*(a\.?m\.?|p\.?m\.?)?", w):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if not ap and h < 8 and not m.group(2):  # "at 6" usually means 6 p.m.
            h += 12
        t = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if "tomorrow" in w or t <= now:
            t += dt.timedelta(days=1)
        return t
    return None


def set_reminder(text: str, when: str) -> str:
    """Set a reminder or timer. text: what to remind about. when: e.g. 'in 20 minutes', '6pm', '18:30', 'tomorrow 9am'."""
    t = _parse_when(when)
    if not t:
        return f"I couldn't work out when '{when}' is."
    household.add_reminder(text, t)
    day = "" if t.date() == dt.date.today() else " tomorrow"
    spoken = t.strftime("%-I %p" if t.minute == 0 else "%-I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.")
    return f"I'll remind you at {spoken}{day}."


def list_reminders() -> str:
    """List upcoming reminders."""
    rem = household.upcoming_reminders()
    return "; ".join(f"{r['when'][11:]} {r['when'][:10]}: {r['text']}" for r in rem) or "No reminders set."


def morning_briefing() -> str:
    """Everything for a morning briefing: weather, rain, calendar, today's list, habit patterns."""
    from concurrent.futures import ThreadPoolExecutor

    checks = {"Weather": weather, "Rain": rain_today, "Calendar": calendar,
              "To-do": todays_tasks, "Habits (last 2 weeks)": habit_report, "Reminders": list_reminders}
    import time

    pool = ThreadPoolExecutor(len(checks))  # all at once; anything slower than 8 s is skipped
    futures = {label: pool.submit(fn) for label, fn in checks.items()}
    deadline, parts = time.time() + 8, []
    for label, f in futures.items():
        try:
            parts.append(f"{label}: {f.result(timeout=max(0.1, deadline - time.time()))}")
        except Exception:  # noqa: BLE001
            parts.append(f"{label}: unavailable right now")
    pool.shutdown(wait=False)
    return "\n".join(parts)


# ---------- Memory ----------

def remember(fact: str) -> str:
    """Permanently remember a fact about the user: preferences, people, tastes, goals, routines.
    Call this on your own initiative whenever you learn something worth keeping."""
    memory.add(fact)
    return "Noted."


def forget(fact: str) -> str:
    """Forget a remembered fact that matches this text."""
    return "Forgotten." if memory.remove(fact) else "I didn't have that remembered."


TOOLS = [
    get_time, open_app, quit_app, set_volume, media_control, run_shortcut, make_note,
    look_at_screen, calendar, web_search, weather, rain_today, travel_time, find_nearby,
    control_device, run_scene,
    todays_tasks, add_task, complete_task, remove_task, log_steps, habit_report, log_note, read_log,
    set_reminder, list_reminders, morning_briefing,
    remember, forget,
]
BY_NAME = {f.__name__: f for f in TOOLS}


def describe(name: str, args: dict) -> str:
    return f"{name}({json.dumps(args)})"
