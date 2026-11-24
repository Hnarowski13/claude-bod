#!/usr/bin/env python3
"""Claude nudges Helena to move: get off the chair, do a quick exercise, stop
for the day.

Two nudges on two separate timers: a short exercise every 5, 10 or 15
minutes of work (her pick, 5 by default), and something kind to herself
every 5, 10, 15, 30 or 45 (her pick too, 15 by default). The exercise timer
restarts when she presses done; kindness keeps a fixed schedule, each one due
its interval after the last was due, however long that one waited behind an
exercise or sat on show. Every CHECK_IN_MINUTES a
workflow check-in asks how it's going and offers one way out of Claude-FOG
(too many Claudes, lost track of what each one is doing), and every
MUSIC_MINUTES a music break suggests putting on something she loves. Each of
the four can be switched off on its own; while exercises or kindness are off,
a line every OFF_REMINDER_MINUTES says so, so they aren't forgotten. Every CAP_CHECK_MINUTES it checks today's hours, and once
they pass DAILY_CAP_HOURS a "stop for the day" line stays up. The cap is hard:
past it, every session refuses prompts until midnight (the mod reads
"locked" from the view).

Entry points:

  bod.py hook     Run by the mod on every prompt she sends.
                  Records that she's working. While the bod mod is
                  showing nudges it does nothing else; without the mod it
                  hands Claude the nudges to pass on in its reply.
  bod.py tick     What the mod (hooks/register.tsx) polls:
                  puts the next nudge on show once one is due and prints
                  what the band above the prompt and the status line should
                  show, as JSON, today's hours worked among it.
  bod.py go | swap | done | snooze | beep
                  The mod's buttons: start the exercise timer, trade the
                  exercise for a different one, finish the nudge, put it
                  off for her snooze minutes, and claim the sound at the
                  end of a countdown (one session plays it, not all).
  bod.py now      `/bod now`: the next exercise on show right away, the
                  other timers left as they are.
  bod.py kindnow  `/bod kind now`: a kindness nudge on show right away,
                  the same way.
  bod.py show move | plank | kind | check | music | off
                  Puts that nudge on show right now, to try the band out
                  without waiting for a timer.
  bod.py level gentle | chair | taichi | easy | medium | hard
                  How much exercise each nudge asks for: one gentle
                  movement (no exercise at all), one movement done
                  sitting down, one tai chi or qi gong movement, one exercise, two, or three with more reps.
                  Easy by default.
  bod.py every 5 | 10 | 15
                  How many minutes of work between exercise nudges. Both can
                  go in one call: bod.py level hard every 10, or
                  just bod.py level hard 10.
  bod.py move every 5 | 10 | 15, kind every 5 | 10 | 15 | 30 | 45
                  The same minutes said the natural way (`move 10` too).
  bod.py move on | off, kind on | off, check on | off, music on | off
                  Exercises, kindness nudges, the workflow check-in or the
                  music break on or off, each on its own (on by default).
  bod.py snooze 2 | 5 | 10 | 15
                  How many minutes "not now" puts a nudge off for (bare
                  `snooze` is the button itself).
  bod.py focus [5 | 10 | 15 | 30 | 45 | 60 | 75 | 90] <what she wants to get done>
                  Starts a focus session (60 minutes when no length is
                  given). Prompts only go through while one runs; when its
                  time is up she gets a few minutes to wrap up, then a break.
  bod.py note     Run by the mod on every prompt that goes through, the
                  prompt on stdin: adds it to the focus session's log.
  bod.py recall <what she remembers>
                  `/bod recall`: at the end of a session she says what it
                  worked on from memory (if she likes), then sees the log.
  bod.py log      `/bod log`: today's focus sessions, goals and prompts.
  bod.py settings What Claude Bod is set to, in a sentence.
  bod.py choices  Her settings and what each may be, as JSON, for the
                  mod's /bod config form.
  bod.py info     Every setting, one per line: her choices and the fixed
                  timers alike.
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
from merged import merged_today  # noqa: E402

# How often to add up today's hours (a scan of every transcript) for the cap.
CAP_CHECK_MINUTES = 30
# How often the workflow check-in comes up.
CHECK_IN_MINUTES = 45
# How often the music break comes up, and what it says.
MUSIC_MINUTES = 60
MUSIC_TEXT = "put on something you love"
# While exercises or kindness nudges are switched off, how often a line says so.
OFF_REMINDER_MINUTES = 60
BREAK_MINUTES = 20
# Hours of Claude time a day. Past them, prompts are refused until midnight.
DAILY_CAP_HOURS = 8
STRETCH_LIMIT_MINUTES = 90
# After a done, how long the band stays empty before the next nudge may show.
QUIET_SECONDS = 60
# The mod polls every few seconds; no tick for this long means it isn't running.
MOD_ALIVE_SECONDS = 60
# How often a tick adds up today's hours again for the status line. Button
# presses never do: the scan takes most of a second and the band waits on it.
WORKED_REFRESH_SECONDS = 60
# How many merged PRs a day the status line's progress bar fills up to.
DAILY_PR_CAP = 15
# How often a tick asks GitHub again for today's merged PRs (a network call).
MERGED_REFRESH_SECONDS = 300
# Focus sessions: prompts only go through while one is running, started on
# purpose with `/bod focus <minutes> <what she wants to get done>`. When its
# time is up she gets WRAP_UP_MINUTES to wrap up, then a FOCUS_BREAK_MINUTES
# break with prompts refused before the next one can start.
FOCUS_CHOICES = (5, 10, 15, 30, 45, 60, 75, 90)
FOCUS_DEFAULT_MINUTES = 60
WRAP_UP_MINUTES = 5
# A sound this long before wrap-up ends, so the break doesn't catch her mid-sentence.
LAST_MINUTE_SECONDS = 60
FOCUS_BREAK_MINUTES = 10
# Each focus session keeps a log of the prompts she sends during it. A long
# prompt (a paste) is cut to its first LOG_PROMPT_CHARS characters, and a
# session keeps at most LOG_MAX_PROMPTS of them.
LOG_PROMPT_CHARS = 200
LOG_MAX_PROMPTS = 100

STATE_PATH = os.environ.get("BOD_STATE") or os.path.expanduser("~/.claude/bod-state.json")
# Her choices, kept apart from the state so a reset never loses them.
SETTINGS_PATH = os.environ.get("BOD_SETTINGS") or os.path.expanduser("~/.claude/bod-settings.json")
# Every finished focus session, one JSON line each: goal, prompts, what she recalled.
HISTORY_PATH = os.environ.get("BOD_HISTORY") or os.path.expanduser("~/.claude/bod-focus-history.jsonl")

# level: (exercises per nudge, how much the reps and seconds grow)
LEVELS = {"gentle": (1, 1), "chair": (1, 1), "taichi": (1, 1), "easy": (1, 1), "medium": (2, 1), "hard": (3, 1.5)}
EVERY_CHOICES = (5, 10, 15)
KIND_CHOICES = (5, 10, 15, 30, 45)
# How many Claudes may be open at once (scripts/claude-limit.py enforces it).
CLAUDES_CHOICES = range(1, 11)
# How long "not now" puts a nudge off for.
SNOOZE_CHOICES = (2, 5, 10, 15)
SWITCH_CHOICES = ("on", "off")
# The setting that switches each nudge on or off ("kind on|off" sets kindness).
SWITCH = {"move": "move", "kind": "kindness", "check": "check", "music": "music"}
DEFAULT_SETTINGS = {"level": "easy", "move": "on", "every": 5, "kindness": "on", "kind": 15, "check": "on",
                    "music": "on", "claudes": 5, "snooze": 5}
# What each setting may be, in the order /bod config shows them.
CHOICES = {"level": tuple(LEVELS), "move": SWITCH_CHOICES, "every": EVERY_CHOICES, "kindness": SWITCH_CHOICES,
           "kind": KIND_CHOICES, "check": SWITCH_CHOICES, "music": SWITCH_CHOICES, "claudes": CLAUDES_CHOICES,
           "snooze": SNOOZE_CHOICES}

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
# The gentle level's: soft movements, not exercise, the same shape as EXERCISES.
GENTLE = [
    ("{} slow neck rolls each way", 3, False),
    ("{} slow shoulder rolls", 5, False),
    ("a {} second reach up to the ceiling", 15, True),
    ("{} wrist circles each way", 5, False),
    ("{} ankle circles each foot", 5, False),
    ("a {} second side stretch each side", 15, True),
    ("a {} second seated twist each side", 15, True),
    ("a {} second chest opener, hands clasped behind you", 15, True),
    ("{} shoulder blade squeezes", 5, False),
    ("a {} second forward fold, arms hanging", 15, True),
]
# The chair level's: chair yoga, all of it done without getting up.
CHAIR = [
    ("{} seated cat-cows, hands on your knees", 5, False),
    ("a {} second seated twist each side", 15, True),
    ("{} seated marches", 20, False),
    ("{} seated leg lifts each leg", 8, False),
    ("a {} second seated forward fold", 15, True),
    ("a {} second seated figure four stretch each side", 20, True),
    ("{} seated heel raises", 15, False),
    ("a {} second seated reach up, fingers laced", 15, True),
    ("{} seated side bends each side", 5, False),
    ("{} slow ear-to-shoulder neck tilts each side", 3, False),
    ("a {} second wrist and finger stretch each hand", 15, True),
    ("a {} second seated eagle arms each side", 15, True),
]
# The taichi level's: slow tai chi and qi gong movements, the same shape again.
TAI_CHI = [
    ("{} slow cloud hands, side to side", 6, False),
    ("a {} second standing post, arms round as if hugging a tree", 30, True),
    ("{} slow lifts of the sky, breathing in as your hands rise", 6, False),
    ("{} draws of the bow each side", 4, False),
    ("{} loose waist turns, arms swinging", 10, False),
    ("{} slow partings of the wild horse's mane each side", 4, False),
    ("{} separations of heaven and earth, one hand up and one down", 4, False),
    ("a {} second golden rooster, standing on one leg each side", 15, True),
    ("{} slow pushes, palms out as if moving a mountain", 6, False),
    ("{} heel drops to shake the whole body loose", 7, False),
]
# What each level picks its movements from; a level not here does exercises.
POOLS = {"gentle": GENTLE, "chair": CHAIR, "taichi": TAI_CHI}
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


TIMES = ("last_prompt", "last_move", "last_cap", "last_kind", "last_check", "last_music", "last_off")
COUNTS = ("moves", "kinds", "checks")
# Only set while the mod runs: its last tick, and the pause after a done.
OPTIONAL_TIMES = ("mod_seen", "quiet_until")
# The nudge on show is {"kind": move | kind | check | music | off, "text", "seconds",
# "beeped", and these times}. "started" is when she pressed go; "due" is when
# a kindness nudge was due, which its done sets last_kind from.
PENDING_TIMES = ("started", "snoozed_until", "due")
LAST = {"move": "last_move", "kind": "last_kind", "check": "last_check", "music": "last_music", "off": "last_off"}


def load_state():
    try:
        with open(STATE_PATH) as fh:
            raw = json.load(fh)
        # last_cap was last_stand while there was a standing desk nudge.
        raw.setdefault("last_cap", raw.get("last_stand"))
        # From before the check-in: its timer starts now-ish, with the others.
        raw.setdefault("last_check", raw.get("last_prompt"))
        # From before the music break: the same.
        raw.setdefault("last_music", raw.get("last_prompt"))
        # From before the switched-off reminder: the same.
        raw.setdefault("last_off", raw.get("last_prompt"))
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
        # {"seconds", "at"}: today's hours as last counted, and when.
        state["worked"] = raw.get("worked") or None
        # {"count", "at"}: today's merged PRs as last counted, and when.
        state["merged"] = raw.get("merged") or None
        # {"started", "minutes", "goal"}: the last focus session she started.
        state["focus"] = raw.get("focus") or None
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
    fresh["worked"] = state["worked"] if state else None
    fresh["merged"] = state["merged"] if state else None
    # A focus session runs on the clock, not on prompts: a break doesn't end it.
    fresh["focus"] = state["focus"] if state else None
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
    raw["worked"] = state["worked"]
    raw["merged"] = state.get("merged")
    raw["focus"] = state.get("focus")
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


def lock_text(worked):
    """Why a prompt is refused once today's hours are past the hard cap."""
    return (
        f"You've been at this about {fmt(worked)} today, past your {DAILY_CAP_HOURS} hour cap, "
        "so Claude is done for today. It opens again at midnight. Go love yourself 💛"
    )


