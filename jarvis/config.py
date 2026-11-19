"""Settings, loaded from the .env file in the project folder."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)


def _load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env()

# Brain
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:8b-instruct")  # local model that can see screenshots
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
# "auto": API if a key is set, else Claude Code (your subscription). "off": local only.
CLAUDE_MODE = os.getenv("CLAUDE_MODE", "auto")

# Voice
# "jarvis" (or any word) is spotted by speech recognition; "hey_jarvis", "alexa",
# "hey_mycroft" and "hey_rhasspy" use lighter dedicated models.
WAKE_WORD = os.getenv("WAKE_WORD", "jarvis")
# how the wake word may be transcribed; whisper sometimes hears "Jarvis" as these
WAKE_PATTERN = os.getenv("WAKE_PATTERN", "(?:jarvis|jervis|javis|jarvas|travis)")
VOICE = os.getenv("VOICE", "bm_george")  # Kokoro voice; or a macOS voice like "Daniel"
DEBUG_VOICE = os.getenv("DEBUG_VOICE") == "1"
FOLLOW_UP_SECONDS = float(os.getenv("FOLLOW_UP_SECONDS", "5"))  # mic stays open after a reply
# speech recognition, on the Mac's GPU; "mlx-community/whisper-small.en-mlx" is lighter but less accurate
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

# Tapo
TAPO_EMAIL = os.getenv("TAPO_EMAIL", "")
TAPO_PASSWORD = os.getenv("TAPO_PASSWORD", "")
# name=ip pairs, e.g. "bedroom=192.168.1.40,desk lamp=192.168.1.41"
TAPO_DEVICES = {
    k.strip().lower(): v.strip()
    for k, v in (p.split("=", 1) for p in os.getenv("TAPO_DEVICES", "").split(",") if "=" in p)
}

USER_NAME = os.getenv("USER_NAME", "sir")
HOME_POSTCODE = os.getenv("HOME_POSTCODE", "")
# added to the to-do list every morning and tracked in the household log
DAILY_HABITS = [h.strip() for h in os.getenv(
    "DAILY_HABITS", "exercise,study,read,ten thousand steps").split(",") if h.strip()]
PROFILE = ROOT / "about me.txt"  # free-form notes about the user, edit any time


def _detect_city() -> str:
    try:
        import httpx

        d = httpx.get("https://ipinfo.io/json", timeout=4).json()
        return ", ".join(x for x in (d.get("city"), d.get("country")) if x)
    except Exception:  # noqa: BLE001
        return ""


CITY = os.getenv("CITY") or _detect_city()
