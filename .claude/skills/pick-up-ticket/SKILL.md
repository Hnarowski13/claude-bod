---
name: pick-up-ticket
description: Pick up a Claude Bod GitHub issue (Hnarowski13/claude-bod), work it in its own git worktree, open a PR, merge by risk, then pull it into the folder her installed plugin runs from. Use whenever Helena says "pu <n>", "pu bod <n>", "pick up ticket/issue <n>", "work on <n>", or gives a bare issue number for Bod's backlog. Invoked as /pick-up-ticket <issue_number>.
---

# Pick up a Bod ticket

Same flow as new-goats: fetch the real ticket, work it in a worktree so the
main checkout is never touched, verify, open a PR, and merge only when the
risk label allows it.

**Never edit `~/Projects/claude-bod` itself.** Her installed `bod` is read
live from that folder, so whatever is checked out there is what every one of
her Claudes runs after `/reload-plugins`. It must stay a clean `main`, and a
merge only reaches her once it's pulled there (step 6). All work happens in
`.claude/worktrees/`.

Where things live in the code, how to test, the version bump and the secrets
scan are in the `update-bod` skill. Load it in step 3.

## 0. Check today's merged-PR count

Before anything else, count the PRs Helena has merged since local midnight,
across both repos:

```bash
gh search prs --author @me --merged --limit 100 --json number,title,repository,closedAt \
  -- "merged:>=$(date -v-1d +%Y-%m-%d)" \
  | jq --argjson start "$(date -v0H -v0M -v0S +%s)" \
      '[.[] | select((.closedAt | fromdateiso8601) >= $start)]'
```

If it's **over 10**, stop. Tell her the count, list them (repo, number,
title), and encourage her *strongly* to stop for the day: say plainly it's a
lot for one day and the backlog will still be there tomorrow. Recommend
stopping rather than offering an even choice, and make her actively confirm
before continuing. Firm and caring, not preachy. At 10 or fewer, carry on
without mentioning it.

## 1. Resolve the issue

```bash
gh issue view <n> --repo Hnarowski13/claude-bod \
  --json number,title,body,url,state,labels,comments,closedByPullRequestsReferences
```

Read the whole body. If it's closed, say so and confirm she still wants it.
If a linked PR is still open (`gh pr view <pr> --repo Hnarowski13/claude-bod
--json state,headRefName`), continue on that PR's branch (step 2) and push to
the same PR.

The `risk:` label decides the end of the flow:

- `risk:low`: push, open a PR, merge, clean up and sync, without checking in.
- `risk:medium`, `risk:high` or no label: push and open a PR, then stop for
  her review.

Never decide the risk yourself or upgrade a ticket to `risk:low`.

If the body says "Depends on #N" and N is still open, tell her before going
further.

## 2. Create the worktree

Slug the title into a few kebab-case words and name the worktree
`issue-<n>-<slug>`.

- **Session started in `~/Projects/claude-bod`:** call `EnterWorktree` with
  that name. It branches from `origin/main` into
  `.claude/worktrees/issue-<n>-<slug>`.
- **Session started elsewhere (e.g. new-goats):** `EnterWorktree` can't reach
  another repo, so create it by hand and use absolute paths (or `git -C`) from
  then on:
  ```bash
  git -C ~/Projects/claude-bod fetch origin
  git -C ~/Projects/claude-bod worktree add \
    .claude/worktrees/issue-<n>-<slug> -b issue-<n>-<slug> origin/main
  ```

For an open PR's branch, check `git worktree list` first and reuse that
worktree if one has it; otherwise create one and
`git checkout -B <headRefName> origin/<headRefName>` inside it.

Color and name the tab by risk (green for low/medium, red for high, `working`
if unlabeled). Start the name with 💪 so a Bod worker stands out from her
new-goats tabs. The script lives in new-goats and is shared:

```bash
~/Projects/new-goats/bin/ticket-tab-color <low|medium|high|working> "💪 bod #<n> <two or three words>"
```

## 3. Implement

Load the `update-bod` skill for where things live and how Bod works. Read
the current code for everything the ticket touches before changing it. Stay
inside the ticket's scope; if it turns out bigger or different than
written, stop and tell her.

