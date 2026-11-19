"""Instant answers for simple commands, no AI needed: lights, volume, music, scenes, the time.
Only short, unambiguous requests match; anything else goes to the brain."""
import re

from . import tools

FILLER = re.compile(r"\b(please|jarvis|could you|can you|would you|will you|for me|just|now|mate|the)\b|[,.!?]", re.I)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", FILLER.sub(" ", text.lower())).strip()


def _pct(t: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(%|percent|per cent)?", t)
    return max(0, min(100, int(m.group(1)))) if m else None


def route(text: str) -> tuple[str, dict, str] | None:
    """Returns (tool name, args, result) if this was a simple command we handled, else None."""
    t = _clean(text)
    if not t or len(t.split()) > 8 or re.search(r"\b(and|then|also|if|why|how|should)\b", t):
        return None  # anything compound or conversational is the brain's job

    def run(tool, **args):
        return tool, args, getattr(tools, tool)(**args)

    # lights
    # must read as a command ("turn the light on"), not a remark ("I left the light on at work")
    if re.search(r"\b(lights?|lamp|bulb)\b", t) and re.match(r"(turn|switch|set|put|dim|make|lights?|lamp|bulb)\b", t) \
            and not re.search(r"\b(is|are|was|were|too|broke|broken|isn'?t|aren'?t|bit)\b", t):
        if re.search(r"\b(off|out)\b", t):
            return run("control_device", name="all", action="off")
        if (p := _pct(t)) is not None:
            return run("control_device", name="all", action="on", brightness=max(p, 1))
        if re.search(r"\bdim\b", t):
            return run("control_device", name="all", action="on", brightness=30)
        if re.search(r"\b(full|max|maximum|brightest)\b", t):
            return run("control_device", name="all", action="on", brightness=100)
        if re.search(r"\bon\b", t):
            return run("control_device", name="all", action="on")
        return None
    # volume
    if re.search(r"\bmute\b", t):
        return run("set_volume", level=0)
    if "volume" in t and (p := _pct(t)) is not None:
        return run("set_volume", level=p)
    # music
    if re.fullmatch(r"(pause|stop)( (music|song|it|playing|playback))?", t):
        return run("media_control", action="pause")
    if re.fullmatch(r"(play|resume)( (some )?(music|song|it|tunes|something))?", t) or t in ("unpause", "resume music"):
        return run("media_control", action="play")
    if re.fullmatch(r"(next|skip)( this| it)?( (song|track|one))?", t):
        return run("media_control", action="next")
    if re.fullmatch(r"(previous|last|go back)( (song|track|one))?", t):
        return run("media_control", action="previous")
    # scenes
    if m := re.fullmatch(r"(?:(?:put )?(?:on |start |activate )?)(movie|focus|relax)(?: mode| time)?", t):
        return run("run_scene", name=m.group(1))
    if re.fullmatch(r"(good ?night|goodnight mode|bedtime|i'?m going to (bed|sleep))", t):
        return run("run_scene", name="goodnight")
    # time
    if re.fullmatch(r"(what time is it|what'?s time|what is time|time)", t):
        return run("get_time")
    return None
