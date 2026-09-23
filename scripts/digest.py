#!/usr/bin/env python3
"""
Once a day: turn the changes collected by the hourly checks into the digest.

Reads pending_changes.json (fetch.py appends to it on every run), writes
  digest.md     the GitHub issue body (names, versions, dates; no links, so it can't ping anyone)
  changed.json  the payload scripts/user_alerts.py mails Pro accounts from
creates the Beehiiv draft, then empties the pending set and marks today as done.

Free accounts are mailed once a week. Each day's changes are also added to
weekly_changes.json (committed); on the weekly day (schedule.WEEKLY_DAY, or
FORCE_WEEKLY=true) that set becomes changed_weekly.json for user_alerts.py and is emptied.

    python3 scripts/digest.py            # normal daily run
    python3 scripts/digest.py --dry-run  # print what would be sent, touch nothing

Devices added by discover.py in the same run are listed at the bottom of the issue.
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch
import schedule

ROOT = Path(__file__).resolve().parent.parent
DISCOVERED = ROOT / "discovered.json"
DRY_RUN = "--dry-run" in sys.argv
CATS = {"R": "Routers & networking", "N": "NAS & storage", "S": "Smart home & cameras",
        "C": "Consoles, drones & e-bikes", "M": "Makers & open firmware",
        "P": "PCs, TVs & gadgets", "A": "Self-hosted apps & servers"}


def added_section(discovered):
    """Plain lines for the issue about what discover.py added today."""
    added = (discovered or {}).get("added") or []
    if not added:
        return ""
    lines = ["", f"## New devices added today ({len(added)})", ""]
    for a in added:
        lines.append(f"- {fetch.full_name(a)} — {CATS.get(a.get('category'), a.get('category'))}")
    lines.append("")
    return "\n".join(lines)


def build(pending, discovered=None):
    """(issue markdown, changed.json payload dict, beehiiv title, beehiiv html) from the pending set."""
    items = fetch.sort_changes(list(pending.get("devices", {}).values()))
    forced = bool(pending.get("forced"))
    if not items:
        return None, None, None, None
    md, html_body = fetch.build_digest(items)
    issue = fetch.build_issue_summary(items) + added_section(discovered)
    payload = {"generated": fetch.NOW, "date": fetch.TODAY.isoformat(), "forced": forced,
               "count": len(items), "devices": items}
    return issue, payload, md.splitlines()[0].lstrip("# ").strip(), html_body


def load_weekly():
    try:
        week = json.loads(fetch.WEEKLY.read_text())
        if isinstance(week.get("devices"), dict):
            return week
    except Exception:
        pass
    return {"since": None, "devices": {}}


def roll_week(week, payload, today, weekly_day):
    """Add today's changes to the week. On the weekly day, return (payload for
    changed_weekly.json or None, emptied week); otherwise (None, the grown week).
    A forced run's "everything changed" never joins the week."""
    week = {"since": week.get("since"), "devices": dict(week.get("devices") or {})}
    if payload and not payload.get("forced"):
        for c in payload["devices"]:
            week["devices"][c["id"]] = c   # a device that moved twice this week: the newest wins
        week["since"] = week["since"] or today
    if not weekly_day:
        return None, week
    items = fetch.sort_changes(list(week["devices"].values()))
    out = ({"generated": fetch.NOW, "date": today, "since": week["since"], "weekly": True,
            "forced": False, "count": len(items), "devices": items} if items else None)
    return out, {"since": None, "devices": {}}


def main():
    pending = fetch.load_pending()
    discovered = json.loads(DISCOVERED.read_text()) if DISCOVERED.exists() else None
    issue, payload, title, html_body = build(pending, discovered)

    for f in (fetch.DIGEST, fetch.CHANGED, fetch.CHANGED_WEEKLY):
        if f.exists() and not DRY_RUN:
            f.unlink()

    if not issue:
        # nothing moved since yesterday; still worth telling the owner what was added
        added = added_section(discovered)
        if added and not DRY_RUN:
            fetch.DIGEST.write_text(f"# Firmware digest — {fetch.TODAY.strftime('%b %-d, %Y')}\n\nNo firmware changes since yesterday.\n" + added)
        print("digest: no changes pending" + (" (issue lists today's additions)" if added else ""))
    else:
        print(f"digest: {payload['count']} change(s) since {pending.get('since')}")
        if DRY_RUN:
            print(issue)
        else:
            fetch.DIGEST.write_text(issue)
            fetch.CHANGED.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
            fetch.beehiiv_draft(title, html_body)

    weekly_day = schedule.is_weekly_day(force=os.environ.get("FORCE_WEEKLY", "").lower() == "true")
    weekly, week = roll_week(load_weekly(), payload, fetch.TODAY.isoformat(), weekly_day)
    if weekly:
        print(f"weekly: {weekly['count']} change(s) since {weekly['since']} for free accounts")
    if not DRY_RUN:
        if weekly:
            fetch.CHANGED_WEEKLY.write_text(json.dumps(weekly, indent=1, ensure_ascii=False) + "\n")
        fetch.WEEKLY.write_text(json.dumps(week, indent=1, ensure_ascii=False) + "\n")
        fetch.PENDING.write_text(json.dumps({"since": None, "forced": False, "devices": {}}, indent=1) + "\n")
        schedule.mark_daily()
        if weekly_day:
            schedule.mark_weekly()
    return 0


if __name__ == "__main__":
    sys.exit(main())