## 4. Verify

From the worktree, all must pass (see `update-bod` for what the validate
warnings mean):

```bash
python3 -m unittest discover scripts
claude plugin test .
claude plugin validate .
```

Add or update a test when behaviour changes.

## 5. Commit, PR, merge by risk

1. If the plugin itself changed (anything outside `.claude/`), bump `version`
   in `.claude-plugin/plugin.json` (patch for tweaks, minor for features),
   measured against `origin/main` at the time. If main moved and
   bumped too, rebase and bump again from main's version, so two PRs never
   ship the same number.
2. Run the secrets scan from `update-bod` (the repo is public).
3. Commit with explicit paths, a short imperative message, `Fixes #<n>`, and
   the session's Co-Authored-By line.
4. Measure the size while the branch exists:
   `git diff --shortstat origin/main...HEAD`, reported as
   `Size: 4 files changed, +120 / −18 lines` with no commentary.
5. On `risk:medium`, `risk:high` or unlabeled, run the automated review
   before pushing, pinned so leftover settings don't change it:
   `/code-review low --max-findings default origin/main...HEAD`. Mention only
   something that breaks a feature, blocks her prompts, loses state or leaks
   a secret; fix nothing on your own.
6. Push the branch and open a PR in `Hnarowski13/claude-bod` with "Closes
   #<n>" in the body. Don't ask first; that's the standing rule.

**`risk:medium`, `risk:high`, unlabeled:** stop. Hand back with what changed
in terms she'll notice, what verification ran, how complex it was (one line
if simple; name what makes it tricky if not), the `Size:` line and the PR
link. Tell her how to try it before merging, in a new terminal tab:

```bash
claude --plugin-dir ~/Projects/claude-bod/.claude/worktrees/issue-<n>-<slug>
```

then `python3 ~/Projects/claude-bod/.claude/worktrees/issue-<n>-<slug>/scripts/bod.py show <plank|move|stand|kind>`
for anything on screen. Turn the tab blue (`... ticket-tab-color ready`) and
leave the worktree in place. Changes she asks for go to the same PR without
asking; put the risk color back while working.

**`risk:low`:** once the PR is open, merge it and delete the branch as two
separate commands (`--delete-branch` fails from a worktree because `main` is
checked out in the main folder):

```bash
gh pr merge <pr> --repo Hnarowski13/claude-bod --squash
gh pr view <pr> --repo Hnarowski13/claude-bod --json state --jq .state   # must print MERGED
git push origin --delete <branch>
```

If verification failed or the work went past the ticket's scope, fall back to
the review path instead, whatever the label. When she reviews a PR and says
merge, do the same and continue to step 6.

## 6. After merge: clean up and sync the installed copy

Do all of this yourself:

1. `~/Projects/new-goats/bin/ticket-tab-color merged` (before removing the
   worktree).
2. Remove the worktree: `ExitWorktree` with `action: "remove"` and
   `discard_changes: true` (the squash put the commits in main under another
   SHA). For one made by hand: `git -C ~/Projects/claude-bod worktree remove
   .claude/worktrees/issue-<n>-<slug>` and delete its local branch.
3. Bring the main checkout, and so her installed plugin, up to date:
   ```bash
   git -C ~/Projects/claude-bod pull --ff-only origin main
   claude plugin list --json | jq -r '.[] | select(.id=="bod@bod") | .folderVersion'
   ```
   The version printed must be the one this PR bumped to. If the pull
   refuses (the folder isn't on `main`, or has local changes), stop and tell
   her what's there; don't stash or reset it.
4. Tell her in one line to run `/reload-plugins` in the Claudes she has open
   (new ones pick it up on their own).

## 7. Report the merge

Recap in a few lines with the `Size:` line, then a verdict as the very last
line. If nothing needs her:

```
IM MERGED!!!!! close me!!
```

If something does (a check only she can do, a decision that's hers, a bug you
found and didn't ticket):

```
IM MERGED!!!!! here's follow ups:
- <what to do, most important first>
```

Leave out FYIs and housekeeping. Only say `IM MERGED` once `gh pr view`
shows `MERGED` and step 6 printed the new version.
