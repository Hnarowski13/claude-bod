# Claude Bod

Looks after the person at the keyboard while Claude Code runs. Works in every project.

- **Movement nudges** in a band above the prompt: a quick exercise every 5 minutes of work (or 10, or 15) and something kind to yourself every 15 (or 10, 30, 45). They have go / done / not now buttons and an exercise timer.
- **Workflow check-in**: every 45 minutes of work, Bod asks how the workflow is going and offers one thing to try against Claude-FOG (too many Claudes, lost track of what each is doing): close merged tabs, finish one session first, and so on. It takes the session over like an exercise does, with done / not now.
- **Countdown**: the status line under the prompt shows how long until the next exercise nudge (`🤸 move in 3:12`), or that Bod is paused after 20 minutes without a prompt.
- **Takeover**: an exercise nudge or check-in takes the session over (a box above the prompt, one exercise per line). Prompts are refused until it's done or put off with "not now". Kindness nudges never block.
- **Stop for the day**: past 4 hours of Claude time today, a "stop for the day" line stays up in the band.
- **Claude cap**: at most 5 Claudes open at once (change it with `/bod claudes <n>`). A newer session refuses prompts until an older one closes.
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
- `/bod kind 5|10|15|30|45`: minutes of work between kindness nudges. 15 by default.
- `/bod claudes 1-20`: how many Claudes may be open at once. 5 by default.
- `/bod now`: an exercise right away, without waiting for the timer. The kindness timer carries on as they were.
- `/bod kind now`: a kindness nudge right away, the same way.
- `/bod settings` says what it's set to. Your choices are kept in `~/.claude/bod-settings.json`.

## Tuning

- Timers, the daily cap and the check-in's fixes (`FOG_FIXES`): constants at the top of `scripts/bod.py`.
- Claude cap: `/bod claudes <n>`, or its default in `DEFAULT_SETTINGS` in `scripts/bod.py`.

## Trying and testing

- Show a nudge now: `python3 scripts/bod.py show plank` (or `move`, `kind`, `check`).
- Tests: `python3 -m unittest discover scripts` and `claude plugin test .`
