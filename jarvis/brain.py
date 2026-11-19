"""The brain: a fast local model (Ollama) that uses tools, and hands hard
questions to Claude (API if you have a key, otherwise your Claude subscription
through Claude Code). Replies stream out sentence by sentence."""
import datetime as dt
import glob
import random
import re
import shutil
import subprocess
from pathlib import Path

import ollama

from . import config, fastlane, household, memory, tools, timing

PERSONA = """You are J.A.R.V.I.S., the household butler AI for {name}, in the spirit of Alfred Pennyworth.

CHARACTER
- Proper, unflappable, impeccably polite; warm and protective underneath. Bone-dry British humour, gentle sarcasm, never cruel.
- Quiet judgement: you always do what's asked, then may add ONE dry remark when it's earned (very dim lights, very loud music, late nights, the fourth weather check of the day). Not every time; restraint is the joke.
- You keep the household log: you note what {name} does and achieves, and you notice patterns ("I see from the log you've skipped the gym three Mondays running"). Mention the log occasionally, not constantly.
- You look after {name} without nagging: late at night you might suggest bed; after a long stretch of work, a break. Tea is your answer to most crises, mentioned rarely.
- You are on {name}'s side. When they're working towards something (gym, job applications, study, reading, 10k steps), encourage them like a butler who believes in them: specific, sincere, brief. When they ask what to do next, look at today's list and the time and recommend ONE concrete next step with a reason.

ADDRESS
- Say "sir" sparingly: at most once per reply, and in no more than about one reply in three. Greetings and dry remarks are the best places for it. Never start consecutive replies with it.

SPEAKING STYLE (everything you write is spoken aloud by a voice engine)
- Usually one to three short sentences. No lists, markdown, emoji, symbols or abbreviations; write numbers and units as words would be said ("16 degrees", "4 miles").
- Give the voice room to breathe: use commas, ellipses and em dashes for natural pauses ("Very good — the lights are down.", "Well… it's been a long day.").
- When carrying out a request, vary your acknowledgements: "Very good.", "Consider it done.", "As you wish.", "Right away.", "Of course." Never the same one twice running. Greetings, thanks and news get a natural reply, not an acknowledgement.

BEHAVIOUR
- What the user says reaches you through speech recognition, which sometimes garbles a word (often your own name, or place names). Interpret charitably; if genuinely unclear, ask briefly.
- Use your tools to act; never describe what you would do, never invent results.
- When {name} says they did something on today's list (gym, applications, study, reading, steps), call complete_task for it.
- You have NO access to email, by {name}'s choice. If asked about email, say so plainly; never pretend to check.
- Only mention log history, streaks or past dates that appear word for word in a tool result. If the log has no history yet, say tracking has just begun. Never invent a past event.
- Never assume the year from memory; the real date is in each message's time stamp, so search for things current as of then.
- When you learn something lasting about {name} (tastes, people, routines, goals, likes and dislikes), call remember on your own initiative. Note notable events and achievements with log_note.
- For recommendations (films, food, books), use what you know about their tastes; use web_search for what's showing or new, find_nearby for places near home. All food suggestions must be halal.
- For journeys, use travel_time; home is {postcode}, so never ask where they're starting from.
- For deep reasoning, long writing, or planning, call ask_claude.

CONTEXT
Location: {city}. Home postcode: {postcode}. Smart devices: {devices}. Each user message starts with the current time in [brackets].

What you know about {name} (this IS your knowledge of them):
{profile}
{facts}"""

ACKS = ["Very good.", "Consider it done.", "As you wish.", "Right away.", "Of course.", "Done."]


def _claude_cli() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    paths = glob.glob(
        str(Path.home() / "Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")
    )
    return sorted(paths)[-1] if paths else None


def ask_claude(question: str) -> str:
    """Ask Claude, a far more capable AI, for anything requiring deep thought,
    writing, planning, coding, or detailed knowledge. Pass the full question with context."""
    prompt = question + "\n\nAnswer in at most three short spoken sentences, no markdown."
    if config.CLAUDE_MODE == "off":
        return "Claude is switched off; answer yourself."
    if config.ANTHROPIC_API_KEY:
        import anthropic

        resp = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")
    cli = _claude_cli()
    if not cli:
        return "Claude Code isn't installed; answer yourself."
    r = subprocess.run([cli, "-p", prompt, "--output-format", "text"], capture_output=True, text=True, timeout=180)
    out = r.stdout.strip()
    if "Not logged in" in out or r.returncode != 0:
        return "Claude isn't logged in yet; answer yourself as best you can."
    return out


