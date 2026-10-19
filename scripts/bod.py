#!/usr/bin/env python3
"""Claude nudges Helena to move: get off the chair, do a quick exercise, stop
for the day.

Two nudges on two separate timers: a short exercise every 5, 10 or 15
minutes of work (her pick, 5 by default), and something kind to herself
every 5, 10, 15, 30 or 45 (her pick too, 15 by default). Every CHECK_IN_MINUTES a
workflow check-in asks how it's going and offers one way out of Claude-FOG
(too many Claudes, lost track of what each one is doing). Every CAP_CHECK_MINUTES it checks today's hours, and once
they pass DAILY_CAP_HOURS a "stop for the day" line stays up.

Entry points:

  bod.py hook     Run by the mod on every prompt she sends.
                  Records that she's working. While the bod mod is
                  showing nudges it does nothing else; without the mod it
                  hands Claude the nudges to pass on in its reply.
  bod.py tick     What the mod (hooks/register.tsx) polls:
                  puts the next nudge on show once one is due and prints
                  what the band above the prompt and the status line should
                  show, as JSON, today's hours worked among it.
  bod.py go | done | snooze | beep
                  The mod's buttons: start the exercise timer, finish the
                  nudge, put it off for SNOOZE_MINUTES, and claim the sound
                  at the end of a countdown (one session plays it, not all).
  bod.py now      `/bod now`: the next exercise on show right away, the
                  other timers left as they are.
  bod.py kindnow  `/bod kind now`: a kindness nudge on show right away,
                  the same way.
  bod.py show move | plank | kind | check
                  Puts that nudge on show right now, to try the band out
                  without waiting for a timer.
  bod.py level easy | medium | hard
                  How much exercise each nudge asks for: one exercise, two,
                  or three with more reps. Easy by default.
  bod.py every 5 | 10 | 15
                  How many minutes of work between exercise nudges. Both can
                  go in one call: bod.py level hard every 10, or
                  just bod.py level hard 10.
  bod.py settings What Claude Bod is set to, in a sentence.
  bod.py status   What the work-check skill runs: hours today, the current
                  stretch without a break, and a verdict.

The timers and the nudge on show live in one state file shared by every
session and worktree, so five sessions open at once still add up to one nudge
per interval, not five, and pressing done in one tab clears it in all of them.
A gap of BREAK_MINUTES or more between prompts counts as having been away,
and restarts every timer rather than nudging the moment she sits back down.

Hours come from a transcript estimate across every project (hours.py), so
they have its caveats: time Claude was
busy alone counts, work away from Claude doesn't.
"""
import contextlib
import fcntl
import json
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hours import GAP_MINUTES, timestamps  # noqa: E402

# How often to add up today's hours (a scan of every transcript) for the cap.
CAP_CHECK_MINUTES = 30
# How often the workflow check-in comes up.
CHECK_IN_MINUTES = 45
BREAK_MINUTES = 20
DAILY_CAP_HOURS = 4
STRETCH_LIMIT_MINUTES = 90
SNOOZE_MINUTES = 5
# After a done, how long the band stays empty before the next nudge may show.
QUIET_SECONDS = 60
# The mod polls every few seconds; no tick for this long means it isn't running.
MOD_ALIVE_SECONDS = 60

STATE_PATH = os.environ.get("BOD_STATE") or os.path.expanduser("~/.claude/bod-state.json")
# Her choices, kept apart from the state so a reset never loses them.
SETTINGS_PATH = os.environ.get("BOD_SETTINGS") or os.path.expanduser("~/.claude/bod-settings.json")

# level: (exercises per nudge, how much the reps and seconds grow)
LEVELS = {"easy": (1, 1), "medium": (2, 1), "hard": (3, 1.5)}
EVERY_CHOICES = (5, 10, 15)
KIND_CHOICES = (5, 10, 15, 30, 45)
# How many Claudes may be open at once (scripts/claude-limit.py enforces it).
CLAUDES_CHOICES = range(1, 21)
DEFAULT_SETTINGS = {"level": "easy", "every": 5, "kind": 15, "claudes": 5}

