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
- type "browser" reads a page pre-rendered by scripts/fetch_browser.py from
  rendered/<id>.html and is otherwise identical to "html".
- status: critical = security-flavoured release in the last 60 days,
          update   = any release in the last 45 days,
          current  = older than that,
          pending  = not tracked yet / never fetched successfully.

When anything changed, two extra files are written next to devices.json and left for the
workflow to consume (neither is committed):
- digest.md    — the human summary that becomes the GitHub issue.
- changed.json — the same changes as data, for scripts/user_alerts.py to match against
                 the devices each subscriber saved on /my-devices.html.
Both are deleted at the start of every run, so their presence means "something changed".
"""
import json, os, re, sys, html, time, urllib.request, urllib.error
import concurrent.futures as cf
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources.json"
OUT = ROOT / "devices.json"
RENDERED = ROOT / "rendered"
OFFLINE = "--offline" in sys.argv
FORCE_DIGEST = "--force-digest" in sys.argv   # write a digest of every tracked device even if nothing changed
DIGEST = ROOT / "digest.md"
CHANGED = ROOT / "changed.json"   # machine-readable digest for scripts/user_alerts.py (written by digest.py)
PENDING = ROOT / "pending_changes.json"   # changes seen since the last daily digest; committed
WORKERS = 12   # parallel source checks; ~600 sources finish in about a minute
UA = "Mozilla/5.0 (compatible; FirmwarelyBot/1.0; +https://firmwarely.com)"
TODAY = datetime.now(ZoneInfo("America/Chicago")).date()   # dates in the site/digest are US Central
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

SECURITY = re.compile(
    r"security|vulnerab|cve-\d|exploit|unauthori[sz]ed|remote code|authentication bypass|"
    r"privilege escalation|patch(?:es|ed)? (?:a|an|the) (?:flaw|issue|vulnerab)|hardening",
    re.I,
)
# Icon family for the site's lists. Keys must exist in icons.js. Category is the fallback;
# the keyword rules pick out the sub-families a category mixes together (cameras vs hubs,
# drones vs consoles, 3D printers vs dev boards, hardware NAS vs self-hosted apps).
ICON_RULES = [
    ("doorbell", r"doorbell|door ?lock|\block\b|chime|deadbolt"),
    ("camera", r"\bcam(era)?s?\b|bullet|dome|floodlight|nvr|frigate|unifi protect|reolink|arlo|wyze|eufycam|blink|rtsp|ipcam|openipc|thingino|insta360|gopro|action cam|alpha a7|eos r|x-t\d|x100|lumix|om-1|nikon z"),
    ("headphones", r"headphone|earbud|airpods|wh-1000|wf-1000|quietcomfort|momentum|elite \d|beats|arctis|\bear \(|sonos ace"),
    ("speaker", r"echo|homepod|nest audio|nest mini|nest hub|sonos|speaker|\bshow\b|soundbar"),
    ("drone", r"drone|mavic|\bmini \d|\bair \d|avata|\bneo\b|\bflip\b|skydio|autel|\bdji\b|gimbal|osmo|hoverair"),
    ("ebike", r"e-?bike|\bbike\b|scooter|levo|\brad\b|vanmoof|cowboy|bosch|shimano|specialized|trek|onewheel|segway|aventon|lectric|super73|fazua|mahle|\bniu\b|apollo|zwift|kickr"),
    ("printer", r"3d printer|printer firmware|bambu|prusa|creality|klipper|marlin|ender|voron|anycubic|elegoo|kobra|slicer|cura|octoprint|mainsail|fluidd|moonraker|qidi|sovol|flsun|formlabs|centauri|k1c|spoolman|manyfold"),
    ("board", r"esp32|esp8266|arduino|raspberry pi (?!500)|\bpico\b|microcontroller|tasmota|esphome|wled|meshtastic|flipper|\bqmk\b|\bzmk\b|betaflight|ardupilot|inav|pinecil|\biron\b|heltec|adafruit|micropython|circuitpython|\bcnc\b|grbl|laser|reprap|duet|cardputer|t-deck|xiao|orange pi|radxa|rock 5|beagle|jetson|nanokvm|jetkvm|\bkvm\b|bus pirate|nodemcu|espruino|emuflight|rotorflight"),
    ("nas", r"\bnas\b|diskstation|rackstation|\bts-\d|\btvs-|\btbs-|truenas|unraid|my cloud|readynas|drobo|terramaster|asustor|openmediavault|\bdsm\b|\bqts\b|\bssd\b|nvme|zimacube|beestation|flashstor|lockerstor|nasync|hexos|rockstor|\bwtr\b|lacie|2big|terastation"),
    ("tv", r"\btv\b|bravia|roku|chromecast|shield tv|streamer|projector|ultragear|ultrasharp|odyssey"),
    ("print", r"laserjet|officejet|deskjet|pixma|ecotank|\bmfc-|\bhl-l|inkjet|laser printer"),
    ("watch", r"\bwatch\b|fenix|forerunner|venu|whoop|oura|fitbit|infinitime|pinetime|bangle|garmin|elemnt"),
    ("tablet", r"kindle|kobo|remarkable|boox|e-?reader|tablet|\bipad\b|palma"),
    ("keyboard", r"keyboard|mx keys|mx master|superlight|stream deck|webcam|brio|facecam|microphone|\bmic\b|\bdock\b|blackwidow|k70|wireless controller|pro controller|dualsense|8bitdo"),
    ("laptop", r"laptop|thinkpad|\bxps\b|elitebook|spectre|zephyrus|surface|macbook|mini pc|motherboard|\bbios\b|swift 14|raspberry pi 500|framework"),
    ("hub", r"\bhub\b|bridge|thermostat|\bplug\b|switch firmware|zigbee|z-wave|matter|homekit|home assistant|smartthings|homey|hubitat|sensor|ev charg|charge controller|sprinkler|irrigation|vacuum|openhab|mqtt|thread|powerwall|wall connector|gateway|pulsar|home flex|water monitor|decora|smart home control|iota|voice preview"),
    ("console", r"playstation|xbox|nintendo|steam deck|rog ally|legion go|analogue|handheld|\bquest\b|vision pro|\bvr\b|\bgame|claw|retroid|anbernic|miyoo|playdate|rg35xx|emulator|retro"),
    ("router", r"router|mesh|access point|\bap\b|switch|gateway|firewall|openwrt|routeros|opnsense|pfsense|eero|orbi|deco|nighthawk|archer|unifi|dream machine|pi-hole|adguard|tailscale|wireguard|\bdns\b|modem|\bvpn\b|zerotier|netbird|hotspot|mifi|extender|surfboard|velop|meraki|balance 20x|rutx|vault fw|aquila|nwa\d"),
]
ICON_RULES = [(k, re.compile(p, re.I)) for k, p in ICON_RULES]
# hardware NAS names are all caught by the "nas" rule, so anything else in N is software
ICON_BY_CATEGORY = {"R": "router", "N": "app", "S": "hub", "C": "console", "M": "board", "P": "laptop", "A": "app"}
# self-hosted services live in several categories; when a name says "server/app" and no
# hardware rule matched, use the app icon rather than the category's hardware
APP_HINT = re.compile(r"server|application|software|client|manager|dashboard|monitor|backup|sync|wiki|media|photo|password|vault|finance|documentation|proxy|\bos\b|operating system|middleware|control panel|web interface|program|player|center|\btool\b|daemon|driver|transcoder|linux|\bhost\b|creator|studio|library|installer|launcher|loader|compatibility|frontend|manager|\bcli\b|toolkit|compiler|debugger|\bcad\b|suite|engine|stack|firmware update", re.I)


def icon_for(dev):
    name = f"{dev.get('brand', '')} {dev.get('model', '')}"
    if dev.get("category") == "A":
        return "app"  # self-hosted software, whatever it is named after
    for key, rx in ICON_RULES:
        if rx.search(name):
            return key
    if APP_HINT.search(name):
        return "app"
    return ICON_BY_CATEGORY.get(dev.get("category"), "app")


EOL = re.compile(r"end[- ]of[- ]life|\bEOL\b|no longer (?:be )?(?:updated|supported|maintained)|discontinued", re.I)
STALE_DAYS = 540  # ~18 months with no release: still tracked, but "current" would mislead
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


MENTION_FRAG = re.compile(r"\s*(?:by|from|-)?\s*@[\w-]+(?:\s+in\s+(?:https?://\S+|#\d+))?", re.I)


MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")                      # [label](url) → label
MD_NOISE = re.compile(r"(^|\n)[ \t]{0,3}(?:#{1,6}[ \t]+|[-*+][ \t]+|>[ \t]?|\d+\.[ \t]+)|`{1,3}|\*{1,3}|_{2,3}|~~")


def clean(text, limit=300):
    """Release notes as plain text. They come from third parties and end up in innerHTML,
    emails and generated pages, so nothing that looks like markup may leave here.

    Unescape first, then strip tags, and repeat: a tag hidden behind entities
    (&lt;img onerror=…&gt;) only appears as a tag after unescaping, so strip-then-unescape
    let it straight through. Markdown is flattened too — headings, bullets, emphasis, code
    ticks and [links](url) all read as noise once the text is prose."""
    text = html.unescape(text or "")
    for _ in range(3):
        stripped = TAG.sub(" ", text)
        if stripped == text and html.unescape(text) == text:
            break  # nothing left to strip and nothing left to decode
        text = html.unescape(stripped)
    text = MD_LINK.sub(r"\1", text)
    text = MD_NOISE.sub(r"\1", text)
    text = MENTION_FRAG.sub("", text)            # "by @user in #123" → gone (would tag real people if re-posted)
    text = re.sub(r"(?<![\w/])#(\d+)", "#\u200b" + r"\1", text)  # "#123" → non-referencing
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("<", "‹").replace(">", "›")   # whatever the regexes missed can't be a tag either
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


def gh_headers():
    """Authenticated when a token is around. Unauthenticated the GitHub API allows 60 calls
    an hour, which the catalog blows through; GITHUB_TOKEN in Actions raises it to 1,000."""
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        h["Authorization"] = "Bearer " + token
    return h


class RateLimited(ValueError):
    """The GitHub API budget for this hour is spent. Not a broken source: keep what we had."""


class NotRenderedThisRun(ValueError):
    """A browser source, on a run that didn't render. Not a broken source: keep what we had."""