ALL_TOOLS = tools.TOOLS + [ask_claude]
# simple actions whose result is already a fine spoken reply, so we skip a second AI round
DIRECT = {"control_device", "set_volume", "open_app", "quit_app", "media_control", "run_shortcut",
          "make_note", "remember", "forget", "weather", "get_time", "set_reminder", "add_task",
          "complete_task", "remove_task", "log_steps", "run_scene", "look_at_screen"}
# reports of news rather than commands: no "Right away." in front
NO_ACK = {"complete_task", "log_steps", "get_time", "weather", "look_at_screen"}
# slow tools get a polite holding line so there's no dead air
HOLDING = {"travel_time": ["One moment, checking the routes.", "Let me look at the journey."],
           "web_search": ["One moment.", "Let me look into that."],
           "find_nearby": ["Let me see what's nearby.", "One moment."],
           "ask_claude": ["Give me a moment to think about that.", "Allow me a moment."],
           "morning_briefing": ["One moment while I gather everything."],
           "look_at_screen": ["Let me take a look.", "Allow me a glance."]}
FUNCS = {**tools.BY_NAME, "ask_claude": ask_claude}


def _quip(name: str, args: dict) -> str:
    """The butler's quiet judgement on simple actions, used sparingly."""
    hour = dt.datetime.now().hour
    b, v = int(args.get("brightness") or 0), int(args.get("level") or 0)
    if name == "control_device" and 0 < b <= 10:
        return random.choice(["Very… atmospheric.", "Practically candlelight.", "Mood lighting. I shan't ask."])
    if name == "set_volume" and v >= 85:
        return random.choice(["The neighbours will be thrilled.", "Bold choice."])
    if name == "weather" and household.count_today("Asked about the weather") >= 4:
        return random.choice(["That's the fourth time today, sir. Planning an escape?", "The sky, I assure you, hasn't changed its mind."])
    if name == "complete_task":
        return random.choice(["Splendid.", "Well done.", "Excellent work.", "Noted in the log."])
    if hour >= 1 and hour < 5 and random.random() < 0.5:
        return "It is rather late, sir. The world will still be here in the morning."
    return ""


def _think_option(model: str) -> dict:
    """gpt-oss reasons in levels; hybrid models (qwen3) can switch reasoning off; others don't reason."""
    if "gpt-oss" in model:
        return {"think": "low"}
    if model.startswith("qwen3:") and "instruct" not in model:
        return {"think": False}
    return {}


