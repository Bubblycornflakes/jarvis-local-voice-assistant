"""Long-term memory: a simple list of facts saved to data/memory.json."""
import json

from .config import DATA

FILE = DATA / "memory.json"


def load() -> list[str]:
    try:
        return json.loads(FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def add(fact: str):
    facts = load()
    if fact not in facts:
        facts.append(fact)
        FILE.write_text(json.dumps(facts, indent=2))


def remove(text: str) -> bool:
    facts = load()
    keep = [f for f in facts if text.lower() not in f.lower()]
    FILE.write_text(json.dumps(keep, indent=2))
    return len(keep) < len(facts)
