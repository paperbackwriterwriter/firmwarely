#!/usr/bin/env python3
"""
Firmwarely nightly fetcher.

Reads sources.json, checks each tracked device's release source, and writes
devices.json for the site. Standard library only — no pip install needed.

  python3 scripts/fetch.py            # normal run
  python3 scripts/fetch.py --offline  # skip network, just (re)build devices.json from what's known

Rules:
- A failed fetch never erases data. The device keeps its last known version and
  gets source_status = "error" with the reason.
- For HTML sources with no date on the page, the release date is the day we first
  saw the new version.
- status: critical = security-flavoured release in the last 60 days,
          update   = any release in the last 45 days,
          current  = older than that,
          pending  = not tracked yet / never fetched successfully.
"""
import json, re, sys, html, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources.json"
OUT = ROOT / "devices.json"
OFFLINE = "--offline" in sys.argv
FORCE_DIGEST = "--force-digest" in sys.argv   # write a digest of every tracked device even if nothing changed
DIGEST = ROOT / "digest.md"
UA = "Mozilla/5.0 (compatible; FirmwarelyBot/1.0; +https://firmwarely.com)"
TODAY = datetime.now(ZoneInfo("America/Chicago")).date()   # dates in the site/digest are US Central
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

SECURITY = re.compile(
    r"security|vulnerab|cve-\d|exploit|unauthori[sz]ed|remote code|authentication bypass|"
    r"privilege escalation|patch(?:es|ed)? (?:a|an|the) (?:flaw|issue|vulnerab)|hardening",
    re.I,
)
EOL = re.compile(r"end[- ]of[- ]life|\bEOL\b|no longer (?:be )?(?:updated|supported|maintained)|discontinued", re.I)
DEFAULT_VERSION = re.compile(r"(\d+(?:\.\d+)+(?:[-_]\w+)*)")
# feed items whose title matches this are skipped unless the source sets its own skip_match
DEFAULT_SKIP = r"\b(rc\d*|beta|alpha|dev|nightly|pre-?release|release candidate|early access)\b"
TAG = re.compile(r"<[^>]+>")

_cache = {}


def get(url):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read().decode("utf-8", "replace")
    _cache[url] = data
    return data