def check_github(src, prev=None):
    """Latest non-prerelease via the GitHub API. src['repo'] = 'owner/name'.

    Sends the ETag from the last successful check as If-None-Match. GitHub answers 304
    when nothing changed and does not count that against the hourly budget (1,000 calls
    for the Actions token), which is what lets ~400 repos be checked every 30 minutes."""
    api = f"https://api.github.com/repos/{src['repo']}/releases/latest"
    headers = gh_headers()
    prev = prev or {}
    if prev.get("etag") and prev.get("version"):
        headers["If-None-Match"] = prev["etag"]
    req = urllib.request.Request(api, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.loads(r.read().decode("utf-8"))
            etag = r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return {"version": prev["version"], "released": prev.get("released"),
                    "notes": prev.get("notes", ""), "source_url": prev.get("source_url"),
                    "etag": prev["etag"]}
        # with a catalog this size an exhausted quota looks like dozens of unrelated
        # failures, so say what it really is
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            raise RateLimited("GitHub API rate limit reached") from None
        if e.code == 404:
            raise ValueError(f"no repo or no stable release: {src['repo']}") from None
        raise
    title = f"{rel.get('name') or ''} {rel.get('tag_name') or ''}"
    v = extract_version(title, src.get("version_regex"))
    if not v:
        raise ValueError(f"no version in release title/tag: {title.strip()}")
    return {
        "version": v,
        "released": parse_date(rel.get("published_at")) or TODAY.isoformat(),
        "notes": clean(rel.get("body") or "") or clean(title),
        "source_url": rel.get("html_url") or f"https://github.com/{src['repo']}/releases",
        "etag": etag,
    }


def check_html(src, prev):
    if src["type"] == "browser":
        f = RENDERED / (src["id"] + ".html")
        if not f.exists():
            # scripts/fetch_browser.py only runs on the daily run, so on the other 47 runs a
            # day there is nothing rendered to read. That is not a broken source. When the
            # directory exists the render did run and this page genuinely failed to render.
            if not RENDERED.exists():
                raise NotRenderedThisRun("not rendered this run (browser sources render once a day)")
            raise ValueError("rendered page missing (browser fetch failed)")
        raw = f.read_text(encoding="utf-8", errors="replace")
    else:
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


GH_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+?)/(?:releases|tags)", re.I)


