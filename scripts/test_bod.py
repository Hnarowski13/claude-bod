"""Tests for bod.py. Run: python3 -m unittest discover scripts"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Never her real choices: each test starts from the defaults (easy, every 5).
SETTINGS_DIR = tempfile.mkdtemp()
os.environ["BOD_SETTINGS"] = os.path.join(SETTINGS_DIR, "settings.json")
import bod  # noqa: E402


def setUpModule():
    # Nudges pick at random; these tests see the list in order instead.
    patch = mock.patch.object(bod, "pick", lambda count: bod.EXERCISES[:count])
    patch.start()
    unittest.addModuleCleanup(patch.stop)


PICK = bod.pick  # the real one, before setUpModule swaps it
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
        plank = [e for e in bod.EXERCISES if "plank" in e[0]]
        with mock.patch.object(bod, "pick", lambda count: plank):
            bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["seconds"], 20)

    def test_one_nudge_at_a_time(self):
        state = working(move=50, cap=50, kind=50)
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

    def test_there_is_no_standing_desk_nudge_any_more(self):
        state = working(cap=31)
        bod.advance(state, NOW, NOT_OVER)
        self.assertIsNone(state["pending"])
        self.assertIsNone(state["stop"])
        self.assertEqual(state["last_cap"], NOW)

    def test_over_the_cap_a_stop_line_stays_up_for_the_day(self):
        state = working(cap=31)
        bod.advance(state, NOW, OVER)
        self.assertIsNone(state["pending"])
        self.assertIn("Stop for the day", state["stop"]["text"])
        self.assertIn("Stop for the day", bod.view(state, NOW)["stop"])

        state["last_prompt"] = NOW + timedelta(days=1)
        bod.advance(state, NOW + timedelta(days=1), NOT_OVER)
        self.assertIsNone(state["stop"])


class OldState(unittest.TestCase):
    def test_a_state_file_from_when_there_was_a_standing_nudge_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            when = (NOW - minutes(10)).isoformat()
            with open(path, "w") as fh:
                json.dump({
                    "last_prompt": when, "last_move": when, "last_stand": when, "last_kind": when,
                    "moves": 3, "kinds": 1,
                    "pending": {"kind": "stand", "text": "x", "seconds": None, "started": None, "snoozed_until": None},
                }, fh)
            old, bod.STATE_PATH = bod.STATE_PATH, path
            try:
                state = bod.load_state()
            finally:
                bod.STATE_PATH = old
        self.assertEqual(state["last_cap"], NOW - minutes(10))
        self.assertEqual(state["moves"], 3)
        self.assertIsNone(state["pending"])


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
        state = self.shown(move=11, kind=46)
        bod.press(state, "done", NOW)
        bod.advance(state, NOW + timedelta(seconds=30), NOT_OVER)
        self.assertIsNone(state["pending"])
        bod.advance(state, NOW + timedelta(seconds=61), NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "kind")

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

    def test_swap_trades_the_exercise_for_one_not_already_on_show(self):
        state = self.shown(move=11)
        with mock.patch.object(bod.random, "sample", lambda pool, count: pool[:count]):
            bod.press(state, "swap", NOW)
        self.assertEqual(state["pending"]["text"], "10 jumping jacks")
        self.assertEqual(state["pending"]["count"], 1)
        self.assertIsNone(state["pending"]["started"])
        self.assertEqual(state["moves"], 0)

    def test_swap_never_brings_back_an_exercise_from_the_set(self):
        text = "10 jumping jacks, then a 20 second plank"
        for _ in range(50):
            swapped, _, count = bod.swapped(text, "medium", 2)
            self.assertEqual(count, 2)
            self.assertNotIn("jumping jacks", swapped)
            self.assertNotIn("plank", swapped)

    def test_swap_leaves_a_started_exercise_alone(self):
        state = self.shown(move=11)
        bod.press(state, "go", NOW)
        bod.press(state, "swap", NOW)
        self.assertEqual(state["pending"]["text"], "5 push ups")

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


class Skips(unittest.TestCase):
    def test_not_now_counts_on_the_nudge_and_in_the_days_total(self):
        state = working(move=11)
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(bod.view(state, NOW)["nudge"]["skipped"], 0)
        bod.press(state, "snooze", NOW)
        bod.press(state, "snooze", NOW + minutes(5))
        back = bod.view(state, NOW + minutes(10))
        self.assertEqual(back["nudge"]["skipped"], 2)
        self.assertEqual(back["skips"], 2)

    def test_a_new_nudge_starts_with_no_skips_but_the_day_keeps_counting(self):
        state = working(move=11)
        bod.advance(state, NOW, NOT_OVER)
        bod.press(state, "snooze", NOW)
        bod.press(state, "done", NOW + minutes(5))
        state["last_move"] = NOW - minutes(10)
        bod.advance(state, NOW + minutes(7), NOT_OVER)
        shown = bod.view(state, NOW + minutes(7))
        self.assertEqual(shown["nudge"]["skipped"], 0)
        self.assertEqual(shown["skips"], 1)

    def test_the_count_starts_over_the_next_day_and_survives_a_break(self):
        state = working(move=11)
        bod.advance(state, NOW, NOT_OVER)
        bod.press(state, "snooze", NOW)
        state = bod.fresh_state(NOW + minutes(30), state)
        self.assertEqual(bod.view(state, NOW + minutes(30))["skips"], 1)
        self.assertEqual(bod.view(state, NOW + timedelta(days=1))["skips"], 0)


class Upcoming(unittest.TestCase):
    EVERY_5 = {"level": "easy", "every": 5, "kind": 15}

    def next_in(self, state, now=NOW):
        """{kind: seconds until it's due} from what the mod is sent."""
        shown = bod.view(state, now, self.EVERY_5)
        if shown["next"] is None:
            return None
        return {kind: (ms - int(now.timestamp() * 1000)) // 1000 for kind, ms in shown["next"].items()}

    def test_counts_down_to_the_exercise(self):
        state = working(move=2)
        self.assertEqual(self.next_in(state), {"move": 180})

    def test_hits_zero_the_moment_the_nudge_goes_on_show(self):
        state = working(move=2)
        due = NOW + minutes(3)
        self.assertEqual(self.next_in(state, due)["move"], 0)
        bod.advance(state, due, NOT_OVER, self.EVERY_5)
        self.assertEqual(state["pending"]["kind"], "move")

    def test_nothing_to_count_while_a_nudge_is_on_show(self):
        state = working(move=6)
        bod.advance(state, NOW, NOT_OVER, self.EVERY_5)
        self.assertIsNone(self.next_in(state))

    def test_not_now_counts_down_to_the_same_nudge_coming_back(self):
        state = working(move=6)
        bod.advance(state, NOW, NOT_OVER, self.EVERY_5)
        bod.press(state, "snooze", NOW)
        self.assertEqual(self.next_in(state), {"move": bod.DEFAULT_SETTINGS["snooze"] * 60})

    def test_not_now_on_kindness_keeps_the_exercise_countdown(self):
        state = working(move=2, kind=46)
        bod.advance(state, NOW, NOT_OVER, self.EVERY_5)
        self.assertEqual(state["pending"]["kind"], "kind")
        bod.press(state, "snooze", NOW)
        # The exercise waits for the kindness nudge to come back and be done.
        self.assertEqual(self.next_in(state), {"move": bod.DEFAULT_SETTINGS["snooze"] * 60})
        later = NOW + minutes(4)
        self.assertEqual(self.next_in(state, later), {"move": 60})

    def test_after_done_nothing_is_due_before_the_quiet_minute_ends(self):
        state = working(move=4.5, kind=46)
        bod.advance(state, NOW, NOT_OVER, self.EVERY_5)
        bod.press(state, "done", NOW)
        self.assertEqual(self.next_in(state), {"move": bod.QUIET_SECONDS})

    def test_away_long_enough_it_says_paused_instead(self):
        state = working(move=2, prompt=bod.BREAK_MINUTES)
        shown = bod.view(state, NOW, self.EVERY_5)
        self.assertTrue(shown["paused"])
        self.assertIsNone(shown["next"])


class RightNow(unittest.TestCase):
    EASY = {"level": "easy", "every": 5, "kind": 15}

    def test_the_next_exercise_goes_up_without_waiting(self):
        state = working(move=1, kind=10)
        bod.right_now(state, NOW, self.EASY)
        self.assertEqual(state["pending"]["kind"], "move")
        self.assertEqual(state["pending"]["text"], "5 push ups")
        # The other timers carry on as they were.
        self.assertEqual(state["last_kind"], NOW - minutes(10))

    def test_done_restarts_the_exercise_timer_and_counts_the_exercise(self):
        state = working(move=1)
        bod.right_now(state, NOW, self.EASY)
        bod.press(state, "done", NOW + minutes(1))
        self.assertEqual(state["last_move"], NOW + minutes(1))
        self.assertEqual(state["moves"], 1)

    def test_a_nudge_already_up_stays(self):
        state = working(kind=46)
        bod.advance(state, NOW, NOT_OVER, self.EASY)
        bod.right_now(state, NOW, self.EASY)
        self.assertEqual(state["pending"]["kind"], "kind")

    def test_a_nudge_put_off_comes_straight_back(self):
        state = working(move=6)
        bod.advance(state, NOW, NOT_OVER, self.EASY)
        bod.press(state, "snooze", NOW)
        bod.right_now(state, NOW + minutes(1), self.EASY)
        self.assertEqual(bod.view(state, NOW + minutes(1), self.EASY)["nudge"]["text"], "5 push ups")

    def test_it_shows_even_after_she_was_away_or_just_pressed_done(self):
        state = working(move=1, prompt=bod.BREAK_MINUTES + 5)
        state["quiet_until"] = NOW + minutes(1)
        bod.right_now(state, NOW, self.EASY)
        bod.advance(state, NOW, NOT_OVER, self.EASY)
        self.assertEqual(bod.view(state, NOW, self.EASY)["nudge"]["kind"], "move")

    def test_kind_now_puts_a_kindness_nudge_up_and_leaves_the_exercise_timer(self):
        state = working(move=1, kind=1)
        bod.right_now(state, NOW, self.EASY, kind="kind")
        self.assertEqual(state["pending"]["kind"], "kind")
        self.assertEqual(state["last_move"], NOW - minutes(1))
        bod.press(state, "done", NOW + minutes(1))
        self.assertEqual(state["last_kind"], NOW + minutes(1))
        self.assertEqual(state["kinds"], 1)


class Prompted(unittest.TestCase):
    def test_with_the_mod_running_claude_is_handed_nothing(self):
        state = working(move=50, cap=50, kind=50, prompt=1)
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


class Levels(unittest.TestCase):
    def setUp(self):
        if os.path.exists(bod.SETTINGS_PATH):
            os.remove(bod.SETTINGS_PATH)

    def test_the_exercise_nudge_comes_every_five_minutes_by_default(self):
        state = working(move=4)
        bod.advance(state, NOW, NOT_OVER)
        self.assertIsNone(state["pending"])
        state = working(move=5)
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "move")

    def test_every_ten_waits_ten_minutes(self):
        settings = {"level": "easy", "every": 10, "kind": 15}
        state = working(move=6)
        bod.advance(state, NOW, NOT_OVER, settings)
        self.assertIsNone(state["pending"])

    def test_kindness_comes_on_its_own_chosen_interval(self):
        state = working(kind=16)
        bod.advance(state, NOW, NOT_OVER, {"level": "easy", "every": 5, "kind": 30})
        self.assertIsNone(state["pending"])
        bod.advance(state, NOW, NOT_OVER, {"level": "easy", "every": 5, "kind": 15})
        self.assertEqual(state["pending"]["kind"], "kind")

    def test_easy_is_one_exercise(self):
        self.assertEqual(bod.exercise("easy"), ("5 push ups", None, 1))

    def test_medium_is_two_exercises(self):
        self.assertEqual(bod.exercise("medium"), ("5 push ups, then 10 jumping jacks", None, 2))

    def test_hard_is_three_exercises_with_more_reps(self):
        text, _, count = bod.exercise("hard", bod.EXERCISES[2:5])
        self.assertEqual(text, "15 squats, then a 30 second plank, then 15 calf raises")
        self.assertEqual(count, 3)

    def test_a_lone_plank_counts_down_and_a_set_counts_up(self):
        self.assertEqual(bod.exercise("easy", bod.EXERCISES[3:4])[1], 20)
        self.assertEqual(bod.exercise("hard", bod.EXERCISES[3:6])[1], None)

    def test_each_nudge_is_a_random_set_of_different_exercises(self):
        with mock.patch.object(bod, "pick", PICK):
            sets = [tuple(bod.pick(3)) for _ in range(50)]
        for picked in sets:
            self.assertEqual(len(set(picked)), 3)
        # Not a fixed rotation: the same set doesn't keep coming back.
        self.assertGreater(len(set(sets)), 10)

    def test_done_counts_every_exercise_in_the_set(self):
        state = working(move=6)
        bod.advance(state, NOW, NOT_OVER, {"level": "hard", "every": 5, "kind": 15, "claudes": 5, "snooze": 5})
        bod.press(state, "done", NOW)
        self.assertEqual(state["moves"], 3)

    def test_a_bad_settings_file_falls_back_to_the_defaults(self):
        with open(bod.SETTINGS_PATH, "w") as fh:
            fh.write('{"level": "extreme", "every": 7, "kind": 15}')
        self.assertEqual(bod.load_settings(), {"level": "easy", "every": 5, "kind": 15, "claudes": 5, "snooze": 5})


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
            self.assertEqual(self.run_bod("show", path, "check")["nudge"]["kind"], "check")

    def test_level_and_every_are_kept_and_checked(self):
        run = lambda *args: subprocess.run(  # noqa: E731
            [sys.executable, os.path.join(HERE, "bod.py"), *args], capture_output=True, text=True
        )
        self.assertEqual(run("level", "hard").stdout.strip(), "Your level is now hard: 3 exercises with more reps per nudge.")
        self.assertEqual(run("every", "15").stdout.strip(), "Your exercises are now every 15 minutes.")
        self.assertEqual(bod.load_settings(), {"level": "hard", "every": 15, "kind": 15, "claudes": 5, "snooze": 5})
        self.assertEqual(run("settings").stdout.strip(), "Claude Bod is on hard: 3 exercises with more reps every 15 minutes, something kind every 15, at most 5 Claudes open at once.")
        both = run("level", "medium", "every", "10")
        self.assertEqual(both.stdout.strip(), "Your level is now medium: 2 exercises per nudge. Your exercises are now every 10 minutes.")
        self.assertEqual(bod.load_settings(), {"level": "medium", "every": 10, "kind": 15, "claudes": 5, "snooze": 5})
        short = run("level", "hard", "15")
        self.assertEqual(short.stdout.strip(), "Your level is now hard: 3 exercises with more reps per nudge. Your exercises are now every 15 minutes.")
        self.assertEqual(bod.load_settings(), {"level": "hard", "every": 15, "kind": 15, "claudes": 5, "snooze": 5})
        run("level", "medium", "every", "10")
        half_bad = run("level", "easy", "every", "7")
        self.assertEqual(half_bad.returncode, 1)
        self.assertEqual(bod.load_settings(), {"level": "medium", "every": 10, "kind": 15, "claudes": 5, "snooze": 5})
        bad = run("every", "7")
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(bad.stdout.strip(), "Pick one of: 5, 10, 15. It's 10 now.")
        self.assertEqual(run("kind", "30").stdout.strip(), "Something kind is now every 30 minutes.")
        self.assertEqual(bod.load_settings()["kind"], 30)
        self.assertEqual(run("kind", "20").stdout.strip(), "Pick one of: 5, 10, 15, 30, 45. It's 30 now.")
        self.assertEqual(bod.load_settings()["kind"], 30)
        self.assertEqual(run("claudes", "3").stdout.strip(), "Your Claude cap is now 3 (was 5).")
        self.assertEqual(run("claudes", "3").stdout.strip(), "Your Claude cap is still 3.")
        self.assertEqual(bod.load_settings()["claudes"], 3)
        too_many = run("claudes", "50")
        self.assertEqual(too_many.returncode, 1)
        self.assertEqual(too_many.stdout.strip(), "Pick a number from 1 to 10. It's 3 now.")
        self.assertEqual(run("claudes", "how", "many").stdout.strip(), "Pick a number from 1 to 10. It's 3 now.")
        lines = run("info").stdout.strip().splitlines()
        self.assertEqual(lines[0], "Claude Bod settings (/bod config to change them in one form):")
        self.assertIn("- Snooze: 5 minutes · /bod snooze 2|5|10|15", lines)
        self.assertEqual(run("snooze", "10").stdout.strip(), "Not now puts a nudge off for 10 minutes.")
        self.assertEqual(run("snooze", "7").stdout.strip(), "Pick one of: 2, 5, 10, 15. It's 10 now.")
        self.assertEqual(json.loads(run("choices").stdout), {
            "settings": {"level": "medium", "every": 10, "kind": 30, "claudes": 3, "snooze": 10},
            "choices": {"level": ["easy", "medium", "hard"], "every": [5, 10, 15], "kind": [5, 10, 15, 30, 45],
                        "claudes": list(range(1, 11)), "snooze": [2, 5, 10, 15]},
        })
        self.assertIn("- Level: medium (2 exercises per nudge) · /bod level easy|medium|hard", lines)
        self.assertIn("- Exercise every 10 minutes of work · /bod every 5|10|15", lines)
        self.assertIn("- Something kind every 30 minutes · /bod kind 5|10|15|30|45", lines)
        self.assertIn("- Claude cap: 3 open at once · /bod claudes 1-10", lines)
        self.assertIn(f"- Daily cap: {bod.DAILY_CAP_HOURS} hours, then a stop-for-the-day line", lines)
        self.assertEqual(bod.load_settings()["claudes"], 3)
        os.remove(bod.SETTINGS_PATH)

    def test_a_state_file_from_before_the_mod_still_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            old = datetime.now().astimezone() - minutes(1)
            with open(path, "w") as fh:
                json.dump({**{key: old.isoformat() for key in bod.TIMES}, "moves": 4, "kinds": 1}, fh)
            self.assertIsNone(self.run_bod("tick", path)["nudge"])
            with open(path) as fh:
                self.assertEqual(json.load(fh)["moves"], 4)



class CheckIn(unittest.TestCase):
    def test_a_check_in_goes_up_every_45_minutes(self):
        state = working(check=44)
        bod.advance(state, NOW, NOT_OVER)
        self.assertIsNone(state["pending"])
        state = working(check=45)
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "check")
        self.assertEqual(state["pending"]["text"], bod.FOG_FIXES[0])

    def test_it_goes_ahead_of_a_due_exercise(self):
        state = working(move=11, check=46)
        bod.advance(state, NOW, NOT_OVER)
        self.assertEqual(state["pending"]["kind"], "check")

    def test_done_restarts_it_and_the_next_one_offers_a_different_fix(self):
        state = working(check=46)
        bod.advance(state, NOW, NOT_OVER)
        bod.press(state, "done", NOW)
        self.assertEqual(state["last_check"], NOW)
        self.assertEqual(state["checks"], 1)
        later = NOW + minutes(46)
        state["last_prompt"] = later
        bod.advance(state, later, NOT_OVER)
        self.assertEqual(state["pending"]["text"], bod.FOG_FIXES[1])

    def test_without_the_mod_claude_passes_it_on(self):
        state = working(check=46, prompt=1)
        state, nudges = bod.prompted(state, NOW)
        self.assertIn(f"Workflow check-in: {bod.CHECK_IN_QUESTION} Try this: {bod.FOG_FIXES[0]}.", nudges)
        self.assertEqual(state["checks"], 1)


class Worked(unittest.TestCase):
    def test_the_view_carries_todays_hours_in_seconds(self):
        shown = bod.view(working(), NOW, worked=timedelta(hours=2, minutes=5))
        self.assertEqual(shown["worked"], 7500)

    def test_hours_that_could_not_be_counted_are_left_out(self):
        self.assertIsNone(bod.view(working(), NOW)["worked"])


if __name__ == "__main__":
    unittest.main()
