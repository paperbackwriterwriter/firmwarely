#!/usr/bin/env python3
"""
Decides whether this run is the once-a-day run.

The workflow polls every 30 minutes, but some work belongs to one run per day: rendering
browser-only vendor pages, discovering new projects, and sending the digest and the
per-user emails (Pro members are promised one email a day, not one per release).

    python3 scripts/schedule.py          # prints daily=true|false (for $GITHUB_OUTPUT)
    python3 scripts/schedule.py --mark   # record that today's daily run happened

The daily run is the first run at or after DAILY_HOUR_UTC whose date hasn't been marked
yet, so a delayed or skipped cron slot can't lose a day. FORCE_DAILY=true (a manual
dispatch) makes any run the daily one.
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "digest_state.json"
DAILY_HOUR_UTC = 8   # 3 AM Central, the old nightly slot


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def is_daily_due(now=None, state=None, force=False):
    now = now or datetime.now(timezone.utc)
    state = load_state() if state is None else state
    if force:
        return True
    return now.hour >= DAILY_HOUR_UTC and state.get("last_daily") != now.date().isoformat()


def mark_daily(now=None):
    now = now or datetime.now(timezone.utc)
    state = load_state()
    state["last_daily"] = now.date().isoformat()
    state["last_daily_at"] = now.replace(microsecond=0).isoformat()
    STATE.write_text(json.dumps(state, indent=1) + "\n")


if __name__ == "__main__":
    if "--mark" in sys.argv:
        mark_daily()
        print("marked")
    else:
        due = is_daily_due(force=os.environ.get("FORCE_DAILY", "").lower() == "true")
        print(f"daily={'true' if due else 'false'}")
