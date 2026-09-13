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
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources.json"
OUT = ROOT / "devices.json"
OFFLINE = "--offline" in sys.argv
UA = "Mozilla/5.0 (compatible; FirmwarelyBot/1.0; +https://firmwarely.com)"
TODAY = datetime.now(timezone.utc).date()
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

SECURITY = re.compile(
    r"security|vulnerab|cve-\d|exploit|unauthori[sz]ed|remote code|authentication bypass|"
    r"privilege escalation|patch(?:es|ed)? (?:a|an|the) (?:flaw|issue|vulnerab)|hardening",
    re.I,
)
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
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%Y-%m-%d"):
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


def check_html(src, prev):
    raw = get(src["url"])
    # search the raw HTML first, then a tag-stripped copy (handles "Version:</b> 1.2.3")
    page = raw if re.search(src["version_regex"], raw) else re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", raw)))
    v = extract_version(page, src["version_regex"])
    if not v:
        raise ValueError("version pattern not found on page")
    changed = not prev or prev.get("version") != v
    released = None
    if src.get("date_regex"):
        m = re.search(src["date_regex"], page)
        released = parse_date(m.group(1)) if m else None
    if not released:
        released = TODAY.isoformat() if changed else prev.get("released")
    return {
        "version": v,
        "released": released,
        "notes": src.get("notes", ""),
        "source_url": src["url"],
    }


def classify(dev):
    if not dev.get("version") or not dev.get("released"):
        return "pending"
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
                res = check_feed(src) if src["type"] == "feed" else check_html(src, prev)
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

        dev["status"] = classify(dev)
        out.append(dev)

    result = {"generated": NOW, "tracked": sum(1 for d in out if d["tracked"]),
              "ok": ok, "failed": failed, "devices": out}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT.name}: {len(out)} devices, {ok} fetched, {len(failed)} failed")


if __name__ == "__main__":
    main()