FOCUS_HOW = (
    "/bod focus <minutes> <what you want to get done>, e.g. /bod focus 60 fix the sorting bug "
    f"(minutes: {', '.join(map(str, FOCUS_CHOICES))})"
)
RECALL_HOW = "/bod recall <in your own words>"


def time_of_day(when):
    """3:42 pm."""
    return when.strftime("%-I:%M %p").lower()


def focus_phase(state, now):
    """Where the focus session stands, as (phase, when that phase ends):
    "working" until its minutes are up, "wrap-up" for WRAP_UP_MINUTES after,
    "break" for FOCUS_BREAK_MINUTES after that, and "none" (ending None) when
    no session is running and one may start."""
    focus = state.get("focus")
    if not focus:
        return "none", None
    work_ends = datetime.fromisoformat(focus["started"]) + timedelta(minutes=focus["minutes"])
    wrap_up_ends = work_ends + timedelta(minutes=WRAP_UP_MINUTES)
    break_ends = wrap_up_ends + timedelta(minutes=FOCUS_BREAK_MINUTES)
    if now < work_ends:
        return "working", work_ends
    if now < wrap_up_ends:
        return "wrap-up", wrap_up_ends
    if now < break_ends:
        return "break", break_ends
    return "none", None


def focus_line(phase, ends, goal, recalled=False):
    """The band's line for the focus session: time to wrap up, or why prompts
    are refused. On the break, until she's answered, it also asks what the
    session worked on (answering is up to her). None while the session is running."""
    if phase == "wrap-up":
        return (f"⏰ Time's up. You have {WRAP_UP_MINUTES} minutes to wrap up: leave notes for next time. "
                f"You set out to: {goal}")
    lock = focus_lock_text(phase, ends)
    if lock and phase == "break" and not recalled:
        return f"🎯 {lock} If you like, before looking: what did we work on? {RECALL_HOW}"
    return f"🎯 {lock}" if lock else None


