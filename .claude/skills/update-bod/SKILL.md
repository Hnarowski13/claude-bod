---
name: update-bod
description: Change the Claude Bod plugin (bod). Use whenever Helena wants to tweak, fix or add to Claude Bod: the movement / standing-desk / kindness nudges, the takeover panel or band, timers and the daily cap, /work-check, or the cap on open Claudes ("make the plank 30 seconds", "bod should also...", "change the Claude limit to 3", "update claude bod"). Also the reference for where things live in Bod's code and how to test it.
---

# Update Claude Bod

Claude Bod is Helena's own plugin, `bod`, in its own public repo:
`~/Projects/claude-bod`, `Hnarowski13/claude-bod`. Its flow matches
new-goats: **every change is a ticket, and every ticket ships through a PR.**
Nothing is pushed straight to `main`.

## A change request

When she asks for a change ("make the plank 30 seconds"):

1. File it as a ticket, following
   `~/Projects/claude-bod/.claude/skills/ticket-creator/SKILL.md` (placeholder
   body, a `risk:` label, duplicates checked). Don't recolor the tab as the
   ticket creator: this session is about to work the ticket.
2. Pick it up straight away, following
   `~/Projects/claude-bod/.claude/skills/pick-up-ticket/SKILL.md`: worktree,
   change, test, PR, merge by risk, pull into the main checkout.

If she only wants it noted for later ("ticket that", "add to the bod
backlog"), do step 1 and stop.

## How her installed copy works

Her installed `bod` (marketplace `bod`, plugin `bod@bod`) is read live from
`~/Projects/claude-bod`. Whatever is checked out there runs in every Claude
after `/reload-plugins`. So:

- Never edit that folder directly; work in `.claude/worktrees/`.
- A merged PR reaches her only once `main` is pulled there
  (`pick-up-ticket` step 6 does it).
- `claude plugin list --json` shows `folderVersion` for what's live. The
  `installPath` cache under `~/.claude/plugins/cache/bod/` is an old record,
  not what runs.

## Where things are

| Change | File |
| --- | --- |
| Level (`LEVELS`), exercise interval choices (`EVERY_CHOICES`), other nudge timers, daily cap, break gap, snooze, exercises, kindness lines, wording | constants at the top of `scripts/bod.py` |
| How many Claudes may be open | `LIMIT` in `scripts/claude-limit.py` |
| The band, the takeover box, buttons, `/bod`, prompt lock, the cap's refusal message, the countdown | `hooks/register.tsx` (no side panel: Claude Code docks panes beside the transcript, so everything draws in the band above the prompt) |
| How hours are counted | `scripts/hours.py` (every project's transcripts) |
| `/work-check` wording and verdicts | `skills/work-check/SKILL.md` |
| Shared state the mod draws from | `types/index.d.ts` (the `PluginState` contract) |
| This workflow (ticketing, pickup, this file) | `.claude/skills/` (repo-only, not shipped in the plugin) |

`bod.py` is the brain (state file `~/.claude/bod-state.json`, shared by every
session); the mod polls it with `bod.py tick` and sends button presses. For a
mod change (`hooks/`), load the `plugin-authoring` skill first: it has the API
and where its types are.

## Testing

From the worktree, all of these must pass:

```bash
python3 -m unittest discover scripts
claude plugin test .
claude plugin validate .
```

Add or update a test when behaviour changes (`scripts/test_bod.py` for
`bod.py`, `hooks/register.test.tsx` for the mod). The two "gating hook
without .catch" validate warnings are intended: a broken hook lets the
prompt through.

To see a nudge: `python3 <worktree>/scripts/bod.py show plank` (or `move`,
`stand`, `kind`) puts one up in every open session right away.

## Shipping details

- **Version:** bump `version` in `.claude-plugin/plugin.json` on every PR that
  changes the plugin (patch for tweaks, minor for features). People who
  installed from GitHub only get a change through `claude plugin update` when
  the version moves. Changes only to `.claude/` don't need a bump.
- **Secrets:** the repo is public. Before committing, call the
  `mcp__plugin-authoring__scan_secrets` tool on the worktree (load it with
  ToolSearch if needed) and check `git diff` for anything that shouldn't be
  public. If it flags a file, stop and tell her which file and what kind of
  secret.
- **Commits:** explicit paths (no `git add -A`), a short imperative message,
  `Fixes #<n>`, and the session's Co-Authored-By line.

## Gotchas

- Plugin names can't start with `claude-`. That's why it's `bod`.
- If a change renames or removes a script that a hook in a *settings file*
  runs, sessions that are already open keep the old hook and block every
  prompt (python exits 2 on a missing file). Prefer doing everything through
  the mod (`hooks/register.tsx`), not classic settings hooks.
- `afplay` (the timer sound) is macOS-only. Keep a failing sound from ever
  breaking a nudge.