# (what to do, with {} for how many, how many on easy, whether it's seconds
# to count down from rather than reps)
EXERCISES = [
    ("{} push ups", 5, False),
    ("{} jumping jacks", 10, False),
    ("{} squats", 10, False),
    ("a {} second plank", 20, True),
    ("{} calf raises", 10, False),
    ("{} lunges each leg", 5, False),
    ("{} high knees", 20, False),
    ("a {} second wall sit", 20, True),
    ("{} glute bridges", 10, False),
    ("{} arm circles each way", 10, False),
    ("{} toe touches", 10, False),
    ("{} chair dips", 5, False),
]
COMPASSION = [
    "give yourself a hug",
    "take three slow breaths",
    "drop your shoulders and unclench your jaw",
    "say one kind thing to yourself",
    "notice one thing you did well today",
    "sip some water",
    "look out a window for a few seconds",
    "talk to yourself the way you'd talk to a friend",
    "put a hand on your heart and breathe",
    "forgive yourself one mistake from today",
    "stretch your arms up and smile",
    "remember you don't have to finish everything today",
]
# Ways out of Claude-FOG, one per check-in, in turn.
FOG_FIXES = [
    "close every tab whose PR has merged",
    "answer the hot pink tabs first, then look at the rest",
    "go through your tabs and say what each one is doing",
    "pick the one session that matters most and finish it before touching another",
    "don't start a new ticket until one of the open ones is merged",
    "drop your Claude cap by one for the next hour (/bod claudes)",
    "write down the one thing you want done this hour",
    "step away from the screen for two minutes, then come back to one tab",
]
CHECK_IN_QUESTION = "How's the workflow going? Feeling the Claude-FOG?"


TIMES = ("last_prompt", "last_move", "last_cap", "last_kind", "last_check")
COUNTS = ("moves", "kinds", "checks")
# Only set while the mod runs: its last tick, and the pause after a done.
OPTIONAL_TIMES = ("mod_seen", "quiet_until")
# The nudge on show is {"kind": move | kind | check, "text", "seconds",
# "beeped", and these times}. "started" is when she pressed go.
PENDING_TIMES = ("started", "snoozed_until")
LAST = {"move": "last_move", "kind": "last_kind", "check": "last_check"}


def load_state():
    try:
        with open(STATE_PATH) as fh:
            raw = json.load(fh)
        # last_cap was last_stand while there was a standing desk nudge.
        raw.setdefault("last_cap", raw.get("last_stand"))
        # From before the check-in: its timer starts now-ish, with the others.
        raw.setdefault("last_check", raw.get("last_prompt"))
        state = {key: datetime.fromisoformat(raw[key]) for key in TIMES}
        for key in COUNTS:
            state[key] = int(raw.get(key, 0))
        for key in OPTIONAL_TIMES:
            state[key] = datetime.fromisoformat(raw[key]) if raw.get(key) else None
        pending = raw.get("pending")
        if pending and pending.get("kind") not in LAST:
            pending = None
        if pending:
            pending = dict(pending)
            for key in PENDING_TIMES:
                pending[key] = datetime.fromisoformat(pending[key]) if pending.get(key) else None
        state["pending"] = pending or None
        # {"text", "date"}: the "stop for the day" line, and the day it is for.
        state["stop"] = raw.get("stop") or None
        # {"count", "date"}: how many times she's said "not now" today.
        state["skips"] = raw.get("skips") or None
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fresh_state(now, state=None):
    """Every timer restarted, as after a break; the counts carry on."""
    fresh = {key: now for key in TIMES}
    for key in COUNTS:
        fresh[key] = state[key] if state else 0
    fresh["mod_seen"] = state["mod_seen"] if state else None
    fresh["quiet_until"] = None
    fresh["pending"] = None
    fresh["stop"] = state["stop"] if state else None
    fresh["skips"] = state["skips"] if state else None
    return fresh


def save_state(state):
    def iso(when):
        return when.isoformat() if when else None

    raw = {key: state[key].isoformat() for key in TIMES}
    raw.update({key: state[key] for key in COUNTS})
    raw.update({key: iso(state[key]) for key in OPTIONAL_TIMES})
    pending = state["pending"]
    if pending:
        pending = {**pending, **{key: iso(pending[key]) for key in PENDING_TIMES}}
    raw["pending"] = pending
    raw["stop"] = state["stop"]
    raw["skips"] = state["skips"]
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(raw, fh)
    os.replace(tmp, STATE_PATH)