def focus_lock_text(phase, ends):
    """Why a prompt is refused for want of a focus session, or None when it may go through."""
    if phase == "none":
        return f"No focus session running. Start one on purpose: {FOCUS_HOW}."
    if phase == "break":
        return f"Focus session over: take your break. The next one can start at {time_of_day(ends)}."
    return None


def start_focus(state, now, args):
    """`/bod focus [minutes] <goal>`: starts a focus session when none is
    running and the break after the last one is over. Returns what to tell her."""
    phase, ends = focus_phase(state, now)
    if phase == "working":
        return f"A focus session is already running, {fmt(ends - now)} left: {state['focus']['goal']}."
    if phase == "wrap-up":
        return (f"Your session's time is up: wrap up, then take your {FOCUS_BREAK_MINUTES} minute break. "
                f"The next one can start at {time_of_day(ends + timedelta(minutes=FOCUS_BREAK_MINUTES))}.")
    if phase == "break":
        return f"Break first: the next focus session can start at {time_of_day(ends)}."

    minutes = FOCUS_DEFAULT_MINUTES
    if args and args[0].isdigit():
        minutes, args = int(args[0]), args[1:]
    if minutes not in FOCUS_CHOICES:
        return f"Pick one of: {', '.join(map(str, FOCUS_CHOICES))} minutes."
    goal = " ".join(args).strip()
    if not goal:
        return f"What do you want to get done this session? Say it after the minutes: {FOCUS_HOW}."

    state["focus"] = {"started": now.isoformat(), "minutes": minutes, "goal": goal}
    work_ends = now + timedelta(minutes=minutes)
    return (f"🎯 Focus session started: {minutes} minutes for \"{goal}\". "
            f"It ends at {time_of_day(work_ends)}, then you get {WRAP_UP_MINUTES} minutes to wrap up.")


