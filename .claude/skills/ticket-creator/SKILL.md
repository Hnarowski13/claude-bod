---
name: ticket-creator
description: Create lightweight placeholder GitHub issues for Claude Bod in Hnarowski13/claude-bod. Use whenever Helena rattles off Bod feature ideas, bugs, or backlog items (movement / standing-desk / kindness nudges, the takeover panel or band, timers, the daily cap, /work-check, the cap on open Claudes) and wants them ticketed rather than built now.
---

# Ticket creator (Claude Bod)

Helena dumps ideas and bugs conversationally, often as one-liners, and wants
each one turned into an issue in `Hnarowski13/claude-bod` *fast*. Default to
minimal placeholder tickets. Don't pad them with acceptance criteria, subtasks
or speculative detail she didn't give you. If her message has a genuinely
useful nuance (a specific number, a dependency, an open question), keep it as
a short bullet or two in the body, and nothing beyond what she said.

Tickets are picked up later with "pu bod <n>".

## Tab color: are you the ticket creator?

Helena usually keeps one Claude session open whose whole job is filing
tickets, alongside several that are each working a ticket. That dedicated
session's iTerm2 tab should be orange, titled "Bod Tickets (tickets)", so she
can find it in the tab bar. The script lives in new-goats and is shared:

```bash
~/Projects/new-goats/bin/ticket-tab-color creator "Bod Tickets"
```

But this skill also gets used offhandedly: a session that's busy with
something else is asked to file a ticket on the side. That session is *not*
the ticket creator, and turning it orange would wipe out the color that says
what it's actually doing. So decide which one you are before touching the tab.

You are the ticket creator, and should turn the tab orange, when either:

- Helena said so, in any wording ("you're my ticket creator", "this is my
  ticket session", "you'll be making tickets for me"), or
- creating tickets is all this session has done: it opened with a ticket
  request and nothing else has happened since.

You are not, and must leave the tab alone, when any of these is true:

- this session has picked up a ticket at any point
- the session has done other real work (code changes, debugging, a review)
  and the ticket request arrived in the middle of it or as a follow-up to it
- you're filing the ticket only as a step toward implementing it yourself
  ("ticket this and fix it")

If it's genuinely unclear, leave the tab alone; a missing orange tab costs
nothing, a wrongly orange one hides a ticket in progress. Once you've turned
it orange there's no need to run the script again for later tickets.

## What goes here vs. new-goats

- Anything about Bod's behaviour (nudges, panel, timers, cap, /work-check,
  the open-Claude limit) → this repo.
- Tooling in new-goats *about* Bod (its skills, CLAUDE.md) → a new-goats
  ticket under its Claude Workflow epic, not here.

## Creating a ticket

There are no epics in this repo: the whole repo is Bod. Every ticket gets
exactly one `risk:` label.

```bash
gh issue create --repo Hnarowski13/claude-bod \
  --title "Short, specific title" \
  --body "Placeholder — flesh out details later." \
  --label "risk:<level>"
```

Reply with the issue number(s) and URL(s), one line each.

## Risk labels

`pick-up-ticket` reads these to decide whether it can push, merge and clean up
on its own or must stop for Helena's review. Default to `risk:medium` when
unsure.

- `risk:low`: a future Claude can merge it without Helena looking. Narrow,
  mechanical, hard to get wrong: copy tweaks, changing a duration or count,
  adding an exercise to an existing list. Not anything she flagged as TBD.
- `risk:medium`: typical feature work and most bug fixes. The default.
- `risk:high`: changes to hooks that run on every prompt or tool call, the
  cap on open Claudes, or anything that could block or break her Claude
  sessions if it goes wrong.

## Before creating: check for duplicates

If it sounds like it might already exist as a ticket or as a built feature,
check first:

```bash
gh issue list --repo Hnarowski13/claude-bod --search "<keyword>" --state all --json number,title
```

For "is this already in Bod" questions, grep `hooks/`, `scripts/` and
`skills/` rather than trusting a ticket title.

## Open / undecided ideas

When she's visibly unsure ("not sure if this is a good idea", "TBD",
"something like that?"), don't turn it into a confident title. Prefix the
title with `TBD - ` or fold the open question into the title, and put her own
uncertainty in the body.

## Batching

For several tickets in one message, run sequential `gh issue create` calls or
loop over a plain indexed array. This machine's `/bin/bash` is 3.2, so no
`declare -A`.