@contextlib.contextmanager
def locked():
    """One reader-writer of the state file at a time, across every session."""
    with open(STATE_PATH + ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def today(now):
    """(time worked today, start of the current stretch without a break)."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = sorted(timestamps(midnight))
    worked = timedelta(0)
    stretch_start = None
    prev = None
    for when in events:
        if prev and when - prev <= timedelta(minutes=GAP_MINUTES):
            worked += when - prev
        if prev is None or when - prev >= timedelta(minutes=BREAK_MINUTES):
            stretch_start = when
        prev = when
    if prev is None or now - prev >= timedelta(minutes=BREAK_MINUTES):
        stretch_start = None
    return worked, stretch_start


def fmt(delta):
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def over_cap(worked):
    return worked >= timedelta(hours=DAILY_CAP_HOURS)


def stop_nudge(worked):
    return (
        f"You've been at this about {fmt(worked)} today, past your {DAILY_CAP_HOURS} hour cap. "
        "Stop for the day. The backlog will still be there tomorrow."
    )


def load_settings():
    try:
        with open(SETTINGS_PATH) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    level = raw.get("level") if raw.get("level") in LEVELS else DEFAULT_SETTINGS["level"]
    every = raw.get("every") if raw.get("every") in EVERY_CHOICES else DEFAULT_SETTINGS["every"]
    kind = raw.get("kind") if raw.get("kind") in KIND_CHOICES else DEFAULT_SETTINGS["kind"]
    claudes = raw.get("claudes") if raw.get("claudes") in CLAUDES_CHOICES else DEFAULT_SETTINGS["claudes"]
    return {"level": level, "every": every, "kind": kind, "claudes": claudes}


def save_settings(settings):
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(settings, fh)
    os.replace(tmp, SETTINGS_PATH)


def pick(count):
    """`count` different exercises, at random, so sets don't keep coming up together."""
    return random.sample(EXERCISES, count)


def exercise(level="easy", picked=None):
    """(text, seconds to count down from or None, how many exercises): as
    many random ones as the level asks for, or the `picked` ones. Only a lone
    timed exercise counts down; a set of them counts up."""
    count, scale = LEVELS[level]
    picked = picked or pick(count)
    count = len(picked)
    amounts = [int(amount * scale + 0.5) for _, amount, _ in picked]
    text = ", then ".join(what.format(n) for (what, _, _), n in zip(picked, amounts))
    seconds = amounts[0] if count == 1 and picked[0][2] else None
    return text, seconds, count


def move_nudge(level="easy"):
    return f"Movement break: {exercise(level)[0]}. Go, I'll wait."


def compassion(kinds):
    return COMPASSION[kinds % len(COMPASSION)]


def kind_nudge(kinds):
    return f"Be nice to yourself: {compassion(kinds)}."


def fog_fix(checks):
    return FOG_FIXES[checks % len(FOG_FIXES)]


def check_nudge(checks):
    return f"Workflow check-in: {CHECK_IN_QUESTION} Try this: {fog_fix(checks)}."


def skips_today(state, now):
    skips = state["skips"]
    return skips["count"] if skips and skips["date"] == now.date().isoformat() else 0


def away(state, now):
    return now - state["last_prompt"] >= timedelta(minutes=BREAK_MINUTES)


def due(state, key, minutes, now):
    return now - state[key] >= timedelta(minutes=minutes)


def mod_alive(state, now):
    return bool(state["mod_seen"]) and now - state["mod_seen"] < timedelta(seconds=MOD_ALIVE_SECONDS)


def prompted(state, now):
    """Record a prompt. Returns (state, nudges for Claude to pass on); there
    are only nudges to pass on when no mod is showing them itself."""
    if state is None or away(state, now):
        return fresh_state(now, state), []
    state["last_prompt"] = now
    if mod_alive(state, now):
        return state, []
    # No mod: nothing draws a nudge left on show, and it would hold up the rest.
    state["pending"] = None

    settings = load_settings()
    nudges = []
    if due(state, "last_move", settings["every"], now):
        text, _, count = exercise(settings["level"])
        nudges.append(f"Movement break: {text}. Go, I'll wait.")
        state["last_move"] = now
        state["moves"] += count
    if due(state, "last_cap", CAP_CHECK_MINUTES, now):
        worked, _ = today(now)
        if over_cap(worked):
            nudges.append(stop_nudge(worked))
        state["last_cap"] = now
    if due(state, "last_kind", settings["kind"], now):
        nudges.append(kind_nudge(state["kinds"]))
        state["last_kind"] = now
        state["kinds"] += 1
    if due(state, "last_check", CHECK_IN_MINUTES, now):
        nudges.append(check_nudge(state["checks"]))
        state["last_check"] = now
        state["checks"] += 1
    return state, nudges


def hook():
    now = datetime.now().astimezone()
    with locked():
        state, nudges = prompted(load_state(), now)
        save_state(state)
    if not nudges:
        return

    print(
        json.dumps(
            {
                "systemMessage": "\n".join(nudges),
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": (
                        "Movement and workflow nudges for the user (they asked for these, from the Claude Bod plugin). "
                        "Open your next reply with each one as a short line of its own, in these words "
                        "or close to them, then carry on with what they asked:\n" + "\n".join(nudges)
                    ),
                },
            }
        )
    )