def focus_sound(state, now):
    """On a tick: the sound that should play now, once each across every
    session, or None: "wrap-up" when wrap-up starts, "last-minute" with
    LAST_MINUTE_SECONDS of it left, and "break" when the break starts. Each
    tick runs under the state lock, so only the first session to see the
    change rings."""
    phase, ends = focus_phase(state, now)
    if phase not in ("wrap-up", "break"):
        return None
    moment = phase
    if phase == "wrap-up" and ends - now <= timedelta(seconds=LAST_MINUTE_SECONDS):
        moment = "last-minute"
    rang = state["focus"].setdefault("rang", [])
    if moment in rang:
        return None
    # A later moment covers the earlier ones it skipped past (a laptop asleep), so they never ring late.
    order = ("wrap-up", "last-minute", "break")
    rang.extend(m for m in order[:order.index(moment) + 1] if m not in rang)
    return moment


def focus(args):
    now = datetime.now().astimezone()
    with locked():
        state = load_state() or fresh_state(now)
        finished = state.get("focus")
        said = start_focus(state, now, args)
        # The session before this one goes into the history once a new one starts.
        if finished and state.get("focus") is not finished:
            keep_in_history(finished)
        save_state(state)
    print(said)


def keep_in_history(session):
    """Adds a finished focus session (its goal, its prompts, what she recalled) to the history file."""
    kept = {key: session.get(key) for key in ("started", "minutes", "goal", "log", "recall")}
    with open(HISTORY_PATH, "a") as fh:
        fh.write(json.dumps(kept) + "\n")


def history():
    """Every focus session in the history file, oldest first. A line that can't be read is skipped."""
    try:
        with open(HISTORY_PATH) as fh:
            lines = fh.readlines()
    except OSError:
        return []
    sessions = []
    for line in lines:
        with contextlib.suppress(ValueError):
            sessions.append(json.loads(line))
    return sessions


def note_prompt(state, now, text):
    """Adds a prompt she sent to the running focus session's log. Only while
    it's running or wrapping up; a long prompt is cut short."""
    phase, _ = focus_phase(state, now)
    if phase not in ("working", "wrap-up"):
        return
    text = " ".join(text.split())
    if not text:
        return
    if len(text) > LOG_PROMPT_CHARS:
        text = text[:LOG_PROMPT_CHARS - 1] + "…"
    log = state["focus"].setdefault("log", [])
    if len(log) < LOG_MAX_PROMPTS:
        log.append({"at": now.isoformat(), "text": text})


def session_summary(session):
    """One focus session, for her to read: when, the goal, then every prompt she sent."""
    started = datetime.fromisoformat(session["started"])
    lines = [f"🎯 {time_of_day(started)}, {session['minutes']} min: {session['goal']}"]
    log = session.get("log") or []
    lines += [f"  - {entry['text']}" for entry in log] or ["  (no prompts logged)"]
    if session.get("recall"):
        lines.append(f"  You remembered: {session['recall']}")
    return "\n".join(lines)


def recall(state, args):
    """`/bod recall <what she remembers>`: keeps her own words on the current
    or last session, then shows what it actually worked on to compare."""
    session = state.get("focus")
    if not session:
        return f"No focus session to look back on yet. Start one: {FOCUS_HOW}."
    words = " ".join(args).strip()
    if not words:
        return (f"What did we work on this session? Say it in your own words before looking: {RECALL_HOW}. "
                "Or /bod log to just see it.")
    session["recall"] = words
    return f"Nice, you remembered. Here's what the session actually worked on:\n{session_summary(session)}"


def todays_log(state, now):
    """`/bod log`: today's focus sessions, oldest first, the current one included."""
    sessions = [*history(), *([state["focus"]] if state.get("focus") else [])]
    todays = [s for s in sessions if datetime.fromisoformat(s["started"]).date() == now.date()]
    if not todays:
        return f"No focus sessions today yet. Start one: {FOCUS_HOW}."
    return "Today's focus sessions:\n" + "\n".join(session_summary(s) for s in todays)


def focus_record(mode, args):
    """`bod.py note` (the prompt comes on stdin), `bod.py recall <words>` and `bod.py log`."""
    now = datetime.now().astimezone()
    with locked():
        state = load_state() or fresh_state(now)
        if mode == "note":
            note_prompt(state, now, sys.stdin.read())
            said = None
        elif mode == "recall":
            said = recall(state, args)
        else:
            said = todays_log(state, now)
        save_state(state)
    if said:
        print(said)


def load_settings():
    try:
        with open(SETTINGS_PATH) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    return {key: raw.get(key) if raw.get(key) in choices else DEFAULT_SETTINGS[key] for key, choices in CHOICES.items()}


def save_settings(settings):
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(settings, fh)
    os.replace(tmp, SETTINGS_PATH)


def pool(level):
    """What a level picks from: its own movements (gentle, chair, taichi), exercises otherwise."""
    return POOLS.get(level, EXERCISES)


def pick(count, level="easy"):
    """`count` different exercises, at random, so sets don't keep coming up together."""
    return random.sample(pool(level), count)


