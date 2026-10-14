"""Tests for bod.py. Run: python3 -m unittest discover scripts"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bod  # noqa: E402

NOW = datetime(2026, 10, 13, 10, 0).astimezone()
NOT_OVER = lambda now: timedelta(hours=1)  # noqa: E731
OVER = lambda now: timedelta(hours=5)  # noqa: E731


def minutes(n):
    return timedelta(minutes=n)


def working(now=NOW, **ago):
    """A state where she just prompted; `move=11` puts last_move 11 minutes back."""
    state = bod.fresh_state(now)
    for name, n in ago.items():
        state[f"last_{name}"] = now - minutes(n)
    return state


class Advance(unittest.TestCase):
    def test_nothing_is_due_right_after_a_break(self):
        state = working()
        bod.advance(state, NOW, NOT_OVER)
        self.assertIsNone(state["pending"])

    def test_an_exercise_goes_on_show_after_ten_minutes(self):
        state = working(move=11)
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "move")
        self.assertEqual(state["pending"]["text"], "5 push ups")
        self.assertIsNone(state["pending"]["started"])

    def test_the_plank_counts_down(self):
        state = working(move=11)
        state["moves"] = 3
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["seconds"], 20)

    def test_one_nudge_at_a_time(self):
        state = working(move=50, stand=50, kind=50)
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "move")
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "move")

    def test_nothing_new_while_she_is_away(self):
        state = working(move=50, prompt=25)
        bod.advance(state, NOW, NOT_OVER)
        self.assertIsNone(state["pending"])

    def test_an_unstarted_nudge_is_dropped_once_she_walks_off(self):
        state = working(move=11)
        bod.advance(state, NOW, NOT_OVER)
        bod.advance(state, NOW + minutes(bod.BREAK_MINUTES), NOT_OVER)
        self.assertIsNone(state["pending"])

    def test_over_the_cap_the_stand_nudge_becomes_a_stop_line_for_the_day(self):
        state = working(stand=31)
        bod.advance(state, NOW, OVER)
        self.assertIsNone(state["pending"])
        self.assertIn("Stop for the day", state["stop"]["text"])
        self.assertIn("Stop for the day", bod.view(state, NOW)["stop"])

        state["last_prompt"] = NOW + timedelta(days=1)
        bod.advance(state, NOW + timedelta(days=1), NOT_OVER)
        self.assertIsNone(state["stop"])


class Press(unittest.TestCase):
    def shown(self, **ago):
        state = working(**ago)
        bod.advance(state, NOW, NOT_OVER)
        return state

    def test_go_starts_the_timer_and_done_reports_how_long_it_took(self):
        state = self.shown(move=11)
        bod.press(state, "go", NOW)
        self.assertEqual(bod.view(state, NOW)["nudge"]["started"], int(NOW.timestamp() * 1000))

        said = bod.press(state, "done", NOW + timedelta(seconds=41))
        self.assertEqual(said, {"took": 41})
        self.assertIsNone(state["pending"])
        self.assertEqual(state["moves"], 1)
        self.assertEqual(state["last_move"], NOW + timedelta(seconds=41))

    def test_after_done_the_band_stays_empty_for_a_minute(self):
        state = self.shown(move=11, stand=31)
        bod.press(state, "done", NOW)
        bod.advance(state, NOW + timedelta(seconds=30), NOT_OVER)
        self.assertIsNone(state["pending"])
        bod.advance(state, NOW + timedelta(seconds=61), NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "stand")

    def test_done_on_a_kindness_nudge_has_no_time_to_report(self):
        state = self.shown(kind=46)
        self.assertEqual(bod.press(state, "done", NOW), {})
        self.assertEqual(state["kinds"], 1)

    def test_not_now_hides_the_nudge_for_five_minutes_then_brings_the_same_one_back(self):
        state = self.shown(move=11)
        bod.press(state, "snooze", NOW)
        self.assertIsNone(bod.view(state, NOW + minutes(4))["nudge"])
        self.assertEqual(bod.view(state, NOW + minutes(5))["nudge"]["text"], "5 push ups")
        self.assertEqual(state["moves"], 0)

    def test_only_the_first_session_to_ask_gets_to_beep(self):
        state = self.shown(move=11)
        state["pending"]["seconds"] = 20
        bod.press(state, "go", NOW)
        self.assertEqual(bod.press(state, "beep", NOW + timedelta(seconds=5)), {})
        self.assertEqual(bod.press(state, "beep", NOW + timedelta(seconds=20)), {"beep": True})
        self.assertEqual(bod.press(state, "beep", NOW + timedelta(seconds=21)), {})

    def test_a_button_with_nothing_on_show_does_nothing(self):
        state = working()
        self.assertEqual(bod.press(state, "done", NOW), {})


class Prompted(unittest.TestCase):
    def test_with_the_mod_running_claude_is_handed_nothing(self):
        state = working(move=50, stand=50, kind=50, prompt=1)
        state["mod_seen"] = NOW - timedelta(seconds=5)
        state, nudges = bod.prompted(state, NOW)
        self.assertEqual(nudges, [])
        self.assertEqual(state["last_prompt"], NOW)
        self.assertEqual(state["moves"], 0)

    def test_without_the_mod_claude_still_passes_the_nudges_on(self):
        state = working(move=11, prompt=1)
        state["mod_seen"] = NOW - minutes(30)
        state["pending"] = {"kind": "move", "text": "x", "seconds": None, "started": None, "snoozed_until": None}
        state, nudges = bod.prompted(state, NOW)
        self.assertEqual(nudges, ["Movement break: 5 push ups. Go, I'll wait."])
        self.assertIsNone(state["pending"])

    def test_coming_back_from_a_break_restarts_every_timer(self):
        state = working(move=50, prompt=25)
        state["moves"] = 2
        state, nudges = bod.prompted(state, NOW)
        self.assertEqual(nudges, [])
        self.assertEqual(state["last_move"], NOW)
        self.assertEqual(state["moves"], 2)


class CommandLine(unittest.TestCase):
    """The state file round trip, as the mod and the hook really run it."""

    def run_bod(self, mode, path, *args):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "bod.py"), mode, *args],
            env={**os.environ, "BOD_STATE": path},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return json.loads(out) if out else None

    def test_tick_go_done_through_the_state_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            self.assertIsNone(self.run_bod("tick", path)["nudge"])

            with open(path) as fh:
                raw = json.load(fh)
            raw["last_move"] = (datetime.now().astimezone() - minutes(11)).isoformat()
            with open(path, "w") as fh:
                json.dump(raw, fh)

            self.assertEqual(self.run_bod("tick", path)["nudge"]["kind"], "move")
            self.assertIsNotNone(self.run_bod("go", path)["nudge"]["started"])
            # The mod just ticked, so the hook leaves the nudging to it.
            self.assertIsNone(self.run_bod("hook", path))
            done = self.run_bod("done", path)
            self.assertIsNone(done["nudge"])
            self.assertIn("took", done)

    def test_show_puts_the_asked_nudge_on_the_band_at_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            self.assertEqual(self.run_bod("show", path, "plank")["nudge"]["seconds"], 20)
            self.assertEqual(self.run_bod("show", path, "kind")["nudge"]["kind"], "kind")
            self.assertEqual(self.run_bod("tick", path)["nudge"]["kind"], "kind")

    def test_a_state_file_from_before_the_mod_still_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            old = datetime.now().astimezone() - minutes(1)
            with open(path, "w") as fh:
                json.dump({**{key: old.isoformat() for key in bod.TIMES}, "moves": 4, "kinds": 1}, fh)
            self.assertIsNone(self.run_bod("tick", path)["nudge"])
            with open(path) as fh:
                self.assertEqual(json.load(fh)["moves"], 4)


if __name__ == "__main__":
    unittest.main()
