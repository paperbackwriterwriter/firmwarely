#!/usr/bin/env python3
"""
Once a day: turn the changes collected by the hourly checks into the digest.

Reads pending_changes.json (fetch.py appends to it on every run), writes
  digest.md     the GitHub issue body (names, versions, dates; no links, so it can't ping anyone)
  changed.json  the payload scripts/user_alerts.py mails from
creates the Beehiiv draft, then empties the pending set and marks today as done.

    python3 scripts/digest.py            # normal daily run
    python3 scripts/digest.py --dry-run  # print what would be sent, touch nothing

Devices added by discover.py in the same run are listed at the bottom of the issue.
"""
import json, sys
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


def main():
    pending = fetch.load_pending()
    discovered = json.loads(DISCOVERED.read_text()) if DISCOVERED.exists() else None
    issue, payload, title, html_body = build(pending, discovered)

    for f in (fetch.DIGEST, fetch.CHANGED):
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

    if not DRY_RUN:
        fetch.PENDING.write_text(json.dumps({"since": None, "forced": False, "devices": {}}, indent=1) + "\n")
        schedule.mark_daily()
    return 0


if __name__ == "__main__":
    sys.exit(main())