def exercise(level="easy", picked=None):
    """(text, seconds to count down from or None, how many exercises): as
    many random ones as the level asks for, or the `picked` ones. Only a lone
    timed exercise counts down; a set of them counts up."""
    count, scale = LEVELS[level]
    picked = picked or pick(count, level)
    count = len(picked)
    amounts = [int(amount * scale + 0.5) for _, amount, _ in picked]
    text = ", then ".join(what.format(n) for (what, _, _), n in zip(picked, amounts))
    seconds = amounts[0] if count == 1 and picked[0][2] else None
    return text, seconds, count


def swapped(text, level="easy", count=1):
    """Another set of `count` exercises for the "swap" button, none of them
    one that's in `text`, so she never gets the jumping jacks back."""
    others = [e for e in pool(level) if e[0].split("{}")[-1].strip() not in text]
    return exercise(level, random.sample(others, count))


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


def music_nudge():
    return f"Music break: {MUSIC_TEXT}."


def switched_off(settings):
    """What the switched-off reminder says, or None while exercises and kindness are both on."""
    off = [(name, command) for kind, name, command in
           (("move", "Exercises", "/bod move on"), ("kind", "kindness nudges", "/bod kind on"))
           if not is_on(settings, kind)]
    if not off:
        return None
    if len(off) == 2:
        return "Exercises and kindness nudges are still off: /bod move on and /bod kind on bring them back"
    name, command = off[0]
    return f"{name[0].upper() + name[1:]} are still off: {command} brings them back"


def skips_today(state, now):
    skips = state["skips"]
    return skips["count"] if skips and skips["date"] == now.date().isoformat() else 0


def away(state, now):
    return now - state["last_prompt"] >= timedelta(minutes=BREAK_MINUTES)


def due(state, key, minutes, now):
    return now - state[key] >= timedelta(minutes=minutes)


def on_schedule(was_due, minutes, now):
    """Where a fixed schedule of every `minutes` stands at `now`: the last
    due time at or before it, starting from `was_due`. A kindness nudge done at
    10:16 that was due at 10:15 leaves the next one due at 10:30; one that sat
    until 10:31 skips the 10:30 slot, so two never come back to back."""
    step = timedelta(minutes=minutes)
    while was_due + step <= now:
        was_due += step
    return was_due


def kindness(state, due):
    """A kindness nudge, due at `due`, as the pending dict holds it."""
    return {"kind": "kind", "text": compassion(state["kinds"]), "seconds": None, "due": due}


def is_on(settings, kind):
    """Whether a nudge is switched on; one with no switch (the switched-off reminder) always is."""
    return kind not in SWITCH or settings[SWITCH[kind]] == "on"


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
    if is_on(settings, "move") and due(state, "last_move", settings["every"], now):
        text, _, count = exercise(settings["level"])
        nudges.append(f"Movement break: {text}. Go, I'll wait.")
        state["last_move"] = now
        state["moves"] += count
    if due(state, "last_cap", CAP_CHECK_MINUTES, now):
        worked, _ = today(now)
        if over_cap(worked):
            nudges.append(stop_nudge(worked))
        state["last_cap"] = now
    if is_on(settings, "kind") and due(state, "last_kind", settings["kind"], now):
        nudges.append(kind_nudge(state["kinds"]))
        state["last_kind"] = now
        state["kinds"] += 1
    if is_on(settings, "check") and due(state, "last_check", CHECK_IN_MINUTES, now):
        nudges.append(check_nudge(state["checks"]))
        state["last_check"] = now
        state["checks"] += 1
    if is_on(settings, "music") and due(state, "last_music", MUSIC_MINUTES, now):
        nudges.append(music_nudge())
        state["last_music"] = now
    if switched_off(settings) and due(state, "last_off", OFF_REMINDER_MINUTES, now):
        nudges.append(f"{switched_off(settings)}.")
        state["last_off"] = now
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
    settings = {**DEFAULT_SETTINGS, **(settings or load_settings())}
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
    if is_on(settings, "check") and due(state, "last_check", CHECK_IN_MINUTES, now):
        pending = {"kind": "check", "text": fog_fix(state["checks"]), "seconds": None}
    elif is_on(settings, "music") and due(state, "last_music", MUSIC_MINUTES, now):
        pending = {"kind": "music", "text": MUSIC_TEXT, "seconds": None}
    elif switched_off(settings) and due(state, "last_off", OFF_REMINDER_MINUTES, now):
        pending = {"kind": "off", "text": switched_off(settings), "seconds": None}
    elif is_on(settings, "move") and due(state, "last_move", settings["every"], now):
        text, seconds, count = exercise(settings["level"])
        pending = {"kind": "move", "text": text, "seconds": seconds, "count": count}
    elif is_on(settings, "kind") and due(state, "last_kind", settings["kind"], now):
        pending = kindness(state, state["last_kind"] + timedelta(minutes=settings["kind"]))
    if pending:
        state["pending"] = {"due": None, **pending, "started": None, "snoozed_until": None, "beeped": False}


