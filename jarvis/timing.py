"""Timing log: how long each step of a request takes, in data/timing.log.
When JARVIS feels slow, this shows which step is to blame."""
import contextlib
import datetime as dt
import threading
import time

from .config import DATA

FILE = DATA / "timing.log"
_lock = threading.Lock()


def log(label: str, seconds: float):
    with _lock:
        with FILE.open("a") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {seconds:6.2f}s  {label}\n")
        if FILE.stat().st_size > 500_000:  # keep it small
            lines = FILE.read_text().splitlines()[-2000:]
            FILE.write_text("\n".join(lines) + "\n")


class _Timer:
    def __init__(self, label):
        self.label, self.t = label, time.perf_counter()

    def done(self):
        log(self.label, time.perf_counter() - self.t)


def start(label: str) -> _Timer:
    return _Timer(label)


@contextlib.contextmanager
def step(label: str):
    t = start(label)
    try:
        yield
    finally:
        t.done()