def advance(state, now, worked_today=lambda now: today(now)[0], settings=None):
    """Put the next nudge on show once one is due and nothing else is showing."""
    settings = settings or load_settings()
    if state["stop"] and state["stop"]["date"] != now.date().isoformat():
        state["stop"] = None
    pending = state["pending"]
    if away(state, now):
        # She walked off: an unstarted nudge is stale by the time she's back.
        if pending and not pending["started"]:
            state["pending"] = None
        return
    if pending or (state["quiet_until"] and now < state["quiet_until"]):
        return

    if due(state, "last_cap", CAP_CHECK_MINUTES, now):
        worked = worked_today(now)
        if over_cap(worked):
            # Not a nudge to finish: it stays up for the day, beside the others.
            state["stop"] = {"text": stop_nudge(worked), "date": now.date().isoformat()}
        state["last_cap"] = now
    # The check-in first: it's the rare one, and the exercise is never far behind.
    if due(state, "last_check", CHECK_IN_MINUTES, now):
        pending = {"kind": "check", "text": fog_fix(state["checks"]), "seconds": None}
    elif due(state, "last_move", settings["every"], now):
        text, seconds, count = exercise(settings["level"])
        pending = {"kind": "move", "text": text, "seconds": seconds, "count": count}
    elif due(state, "last_kind", settings["kind"], now):
        pending = {"kind": "kind", "text": compassion(state["kinds"]), "seconds": None}
    if pending:
        state["pending"] = {**pending, "started": None, "snoozed_until": None, "beeped": False}


def right_now(state, now, settings=None, kind="move"):
    """`/bod now`: the next exercise on show at once, without waiting for its
    timer or touching the others; `/bod kind now` (kind="kind") does the same
    with a kindness nudge. A nudge already up stays; one put off with
    "not now" comes straight back."""
    pending = state["pending"]
    # Asking counts as being here: a tick won't drop it as stale.
    state["last_prompt"] = now
    state["quiet_until"] = None
    if pending:
        pending["snoozed_until"] = None
        return
    if kind == "kind":
        state["pending"] = {
            "kind": "kind", "text": compassion(state["kinds"]), "seconds": None,
            "started": None, "snoozed_until": None, "beeped": False,
        }
        return
    settings = settings or load_settings()
    text, seconds, count = exercise(settings["level"])
    state["pending"] = {
        "kind": "move", "text": text, "seconds": seconds, "count": count,
        "started": None, "snoozed_until": None, "beeped": False,
    }


