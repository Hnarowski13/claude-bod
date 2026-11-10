"""How many PRs she's merged today, for the status line's progress bar.

Counts her PRs merged since local midnight, in every repo, through `gh`.
A PR in one of HALF_WEIGHT_REPOS counts as half: Bod changes are small and
she tests them by using them, the same rule pick-up-ticket uses.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta

# Repos whose PRs count as half a PR.
HALF_WEIGHT_REPOS = {"claude-bod"}
# The gh command; tests point it somewhere that doesn't exist so they never
# reach GitHub.
GH = os.environ.get("BOD_GH") or "gh"
# Long enough for a slow network, short enough that a tick never hangs.
GH_TIMEOUT_SECONDS = 15


def weight(repo_name):
    return 0.5 if repo_name in HALF_WEIGHT_REPOS else 1


def count(prs, midnight):
    """Today's weighted count from `gh search prs` results."""
    return sum(
        weight(pr["repository"]["name"])
        for pr in prs
        if pr.get("closedAt") and parse(pr["closedAt"]) >= midnight
    )


def parse(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def merged_today(now):
    """Today's weighted count, or None when `gh` can't say (not installed,
    not logged in, offline): a missing bar beats a broken tick."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # `merged:>=` compares in UTC, so search from a day early and cut at
    # local midnight here.
    since = (midnight - timedelta(days=1)).date().isoformat()
    try:
        found = subprocess.run(
            [GH, "search", "prs", "--author", "@me", "--merged", "--limit", "100",
             "--json", "repository,closedAt", "--", f"merged:>={since}"],
            capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS,
        )
        if found.returncode != 0:
            return None
        return count(json.loads(found.stdout), midnight)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
