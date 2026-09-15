#!/usr/bin/env python3
"""
Find and vet new projects to track, once a day.

Searches GitHub for well-known projects in the topics Firmwarely covers, rejects anything
that isn't a shipping product (lists, tutorials, libraries, templates), proves that the
project publishes a parsable stable release, and only then adds it to sources.json and
devices.json. Consumer hardware from manufacturers can't be discovered this way: those
vendors publish no machine-readable feed, so they stay hand-curated.

    python3 scripts/discover.py            # add up to MAX_ADDS vetted projects
    python3 scripts/discover.py --dry-run  # show what would be added, change nothing

Writes discovered.json (what was added and why others were rejected) for digest.py.
Needs GITHUB_TOKEN; the search API allows 30 requests a minute.
"""
import json, os, re, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch

ROOT = Path(__file__).resolve().parent.parent
DISCOVERED = ROOT / "discovered.json"
DRY_RUN = "--dry-run" in sys.argv

MAX_ADDS = 10          # per day: the catalogue grows steadily, not in a lump
MIN_STARS = 1500       # below this the "product" signal gets noisy
MAX_RELEASE_AGE_DAYS = 730
MAX_PUSH_AGE_DAYS = 365
TOPICS_PER_DAY = 5
MAX_CHECKS = 60        # live release checks per day; each costs one API call

# topics that map to what the site already covers; rotated a few per day
TOPICS = ["self-hosted", "selfhosted", "home-automation", "homelab", "firmware", "esp32", "nas", "3d-printing",
          "router", "smart-home", "iot", "media-server", "backup", "monitoring", "vpn", "dns", "emulator",
          "retro-gaming", "openwrt", "home-assistant", "docker", "reverse-proxy", "password-manager",
          "network-monitoring", "zigbee", "mqtt", "klipper", "arduino", "raspberry-pi", "photo-management"]

# a repo is a product only if none of these describe it
NOT_A_PRODUCT = re.compile(
    r"awesome|curated|\blists?\b|tutorial|course|\bbook\b|cheat ?sheet|interview|roadmap|template|boilerplate|"
    r"\bexamples?\b|\bsamples?\b|\bdemo\b|collection|resources|\blearn(ing)?\b|\bguide\b|\bdocs?\b|documentation|"
    r"specification|proposal|\bpaper\b|dataset|benchmark|hackathon|challenge|algorithms|leetcode|dotfiles|"
    r"wallpapers?|\bicons?\b|\bfonts?\b|\btheme\b|\bsdk\b|\blibrary\b|\bframework\b|bindings|wrapper|\bplugin\b|"
    r"\bextension\b|starter|scaffold|\bmirror\b|archive of|deprecated|unmaintained|no longer", re.I)

# topic → category, most specific first; anything else is self-hosted software
CATEGORY_TOPICS = [
    ("R", r"^(router|openwrt|dns|vpn|networking|proxy|reverse-proxy|wireguard|firewall|network-monitoring|adblock|tunnel|ddns|certificates?|tls|dhcp)$"),
    ("N", r"^(nas|storage|backup|backups|filesystem|s3|file-sync|object-storage|sync|cloud-storage|zfs)$"),
    ("S", r"^(home-automation|home-assistant|homeassistant|smart-home|smarthome|iot|zigbee|z-wave|zwave|mqtt|matter|homekit|esphome|camera|nvr|surveillance|thermostat|hue)$"),
    ("C", r"^(emulator|emulation|retro-gaming|retrogaming|gaming|steam-deck|drone|drones|flight-controller|handheld|game-streaming|betaflight)$"),
    ("M", r"^(esp32|esp8266|arduino|3d-printing|3d-printer|klipper|firmware|embedded|microcontroller|rtos|cnc|raspberry-pi|keyboard|qmk|stm32|fpga|hardware|marlin|platformio)$"),
]
CATEGORY_TOPICS = [(k, re.compile(p)) for k, p in CATEGORY_TOPICS]


def api(url):
    req = urllib.request.Request(url, headers=fetch.gh_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def humanize(name):
    """Repo name → brand: 'uptime-kuma' → 'Uptime Kuma', 'NocoDB' stays 'NocoDB'."""
    words = re.split(r"[-_]+", name.strip())
    out = []
    for w in words:
        if not w:
            continue
        out.append(w.capitalize() if w.islower() else w)
    return " ".join(out) or name


# a model line must not end on one of these: cutting at 60 chars used to leave dangling
# fragments like "…build and manage the" or "…capable of performing" in live page titles
DANGLING = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "for", "with",
            "from", "into", "via", "that", "which", "who", "your", "our", "its", "their", "this",
            "is", "are", "be", "as", "so", "you", "can", "will", "helps", "capable", "providing",
            "performing", "using", "made", "built", "designed", "powered", "based", "more", "than",
            "all", "any", "every", "without", "while", "when", "where", "how", "what", "it"}


