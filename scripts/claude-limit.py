#!/usr/bin/env python3
"""Cap how many interactive Claude sessions can be in use at once.

UserPromptSubmit hook. Live sessions are ranked oldest first; a session
outside the first `claudes` (a Claude Bod setting, `/bod claudes <n>`) gets its prompts refused until an older one closes.
Fails open: if anything goes wrong, the prompt goes through.
"""
import json
import os
import sys
from pathlib import Path

SESSIONS_DIR = Path.home() / ".claude" / "sessions"


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def live_sessions():
    sessions = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            s = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if s.get("kind", "interactive") != "interactive":
            continue
        pid = s.get("pid")
        if isinstance(pid, int) and alive(pid):
            sessions.append(s)
    return sorted(sessions, key=lambda s: s.get("startedAt", 0))


def main():
    try:
        from bod import load_settings
        limit = load_settings()["claudes"]
        my_id = json.load(sys.stdin).get("session_id")
        sessions = live_sessions()
        ids = [s.get("sessionId") for s in sessions]
        if my_id not in ids or ids.index(my_id) < limit:
            return
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"You have {len(sessions)} Claudes open — the limit is {limit}. "
                "Close one of the others, then send this again. Your mind will thank you."
            ),
        }))
    except Exception:
        return


if __name__ == "__main__":
    main()