def press(state, button, now):
    """Apply one of the mod's buttons. Returns what to tell the mod besides
    the view: how long a finished exercise took, or that it should beep."""
    pending = state["pending"]
    if not pending:
        return {}
    if button == "go":
        pending["started"] = pending["started"] or now
        pending["snoozed_until"] = None
    elif button == "snooze":
        pending["snoozed_until"] = now + timedelta(minutes=SNOOZE_MINUTES)
        pending["started"] = None
        pending["beeped"] = False
        # This nudge says so when it comes back; the status line keeps the day's total.
        pending["skipped"] = pending.get("skipped", 0) + 1
        state["skips"] = {"count": skips_today(state, now) + 1, "date": now.date().isoformat()}
    elif button == "done":
        state[LAST[pending["kind"]]] = now
        if pending["kind"] == "move":
            # How many exercises she's done, the whole set counted.
            state["moves"] += pending.get("count", 1)
        elif pending["kind"] == "kind":
            state["kinds"] += 1
        elif pending["kind"] == "check":
            state["checks"] += 1
        state["pending"] = None
        state["quiet_until"] = now + timedelta(seconds=QUIET_SECONDS)
        if pending["started"]:
            return {"took": int((now - pending["started"]).total_seconds())}
    elif button == "beep":
        is_over = (
            pending["started"]
            and pending["seconds"]
            and now - pending["started"] >= timedelta(seconds=pending["seconds"])
        )
        if is_over and not pending["beeped"]:
            pending["beeped"] = True
            return {"beep": True}
    return {}


def upcoming(state, now, settings=None):
    """When the exercise nudge will next show, or None while a nudge is on
    show. Nothing new shows during the pause after a done, and a nudge put off
    with "not now" comes back when its snooze ends, ahead of the rest, so the
    exercise can't show before then either."""
    pending = state["pending"]
    earliest = state["quiet_until"] or now
    if pending:
        snoozed = pending["snoozed_until"]
        if not (snoozed and now < snoozed):
            return None
        earliest = snoozed
    settings = settings or load_settings()
    return {
        "move": max(state["last_move"] + timedelta(minutes=settings["every"]), earliest),
    }


def view(state, now, settings=None, worked=None):
    """What the band shows, with times in epoch milliseconds for the mod.
    "next" is when each nudge is due; "paused" means she's been away long
    enough that nothing shows until her next prompt restarts the timers;
    "worked" is how many seconds she's worked today, when it was counted;
    "skips" is how many times she's said "not now" today."""

    def ms(when):
        return int(when.timestamp() * 1000)

    paused = away(state, now)
    due_at = None if paused else upcoming(state, now, settings)
    nudge = state["pending"]
    if nudge and nudge["snoozed_until"] and now < nudge["snoozed_until"]:
        nudge = None
    if nudge:
        nudge = {
            "kind": nudge["kind"],
            "text": nudge["text"],
            "seconds": nudge["seconds"],
            "started": ms(nudge["started"]) if nudge["started"] else None,
            "skipped": nudge.get("skipped", 0),
        }
    return {
        "now": ms(now),
        "nudge": nudge,
        "stop": state["stop"]["text"] if state["stop"] else None,
        "next": {kind: ms(when) for kind, when in due_at.items()} if due_at else None,
        "paused": paused,
        "worked": int(worked.total_seconds()) if worked is not None else None,
        "skips": skips_today(state, now),
    }


def worked_so_far(now):
    """Today's hours for the status line, or None when the transcripts can't
    be read (one deleted mid-read, say): a missing timer beats a broken tick."""
    try:
        return today(now)[0]
    except OSError:
        return None


def mod(button):
    now = datetime.now().astimezone()
    with locked():
        state = load_state() or fresh_state(now)
        said = {}
        if button == "tick":
            state["mod_seen"] = now
            advance(state, now)
        elif button == "now":
            right_now(state, now)
        elif button == "kindnow":
            right_now(state, now, kind="kind")
        else:
            said = press(state, button, now)
        save_state(state)
    print(json.dumps({**view(state, now, worked=worked_so_far(now)), **said}))


def show(kind):
    now = datetime.now().astimezone()
    with locked():
        state = fresh_state(now, load_state())
        plank = kind == "plank"
        kind = "move" if plank else kind
        state[LAST[kind]] = now - timedelta(minutes=max(*EVERY_CHOICES, *KIND_CHOICES, CHECK_IN_MINUTES))
        advance(state, now, lambda now: timedelta(0))
        if plank:
            # A lone plank, to see the countdown.
            text, seconds, count = exercise("easy", [next(e for e in EXERCISES if "plank" in e[0])])
            state["pending"].update(text=text, seconds=seconds, count=count)
        save_state(state)
    print(json.dumps(view(state, now)))