# a trailing phrase that the 60-char cut left incomplete: drop the whole phrase, not just
# the last word, so "…platform providing secure access" becomes "…platform"
PHRASE_TAIL = (r"\s+(?:with|for|to|of|in|on|by|from|into|via|at|using|that|which|who|so|"
               r"providing|offering|enabling|allowing|helping|helps|lets|designed|built|powered|"
               r"based|capable|able|made|supporting|featuring)\s+.*$")


def trim_dangling(text):
    """Drop trailing words that leave the line reading as a cut-off sentence."""
    words = text.split()
    while words and re.sub(r"[^\w]", "", words[-1]).lower() in DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ,;:-–—")


def short_model(description, brand):
    """Description → the catalogue's 'model' line: one plain clause, no marketing, <= 60 chars.

    This text becomes the device page's <title> and meta description, so a fragment ending
    mid-phrase ("…build and manage the") is visible on the live site, not just in the data."""
    d = re.sub(r"[\U0001F300-\U0001FAFF☀-➿⭐✅️]", "", description or "")  # emoji
    d = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", d)              # markdown links
    d = re.sub(r"https?://\S+", "", d)
    d = re.sub(r"\s+", " ", d).strip(" .!-–—|:")
    # first clause that isn't just the project's own name ("Immich - High performance ..." style)
    clauses = [c.strip() for c in re.split(r"(?<=[a-z0-9\)])[.!]\s|\s[-–—|]\s|;|:\s", d) if c.strip()]
    clauses = [c for c in clauses if c.lower() not in (brand.lower(), brand.lower().replace(" ", "-"), brand.lower().replace(" ", ""))]
    d = clauses[0] if clauses else ""
    d = re.sub(rf"^{re.escape(brand)}\s*(is|-|:|,)?\s*(an?|the)?\s*", "", d, flags=re.I).strip()
    # a tail that only restates the brand adds nothing ("…knowledge base with Trilium Notes")
    tail = re.search(rf"\s+(?:with|using|for|by|powered by)\s+{re.escape(brand)}\b.*$", d, flags=re.I)
    if tail and len(d[: tail.start()].split()) >= 3:
        d = d[: tail.start()]
    # repo descriptions often open as an instruction to the reader
    d = re.sub(r"^(build|create|make|manage|run|deploy|host|self[- ]host|turn|organize|organise|track|keep)\s+(your|the|a|an)\s+", "", d, flags=re.I)
    d = re.sub(r"^(your|our|their|its)\s+", "", d, flags=re.I)
    d = re.sub(r"^(an?|the)\s+", "", d, flags=re.I)
    d = re.sub(r"^(free|open[- ]source|self[- ]hosted|modern|simple|lightweight|powerful|fast|easy|blazing[- ]fast|privacy[- ]friendly|and)\s+(and\s+)?", "", d, flags=re.I)
    d = re.sub(r"^(free|open[- ]source|self[- ]hosted|modern|simple|lightweight|powerful|fast|easy)\s+", "", d, flags=re.I)
    if len(d) > 60:
        # a description too long to keep whole gets cut back to a phrase boundary rather
        # than mid-clause, so the result is a shorter true statement, not a fragment
        d = d[:60].rsplit(" ", 1)[0]
        for _ in range(4):
            shorter = re.sub(PHRASE_TAIL, "", d, flags=re.I)
            if shorter == d or len(shorter.split()) < 2:
                break
            d = shorter
    d = trim_dangling(d)
    d = d[:1].upper() + d[1:] if d else d
    return d or "Self-hosted software"


def category_for(topics, description):
    for key, rx in CATEGORY_TOPICS:
        if any(rx.match(t) for t in topics):
            return key
    return "A"


def slug(name):
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def vet(repo, known_repos, known_names):
    """Return a rejection reason, or None if the repo may be added."""
    full = repo["full_name"].lower()
    if full in known_repos:
        return "already tracked"
    if repo.get("fork") or repo.get("archived") or repo.get("disabled") or repo.get("is_template"):
        return "fork/archived/template"
    if (repo.get("stargazers_count") or 0) < MIN_STARS:
        return "too few stars"
    desc = (repo.get("description") or "").strip()
    if len(desc) < 15:
        return "no description"
    if not repo.get("license"):
        return "no license"
    pushed = fetch.parse_date(repo.get("pushed_at") or "")
    if not pushed or (datetime.now(timezone.utc).date() - datetime.fromisoformat(pushed).date()).days > MAX_PUSH_AGE_DAYS:
        return "not pushed in a year"
    blob = " ".join([repo["name"], desc, " ".join(repo.get("topics") or [])])
    if NOT_A_PRODUCT.search(blob):
        return "not a product (list/library/tutorial)"
    brand = humanize(repo["name"])
    if (brand.lower(), short_model(desc, brand).lower()) in known_names:
        return "name already in catalogue"
    return None