def right_now(state, now, settings=None, kind="move"):
    """`/bod now`: the next exercise on show at once, without waiting for its
    timer or touching the others; `/bod kind now` (kind="kind") does the same
    with a kindness nudge. A nudge already up stays; one put off with
    "not now" comes straight back, unless she asked for the other kind: then
    that one goes up and the put-off one is due again when its snooze ends."""
    pending = state["pending"]
    # Asking counts as being here: a tick won't drop it as stale.
    state["last_prompt"] = now
    state["quiet_until"] = None
    snoozed = pending and pending["snoozed_until"] and now < pending["snoozed_until"]
    if snoozed and pending["kind"] != kind:
        settings = {**DEFAULT_SETTINGS, **(settings or load_settings())}
        every = {"move": settings["every"], "kind": settings["kind"], "check": CHECK_IN_MINUTES,
                 "music": MUSIC_MINUTES, "off": OFF_REMINDER_MINUTES}[pending["kind"]]
        state[LAST[pending["kind"]]] = pending["snoozed_until"] - timedelta(minutes=every)
        pending = None
    if pending:
        pending["snoozed_until"] = None
        return
    if kind == "kind":
        # Asked for, so due now: the schedule runs on from here.
        state["pending"] = {**kindness(state, now), "started": None, "snoozed_until": None, "beeped": False}
        return
    settings = settings or load_settings()
    text, seconds, count = exercise(settings["level"])
    state["pending"] = {
        "kind": "move", "text": text, "seconds": seconds, "count": count, "due": None,
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
    elif button == "swap":
        # Only an exercise not yet started; a running timer stays as it is.
        if pending["kind"] == "move" and not pending["started"]:
            text, seconds, count = swapped(pending["text"], load_settings()["level"], pending.get("count", 1))
            pending.update(text=text, seconds=seconds, count=count, beeped=False)
    elif button == "snooze":
        pending["snoozed_until"] = now + timedelta(minutes=load_settings()["snooze"])
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
            # The schedule runs from when it was due, not from the done, so
            # waiting behind an exercise never pushes the next one back.
            state["last_kind"] = on_schedule(pending.get("due") or now, load_settings()["kind"], now)
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
    """When the exercise and kindness nudges will next show, each left out
    while it's switched off, or None while a nudge is on show. Nothing new
    shows during the pause after a done, and a nudge put off with "not now"
    comes back when its snooze ends, ahead of the rest, so neither can show
    before then either."""
    pending = state["pending"]
    earliest = state["quiet_until"] or now
    if pending:
        snoozed = pending["snoozed_until"]
        if not (snoozed and now < snoozed):
            return None
        earliest = snoozed
    settings = {**DEFAULT_SETTINGS, **(settings or load_settings())}
    every = {"move": settings["every"], "kind": settings["kind"]}
    return {
        kind: max(state[LAST[kind]] + timedelta(minutes=minutes), earliest)
        for kind, minutes in every.items() if is_on(settings, kind)
    }


def view(state, now, settings=None, worked=None, merged=None):
    """What the band shows, with times in epoch milliseconds for the mod.
    "next" is when each nudge is due; "paused" means she's been away long
    enough that nothing shows until her next prompt restarts the timers;
    "worked" is how many seconds she's worked today, when it was counted;
    "skips" is how many times she's said "not now" today;
    "merged" is today's merged PRs against the daily cap, when they were counted;
    "focus" is where the focus session stands (its phase, when that ends, its goal);
    "locked" is why prompts are refused: today's hours are past the hard cap,
    or no focus session is running. None while they may go through."""

    def ms(when):
        return int(when.timestamp() * 1000)

    phase, phase_ends = focus_phase(state, now)
    goal = state["focus"]["goal"] if phase != "none" else None
    cap_lock = lock_text(worked) if worked is not None and over_cap(worked) else None
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
        "next": {kind: ms(when) for kind, when in due_at.items()} if due_at is not None else None,
        "paused": paused,
        "worked": int(worked.total_seconds()) if worked is not None else None,
        "skips": skips_today(state, now),
        "merged": {"count": merged, "cap": DAILY_PR_CAP} if merged is not None else None,
        "focus": {"phase": phase, "ends": ms(phase_ends) if phase_ends else None, "goal": goal,
                  "line": focus_line(phase, phase_ends, goal, bool(phase != "none" and state["focus"].get("recall")))},
        "locked": cap_lock or focus_lock_text(phase, phase_ends),
    }


def worked_so_far(now):
    """Today's hours for the status line, or None when the transcripts can't
    be read (one deleted mid-read, say): a missing timer beats a broken tick."""
    try:
        return today(now)[0]
    except OSError:
        return None


def last_counted(state, now, button):
    """Today's hours as last counted, when they'll do instead of a new scan:
    always for a button press, and for a tick while they're under a minute old.
    None when they need counting again (none yet, or from another day)."""
    cached = state.get("worked")
    if not cached:
        return None
    at = datetime.fromisoformat(cached["at"])
    if at.date() != now.date():
        return None
    if button == "tick" and (now - at).total_seconds() >= WORKED_REFRESH_SECONDS:
        return None
    return timedelta(seconds=cached["seconds"])


def last_merged(state, now, button):
    """Today's merged PRs as last counted, when they'll do instead of asking
    GitHub again: always for a button press, and for a tick while they're
    under MERGED_REFRESH_SECONDS old. None when they need counting again."""
    cached = state.get("merged")
    if not cached:
        return None
    at = datetime.fromisoformat(cached["at"])
    if at.date() != now.date():
        return None
    if button == "tick" and (now - at).total_seconds() >= MERGED_REFRESH_SECONDS:
        return None
    return cached["count"]


def remember(key, value, now):
    """Save a fresh count under `key` without losing what other sessions saved."""
    with locked():
        latest = load_state()
        if latest is not None:
            latest[key] = {**value, "at": now.isoformat()}
            save_state(latest)


