# Claude Bod

Looks after the person at the keyboard while Claude Code runs. Works in every project.

- **Movement nudges** in a band above the prompt: a quick exercise every 5 minutes of work (or 10, or 15), the standing desk every 30, something kind to yourself every 45. They have go / done / not now buttons and an exercise timer.
- **Countdown**: the status line under the prompt shows how long until the next exercise and standing nudge (`🤸 move in 3:12 · 🚶 stand in 18:40`), or that Bod is paused after 20 minutes without a prompt.
- **Takeover**: an exercise or standing-desk nudge takes the session over (a panel in giant letters, `/bod` opens it on a narrow terminal). Prompts are refused until it's done or put off with "not now". Kindness nudges never block.
- **Stop for the day**: past 4 hours of Claude time today, the standing nudge becomes "stop for the day".
- **Claude cap**: at most 4 Claudes open at once. A newer session refuses prompts until an older one closes.
- **`/work-check`**: hours today, the current stretch, and a verdict (keep going, take a break, or stop).

Hours are estimated from Claude Code's transcripts across every project. Every session shares one state file, `~/.claude/bod-state.json`, so five sessions still add up to one nudge per interval.

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install bod --marketplace Hnarowski13/claude-bod
```

Answer `y` to add the marketplace, then pick a scope (user, so it works in every project). Or from a shell:

```
claude plugin install bod --marketplace Hnarowski13/claude-bod
```

Needs `python3` on your PATH. The movement timer's sound uses macOS's `afplay`.

### Developing

To run it from a local clone, so edits show up after `/reload-plugins`:

```
claude plugin marketplace add ~/Projects/claude-bod
claude plugin install bod@bod
```

## Level and timing

- `/bod level easy|medium|hard`: one exercise per nudge, two, or three with more reps and longer holds. Easy by default.
- `/bod every 5|10|15`: minutes of work between exercise nudges. 5 by default.
- `/bod now`: an exercise right away, without waiting for the timer. The standing and kindness timers carry on as they were.
- `/bod settings` says what it's set to. Your choices are kept in `~/.claude/bod-settings.json`.

## Tuning

- Timers and the daily cap: constants at the top of `scripts/bod.py`.
- Claude cap: `LIMIT` at the top of `scripts/claude-limit.py`.

## Trying and testing

- Show a nudge now: `python3 scripts/bod.py show plank` (or `move`, `stand`, `kind`).
- Tests: `python3 -m unittest discover scripts` and `claude plugin test .`
