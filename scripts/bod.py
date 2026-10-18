#!/usr/bin/env python3
"""Claude nudges Helena to move: get off the chair, do a quick exercise, stop
for the day.

Three nudges on three separate timers: a short exercise every 5, 10 or 15
minutes of work (her pick, 5 by default), "go stand / walk" every STAND_MINUTES, and something kind to herself
every KIND_MINUTES. Once today's hours pass DAILY_CAP_HOURS the standing one
becomes "stop for the day" instead.

Entry points:

  bod.py hook     Run by the mod on every prompt she sends.
                  Records that she's working. While the bod mod is
                  showing nudges it does nothing else; without the mod it
                  hands Claude the nudges to pass on in its reply.
  bod.py tick     What the mod (hooks/register.tsx) polls:
                  puts the next nudge on show once one is due and prints
                  what the band above the prompt should show, as JSON.
  bod.py go | done | snooze | beep
                  The mod's buttons: start the exercise timer, finish the
                  nudge, put it off for SNOOZE_MINUTES, and claim the sound
                  at the end of a countdown (one session plays it, not all).
  bod.py now      `/bod now`: the next exercise on show right away, the
                  other timers left as they are.
  bod.py show move | plank | stand | kind
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
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hours import GAP_MINUTES, timestamps  # noqa: E402

STAND_MINUTES = 30
KIND_MINUTES = 45
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
# How many Claudes may be open at once (scripts/claude-limit.py enforces it).
CLAUDES_CHOICES = range(1, 21)
DEFAULT_SETTINGS = {"level": "easy", "every": 5, "claudes": 5}

POSTURE = "Hey, are you sitting not good? Go use your standing desk and walking treadmill."
# (what to do, with {} for how many, how many on easy, whether it's seconds
# to count down from rather than reps)
EXERCISES = [
    ("{} push ups", 5, False),
    ("{} jumping jacks", 10, False),
    ("{} squats", 10, False),
    ("a {} second plank", 20, True),
    ("{} calf raises", 10, False),
    ("{} lunges each leg", 5, False),
]
COMPASSION = [
    "give yourself a hug",
    "take three slow breaths",
    "drop your shoulders and unclench your jaw",
    "say one kind thing to yourself",
]


TIMES = ("last_prompt", "last_move", "last_stand", "last_kind")
COUNTS = ("moves", "kinds")
# Only set while the mod runs: its last tick, and the pause after a done.
OPTIONAL_TIMES = ("mod_seen", "quiet_until")
# The nudge on show is {"kind": move | stand | kind, "text", "seconds",
# "beeped", and these times}. "started" is when she pressed go.
PENDING_TIMES = ("started", "snoozed_until")
LAST = {"move": "last_move", "stand": "last_stand", "kind": "last_kind"}


def load_state():
    try:
        with open(STATE_PATH) as fh:
            raw = json.load(fh)
        state = {key: datetime.fromisoformat(raw[key]) for key in TIMES}
        for key in COUNTS:
            state[key] = int(raw.get(key, 0))
        for key in OPTIONAL_TIMES:
            state[key] = datetime.fromisoformat(raw[key]) if raw.get(key) else None
        pending = raw.get("pending")
        if pending:
            pending = dict(pending)
            for key in PENDING_TIMES:
                pending[key] = datetime.fromisoformat(pending[key]) if pending.get(key) else None
        state["pending"] = pending or None
        # {"text", "date"}: the "stop for the day" line, and the day it is for.
        state["stop"] = raw.get("stop") or None
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fresh_state(now, state=None):
    """Every timer restarted, as after a break; the rotations carry on."""
    fresh = {key: now for key in TIMES}
    for key in COUNTS:
        fresh[key] = state[key] if state else 0
    fresh["mod_seen"] = state["mod_seen"] if state else None
    fresh["quiet_until"] = None
    fresh["pending"] = None
    fresh["stop"] = state["stop"] if state else None
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


def stand_nudge(worked):
    return stop_nudge(worked) if over_cap(worked) else POSTURE


def load_settings():
    try:
        with open(SETTINGS_PATH) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    level = raw.get("level") if raw.get("level") in LEVELS else DEFAULT_SETTINGS["level"]
    every = raw.get("every") if raw.get("every") in EVERY_CHOICES else DEFAULT_SETTINGS["every"]
    claudes = raw.get("claudes") if raw.get("claudes") in CLAUDES_CHOICES else DEFAULT_SETTINGS["claudes"]
    return {"level": level, "every": every, "claudes": claudes}


def save_settings(settings):
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(settings, fh)
    os.replace(tmp, SETTINGS_PATH)


def exercise(moves, level="easy"):
    """(text, seconds to count down from or None, how many exercises): the
    next ones in the rotation, as many as the level asks for. Only a lone
    timed exercise counts down; a set of them counts up."""
    count, scale = LEVELS[level]
    picked = [EXERCISES[(moves + i) % len(EXERCISES)] for i in range(count)]
    amounts = [int(amount * scale + 0.5) for _, amount, _ in picked]
    text = ", then ".join(what.format(n) for (what, _, _), n in zip(picked, amounts))
    seconds = amounts[0] if count == 1 and picked[0][2] else None
    return text, seconds, count


def move_nudge(moves, level="easy"):
    return f"Movement break: {exercise(moves, level)[0]}. Go, I'll wait."


def compassion(kinds):
    return COMPASSION[kinds % len(COMPASSION)]


def kind_nudge(kinds):
    return f"Be nice to yourself: {compassion(kinds)}."


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
        text, _, count = exercise(state["moves"], settings["level"])
        nudges.append(f"Movement break: {text}. Go, I'll wait.")
        state["last_move"] = now
        state["moves"] += count
    if due(state, "last_stand", STAND_MINUTES, now):
        worked, _ = today(now)
        nudges.append(stand_nudge(worked))
        state["last_stand"] = now
    if due(state, "last_kind", KIND_MINUTES, now):
        nudges.append(kind_nudge(state["kinds"]))
        state["last_kind"] = now
        state["kinds"] += 1
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
                        "Movement nudges for the user (they asked for these, from the Claude Bod plugin). "
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

    if due(state, "last_stand", STAND_MINUTES, now):
        worked = worked_today(now)
        if over_cap(worked):
            # Not a nudge to finish: it stays up for the day, beside the others.
            state["stop"] = {"text": stop_nudge(worked), "date": now.date().isoformat()}
            state["last_stand"] = now
    if due(state, "last_move", settings["every"], now):
        text, seconds, count = exercise(state["moves"], settings["level"])
        pending = {"kind": "move", "text": text, "seconds": seconds, "count": count}
    elif due(state, "last_stand", STAND_MINUTES, now):
        pending = {"kind": "stand", "text": POSTURE, "seconds": None}
    elif due(state, "last_kind", KIND_MINUTES, now):
        pending = {"kind": "kind", "text": compassion(state["kinds"]), "seconds": None}
    if pending:
        state["pending"] = {**pending, "started": None, "snoozed_until": None, "beeped": False}


def right_now(state, now, settings=None):
    """`/bod now`: the next exercise on show at once, without waiting for its
    timer or touching the others. A nudge already up stays; one put off with
    "not now" comes straight back."""
    pending = state["pending"]
    # Asking counts as being here: a tick won't drop it as stale.
    state["last_prompt"] = now
    state["quiet_until"] = None
    if pending:
        pending["snoozed_until"] = None
        return
    settings = settings or load_settings()
    text, seconds, count = exercise(state["moves"], settings["level"])
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
    elif button == "done":
        state[LAST[pending["kind"]]] = now
        if pending["kind"] == "move":
            # The rotation moves past every exercise in the set.
            state["moves"] += pending.get("count", 1)
        elif pending["kind"] == "kind":
            state["kinds"] += 1
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
    """When the exercise and standing nudges will next show, or None while one
    is on show. Nothing new shows during the pause after a done, and a nudge
    put off with "not now" comes back when its snooze ends, ahead of the rest."""
    pending = state["pending"]
    if pending:
        snoozed = pending["snoozed_until"]
        if snoozed and now < snoozed and pending["kind"] in ("move", "stand"):
            return {pending["kind"]: snoozed}
        return None
    settings = settings or load_settings()
    earliest = state["quiet_until"] or now
    return {
        "move": max(state["last_move"] + timedelta(minutes=settings["every"]), earliest),
        "stand": max(state["last_stand"] + timedelta(minutes=STAND_MINUTES), earliest),
    }


def view(state, now, settings=None):
    """What the band shows, with times in epoch milliseconds for the mod.
    "next" is when each nudge is due; "paused" means she's been away long
    enough that nothing shows until her next prompt restarts the timers."""

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
        }
    return {
        "now": ms(now),
        "nudge": nudge,
        "stop": state["stop"]["text"] if state["stop"] else None,
        "next": {kind: ms(when) for kind, when in due_at.items()} if due_at else None,
        "paused": paused,
    }


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
        else:
            said = press(state, button, now)
        save_state(state)
    print(json.dumps({**view(state, now), **said}))


def show(kind):
    now = datetime.now().astimezone()
    with locked():
        state = fresh_state(now, load_state())
        if kind == "plank":
            kind = "move"
            state["moves"] = next(i for i, (_, _, timed) in enumerate(EXERCISES) if timed)
        state[LAST[kind]] = now - timedelta(minutes=max(*EVERY_CHOICES, STAND_MINUTES, KIND_MINUTES))
        advance(state, now, lambda now: timedelta(0))
        save_state(state)
    print(json.dumps(view(state, now)))


def describe(settings):
    count, _ = LEVELS[settings["level"]]
    what = "one exercise" if count == 1 else f"{count} exercises" + (" with more reps" if settings["level"] == "hard" else "")
    return (f"Claude Bod is on {settings['level']}: {what} every {settings['every']} minutes, "
            f"at most {settings['claudes']} Claudes open at once.")


def choose(args):
    """Set the level, the minutes and/or the Claude cap, given as pairs
    ("level hard every 10 claudes 5", or just "level hard 10"); prints only what changed. Nothing is
    saved unless every pair is valid."""
    settings = load_settings()
    # A bare number is the minutes: "level hard 10" means "level hard every 10".
    args = [part for i, arg in enumerate(args)
            for part in (["every", arg] if arg.isdigit() and (i == 0 or args[i - 1] not in ("every", "claudes")) else [arg])]
    if not args or len(args) % 2:
        args = [*args, ""]
    for key, value in zip(args[::2], args[1::2]):
        if key == "every":
            value = int(value) if value.isdigit() else None
            choices = EVERY_CHOICES
        elif key == "claudes":
            value = int(value) if value.isdigit() else None
            choices = CLAUDES_CHOICES
        elif key == "level":
            choices = tuple(LEVELS)
        else:
            print("Use: level easy|medium|hard, every 5|10|15, claudes 1-20.")
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
        print(f"Last standing desk nudge: {fmt(now - state['last_stand'])} ago")
        print(f"Last compassion nudge: {fmt(now - state['last_kind'])} ago")

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
    elif mode in ("tick", "now", "go", "done", "snooze", "beep"):
        mod(mode)
    elif mode in ("level", "every", "claudes"):
        choose(sys.argv[1:])
    elif mode == "settings":
        print(describe(load_settings()))
    elif mode == "show" and sys.argv[2:] and sys.argv[2] in (*LAST, "plank"):
        show(sys.argv[2])
    else:
        status()