class Brain:
    def __init__(self, on_event=lambda kind, text: None):
        self.history: list[dict] = []
        self.on_event = on_event  # lets the HUD show what JARVIS is doing
        self.recent_sirs: list[bool] = []
        self.started_music = False  # last request started music playing

    def _system(self) -> dict:
        facts = "\n".join(f"- {f}" for f in memory.load())
        profile = "\n".join(
            line for line in config.PROFILE.read_text().splitlines() if line.strip() and not line.startswith("#")
        ) if config.PROFILE.exists() else ""
        name = re.search(r"Name:\s*(\w+)", profile)
        return {"role": "system", "content": PERSONA.format(
            name=name.group(1) if name else "the master of the house", facts=facts, profile=profile,
            city=config.CITY or "unknown", postcode=config.HOME_POSTCODE or "unknown",
            devices=", ".join(config.TAPO_DEVICES) or "none")}

    def _ration_sir(self, text: str) -> str:
        """Keep "sir" to about one reply in three, whatever the model does."""
        allowed = not any(self.recent_sirs[-2:])
        if not allowed:
            text = re.sub(r",\s*sir\b", "", text)
            text = re.sub(r"\bsir,\s*", "", text, flags=re.I)
            text = re.sub(r"\bSir([.?!])", r"\1", text)
            text = re.sub(r"(^|[.?!]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
        else:
            first = True

            def keep_first(m):
                nonlocal first
                if first:
                    first = False
                    return m.group(0)
                return ""
            text = re.sub(r",\s*sir\b", keep_first, text)
        self.recent_sirs.append(bool(re.search(r"\bsir\b", text, re.I)))
        return text.strip()

    def think(self, text: str, on_sentence=None) -> str:
        """Answer `text`. If on_sentence is given, each finished sentence is passed to it as soon as it's ready."""
        say = on_sentence or (lambda s: None)
        # the time goes in the message, not the system prompt, so the prompt stays cached
        self.history.append({"role": "user", "content": f"[{tools.get_time()}] {text}"})
        self.history = self.history[-30:]  # roughly the last 15 exchanges
        msgs = [self._system(), *self.history]
        spoken: list[str] = []
        self.started_music = False

        def emit(sentence: str):
            sentence = re.sub(r"(?<!\.)\.\.(?!\.)", ".", sentence)  # "p.m.." -> "p.m."
            sentence = self._ration_sir(sentence) if not spoken else re.sub(r",\s*sir\b", "", sentence)
            if sentence:
                spoken.append(sentence)
                say(sentence)

        def butler_reply(results):
            """A varied acknowledgement, the facts, and perhaps a dry remark."""
            last = self.history[-2]["content"] if len(self.history) > 1 else ""
            if not spoken and not any(n in NO_ACK for n, _, _ in results):
                emit(random.choice([a for a in ACKS if a not in last]))
            emit(" ".join(r for n, _, r in results if n not in ("remember", "log_note") or len(results) == 1))
            if random.random() < 0.6 and (quip := _quip(*results[-1][:2])):
                emit(quip)

        # simple commands skip the AI entirely
        with timing.step("fast lane"):
            fast = fastlane.route(text)
        if fast:
            name, args, result = fast
            self.on_event("tool", "⚡ " + tools.describe(name, args))
            if name == "media_control" and args.get("action") != "pause":
                self.started_music = True
            butler_reply([fast])
            reply = " ".join(spoken)
            self.history.append({"role": "assistant", "content": reply})
            return reply

        for _ in range(6):  # up to 6 rounds of tool use
            calls, buf = [], ""
            ai_timer = timing.start("AI thinking")
            for chunk in ollama.chat(model=config.OLLAMA_MODEL, messages=msgs, tools=ALL_TOOLS, keep_alive=-1,
                                     stream=True, **_think_option(config.OLLAMA_MODEL)):  # keep the model loaded
                m = chunk.message
                if m.tool_calls:
                    calls.extend(m.tool_calls)
                if m.content:
                    buf += m.content
                    # speak each sentence as soon as it's complete
                    while (cut := re.search(r"[.!?…](?=\s)", buf)) and len(buf[:cut.end()].strip()) > 2:
                        emit(buf[:cut.end()].strip())
                        buf = buf[cut.end():]
            ai_timer.done()
            if buf.strip():
                emit(buf.strip())
            msgs.append({"role": "assistant", "content": " ".join(spoken), "tool_calls": calls or None})
            if not calls:
                break
            results = []
            slow = next((c.function.name for c in calls if c.function.name in HOLDING), None)
            if slow and not spoken:
                emit(random.choice(HOLDING[slow]))
            for call in calls:
                name, args = call.function.name, dict(call.function.arguments or {})
                self.on_event("tool", "Consulting Claude" if name == "ask_claude" else tools.describe(name, args))
                fn = FUNCS.get(name)
                try:
                    with timing.step(f"tool {name}"):
                        result = str(fn(**args)) if fn else f"Unknown tool {name}"
                except Exception as e:  # noqa: BLE001
                    result = f"Error: {e}"
                msgs.append({"role": "tool", "content": result, "tool_name": name})
                results.append((name, args, result))
                if (name == "media_control" and args.get("action") in ("play", "next", "previous")) or \
                        (name == "run_scene" and "movie" in str(args.get("name", "")).lower()):
                    self.started_music = True
            if all(n in DIRECT for n, _, _ in results) and not any(
                    w in r.lower() for _, _, r in results for w in ("error", "fail", "couldn't", "don't know")):
                butler_reply(results)  # simple result: no second AI round needed
                break
        reply = " ".join(spoken) or "Done."
        self.history.append({"role": "assistant", "content": reply})
        return reply