def mod(button):
    now = datetime.now().astimezone()
    with locked():
        state = load_state() or fresh_state(now)
        said = {}
        if button == "tick":
            state["mod_seen"] = now
            advance(state, now)
            sound = focus_sound(state, now)
            if sound:
                said = {"sound": sound}
        elif button == "now":
            right_now(state, now)
        elif button == "kindnow":
            right_now(state, now, kind="kind")
        else:
            said = press(state, button, now)
        worked = last_counted(state, now, button)
        merged = last_merged(state, now, button)
        save_state(state)
    # Counted outside the lock, so a press in another session isn't kept waiting.
    if worked is None:
        worked = worked_so_far(now)
        if worked is not None:
            remember("worked", {"seconds": int(worked.total_seconds())}, now)
    if merged is None and button == "tick":
        merged = merged_today(now)
        if merged is not None:
            remember("merged", {"count": merged}, now)
    print(json.dumps({**view(state, now, worked=worked, merged=merged), **said}))


def show(kind):
    now = datetime.now().astimezone()
    with locked():
        state = fresh_state(now, load_state())
        plank = kind == "plank"
        kind = "move" if plank else kind
        state[LAST[kind]] = now - timedelta(minutes=max(*EVERY_CHOICES, *KIND_CHOICES, CHECK_IN_MINUTES, MUSIC_MINUTES, OFF_REMINDER_MINUTES))
        # Shown even when it's switched off: this is for trying the band out.
        # The switched-off reminder shows as if exercises were off.
        trying = {"move": "off"} if kind == "off" else {SWITCH[kind]: "on"}
        advance(state, now, lambda now: timedelta(0), {**load_settings(), **trying})
        if plank:
            # A lone plank, to see the countdown.
            text, seconds, count = exercise("easy", [next(e for e in EXERCISES if "plank" in e[0])])
            state["pending"].update(text=text, seconds=seconds, count=count)
        save_state(state)
    print(json.dumps(view(state, now)))


def per_nudge(level):
    """What each nudge asks for on `level`, in a few words."""
    if level == "gentle":
        return "one gentle movement"
    if level == "chair":
        return "one movement from your chair"
    if level == "taichi":
        return "one tai chi or qi gong movement"
    count, _ = LEVELS[level]
    return "one exercise" if count == 1 else f"{count} exercises" + (" with more reps" if level == "hard" else "")


def describe(settings):
    what = per_nudge(settings["level"])
    move = f"{what} every {settings['every']} minutes" if is_on(settings, "move") else "exercises off"
    kind = f"something kind every {settings['kind']}" if is_on(settings, "kind") else "kindness off"
    check = "" if is_on(settings, "check") else ", workflow check-in off"
    music = "" if is_on(settings, "music") else ", music break off"
    return f"Claude Bod is on {settings['level']}: {move}, {kind}{check}{music}, at most {settings['claudes']} Claudes open at once."


def info(settings):
    """Every setting, one per line: her choices first, then the ones fixed in this file."""
    what = per_nudge(settings["level"])
    return "\n".join([
        "Claude Bod settings (/bod config to change them in one form):",
        f"- Level: {settings['level']} ({what} per nudge) · /bod level {'|'.join(LEVELS)}",
        (f"- Exercise every {settings['every']} minutes of work · /bod move every {'|'.join(map(str, EVERY_CHOICES))} · /bod move off"
         if is_on(settings, "move") else "- Exercises: off · /bod move on"),
        (f"- Something kind every {settings['kind']} minutes · /bod kind every {'|'.join(map(str, KIND_CHOICES))} · /bod kind off"
         if is_on(settings, "kind") else "- Kindness: off · /bod kind on"),
        f"- Claude cap: {settings['claudes']} open at once · /bod claudes {CLAUDES_CHOICES[0]}-{CLAUDES_CHOICES[-1]}",
        (f"- Workflow check-in every {CHECK_IN_MINUTES} minutes · /bod check off"
         if is_on(settings, "check") else "- Workflow check-in: off · /bod check on"),
        (f"- Music break every {MUSIC_MINUTES} minutes · /bod music off"
         if is_on(settings, "music") else "- Music break: off · /bod music on"),
        f"- Snooze: {settings['snooze']} minutes · /bod snooze {'|'.join(map(str, SNOOZE_CHOICES))}",
        f"- Away for {BREAK_MINUTES} minutes counts as a break and restarts the timers",
        f"- Daily cap: {DAILY_CAP_HOURS} hours, then prompts are refused until midnight",
        (f"- Focus sessions: prompts only go through during one, then {WRAP_UP_MINUTES} minutes to wrap up "
         f"and a {FOCUS_BREAK_MINUTES} minute break · {FOCUS_HOW}"),
        "- Focus log: every prompt in a session is kept · /bod log for today's · /bod recall <in your own words> to test your memory first",
        f"- Take a break after {STRETCH_LIMIT_MINUTES} minutes without one (/work-check)",
    ])