def describe(settings):
    count, _ = LEVELS[settings["level"]]
    what = "one exercise" if count == 1 else f"{count} exercises" + (" with more reps" if settings["level"] == "hard" else "")
    return (f"Claude Bod is on {settings['level']}: {what} every {settings['every']} minutes, "
            f"something kind every {settings['kind']}, at most {settings['claudes']} Claudes open at once.")


def choose(args):
    """Set the level, the minutes, the kindness minutes and/or the Claude cap, given as pairs
    ("level hard every 10 kind 30 claudes 5", or just "level hard 10"); prints only what changed. Nothing is
    saved unless every pair is valid."""
    settings = load_settings()
    # A bare number is the minutes: "level hard 10" means "level hard every 10".
    args = [part for i, arg in enumerate(args)
            for part in (["every", arg] if arg.isdigit() and (i == 0 or args[i - 1] not in ("every", "kind", "claudes")) else [arg])]
    if not args or len(args) % 2:
        args = [*args, ""]
    for key, value in zip(args[::2], args[1::2]):
        if key == "every":
            value = int(value) if value.isdigit() else None
            choices = EVERY_CHOICES
        elif key == "kind":
            value = int(value) if value.isdigit() else None
            choices = KIND_CHOICES
        elif key == "claudes":
            value = int(value) if value.isdigit() else None
            choices = CLAUDES_CHOICES
        elif key == "level":
            choices = tuple(LEVELS)
        else:
            print("Use: level easy|medium|hard, every 5|10|15, kind 5|10|15|30|45, claudes 1-20.")
            sys.exit(1)
        if value not in choices:
            print(f"Pick a number from {choices[0]} to {choices[-1]}." if isinstance(choices, range)
                  else f"Pick one of: {', '.join(str(c) for c in choices)}.")
            sys.exit(1)
        settings[key] = value
    save_settings(settings)
    print(" ".join(confirm(key, settings) for key in dict.fromkeys(args[::2])))


def confirm(key, settings):
    """One line saying what a setting is now."""
    if key == "level":
        count, _ = LEVELS[settings["level"]]
        what = "one exercise" if count == 1 else f"{count} exercises" + (" with more reps" if settings["level"] == "hard" else "")
        return f"Your level is now {settings['level']}: {what} per nudge."
    if key == "every":
        return f"Your exercises are now every {settings['every']} minutes."
    if key == "kind":
        return f"Something kind is now every {settings['kind']} minutes."
    return f"Your Claude cap is now {settings['claudes']}."


def status():
    now = datetime.now().astimezone()
    worked, stretch_start = today(now)
    print(f"Worked today: {fmt(worked)} (cap {DAILY_CAP_HOURS}h)")
    print(describe(load_settings()))
    if stretch_start:
        print(f"Current stretch: {fmt(now - stretch_start)} without a {BREAK_MINUTES} minute break")
    else:
        print(f"Current stretch: none (no activity in the last {BREAK_MINUTES} minutes)")
    state = load_state()
    if state:
        print(f"Last movement nudge: {fmt(now - state['last_move'])} ago")
        print(f"Last compassion nudge: {fmt(now - state['last_kind'])} ago")
        print(f"Last workflow check-in: {fmt(now - state['last_check'])} ago")

    if over_cap(worked):
        print("Verdict: STOP for the day, over the cap")
    elif stretch_start and now - stretch_start >= timedelta(minutes=STRETCH_LIMIT_MINUTES):
        print("Verdict: BREAK now, the stretch is too long")
    else:
        left = timedelta(hours=DAILY_CAP_HOURS) - worked
        print(f"Verdict: OK, about {fmt(left)} left today")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "hook":
        # A nudge is never worth blocking a prompt over.
        try:
            hook()
        except Exception:
            pass
    elif mode in ("tick", "now", "kindnow", "go", "done", "snooze", "beep"):
        mod(mode)
    elif mode in ("level", "every", "kind", "claudes"):
        choose(sys.argv[1:])
    elif mode == "settings":
        print(describe(load_settings()))
    elif mode == "show" and sys.argv[2:] and sys.argv[2] in (*LAST, "plank"):
        show(sys.argv[2])
    else:
        status()