def update_url(src):
    """Where someone actually goes to get this firmware — not the changelog.

    Explicit wins; otherwise a GitHub project's releases page, or the vendor support page
    we already read the version from. Non-GitHub feeds (the UniFi RSS, say) are a changelog
    with no download behind them, so they get nothing here and update_guides.json supplies
    the route instead."""
    if src.get("update_url"):
        return src["update_url"]
    if src.get("repo"):
        return f"https://github.com/{src['repo']}/releases"
    url = src.get("url") or ""
    m = GH_URL.search(url)
    if m:
        return f"https://github.com/{m.group(1)}/releases"
    if src["type"] in ("html", "browser"):
        return src.get("page_url") or url or None
    return None


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
    if age > STALE_DAYS:
        return "stale"
    return "current"


def device_record(src, prev):
    """The devices.json entry for a source before tonight's check, carrying forward
    whatever the last run knew. discover.py builds new devices through this too."""
    return {
        "id": src["id"], "brand": src["brand"], "model": src["model"], "category": src["category"],
        "tracked": src["type"] != "manual",
        "version": prev.get("version"), "released": prev.get("released"),
        "notes": prev.get("notes", ""), "source_url": prev.get("source_url") or src.get("url"),
        "product_url": src.get("product_url"),
        "update_url": update_url(src),
        "history": prev.get("history", []),
        "etag": prev.get("etag"),
        "checked": prev.get("checked"), "source_status": prev.get("source_status", "pending"),
    }


