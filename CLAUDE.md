# Claude Bod

Helena's wellness plugin, `bod`. See README.md for what it does.

## Workflow

- Every change is a ticket (issue in `Hnarowski13/claude-bod`), and every ticket ships through a PR. Never push straight to `main`.
- Filing tickets: `.claude/skills/ticket-creator`. Working one ("pu <n>"): `.claude/skills/pick-up-ticket`. Where things live and how to test: `.claude/skills/update-bod`.
- Her installed `bod` runs live from this folder, so never edit it directly: work in `.claude/worktrees/`. After a merge, `git pull --ff-only origin main` here is what puts the change in her Claudes (then `/reload-plugins`).
