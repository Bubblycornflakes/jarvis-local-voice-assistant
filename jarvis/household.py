"""The household log: daily to-dos, habits, reminders, and a diary of what happened.
Everything is plain JSON in data/ so it survives restarts."""
import datetime as dt
import json
import re
import threading

from .config import DATA, DAILY_HABITS

_lock = threading.Lock()


def _load(name: str, default):
    try:
        return json.loads((DATA / name).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(name: str, data):
    (DATA / name).write_text(json.dumps(data, indent=2))


def today() -> str:
    return dt.date.today().isoformat()


# ---------- tasks & habits ----------

def tasks_for(day: str | None = None) -> list[dict]:
    """Today's list always starts with the daily habits."""
    day = day or today()
    with _lock:
        all_tasks = _load("tasks.json", {})
        if day not in all_tasks and day == today():
            all_tasks[day] = [{"task": h, "done": False, "habit": True} for h in DAILY_HABITS]
            _save("tasks.json", all_tasks)
        return all_tasks.get(day, [])


def _update(day: str, tasks: list[dict]):
    with _lock:
        all_tasks = _load("tasks.json", {})
        all_tasks[day] = tasks
        _save("tasks.json", all_tasks)


def add_task(task: str, day: str | None = None):
    day = day or today()
    tasks = tasks_for(day)
    tasks.append({"task": task, "done": False, "habit": False})
    _update(day, tasks)


def _match(tasks: list[dict], text: str) -> dict | None:
    words = set(re.findall(r"\w+", text.lower()))
    best = max(tasks, key=lambda t: len(words & set(re.findall(r"\w+", t["task"].lower()))), default=None)
    return best if best and words & set(re.findall(r"\w+", best["task"].lower())) else None


def complete_task(text: str) -> str | None:
    tasks = tasks_for()
    t = _match(tasks, text)
    if not t:
        return None
    t["done"] = True
    t["at"] = dt.datetime.now().strftime("%H:%M")
    _update(today(), tasks)
    log(f"Completed: {t['task']}")
    return t["task"]


def remove_task(text: str) -> str | None:
    tasks = tasks_for()
    t = _match(tasks, text)
    if not t:
        return None
    tasks.remove(t)
    _update(today(), tasks)
    return t["task"]


def habit_history(days: int = 14) -> str:
    """Per-habit record over recent days, e.g. 'gym: done 3 of 13 days, skipped Mon 20, Mon 27'."""
    all_tasks = _load("tasks.json", {})
    lines = []
    past = [(dt.date.today() - dt.timedelta(days=i)) for i in range(1, days + 1)]
    for habit in DAILY_HABITS:
        tracked = [(d, next((t for t in all_tasks.get(d.isoformat(), []) if t["task"] == habit), None)) for d in past]
        tracked = [(d, t) for d, t in tracked if t]
        if not tracked:
            continue
        missed = [d.strftime("%a %d") for d, t in tracked if not t["done"]]
        lines.append(f"{habit}: done {len(tracked) - len(missed)} of {len(tracked)} days"
                     + (f"; missed {', '.join(missed[:6])}" if missed else ""))
    return "\n".join(lines) or "No history yet; tracking started recently."


# ---------- the log (diary) ----------

def log(text: str):
    with _lock:
        entries = _load("log.json", [])
        entries.append({"when": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "text": text})
        _save("log.json", entries[-2000:])


def recent_log(days: int = 7) -> str:
    cutoff = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    entries = [e for e in _load("log.json", []) if e["when"] >= cutoff]
    return "\n".join(f"{e['when']}: {e['text']}" for e in entries[-60:]) or "The log is empty."


def count_today(prefix: str) -> int:
    """How many times something was logged today, e.g. asked about the weather."""
    return sum(1 for e in _load("log.json", []) if e["when"].startswith(today()) and e["text"].startswith(prefix))


# ---------- reminders ----------

def add_reminder(text: str, when: dt.datetime):
    with _lock:
        rem = _load("reminders.json", [])
        rem.append({"text": text, "when": when.isoformat(timespec="minutes")})
        _save("reminders.json", rem)


def due_reminders() -> list[str]:
    """Pop and return reminders whose time has come."""
    now = dt.datetime.now().isoformat(timespec="minutes")
    with _lock:
        rem = _load("reminders.json", [])
        due = [r for r in rem if r["when"] <= now]
        if due:
            _save("reminders.json", [r for r in rem if r["when"] > now])
    return [r["text"] for r in due]


def upcoming_reminders() -> list[dict]:
    return sorted(_load("reminders.json", []), key=lambda r: r["when"])


def flag(name: str) -> bool:
    """True the first time it's called each day for this name (e.g. morning briefing)."""
    with _lock:
        flags = _load("flags.json", {})
        if flags.get(name) == today():
            return False
        flags[name] = today()
        _save("flags.json", flags)
        return True