def check_source(src, prev):
    """Run the right checker for one source. Returns (result, None), or (None, error) where
    an error starting with "skipped:" means nothing is known to be wrong with the source."""
    try:
        if src["type"] == "feed":
            return check_feed(src), None
        if src["type"] == "github":
            return check_github(src, prev), None
        return check_html(src, prev), None
    except (RateLimited, NotRenderedThisRun) as e:
        return None, f"skipped: {e}"
    except Exception as e:
        return None, f"error: {type(e).__name__}: {str(e)[:120]}"


def apply_result(dev, res):
    """Fold a successful check into the device record (version, history, dates)."""
    if res["version"] != dev["version"]:
        dev["history"] = ([{"version": res["version"], "released": res["released"]}] + dev["history"])[:6]
    elif dev["history"] and dev["history"][0].get("version") == res["version"]:
        dev["history"][0]["released"] = res["released"]   # keep history in sync if the date got corrected
    dev.update(res)
    dev["checked"] = NOW
    dev["source_status"] = "ok"


def finish_record(dev):
    dev["eol"] = bool(EOL.search(dev.get("notes") or ""))
    dev["status"] = classify(dev)
    dev["icon"] = icon_for(dev)
    return dev


def load_pending():
    try:
        data = json.loads(PENDING.read_text())
        if isinstance(data, dict) and isinstance(data.get("devices"), dict):
            return data
    except Exception:
        pass
    return {"since": None, "forced": False, "devices": {}}


