#!/usr/bin/env python3
"""
Send the subscriber emails to one address, to see them as subscribers will.

Builds both kinds from this week's real changes so far (weekly_changes.json plus
pending_changes.json, read only; nothing is drained or committed):
  - the weekly digest someone with no saved devices gets on Monday
  - a personal alert, as for someone who saved three of this week's devices
and sends each to the given address with "[TEST]" in the subject. Nobody else is mailed.
Early in a week there may be only one kind of change, so the most recent catalogue
releases of any missing kind (security fix, other release, end of life) are added, up to
three each, so every status color shows.

    python3 scripts/send_test.py you@example.com

Used by .github/workflows/send-test-email.yml (needs RESEND_API_KEY).
"""
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest
import fetch
import user_alerts as ua


def this_week():
    _, payload, _, _ = digest.build(fetch.load_pending())
    weekly, _ = digest.roll_week(digest.load_weekly(), payload, fetch.TODAY.isoformat(), True)
    return (weekly or {}).get("devices", [])


def with_every_status(changes, per_status=3):
    """This week's changes, plus recent catalogue releases of any status they lack."""
    import json
    have = {"current" if c.get("status") == "stale" else c.get("status") for c in changes}
    devices = json.loads(fetch.OUT.read_text())["devices"]
    recent = sorted((d for d in devices if d.get("version") and d.get("released")),
                    key=lambda d: d["released"], reverse=True)
    extra = []
    for status in ("critical", "update", "current", "eol"):
        if status not in have:
            extra += [fetch.change_record(d, {}) for d in recent if d.get("status") == status][:per_status]
    return fetch.sort_changes(changes + extra)


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", sys.argv[1]):
        print(__doc__)
        return 2
    to = sys.argv[1]
    changes = with_every_status(this_week())
    if not changes:
        print("nothing has changed yet this week; no test email to build")
        return 1
    # a personal alert shows one of each kind when the week has them: security first
    picks = []
    for status in ("critical", "eol", "update", "current"):
        picks += [c for c in changes if c.get("status") == status and c not in picks][:1]
    hits = [{"change": c, "yours": ""} for c in picks[:3]]
    emails = [("[TEST] " + ua.digest_subject(fetch.TODAY.isoformat(), True), ua.render_digest(changes, True)),
              ("[TEST] " + ua.subject_for(hits, True), ua.render(hits, True))]
    failed = 0
    for subject, body in emails:
        ok, err = ua.send(to, subject, body)
        print(f"{'sent' if ok else 'FAIL'}  {subject}" + ("" if ok else f": {err}"))
        failed += not ok
    print(f"{len(changes)} change(s) this week")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
