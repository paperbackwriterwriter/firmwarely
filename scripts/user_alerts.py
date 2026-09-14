#!/usr/bin/env python3
"""
Firmwarely per-user alerts.

Reads changed.json (written by scripts/fetch.py only when something actually changed)
and emails each subscriber about the devices *they* saved on /my-devices.html — and
nothing else. Standard library only, same as the rest of the pipeline.

  python3 scripts/user_alerts.py             # send
  python3 scripts/user_alerts.py --dry-run   # print who would get what, send nothing

A subscriber is mailed when all of these hold:
- their plan is in USER_ALERT_PLANS (default "pro" — free accounts get the weekly digest),
- their Beehiiv subscription is active,
- they saved a device that moved tonight,
- and the version they recorded is older than the one we just found. Someone already on
  tonight's version, or ahead of it, is left alone. A blank version still gets the alert.

Env:
  BEEHIIV_API_KEY, BEEHIIV_PUB_ID   read the subscriber list and their saved devices
  RESEND_API_KEY                    send the mail (same provider as the sign-in links)
  RESEND_FROM                       From: header (default matches lib/fw.js)
  SITE_URL                          default https://firmwarely.com
  USER_ALERT_PLANS                  comma list of plans to mail, or "all" (default "pro")
  USER_ALERT_TEST_EMAIL             send every alert to this address instead of the
                                    subscriber, and prefix the subject with [TEST]
  USER_ALERT_MAX                    stop after this many emails (default 500)

Safety: a forced run (fetch.py --force-digest) marks every tracked device as changed, so
it refuses to mail real subscribers unless USER_ALERT_TEST_EMAIL is set.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGED = ROOT / "changed.json"
UA = "Mozilla/5.0 (compatible; FirmwarelyBot/1.0; +https://firmwarely.com)"
BEEHIIV = "https://api.beehiiv.com/v2/publications/"
RESEND = "https://api.resend.com/emails"
PAGE_SIZE = 100
MAX_PAGES = 100          # 10k subscribers; a runaway loop stops here
SEND_GAP = 0.6           # seconds between sends, to stay under Resend's rate limit

DRY_RUN = "--dry-run" in sys.argv
SITE = (os.environ.get("SITE_URL") or "https://firmwarely.com").rstrip("/")
FROM = os.environ.get("RESEND_FROM") or "Firmwarely <onboarding@resend.dev>"
TEST_TO = (os.environ.get("USER_ALERT_TEST_EMAIL") or "").strip()
MAX_EMAILS = int(os.environ.get("USER_ALERT_MAX") or 500)
PLANS = [p.strip().lower() for p in (os.environ.get("USER_ALERT_PLANS") or "pro").split(",") if p.strip()]


# ---------- version comparison (mirrors norm/compare in my-devices.html) ----------

def norm(v):
    return re.sub(r"^v(?=\d)", "", str(v or "").strip().lower())


def parts(v):
    return [p for p in re.split(r"[^0-9a-z]+", norm(v)) if p]


def compare(a, b):
    """-1 if a < b, 0 if equal, 1 if a > b, None if either side is blank."""
    if not norm(a) or not norm(b):
        return None
    if norm(a) == norm(b):
        return 0
    pa, pb = parts(a), parts(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else "0"
        y = pb[i] if i < len(pb) else "0"
        if x.isdigit() and y.isdigit():
            if int(x) != int(y):
                return -1 if int(x) < int(y) else 1
        elif x != y:
            return -1 if x < y else 1
    return 0


# ---------- Beehiiv ----------

def api(url, key, tries=3):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + key, "Accept": "application/json", "User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise ValueError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        except Exception:
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    return None


def subscribers(key, pub):
    """Every active subscriber with their custom fields. Yields raw Beehiiv records."""
    base = BEEHIIV + pub + "/subscriptions"
    expand = "expand[]=custom_fields"   # the list endpoint's documented form
    page = 1
    while page <= MAX_PAGES:
        url = f"{base}?{expand}&status=active&limit={PAGE_SIZE}&page={page}"
        body = api(url, key) or {}
        rows = body.get("data") or []
        # Older accounts answer the singular form; if nothing came back expanded, ask again.
        if page == 1 and rows and not any("custom_fields" in s for s in rows):
            expand = "expand=custom_fields"
            body = api(f"{base}?{expand}&status=active&limit={PAGE_SIZE}&page={page}", key) or {}
            rows = body.get("data") or []
        for s in rows:
            yield s
        total = body.get("total_pages")
        if not rows or (total and page >= total) or len(rows) < PAGE_SIZE:
            return
        page += 1


def fields(sub):
    return {f.get("name"): f.get("value") for f in (sub.get("custom_fields") or []) if f.get("name")}


def saved_devices(value):
    """The `devices` custom field written by /api/me — [["id","ver"],...] or [{id,version}]."""
    out = []
    try:
        parsed = json.loads(value or "[]")
    except Exception:
        return out
    if not isinstance(parsed, list):
        return out
    for d in parsed:
        if isinstance(d, list) and d:
            out.append({"id": str(d[0]), "version": str(d[1] if len(d) > 1 and d[1] else "")})
        elif isinstance(d, dict) and d.get("id"):
            out.append({"id": str(d["id"]), "version": str(d.get("version") or "")})
    return out


# ---------- the email ----------

def subject_for(hits):
    one = len(hits) == 1
    what = (f"your {hits[0]['change']['brand']} {hits[0]['change']['model']}" if one
            else f"{len(hits)} of your devices")
    if any(h["change"]["status"] == "critical" for h in hits):
        return f"Security fix{'' if one else 'es'} for {what}"
    if all(h["change"].get("eol") for h in hits):
        return f"End-of-life notice{'' if one else 's'} for {what}"
    return f"New firmware for {what}"


def render(hits):
    rows = []
    for h in hits:
        c, yours = h["change"], h["yours"]
        name = html.escape(f"{c['brand']} {c['model']}")
        flag = ("🔴 Security fix" if c["status"] == "critical"
                else "⚫ End of life" if c.get("eol") else "🟡 Update")
        line = (f"<strong>{name}</strong> — {flag}<br>"
                f"Latest: <code>{html.escape(c['version'])}</code>")
        if c.get("released"):
            line += f" ({html.escape(c['released'])})"
        line += "<br>You have: " + (f"<code>{html.escape(yours)}</code>" if yours
                                    else "<em>no version recorded</em>")
        note = (c.get("notes") or "").strip()
        if note:
            note = note[:220] + "…" if len(note) > 220 else note
            line += f'<br><span style="color:#555">{html.escape(note)}</span>'
        links = [f'<a href="{html.escape(c["page_url"])}">device page</a>']
        if c.get("source_url"):
            links.append(f'<a href="{html.escape(c["source_url"])}">release notes</a>')
        line += '<br><span style="font-size:14px">' + " · ".join(links) + "</span>"
        rows.append(f'<li style="margin:0 0 18px">{line}</li>')

    n = len(hits)
    return (
        '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:16px;'
        'line-height:1.5;color:#111;max-width:600px">'
        f"<p>Here's what changed on {'a device' if n == 1 else f'{n} devices'} you track "
        "on Firmwarely.</p>"
        '<ul style="padding-left:18px">' + "".join(rows) + "</ul>"
        '<p style="color:#666;font-size:14px">You are getting this because you saved these '
        f'devices on <a href="{html.escape(SITE)}/my-devices.html">My devices</a>. '
        "Add, remove or update them there any time.</p></div>"
    )


def send(to, subject, body):
    payload = {"from": FROM, "to": [to], "subject": subject, "html": body,
               "headers": {"List-Unsubscribe": f"<{SITE}/my-devices.html>"}}
    req = urllib.request.Request(
        RESEND, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + os.environ["RESEND_API_KEY"],
                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            json.loads(r.read().decode("utf-8", "replace"))
        return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------- run ----------

def main():
    if not CHANGED.exists():
        print("No changed.json — nothing changed tonight, no per-user alerts.")
        return 0

    data = json.loads(CHANGED.read_text())
    changes = {c["id"]: c for c in data.get("devices", []) if c.get("id") and c.get("version")}
    if not changes:
        print("changed.json is empty — no per-user alerts.")
        return 0
    if data.get("forced") and not TEST_TO:
        print("changed.json is from a forced run (every device looks changed). "
              "Set USER_ALERT_TEST_EMAIL to send it somewhere safe. Skipping.")
        return 0

    key, pub = os.environ.get("BEEHIIV_API_KEY"), os.environ.get("BEEHIIV_PUB_ID")
    if not (key and pub):
        print("No BEEHIIV_API_KEY/BEEHIIV_PUB_ID — per-user alerts not configured, skipping.")
        return 0
    if not (DRY_RUN or os.environ.get("RESEND_API_KEY")):
        print("No RESEND_API_KEY — per-user alerts not configured, skipping.")
        return 0

    print(f"{len(changes)} device(s) changed; mailing plans: {', '.join(PLANS)}"
          + (f"; TEST → {TEST_TO}" if TEST_TO else "")
          + ("; DRY RUN" if DRY_RUN else ""))

    seen = sent = skipped = failed = 0
    try:
        people = list(subscribers(key, pub))
    except Exception as e:
        print(f"Couldn't read the subscriber list: {e}", file=sys.stderr)
        return 1

    for sub in people:
        seen += 1
        email = str(sub.get("email") or "").strip().lower()
        if not email:
            continue
        f = fields(sub)
        plan = (f.get("plan") or "free").strip().lower()
        if "all" not in PLANS and plan not in PLANS:
            continue

        hits = []
        for d in saved_devices(f.get("devices")):
            c = changes.get(d["id"])
            if not c:
                continue
            # already on tonight's version (or ahead of it) → nothing to tell them
            if compare(d["version"], c["version"]) in (0, 1):
                continue
            hits.append({"change": c, "yours": d["version"]})
        if not hits:
            continue

        hits.sort(key=lambda h: (h["change"]["status"] != "critical",
                                 h["change"]["brand"], h["change"]["model"]))
        subject = subject_for(hits)
        to = TEST_TO or email
        if TEST_TO:
            subject = "[TEST] " + subject

        if sent >= MAX_EMAILS:
            skipped += 1
            continue
        names = ", ".join(f"{h['change']['brand']} {h['change']['model']}" for h in hits)
        if DRY_RUN:
            print(f"  would mail {to:40s} {len(hits)} device(s): {names}")
            sent += 1
            continue
        ok, err = send(to, subject, render(hits))
        if ok:
            sent += 1
            print(f"  sent  {to:40s} {len(hits)} device(s): {names}")
        else:
            failed += 1
            print(f"  FAIL  {to:40s} {err}", file=sys.stderr)
        time.sleep(SEND_GAP)

    verb = "would send" if DRY_RUN else "sent"
    print(f"\n{seen} subscriber(s) checked, {verb} {sent} email(s), {failed} failed"
          + (f", {skipped} over the {MAX_EMAILS} cap" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