def main():
    cfg = json.loads(SOURCES.read_text())
    previous, prev_meta = {}, {}
    if OUT.exists():
        try:
            prev_meta = json.loads(OUT.read_text())
            previous = {d["id"]: d for d in prev_meta.get("devices", [])}
        except Exception:
            previous, prev_meta = {}, {}

    records = [(src, device_record(src, previous.get(src["id"], {}))) for src in cfg["devices"]]
    ok, failed, skipped = 0, [], {}   # skipped: reason -> count, so the log says which reason
    if not OFFLINE:
        # every source is independent, so check them side by side; order is preserved
        to_check = [(src, dev) for src, dev in records if dev["tracked"]]
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(lambda pair: check_source(pair[0], previous.get(pair[0]["id"], {})), to_check))
        for (src, dev), (res, err) in zip(to_check, results):
            if res:
                apply_result(dev, res)
                ok += 1
                print(f"  ok   {src['id']:40s} {res['version']}  ({res['released']})")
            elif err.startswith("skipped:"):
                # keep last run's data and status; nothing is known to be wrong with the source
                reason = err.split("skipped:", 1)[1].strip()
                skipped[reason] = skipped.get(reason, 0) + 1
            else:
                dev["checked"] = NOW
                dev["source_status"] = err
                failed.append(src["id"])
                print(f"  FAIL {src['id']:40s} {err}")
        for reason, n in sorted(skipped.items()):
            print(f"  skipped {n} source(s): {reason}; their last data stands")

    out = [finish_record(dev) for _, dev in records]

    if OFFLINE:
        # nothing was checked, so don't claim every source just failed
        ok, failed = prev_meta.get("ok", 0), prev_meta.get("failed", [])
    result = {"generated": NOW, "tracked": sum(1 for d in out if d["tracked"]),
              "ok": ok, "failed": failed, "devices": out}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT.name}: {len(out)} devices, {ok} fetched, {len(failed)} failed, {sum(skipped.values())} skipped")

    # ---- what moved this run joins the pending set; scripts/digest.py drains it once a day ----
    changed = [d for d in out if d["tracked"] and d.get("version")
               and (FORCE_DIGEST or is_new_release(d, previous))]
    if changed:
        pending = load_pending()
        for d in changed:
            rec = change_record(d, previous)
            earlier = pending["devices"].get(d["id"])
            if earlier and earlier.get("previous"):
                rec["previous"] = earlier["previous"]   # "you were on X" means X at the start of the window
            pending["devices"][d["id"]] = rec
        pending["since"] = pending.get("since") or NOW
        pending["forced"] = bool(pending.get("forced")) or FORCE_DIGEST
        PENDING.write_text(json.dumps(pending, indent=1, ensure_ascii=False) + "\n")
        print(f"changes: {len(changed)} this run, {len(pending['devices'])} pending for the daily digest")
    else:
        print("changes: none this run")


def is_new_release(dev, previous):
    """True only when a device we already had a version for moved to a different one.

    The first time a source resolves there is nothing to compare against. That is a device
    joining the catalog, not a release anyone missed — announcing it would mail every
    subscriber about firmware they may have been running for a year, and adding a batch of
    devices at once would do it hundreds of times over."""
    if not dev["tracked"] or not dev.get("version"):
        return False
    prev = previous.get(dev["id"]) or {}
    if not prev.get("version"):
        return False
    return dev["version"] != prev["version"]


def change_record(d, previous):
    """One device that moved, carrying the version it came from so a subscriber can be told
    "you were on X"."""
    return {
        "id": d["id"],
        "brand": d["brand"],
        "model": d["model"],
        "category": d.get("category"),
        "status": d["status"],
        "version": d["version"],
        "previous": previous.get(d["id"], {}).get("version"),
        "released": d.get("released"),
        "eol": bool(d.get("eol")),
        "notes": d.get("notes", ""),
        "source_url": d.get("source_url"),
        "page_url": f"https://www.firmwarely.com/devices/{d['id']}/",
    }


def sort_changes(items):
    return sorted(items, key=lambda x: (x["status"] != "critical", x["brand"], x["model"]))


def write_changed_file(items, forced=False):
    """changed.json for scripts/user_alerts.py: newest-and-scariest first. Not committed —
    digest.py writes it and the workflow reads it in the same run."""
    payload = {"generated": NOW, "date": TODAY.isoformat(), "forced": forced,
               "count": len(items), "devices": sort_changes(items)}
    CHANGED.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")


def build_issue_summary(changed):
    """Plain summary for the GitHub issue. Deliberately contains no release-note text and no external
    links, so it can never @mention or cross-reference anyone on GitHub."""
    date = TODAY.strftime("%b %-d, %Y")
    lines = [f"# Firmware digest — {date}", "",
             f"{len(changed)} change(s). Full digest with release notes is in the Beehiiv draft.", ""]
    for d in sorted(changed, key=lambda x: (x["status"] != "critical", x["brand"], x["model"])):
        flag = {"critical": "🔴 security", "update": "🟡 update", "eol": "⚫ end of life"}.get(d["status"], "⚪")
        lines.append(f"- {flag} — {d['brand']} {d['model']}: `{d['version']}` ({d.get('released','')})")
    lines += ["", "Site: firmwarely dot com (link omitted on purpose)", ""]
    return "\n".join(lines)


def build_digest(changed):
    date = TODAY.strftime("%b %-d, %Y")
    groups = {"critical": [], "update": [], "current": [], "eol": []}
    for d in changed:
        groups.setdefault("current" if d["status"] == "stale" else d["status"], []).append(d)
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
