"""Tests for the fast lane (instant commands) and a few helpers.

Run from the project folder:  python -m unittest discover -s tests -v
The real tools are replaced with recorders, so nothing is switched on or played.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import fastlane, tools  # noqa: E402

# (what the user says, tool the fast lane should call or None for "leave it to the brain", expected args)
CASES = [
    # lights
    ("turn the lights off", "control_device", {"name": "all", "action": "off"}),
    ("Jarvis, switch the light on please", "control_device", {"name": "all", "action": "on"}),
    ("dim the lights", "control_device", {"name": "all", "action": "on", "brightness": 30}),
    ("set the lights to 50 percent", "control_device", {"name": "all", "action": "on", "brightness": 50}),
    ("lights full", "control_device", {"name": "all", "action": "on", "brightness": 100}),
    # volume
    ("mute", "set_volume", {"level": 0}),
    ("set the volume to 40", "set_volume", {"level": 40}),
    # music
    ("pause", "media_control", {"action": "pause"}),
    ("stop the music", "media_control", {"action": "pause"}),
    ("play some music", "media_control", {"action": "play"}),
    ("resume", "media_control", {"action": "play"}),
    ("skip this song", "media_control", {"action": "next"}),
    ("previous track", "media_control", {"action": "previous"}),
    # scenes and time
    ("movie mode", "run_scene", {"name": "movie"}),
    ("goodnight", "run_scene", {"name": "goodnight"}),
    ("what time is it", "get_time", {}),
    # must NOT be handled here: remarks, questions, compound requests
    ("I left the light on at work", None, None),
    ("the lights are too bright", None, None),
    ("why is the light flickering", None, None),
    ("turn the lights off and play some music", None, None),
    ("how do I mute a call in Zoom", None, None),
    ("tell me about the history of London", None, None),
    ("what is the weather like", None, None),
    ("", None, None),
]


class FastLane(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.patchers = []
        for name in ("control_device", "set_volume", "media_control", "run_scene", "get_time"):
            p = mock.patch.object(tools, name, side_effect=lambda _n=name, **kw: self.calls.append((_n, kw)) or "ok")
            p.start()
            self.patchers.append(p)

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_cases(self):
        wrong = []
        for text, tool, args in CASES:
            self.calls.clear()
            result = fastlane.route(text)
            if tool is None:
                if result is not None or self.calls:
                    wrong.append((text, "should have passed to the brain", result))
            else:
                got = (result[0], result[1]) if result else None
                if got != (tool, args):
                    wrong.append((text, (tool, args), got))
        self.assertEqual(wrong, [], f"{len(wrong)} of {len(CASES)} cases wrong")

    def test_named_device_goes_to_the_brain(self):
        with mock.patch.dict(fastlane.config.TAPO_DEVICES, {"desk lamp": "192.0.2.1"}):
            self.assertIsNone(fastlane.route("switch off the desk lamp"))
            self.assertIsNotNone(fastlane.route("turn the lights off"))

    def test_volume_is_clamped(self):
        result = fastlane.route("set the volume to 250")
        self.assertEqual(result[1], {"level": 100})


class Reminders(unittest.TestCase):
    def test_relative_minutes(self):
        import datetime as dt
        t = tools._parse_when("in 20 minutes")
        delta = (t - dt.datetime.now()).total_seconds() / 60
        self.assertAlmostEqual(delta, 20, delta=0.5)

    def test_pm_time(self):
        t = tools._parse_when("6pm")
        self.assertEqual((t.hour, t.minute), (18, 0))

    def test_tomorrow_is_in_the_future(self):
        import datetime as dt
        self.assertGreater(tools._parse_when("tomorrow 9am"), dt.datetime.now())

    def test_unparseable_returns_none(self):
        self.assertIsNone(tools._parse_when("whenever"))


if __name__ == "__main__":
    unittest.main()