def clean(text, limit=300):
    text = html.unescape(TAG.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed(xml_text):
    """Return list of {title, link, date, body} from RSS or Atom, newest first."""
    root = ET.fromstring(xml_text)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        it = {"title": "", "link": "", "date": None, "body": ""}
        for c in el:
            t = local(c.tag)
            if t == "title":
                it["title"] = (c.text or "").strip()
            elif t == "link":
                it["link"] = c.get("href") or (c.text or "").strip()
            elif t in ("pubDate", "published", "updated") and not it["date"]:
                it["date"] = parse_date(c.text)
            elif t in ("description", "content", "summary") and not it["body"]:
                it["body"] = c.text or ""
        items.append(it)
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return items


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        pass
    for fmt in ("%m/%d/%Y", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%b. %d, %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    return None


def extract_version(text, pattern):
    m = re.search(pattern, text) if pattern else DEFAULT_VERSION.search(text)
    return m.group(1) if m else None


def check_feed(src):
    items = parse_feed(get(src["url"]))
    match = re.compile(src["item_match"], re.I) if src.get("item_match") else None
    skip_pat = src.get("skip_match", DEFAULT_SKIP)
    skip = re.compile(skip_pat, re.I) if skip_pat else None
    for it in items:
        if match and not match.search(it["title"]):
            continue
        if skip and skip.search(it["title"]):
            continue
        v = extract_version(it["title"], src.get("version_regex"))
        if not v:
            continue
        return {
            "version": v,
            "released": it["date"] or TODAY.isoformat(),
            "notes": clean(it["body"]) or clean(it["title"]),
            "source_url": it["link"] or src["url"],
        }
    raise ValueError("no matching item in feed")


def check_github(src):
    """Latest non-prerelease via the GitHub API. src['repo'] = 'owner/name'."""
    api = f"https://api.github.com/repos/{src['repo']}/releases/latest"
    req = urllib.request.Request(api, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.loads(r.read().decode("utf-8"))
    title = f"{rel.get('name') or ''} {rel.get('tag_name') or ''}"
    v = extract_version(title, src.get("version_regex"))
    if not v:
        raise ValueError(f"no version in release title/tag: {title.strip()}")
    return {
        "version": v,
        "released": parse_date(rel.get("published_at")) or TODAY.isoformat(),
        "notes": clean(rel.get("body") or "") or clean(title),
        "source_url": rel.get("html_url") or f"https://github.com/{src['repo']}/releases",
    }


def check_html(src, prev):
    raw = get(src["url"])
    # work on a tag-stripped copy so "Version:</b> 1.2.3" and multi-line layouts match; fall back to raw
    text = re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", raw)))
    page = text if re.search(src["version_regex"], text) else raw
    v = extract_version(page, src["version_regex"])
    if not v:
        raise ValueError("version pattern not found on page")
    changed = not prev or prev.get("version") != v
    released = None
    anchor = re.escape(v)  # "{version}" in date_regex / notes_regex is replaced with the matched version
    if src.get("date_regex"):
        m = re.search(src["date_regex"].replace("{version}", anchor), page, re.S)
        released = parse_date(m.group(1)) if m else None
    if not released:
        released = TODAY.isoformat() if changed else prev.get("released")
    notes = src.get("notes", "")
    if src.get("notes_regex"):
        m = re.search(src["notes_regex"].replace("{version}", anchor), page, re.S)
        if m:
            notes = clean(m.group(1))
    return {
        "version": v,
        "released": released,
        "notes": notes,
        "source_url": src.get("page_url") or src["url"],
    }


def classify(dev):
    if not dev.get("version") or not dev.get("released"):
        return "pending"
    if dev.get("eol"):
        return "eol"
    try:
        age = (TODAY - datetime.fromisoformat(dev["released"]).date()).days
    except Exception:
        return "current"
    text = f"{dev.get('notes','')} {dev.get('version','')}"
    if age <= 60 and SECURITY.search(text):
        return "critical"
    if age <= 45:
        return "update"
    return "current"


def main():
    cfg = json.loads(SOURCES.read_text())
    previous = {}
    if OUT.exists():
        try:
            previous = {d["id"]: d for d in json.loads(OUT.read_text()).get("devices", [])}
        except Exception:
            previous = {}

    out, ok, failed = [], 0, []
    for src in cfg["devices"]:
        prev = previous.get(src["id"], {})
        dev = {
            "id": src["id"], "brand": src["brand"], "model": src["model"], "category": src["category"],
            "tracked": src["type"] != "manual",
            "version": prev.get("version"), "released": prev.get("released"),
            "notes": prev.get("notes", ""), "source_url": prev.get("source_url") or src.get("url"),
            "product_url": src.get("product_url"),
            "history": prev.get("history", []),
            "checked": prev.get("checked"), "source_status": prev.get("source_status", "pending"),
        }

        if dev["tracked"] and not OFFLINE:
            try:
                if src["type"] == "feed":
                    res = check_feed(src)
                elif src["type"] == "github":
                    res = check_github(src)
                else:
                    res = check_html(src, prev)
                if res["version"] != dev["version"]:
                    dev["history"] = ([{"version": res["version"], "released": res["released"]}] + dev["history"])[:6]
                dev.update(res)
                dev["checked"] = NOW
                dev["source_status"] = "ok"
                ok += 1
                print(f"  ok   {src['id']:40s} {res['version']}  ({res['released']})")
            except Exception as e:
                dev["checked"] = NOW
                dev["source_status"] = f"error: {type(e).__name__}: {str(e)[:120]}"
                failed.append(src["id"])
                print(f"  FAIL {src['id']:40s} {dev['source_status']}")
            time.sleep(0.5)

        dev["eol"] = bool(EOL.search(dev.get("notes") or ""))
        dev["status"] = classify(dev)
        out.append(dev)

    result = {"generated": NOW, "tracked": sum(1 for d in out if d["tracked"]),
              "ok": ok, "failed": failed, "devices": out}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT.name}: {len(out)} devices, {ok} fetched, {len(failed)} failed")

    # ---- what changed since last night → digest.md (+ optional Beehiiv draft) ----
    changed = [d for d in out if d["tracked"] and d.get("version")
               and (FORCE_DIGEST or d["version"] != previous.get(d["id"], {}).get("version"))]
    if DIGEST.exists():
        DIGEST.unlink()
    if changed:
        md, html_body = build_digest(changed)
        DIGEST.write_text(md)
        print(f"digest: {len(changed)} change(s) → {DIGEST.name}")
        beehiiv_draft(md.splitlines()[0].lstrip("# ").strip(), html_body)
    else:
        print("digest: no changes since last run")


def build_digest(changed):
    date = TODAY.strftime("%b %-d, %Y")
    groups = {"critical": [], "update": [], "current": [], "eol": []}
    for d in changed:
        groups.setdefault(d["status"], []).append(d)
    order = [("critical", "Security fixes — update now"), ("update", "New firmware"),
             ("current", "Also released"), ("eol", "End of life notices")]
    md = [f"# Firmware digest — {date}", ""]
    html_parts = []
    for key, heading in order:
        items = groups.get(key) or []
        if not items:
            continue
        md += [f"## {heading}", ""]
        html_parts.append(f"<h2>{heading}</h2><ul>")
        for d in items:
            name = f"{d['brand']} {d['model']}"
            when = d.get("released") or ""
            note = (d.get("notes") or "").strip()
            note = note[:220] + "…" if len(note) > 220 else note
            md.append(f"- **{name}** → `{d['version']}` ({when}) — {note} [notes]({d['source_url']})")
            html_parts.append(f"<li><strong>{html.escape(name)}</strong> → <code>{html.escape(d['version'])}</code> ({when})"
                              f" — {html.escape(note)} <a href=\"{html.escape(d['source_url'])}\">release notes</a></li>")
        md.append("")
        html_parts.append("</ul>")
    md += ["---", "Tracked by [Firmwarely](https://firmwarely.com). Reply to this email to request a device.", ""]
    html_parts.append('<p>Tracked by <a href="https://firmwarely.com">Firmwarely</a>. Reply to this email to request a device.</p>')
    return "\n".join(md), "".join(html_parts)


def beehiiv_draft(title, html_body):
    """Create a DRAFT post in Beehiiv so it can be reviewed and sent by hand. Needs BEEHIIV_API_KEY and BEEHIIV_PUB_ID."""
    import os
    key, pub = os.environ.get("BEEHIIV_API_KEY"), os.environ.get("BEEHIIV_PUB_ID")
    if not (key and pub):
        print("beehiiv: no API key/pub id in environment, skipping draft")
        return
    payload = {"title": title, "subtitle": "What changed on the devices you own",
               "status": "draft", "body_content": html_body, "content_tags": ["digest"]}
    req = urllib.request.Request(f"https://api.beehiiv.com/v2/publications/{pub}/posts",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
            print(f"beehiiv: draft created — {body.get('data', {}).get('web_url') or body.get('data', {}).get('id')}")
    except urllib.error.HTTPError as e:
        print(f"beehiiv: draft FAILED {e.code}: {e.read().decode()[:300]}")
    except Exception as e:
        print(f"beehiiv: draft FAILED: {e}")


if __name__ == "__main__":
    main()
