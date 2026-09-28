#!/usr/bin/env python3
"""
Rebuild a weekly email that went out wrong, from the repo's own history.

The weekly run turns weekly_changes.json (the week so far) plus that morning's
pending_changes.json into changed_weekly.json, then empties the week. Both files are
committed by every hourly run, so the state just before a given daily run is still in git.
This writes changed_weekly.json from that state for scripts/user_alerts.py, and touches
nothing that is committed.

    python3 scripts/rebuild_week.py <commit before the daily run> <the daily run's commit> [YYYY-MM-DD]

The second commit adds what the daily run itself found (it checks every source again
before building the digest): each device whose version differs between the two.

Used by .github/workflows/resend-weekly.yml.
"""
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest
import fetch


def at(commit, path):
    out = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    commit, after = sys.argv[1], sys.argv[2]
    day = sys.argv[3] if len(sys.argv) > 3 else fetch.TODAY.isoformat()
    week, pending = at(commit, "weekly_changes.json"), at(commit, "pending_changes.json")
    before = {d["id"]: d for d in at(commit, "devices.json")["devices"]}
    for d in at(after, "devices.json")["devices"]:
        prev = before.get(d["id"])
        if prev and d.get("version") and d.get("version") != prev.get("version"):
            pending["devices"][d["id"]] = fetch.change_record(d, before)
    _, payload, _, _ = digest.build(pending)
    weekly, _ = digest.roll_week(week, payload, day, True)
    if not weekly:
        print(f"nothing collected as of {commit}; no weekly email to rebuild")
        return 1
    fetch.CHANGED_WEEKLY.write_text(json.dumps(weekly, indent=1, ensure_ascii=False) + "\n")
    print(f"changed_weekly.json: {weekly['count']} change(s) since {weekly['since']} (state at {commit}..{after})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
