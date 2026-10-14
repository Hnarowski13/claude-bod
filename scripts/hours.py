"""Timestamps of Claude activity, from Claude Code's session transcripts
(~/.claude/projects/*/*.jsonl), where every line is timestamped. Every project,
session and worktree is merged into one timeline: the point is how long you've
been at it today, not on what.

A stretch counts as worked when the gap to the previous event is at most
GAP_MINUTES. It's an estimate: it misses work done away from Claude and
includes time Claude was busy while nobody was at the keyboard.
"""
import glob
import json
import os
from datetime import datetime

GAP_MINUTES = 30


def timestamps(cutoff):
    root = os.path.expanduser("~/.claude/projects")
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        if datetime.fromtimestamp(os.path.getmtime(path)).astimezone() < cutoff:
            continue
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    ts = json.loads(line).get("timestamp")
                    when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                except (ValueError, AttributeError):
                    continue
                if when >= cutoff:
                    yield when