def candidate_entry(repo, ids):
    brand = humanize(repo["name"])
    model = short_model(repo.get("description") or "", brand)
    dev_id = slug(repo["name"])
    if dev_id in ids:
        dev_id = slug(f"{repo['owner']['login']}-{repo['name']}")
    return {"id": dev_id, "brand": brand, "model": model,
            "category": category_for(repo.get("topics") or [], repo.get("description") or ""),
            "type": "github", "repo": repo["full_name"], "product_url": repo["html_url"]}


def todays_topics(day=None):
    day = day or datetime.now(timezone.utc).timetuple().tm_yday
    start = (day * TOPICS_PER_DAY) % len(TOPICS)
    return [TOPICS[(start + i) % len(TOPICS)] for i in range(TOPICS_PER_DAY)]


def main():
    src = json.loads(fetch.SOURCES.read_text())
    devices_doc = json.loads(fetch.OUT.read_text()) if fetch.OUT.exists() else {"devices": []}
    known_repos = {d["repo"].lower() for d in src["devices"] if d.get("repo")}
    known_repos |= {m.group(1).lower() for d in src["devices"] if d.get("url")
                    for m in [re.search(r"github\.com/([^/]+/[^/]+)/", d["url"])] if m}
    known_names = {(d["brand"].lower(), d["model"].lower()) for d in src["devices"]}
    ids = {d["id"] for d in src["devices"]}

    rejected, added, seen, checks, out_of_budget = {}, [], set(), 0, False
    for topic in todays_topics():
        if out_of_budget:
            break
        q = urllib.parse.quote(f"topic:{topic} stars:>={MIN_STARS} archived:false fork:false")
        try:
            page = api(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=50")
        except Exception as e:
            print(f"  search {topic}: {type(e).__name__}: {str(e)[:80]}")
            continue
        for repo in page.get("items", []):
            if repo["full_name"].lower() in seen:
                continue
            seen.add(repo["full_name"].lower())
            why = vet(repo, known_repos, known_names)
            if why:
                rejected[why] = rejected.get(why, 0) + 1
                continue
            if checks >= MAX_CHECKS:
                rejected["not checked (daily budget)"] = rejected.get("not checked (daily budget)", 0) + 1
                continue
            entry = candidate_entry(repo, ids)
            checks += 1
            res, err = fetch.check_source(entry, {})
            if err and err.startswith("skipped:"):
                print("  GitHub API budget spent; stopping discovery for today")
                out_of_budget = True
                break
            if err:
                rejected["no parsable stable release"] = rejected.get("no parsable stable release", 0) + 1
                print(f"  skip {repo['full_name']:45s} {err}")
                continue
            released = res.get("released")
            if not released or (fetch.TODAY - datetime.fromisoformat(released).date()).days > MAX_RELEASE_AGE_DAYS:
                rejected["no release in two years"] = rejected.get("no release in two years", 0) + 1
                continue
            dev = fetch.device_record(entry, {})
            fetch.apply_result(dev, res)
            fetch.finish_record(dev)
            added.append({**entry, "stars": repo.get("stargazers_count"), "version": res["version"], "released": released})
            print(f"  add  {repo['full_name']:45s} → {entry['brand']} / {entry['model']} [{entry['category']}] {res['version']}")
            known_repos.add(repo["full_name"].lower()); known_names.add((entry["brand"].lower(), entry["model"].lower())); ids.add(entry["id"])
            if not DRY_RUN:
                src["devices"].append(entry)
                devices_doc["devices"].append(dev)
            if len(added) >= MAX_ADDS:
                break
        if len(added) >= MAX_ADDS:
            break
        time.sleep(2)   # search API: 30 requests a minute

    if added and not DRY_RUN:
        fetch.SOURCES.write_text(json.dumps(src, indent=1, ensure_ascii=False) + "\n")
        devices_doc["tracked"] = sum(1 for d in devices_doc["devices"] if d.get("tracked"))
        fetch.OUT.write_text(json.dumps(devices_doc, indent=1, ensure_ascii=False) + "\n")
    report = {"date": fetch.TODAY.isoformat(), "topics": todays_topics(), "considered": len(seen),
              "added": added, "rejected": rejected}
    if not DRY_RUN:
        DISCOVERED.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"\ndiscover: {len(seen)} candidates, added {len(added)}; rejected {rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