def choose(args):
    """Set the level, the minutes, the kindness minutes, the Claude cap and/or switch a nudge on or off, given as
    pairs ("level hard move every 10 kind every 30 claudes 5 check off", or just "level hard 10"); prints only what changed. Nothing is
    saved unless every pair is valid."""
    settings = load_settings()
    before = dict(settings)
    args = natural(args)
    # A bare number is the minutes: "level hard 10" means "level hard every 10".
    args = [part for i, arg in enumerate(args)
            for part in (["every", arg] if arg.isdigit() and (i == 0 or args[i - 1] not in ("every", "kind", "claudes", "snooze")) else [arg])]
    if not args or len(args) % 2:
        args = [*args, ""]
    keys = []
    for key, value in zip(args[::2], args[1::2]):
        if key == "kind" and value in SWITCH_CHOICES:
            key = SWITCH["kind"]
        if key in ("move", "kindness", "check", "music"):
            choices = SWITCH_CHOICES
        elif key == "every":
            value = int(value) if value.isdigit() else None
            choices = EVERY_CHOICES
        elif key == "kind":
            value = int(value) if value.isdigit() else None
            choices = KIND_CHOICES
        elif key == "claudes":
            value = int(value) if value.isdigit() else None
            choices = CLAUDES_CHOICES
        elif key == "snooze":
            value = int(value) if value.isdigit() else None
            choices = SNOOZE_CHOICES
        elif key == "level":
            choices = tuple(LEVELS)
        else:
            print(f"Use: level {'|'.join(LEVELS)}, move every 5|10|15, kind every 5|10|15|30|45, claudes 1-10, "
                  "snooze 2|5|10|15, move on|off, kind on|off, check on|off, music on|off.")
            sys.exit(1)
        if value not in choices:
            pick = (f"Pick a number from {choices[0]} to {choices[-1]}." if isinstance(choices, range)
                    else f"Pick one of: {', '.join(str(c) for c in choices)}.")
            print(f"{pick} It's {settings[key]} now.")
            sys.exit(1)
        settings[key] = value
        keys.append(key)
    switch_on_by_minutes(settings, keys)
    save_settings(settings)
    drop_switched_off(settings)
    print(" ".join(confirm(key, settings, before) for key in dict.fromkeys(keys)))


# Setting how often a nudge comes means she wants it: its minutes switch it on.
SWITCHED_ON_BY = {"every": "move", "kind": "kindness"}


def switch_on_by_minutes(settings, keys):
    """Switches exercises or kindness on when she set their minutes, unless the
    same call also switched that one off on purpose ("move off every 10")."""
    for minutes_key, switch in SWITCHED_ON_BY.items():
        if minutes_key in keys and switch not in keys:
            settings[switch] = "on"


def natural(args):
    """The words she'd say, as the pairs choose() takes: "move every 10" and
    "move 10" are "every 10", "kind every 30" is "kind 30"."""
    out = []
    i = 0
    while i < len(args):
        word = args[i]
        after = args[i + 1] if i + 1 < len(args) else ""
        if word in ("move", "kind") and after == "every":
            out.append("every" if word == "move" else "kind")
            i += 2
        elif word == "move" and after.isdigit():
            out.append("every")
            i += 1
        else:
            out.append(word)
            i += 1
    return out


def drop_switched_off(settings):
    """A nudge on show whose kind was just switched off goes, unless she's already doing it,
    and so does the switched-off reminder once nothing it names is off."""
    with locked():
        state = load_state()
        pending = state and state["pending"]
        if pending and pending["kind"] == "off":
            stale = switched_off(settings) is None
        else:
            stale = pending and not pending["started"] and not is_on(settings, pending["kind"])
        if stale:
            state["pending"] = None
            save_state(state)


def confirm(key, settings, before):
    """One line saying what a setting is now (and, for the Claude cap, what it was)."""
    if key == "level":
        what = per_nudge(settings["level"])
        return f"Your level is now {settings['level']}: {what} per nudge."
    if key == "every":
        back = " They're back on." if before["move"] == "off" and is_on(settings, "move") else ""
        return f"Your exercises are now every {settings['every']} minutes.{back}"
    if key == "kind":
        back = " Kindness nudges are back on." if before["kindness"] == "off" and is_on(settings, "kind") else ""
        return f"Something kind is now every {settings['kind']} minutes.{back}"
    if key == "move":
        return f"Exercises are on, every {settings['every']} minutes." if is_on(settings, "move") else "Exercises are off."
    if key == "kindness":
        return (f"Kindness nudges are on, every {settings['kind']} minutes." if is_on(settings, "kind")
                else "Kindness nudges are off.")
    if key == "check":
        return (f"The workflow check-in is on, every {CHECK_IN_MINUTES} minutes." if is_on(settings, "check")
                else "The workflow check-in is off.")
    if key == "music":
        return (f"The music break is on, every {MUSIC_MINUTES} minutes." if is_on(settings, "music")
                else "The music break is off.")
    if key == "snooze":
        return f"Not now puts a nudge off for {settings['snooze']} minutes."
    if settings["claudes"] == before["claudes"]:
        return f"Your Claude cap is still {settings['claudes']}."
    return f"Your Claude cap is now {settings['claudes']} (was {before['claudes']})."


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
        print(f"Last music break: {fmt(now - state['last_music'])} ago")

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
    elif mode in ("tick", "now", "kindnow", "go", "swap", "done", "snooze", "beep") and not (mode == "snooze" and sys.argv[2:]):
        mod(mode)
    elif mode in ("level", "every", "kind", "claudes", "snooze", "move", "check", "music"):
        choose(sys.argv[1:])
    elif mode == "focus":
        focus(sys.argv[2:])
    elif mode in ("note", "recall", "log"):
        focus_record(mode, sys.argv[2:])
    elif mode == "settings":
        print(describe(load_settings()))
    elif mode == "choices":
        print(json.dumps({"settings": load_settings(),
                          "choices": {key: list(choices) for key, choices in CHOICES.items()}}))
    elif mode == "info":
        print(info(load_settings()))
    elif mode == "show" and sys.argv[2:] and sys.argv[2] in (*LAST, "plank"):
        show(sys.argv[2])
    else:
        status()
