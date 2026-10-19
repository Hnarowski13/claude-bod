---
name: work-check
description: Check how long Helena has been working today and tell her whether to keep going, take a break, or stop for the day. Use whenever she says "work check", "how long have I been working", "should I stop", "should I take a break", "am I over my hours", or "/work-check".
---

# Work check

Helena doesn't want to be prompting AI for more than about 4 hours in one day.
This skill looks at how long she's been at it and gives her a straight answer.

## 1. Get the numbers

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/bod.py" status
```

It prints the time worked today, the current stretch without a break, how long
ago the last movement and compassion nudges went out, and a `Verdict:` line. The hours are a
transcript-based estimate across every project, session and worktree, so they include time Claude was busy on its own and miss anything
done away from Claude. Treat them as rough.

## 2. Tell her

Answer in two or three lines, verdict first, then the numbers behind it.

- **`STOP`** (over the 4 hour cap): tell her plainly to stop for the day. Give
  the hours, say stopping now is the right call and that the backlog will
  still be there tomorrow. Recommend it, don't present it as an even choice.
  It's still her call: be firm and caring, not preachy. If she has work in
  flight, offer to get it to a safe stopping point (committed, servers left
  as they are) and nothing more.
- **`BREAK`** (a long stretch with no break): tell her to step away for at
  least 15 minutes before the next prompt, and how long the stretch has been.
- **`OK`**: say how much is left before the cap. If under an hour is left, say
  so, so she can pick a last ticket that fits.

Don't pad it with advice she didn't ask for, and don't repeat the verdict on
later replies in the same session unless she asks again.

## Tuning

The cap, the stretch limit and the two nudge intervals are constants at the
top of `scripts/bod.py` in the Claude Bod plugin (bod). The same script is what
sends a movement nudge every 5 minutes (her `/bod every` choice)
and a compassion nudge (a hug, a few slow breaths) every 15 (her `/bod kind` choice), and it puts up a "stop for the day" line once the cap
is passed.
