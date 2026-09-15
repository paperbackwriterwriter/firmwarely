#!/usr/bin/env python3
"""
Builds static pages from devices.json:

  devices/<id>/index.html   one page per device  → firmwarely.com/devices/<id>
  devices/index.html        all devices, grouped by category
  category/<slug>/          one landing page per category
  brands/<slug>/            one landing page per brand with BRAND_MIN+ devices
  pro/thanks/index.html     post-checkout page
  legal/index.html          privacy + terms
  404.html                  Vercel serves it for unknown paths
  sitemap.xml, robots.txt   per-URL lastmod from the newest release each page shows

Reuses the <style> block from index.html so pages match the site. Run after fetch.py.
"""
import json, re, html
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://www.firmwarely.com"  # the apex redirects here, so canonicals must too
CATS = {"R": "Routers & networking", "N": "NAS & storage", "S": "Smart home & cameras",
        "C": "Consoles, drones & e-bikes", "M": "Makers & open firmware",
        "P": "PCs, TVs & gadgets", "A": "Self-hosted apps & servers"}
LABEL = {"critical": "critical fix", "update": "new version", "current": "current",
         "pending": "watching soon", "eol": "end of life", "stale": "no recent release"}
GUIDES = json.loads((ROOT / "update_guides.json").read_text()) if (ROOT / "update_guides.json").exists() else {}

# Category and brand landing pages: crawlable entry points with real text, so a search for
# "synology firmware" or "router firmware updates" has a page to land on that isn't a JS table.
CAT_SLUG = {"R": "routers", "N": "nas", "S": "smart-home", "C": "consoles-drones-ebikes", "M": "makers",
            "P": "pcs-tvs-gadgets", "A": "self-hosted"}
CAT_SHORT = {"R": "Router & networking", "N": "NAS & storage", "S": "Smart home & camera",
             "C": "Console, drone & e-bike", "M": "Maker & open-source",
             "P": "PC, TV & gadget", "A": "Self-hosted app"}
CAT_INTRO = {
    "R": "Routers, mesh systems, switches and access points sit between everything you own and the internet, which makes them the devices most worth keeping patched. Vendors ship fixes for authentication bypasses and remote code execution several times a year, often quietly. Firmwarely reads each manufacturer's release page every 30 minutes and records the version, date and what changed.",
    "N": "A NAS holds your backups, photos and documents and is usually reachable from the whole house, so a missed security update matters more here than almost anywhere else. DSM, QTS, TrueNAS and Unraid all publish structured release notes; Firmwarely checks them every 30 minutes and flags the releases that fix vulnerabilities.",
    "S": "Cameras, doorbells, hubs and smart speakers update through their apps and rarely tell you what changed. Firmwarely tracks the manufacturers' official release notes so you can see the current version, when it shipped and whether it closed a security hole, even for devices that update silently.",
    "C": "Consoles, drones and e-bikes carry firmware that changes how they behave, from flight-safety databases to battery management. Manufacturers publish release notes, but nobody reads them at the right moment. Firmwarely records each release and emails you when one lands for something you own.",
    "M": "Open-source firmware and self-hosted software move fast, and a stale version can mean missing features or an unpatched dependency. Firmwarely watches the projects' own release feeds on GitHub and elsewhere, so you see new tags and their notes within the hour.",
    "P": "Laptops, motherboards, TVs, printers, headphones, cameras and e-readers all run firmware, and most of it updates from a settings menu nobody opens. BIOS releases close security holes, TV updates change what apps work, and camera firmware adds autofocus modes years after purchase. Firmwarely lists the current version and the manufacturer's notes so you know when it is worth the trip into the menu.",
    "A": "Self-hosted apps and servers are the software people run on their own NAS, mini PC or VPS: media servers, dashboards, password managers, home automation, monitoring and databases. They ship far more often than appliances, and a missed release can mean a known vulnerability on a box reachable from the internet. Firmwarely reads each project's release feed every 30 minutes and keeps the version, date and notes in one place.",
}
# how a category reads mid-sentence ("NAS" must stay upper-case)
CAT_PHRASE = {"R": "routers & networking", "N": "NAS & storage", "S": "smart home & cameras",
              "C": "consoles, drones & e-bikes", "M": "makers & open firmware",
              "P": "PCs, TVs & gadgets", "A": "self-hosted apps & servers"}
ICONS = json.loads(re.search(r"/\*json\*/(\{.*?\})/\*end\*/", (ROOT / "icons.js").read_text(), re.S).group(1))


def icon_svg(key, cls="ico"):
    return f'<svg class="{cls}" viewBox="0 0 64 64" aria-hidden="true">{ICONS.get(key) or ICONS["app"]}</svg>'


BRAND_MIN = 2          # brands with fewer devices don't get their own page (too thin)
DESC_MAX = 155         # meta descriptions are cut around here in search results


def slugify(text):
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", text.lower()))


def cat_path(key):
    return f"/category/{CAT_SLUG[key]}/"


def brand_path(brand):
    return f"/brands/{slugify(brand)}/"


def time_tag(d):
    """A machine-readable date for crawlers, the friendly one for people."""
    return f'<time datetime="{esc(d)}">{fmt(d)}</time>' if d else "—"


def fit_desc(candidates):
    for t in candidates:
        if len(t) <= DESC_MAX:
            return t
    t = candidates[-1]
    return t if len(t) <= DESC_MAX else t[: DESC_MAX - 1].rstrip() + "…"


def is_live(d):
    return bool(d.get("version")) and d.get("status") != "pending"


def device_list(items, show_brand=True):
    """The same compact list the catalogue uses: name → version, date."""
    out = ["<ul>"]
    for d in items:
        name = f"{d['brand']} {d['model']}" if show_brand else d["model"]
        v = f"{esc(d['version'])} · {fmt(d.get('released'))}" if is_live(d) else "watching soon"
        out.append(f'<li><a href="/devices/{d["id"]}/">{icon_svg(d.get("icon"))}{esc(name)}</a><span>{v}</span></li>')
    out.append("</ul>")
    return "".join(out)


def by_recent(items):
    return sorted([d for d in items if is_live(d)], key=lambda x: x.get("released") or "", reverse=True)


def guide(d):
    """Most specific update guide for a device: by id, then brand, then how it's tracked,
    then its category. Returns (steps, url) — url prefers the guide's own over the derived."""
    g = (GUIDES.get("by_id", {}).get(d["id"])
         or GUIDES.get("by_brand", {}).get(d["brand"]))
    if not g and "github.com" in (d.get("update_url") or ""):
        # a GitHub project is either something you run on a server or something you flash
        kind = "github_flash" if d["id"] in GUIDES.get("flash_ids", []) else "github"
        g = GUIDES.get("by_kind", {}).get(kind)
    if not g:
        g = GUIDES.get("by_category", {}).get(d["category"]) or {}
    return g.get("steps") or [], g.get("url") or d.get("update_url")


HOWTO = {
    "R": "Log in to the router's admin page (usually at 192.168.1.1 or via the manufacturer's app), open the firmware or system update section, and apply the update. Most routers reboot for a minute or two.",
    "N": "Open the NAS control panel, go to the update or system section, and install the new version. Back up important data first; NAS updates can take several minutes.",
    "S": "Updates usually arrive through the manufacturer's phone app or roll out automatically. Open the device's settings in the app and look for a firmware or software section.",
    "C": "Consoles update through their system settings or on next connection. Drones and e-bikes update through the manufacturer's app while the device is connected.",
    "M": "Follow the project's release page for the flashing or OTA procedure. Many maker devices update from a web installer or the project's desktop app.",
    "P": "Use the manufacturer's companion app or the device's own settings menu; PCs and motherboards use a BIOS utility, TVs a Software Update menu, cameras a file copied to a memory card.",
    "A": "Pull the new image or package and restart the service. Read the release notes and back up the data directory first; most projects can't downgrade once the database has migrated.",
}

esc = html.escape


def fmt(d):
    if not d:
        return "—"
    try:
        return datetime.fromisoformat(d).strftime("%b %-d, %Y")
    except Exception:
        return d


def month(d):
    try:
        return datetime.fromisoformat(d).strftime("%b %Y")
    except Exception:
        return ""


def styles():
    s = (ROOT / "index.html").read_text()
    m = re.search(r"<style>(.*?)</style>", s, re.S)
    return (m.group(1) if m else "") + """
  .crumbs{font-family:var(--mono);font-size:.8rem;color:var(--muted);margin:1.5rem 0 .5rem}
  .crumbs a{color:var(--muted)}
  .dev{display:grid;grid-template-columns:1fr;gap:2rem;padding-top:2rem}
  @media(min-width:900px){.dev{grid-template-columns:2fr 1fr}}
  .card{border:1px solid var(--line);border-radius:12px;padding:1.25rem;background:var(--panel)}
  .kv{display:grid;grid-template-columns:150px 1fr;gap:.55rem 1rem;font-size:.95rem;margin:1rem 0 0}
  .kv dt{color:var(--muted);font-family:var(--mono);font-size:.8rem}
  .kv dd{margin:0;font-family:var(--mono)}
  .hist{width:100%;border-collapse:collapse;margin-top:.5rem;font-family:var(--mono);font-size:.85rem}
  .hist td{padding:.5rem 0;border-top:1px solid var(--line)}
  .hist td:last-child{text-align:right;color:var(--muted)}
  ol.upd-steps{display:block;margin:1rem 0 0;padding-left:1.5rem;color:var(--text);list-style:decimal}
  ol.upd-steps li{list-style:decimal;margin:0 0 .6rem;line-height:1.55}
  ol.upd-steps li::marker{color:var(--amber);font-weight:600}
  h1.dev-h{font-size:clamp(1.6rem,4vw,2.4rem);line-height:1.15;margin:.25rem 0 .5rem}
  .faq h3{font-size:1rem;margin:1.25rem 0 .35rem}
  .faq p{color:var(--muted);margin:0}
  .brandlist h2{font-family:var(--mono);font-size:1rem;color:var(--amber);margin:1.75rem 0 .5rem}
  .brandlist ul{list-style:none;padding:0;margin:0;display:grid;gap:.4rem}
  .brandlist li{display:flex;justify-content:space-between;gap:1rem;border-top:1px solid var(--line);padding:.6rem 0}
  .brandlist li a{display:inline-flex;align-items:center;gap:.6rem}
  .brandlist li span{font-family:var(--mono);font-size:.85rem;color:var(--muted)}
  .brandlist .fine{margin:.5rem 0 0;font-size:.85rem}
  .related{margin-top:2.5rem}
  .pro-hero{display:grid;grid-template-columns:1fr;gap:2.5rem;align-items:center;padding:3.5rem 0 2.5rem}
  @media(min-width:900px){.pro-hero{grid-template-columns:1.1fr 1fr}}
  .pro-hero .kicker{font-family:var(--mono);color:var(--amber);font-size:.85rem;letter-spacing:.04em;text-transform:uppercase;margin:0 0 .75rem}
  .pro-hero h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.08;margin:0 0 1rem;letter-spacing:-.02em}
  .pro-hero .lede{font-size:1.15rem;color:var(--muted);margin:0 0 1.5rem;max-width:56ch}
  .pro-hero form{display:grid;gap:.6rem;max-width:460px}
  .pro-hero form .row{display:flex;gap:.6rem;flex-wrap:wrap}
  .pro-hero form input[type=email]{flex:1;min-width:220px}
  .gallery{display:grid;grid-template-columns:repeat(2,1fr);gap:.75rem}
  @media(min-width:700px){.gallery{grid-template-columns:repeat(4,1fr)}}
  .gallery a{display:flex;flex-direction:column;align-items:center;gap:.6rem;padding:1.1rem .75rem;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--muted);text-decoration:none;font-family:var(--mono);font-size:.78rem;text-align:center;transition:border-color .15s,transform .15s}
  .gallery a:hover{border-color:var(--amber);color:var(--text);transform:translateY(-2px)}
  .gallery svg{width:56px;height:56px;color:var(--amber);fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
  .gallery svg .g{stroke:var(--green)}
  .gallery svg .f{fill:var(--green);stroke:none}
  .pro-perks{display:grid;grid-template-columns:1fr;gap:1rem;margin:1.5rem 0 0}
  @media(min-width:700px){.pro-perks{grid-template-columns:repeat(3,1fr)}}
  .pro-perks .card h3{margin:0 0 .35rem;font-size:1rem}
  .pro-perks .card p{margin:0;color:var(--muted);font-size:.95rem}
  .pro-price{font-family:var(--mono);font-size:1.6rem;font-weight:600;margin:0 0 .25rem}
  .pro-price small{font-size:.9rem;color:var(--muted);font-weight:400}
"""


def head(title, desc, path, extra="", noindex=False):
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}{path}">
{robots}<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<meta property="og:site_name" content="Firmwarely">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE}{path}">
<meta property="og:type" content="website">
<meta property="og:image" content="{SITE}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE}/og.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{STYLES}</style>
{extra}
</head>
<body>
<header>
  <div class="wrap nav">
    <a class="brand" href="/"><i></i>Firmwarely</a>
    <button class="menu" type="button" aria-label="Menu" aria-expanded="false" aria-controls="navlinks">☰</button>
    <ul id="navlinks">
      <li class="hide-m"><a href="/devices/">Devices</a></li>
      <li class="hide-m"><a href="/dashboard.html">Dashboard</a></li>
      <li class="hide-m"><a href="/my-devices.html">My devices</a></li>
      <li class="hide-m"><a href="/#how">How it works</a></li>
      <li class="hide-m"><a href="/#pricing">Pricing</a></li>
      <li><a class="btn" href="#signup">Get alerts</a></li>
    </ul>
  </div>
</header>
<script>(function(){{var n=document.querySelector(".nav"),b=n&&n.querySelector(".menu");if(!b)return;b.addEventListener("click",function(){{var o=n.classList.toggle("open");b.setAttribute("aria-expanded",String(o));b.textContent=o?"✕":"☰";}});}})();</script>
<main>
"""


def signup(device_name=""):
    return f"""
<section id="signup" class="signup">
  <div class="wrap">
    <h2>Get alerts for {esc(device_name) if device_name else "your devices"}</h2>
    <p style="color:var(--muted)">One email when a new or critical firmware ships. Free for up to 3 devices.</p>
    <form id="signup-form" novalidate>
      <label class="sr" for="s-email">Email address</label>
      <div class="row"><input id="s-email" name="email" type="email" placeholder="you@example.com" autocomplete="email" required></div>
      <label class="sr" for="s-devices">Devices to watch</label>
      <input id="s-devices" name="devices" type="text" value="{esc(device_name)}" placeholder="Devices to watch (optional)">
      <input type="hidden" name="plan" value="free">
      <div><button class="btn" type="submit">Start watching</button></div>
      <div id="s-msg" aria-live="polite"></div>
    </form>
  </div>
</section>
"""


FOOT = """
</main>
<footer>
  <div class="wrap">
    <span>© <span id="year"></span> Firmwarely. Device and brand names belong to their manufacturers.</span>
    <span><a href="/devices/">Devices</a> &nbsp;·&nbsp; <a href="/#pricing">Pricing</a> &nbsp;·&nbsp; <a href="/legal/">Legal</a> &nbsp;·&nbsp; <a href="mailto:hello@firmwarely.com">Contact</a></span>
  </div>
</footer>
<script>
document.getElementById("year").textContent = new Date().getFullYear();
const f = document.getElementById("signup-form");
if (f) f.addEventListener("submit", async e => {
  e.preventDefault();
  const msg = document.getElementById("s-msg"), btn = f.querySelector("button[type=submit]");
  const email = f.email.value.trim();
  if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)) { msg.className = "err"; msg.textContent = "Enter a valid email address to continue."; return; }
  btn.disabled = true; msg.className = ""; msg.textContent = "Saving…";
  try {
    const r = await fetch("/api/subscribe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, plan: f.plan.value, devices: f.devices.value.trim() }) });
    let d = {}; try { d = await r.json(); } catch {}
    if (!r.ok || !d.ok) throw new Error(d.error || "Couldn't save that just now. Try again in a minute.");
    f.innerHTML = '<p class="ok" style="margin:0">You\\'re on the list. Check your inbox for a confirmation.</p>';
  } catch (err) { btn.disabled = false; msg.className = "err"; msg.textContent = err.message; }
});
</script>
</body>
</html>
"""


TITLE_MAX = 70  # search results truncate around here


def fit_title(candidates):
    """First candidate that fits a search-result title; the shortest one, trimmed, if none do."""
    for t in candidates:
        if len(t) <= TITLE_MAX:
            return t
    t = candidates[-1]
    return t if len(t) <= TITLE_MAX else t[: TITLE_MAX - 1].rstrip() + "…"


def device_page(d, ctx=None):
    ctx = ctx or {}
    name = f"{d['brand']} {d['model']}"
    path = f"/devices/{d['id']}/"
    cat = CATS.get(d["category"], "")
    live = is_live(d)
    # plenty of names already end in "firmware" ("Klipper 3D printer firmware"), so only
    # add the word when it isn't there — otherwise the title stutters. Self-hosted software
    # doesn't have firmware at all, so it gets "releases" wording throughout.
    software = d["category"] == "A"
    fw = "" if (software or "firmware" in name.lower()) else " firmware"
    noun = "version" if software else "firmware"
    if live:
        v = d["version"]
        title = fit_title([f"{name}{fw} — latest version {v} ({month(d['released'])}) | Firmwarely",
                           f"{name}{fw} — latest version {v} | Firmwarely",
                           f"{name}{fw} {v} | Firmwarely",
                           f"{name}{fw} {v}"])
        desc = fit_desc([f"Latest {name} {noun} is {v}, released {fmt(d['released'])}. Release notes, version history, how to update, and email alerts for new or security fixes.",
                         f"Latest {name} {noun} is {v}, released {fmt(d['released'])}. Release notes, version history and update alerts.",
                         f"{name} {noun} {v} ({fmt(d['released'])}): release notes, history and alerts.",
                         f"{name} {noun} {v}: release notes, history and alerts."])
    else:
        title = fit_title([f"{name}{fw} updates — alerts & release tracking | Firmwarely",
                           f"{name}{fw} updates — release tracking | Firmwarely",
                           f"{name}{fw} updates | Firmwarely",
                           f"{name}{fw} updates"])
        desc = fit_desc([f"Track {name}{fw} updates. Firmwarely watches the manufacturer's release page and emails you when a new or security update ships.",
                         f"Track {name}{fw} updates and get an email when a new or security update ships.",
                         f"{name}{fw} update tracking and alerts."])

    notes = d.get("notes") or ""
    hist = list(d.get("history") or [])
    if hist and hist[0].get("version") == d.get("version") and d.get("released"):
        hist[0] = {**hist[0], "released": d["released"]}
    if not hist and live:
        hist = [{"version": d["version"], "released": d.get("released")}]

    # Structured data: where this page sits, what it describes, and when it was last refreshed.
    graph = [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Devices", "item": f"{SITE}/devices/"},
            {"@type": "ListItem", "position": 2, "name": cat, "item": f"{SITE}{cat_path(d['category'])}"},
            {"@type": "ListItem", "position": 3, "name": name, "item": f"{SITE}{path}"}]},
        {"@type": "WebPage", "@id": f"{SITE}{path}", "url": f"{SITE}{path}", "name": title,
         "description": desc, "isPartOf": {"@type": "WebSite", "name": "Firmwarely", "url": f"{SITE}/"},
         **({"dateModified": d["checked"][:10]} if d.get("checked") else {})},
    ]
    if live:
        app = {"@type": "SoftwareApplication", "name": f"{name} firmware", "applicationCategory": "Firmware",
               "operatingSystem": name, "softwareVersion": d["version"],
               "author": {"@type": "Organization", "name": d["brand"]}}
        if d.get("released"):
            app["datePublished"] = d["released"]
        if notes:
            app["releaseNotes"] = notes
        if d.get("source_url"):
            app["url"] = d["source_url"]
        graph.append(app)
    ld = {"@context": "https://schema.org", "@graph": graph}
    extra = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'

    rows = "".join(f"<tr><td>{esc(h['version'])}</td><td>{time_tag(h.get('released'))}</td></tr>" for h in hist[:6])

    # a sentence of real prose that no other page has
    if live:
        first = hist[-1].get("released") if hist else None
        span = (f" Firmwarely has recorded {len(hist)} versions since {fmt(first)}." if len(hist) > 1 and first else "")
        intro = (f"{'' if software else 'The '}{name} is tracked under {CAT_PHRASE[d['category']]}. Its latest {noun}, {d['version']}, "
                 f"shipped on {fmt(d.get('released'))}.{span}")
    else:
        intro = (f"{'' if software else 'The '}{name} is on our list under {CAT_PHRASE[d['category']]} but isn't being checked yet. "
                 f"Sign up and we'll prioritise it.")

    steps, upd = guide(d)
    step_html = "".join(f"<li>{esc(x)}</li>" for x in steps)
    # the page's whole point: one click to the place that actually updates the thing
    cta = (f'<a class="btn" href="{esc(upd)}" target="_blank" rel="noopener">Open update page ↗</a>'
           if upd else "")
    how = f"""
      <h2 id="update" style="margin-top:2rem">How to update {"" if software else "the "}{esc(name)}</h2>
      <div class="card">
        {cta}
        <ol class="upd-steps">{step_html}</ol>
        <p class="fine" style="margin:.75rem 0 0">Always download firmware from the manufacturer or project itself.
        Firmwarely links out; it never hosts firmware.</p>
      </div>"""

    # internal links: the rest of the brand, and what else moved recently in this category
    related = ""
    siblings = [x for x in ctx.get("by_brand", {}).get(d["brand"], []) if x["id"] != d["id"]]
    others = [x for x in by_recent(ctx.get("by_cat", {}).get(d["category"], [])) if x["id"] != d["id"]][:6]
    if siblings or others:
        related = '<div class="related brandlist">'
        if siblings:
            more = (f' <a href="{brand_path(d["brand"])}">All {esc(d["brand"])} devices →</a>'
                    if len(ctx.get("by_brand", {}).get(d["brand"], [])) >= BRAND_MIN else "")
            related += f'<h2>More from {esc(d["brand"])}</h2>{device_list(sorted(siblings, key=lambda x: x["model"])[:6], show_brand=False)}<p class="fine">{more}</p>'
        if others:
            related += f'<h2>Recently updated in {esc(cat)}</h2>{device_list(others)}<p class="fine"><a href="{cat_path(d["category"])}">All {esc(CAT_PHRASE[d["category"]])} devices →</a></p>'
        related += "</div>"

    body = head(title, desc, path, extra)
    body += f"""
<div class="wrap">
  <div class="crumbs"><a href="/devices/">Devices</a> / <a href="{cat_path(d['category'])}">{esc(cat)}</a> / {esc(name)}</div>
  <div class="dev">
    <div>
      <h1 class="dev-h">{esc(name)} {"releases" if software else "firmware"}</h1>
      <span class="status {d['status']}">{LABEL.get(d['status'], d['status'])}</span>
      <p style="color:var(--muted);margin:1rem 0 0">{esc(intro)}</p>
      <div class="card" style="margin-top:1.25rem">
        <dl class="kv">
          <dt>Latest {noun}</dt><dd>{esc(d['version']) if live else "—"}</dd>
          <dt>Released</dt><dd>{time_tag(d.get('released')) if live else "—"}</dd>
          <dt>Category</dt><dd><a href="{cat_path(d['category'])}">{esc(cat)}</a></dd>
          <dt>Last checked</dt><dd>{time_tag((d.get('checked') or '')[:10]) if d.get('checked') else "—"}</dd>
        </dl>
      </div>
      {how}
      <h2 style="margin-top:2rem">What changed</h2>
      <p style="color:var(--muted)">{esc(notes) if notes else ("Not tracked yet. Sign up below and we'll prioritise this device." if not live else "See the manufacturer's release notes for details.")}</p>
      {f'<p><a href="{esc(d["source_url"])}" target="_blank" rel="noopener">Manufacturer release notes ↗</a></p>' if d.get("source_url") and live else ""}
      {f'<h2 style="margin-top:2rem">Version history</h2><table class="hist">{rows}</table>' if rows else ""}
      <div class="faq">
        <h2 style="margin-top:2rem">FAQ</h2>
        <h3>What is the latest {noun} {"of" if software else "for the"} {esc(name)}?</h3>
        <p>{(f"Version {esc(d['version'])}, released {fmt(d.get('released'))}. " if live else "We haven't recorded a version yet. ")}This page is refreshed every 30 minutes from the manufacturer's release page.</p>
        <h3>How do I update {"" if software else "the "}{esc(name)}?</h3>
        <p><a href="#update">See the step-by-step above.</a> {esc(HOWTO.get(d['category'], ''))}</p>
        <h3>How does Firmwarely know when there's a new version?</h3>
        <p>Every 30 minutes we read the manufacturer's official release page{(" for the " + esc(name)) if live else ""} and record the version, date and changelog. Subscribers watching this device get one email a day when it changed.</p>
        <h3>Is this an official {esc(d['brand'])} page?</h3>
        <p>No. Firmwarely is independent. {"Project and product names belong to their owners; always install releases from the project's own source." if software else "Device and brand names belong to their manufacturers; always download firmware from the official source."}</p>
      </div>
      {related}
    </div>
    <aside>
      <div class="card">
        <h2 style="margin:0 0 .5rem;font-size:1.05rem">Watch this device</h2>
        <p style="color:var(--muted);font-size:.95rem;margin:0 0 .75rem">Get one email when {esc(d['brand'])} ships a new or security {"release of" if software else "firmware for the"} {esc(d['model'])}.</p>
        <a class="btn" href="#signup">Get alerts</a>
        <p style="margin:.75rem 0 0"><a href="/my-devices.html#d={esc(d['id'])}">Track this in My devices →</a></p>
        {f'<p style="margin:.5rem 0 0"><a href="#update">How to update this device</a></p>' if steps else ""}
        {product_link(d)}
      </div>
    </aside>
  </div>
</div>
"""
    body += signup(name) + FOOT
    return body


def category_page(key, devices, brands):
    items = [d for d in devices if d["category"] == key]
    cat, short = CATS[key], CAT_SHORT[key]
    live = [d for d in items if is_live(d)]
    top_brands = [b for b, _ in sorted(((b, n) for b, n in brands.items() if n >= BRAND_MIN and any(d["brand"] == b for d in items)),
                                       key=lambda x: -x[1])][:8]
    names = ", ".join(top_brands[:5])
    what = "releases" if key == "A" else "firmware updates"
    title = fit_title([f"{short} {what} — {names} | Firmwarely",
                       f"{short} {what} | Firmwarely",
                       f"{short} {what}"])
    kind = "versions" if key == "A" else "firmware"
    desc = fit_desc([f"Latest {kind} for {len(items)} {CAT_PHRASE[key]} from {names} and more, checked every 30 minutes. Version, release date, what changed and how to update.",
                     f"Latest {kind} for {len(items)} {CAT_PHRASE[key]}, checked every 30 minutes, with release notes and update guides.",
                     f"{cat}: {kind}, release notes and update alerts."])
    recent = by_recent(items)[:8]
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Devices", "item": f"{SITE}/devices/"},
            {"@type": "ListItem", "position": 2, "name": cat, "item": f"{SITE}{cat_path(key)}"}]},
        {"@type": "ItemList", "name": f"{cat} firmware", "numberOfItems": len(items),
         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": f"{d['brand']} {d['model']}",
                              "url": f"{SITE}/devices/{d['id']}/"} for i, d in enumerate(items)]}]}
    extra = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
    brand_links = "".join(f'<a class="chip" href="{brand_path(b)}">{esc(b)}</a>' for b in top_brands)
    other_cats = "".join(f'<a class="chip" href="{cat_path(k)}">{esc(CATS[k])}</a>' for k in CATS if k != key)
    return head(title, desc, cat_path(key), extra) + f"""
<div class="wrap brandlist" style="padding-top:2rem">
  <div class="crumbs"><a href="/devices/">Devices</a> / {esc(cat)}</div>
  <h1 class="dev-h">{esc(cat)}: latest {what}</h1>
  <p style="color:var(--muted);max-width:70ch">{esc(CAT_INTRO[key])}</p>
  <p style="color:var(--muted)">{len(items)} devices in this category, {len(live)} with a recorded version.</p>
  {f'<div class="browse"><span>Brands</span>{brand_links}</div>' if brand_links else ""}
  {f'<h2>Latest releases</h2>{device_list(recent)}' if recent else ""}
  <h2>All {esc(CAT_PHRASE[key])} devices</h2>
  {device_list(sorted(items, key=lambda x: (not is_live(x), x["brand"], x["model"])))}
  <div class="browse" style="margin-top:2rem"><span>Other categories</span>{other_cats}</div>
</div>
""" + signup() + FOOT


def brand_page(brand, items):
    live = by_recent(items)
    cats = sorted({CATS[d["category"]] for d in items})
    software = all(d["category"] == "A" for d in items)
    what = "releases" if software else "firmware updates"
    unit = "projects" if software else "devices"
    title = fit_title([f"{brand} {what} — {len(items)} {unit} tracked | Firmwarely",
                       f"{brand} {what} | Firmwarely",
                       f"{brand} {what}"])
    newest = live[0] if live else None
    desc = fit_desc([(f"Latest {brand} {'versions' if software else 'firmware'} for {len(items)} {unit}, checked every 30 minutes. Newest release: {newest['model']} {newest['version']} on {fmt(newest.get('released'))}." if newest
                      else f"{brand} {'versions' if software else 'firmware'} for {len(items)} {unit}, checked every 30 minutes with release notes and update guides."),
                     f"{brand} versions, release notes and update alerts for {len(items)} {unit}.",
                     f"{brand} {what} and alerts."])
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Devices", "item": f"{SITE}/devices/"},
            {"@type": "ListItem", "position": 2, "name": brand, "item": f"{SITE}{brand_path(brand)}"}]},
        {"@type": "ItemList", "name": f"{brand} firmware", "numberOfItems": len(items),
         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": f"{d['brand']} {d['model']}",
                              "url": f"{SITE}/devices/{d['id']}/"} for i, d in enumerate(items)]}]}
    extra = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
    intro = (f"Firmwarely tracks {len(items)} {brand} {unit} across {', '.join(CAT_PHRASE[k] for k in CATS if any(d['category'] == k for d in items))}. "
             + (f"The most recent {brand} release we recorded is {newest['model']} {newest['version']} on {fmt(newest.get('released'))}. " if newest else "")
             + "Each device page has the current version, release notes, version history and how to update.")
    cat_links = "".join(f'<a class="chip" href="{cat_path(k)}">{esc(CATS[k])}</a>' for k in CATS if any(d["category"] == k for d in items))
    return head(title, desc, brand_path(brand), extra) + f"""
<div class="wrap brandlist" style="padding-top:2rem">
  <div class="crumbs"><a href="/devices/">Devices</a> / {esc(brand)}</div>
  <h1 class="dev-h">{esc(brand)} {what}</h1>
  <p style="color:var(--muted);max-width:70ch">{esc(intro)}</p>
  <div class="browse"><span>Categories</span>{cat_links}</div>
  <h2>{esc(brand)} {unit}</h2>
  {device_list(sorted(items, key=lambda x: (not is_live(x), x["model"])), show_brand=False)}
</div>
""" + signup(brand) + FOOT


# Stylised line-art of the device families we track: drawn here so the page needs no
# third-party images and nothing we don't have the rights to.
DEVICE_ART = [  # (label, category page, icon family)
    ("Routers & mesh", "R", "router"),
    ("NAS & storage", "N", "nas"),
    ("Security cameras", "S", "camera"),
    ("Doorbells & hubs", "S", "doorbell"),
    ("Consoles", "C", "console"),
    ("Drones", "C", "drone"),
    ("E-bikes", "C", "ebike"),
    ("3D printers & makers", "M", "printer"),
]


def pro_page():
    title = "Firmwarely Pro waitlist — founding-member price | Firmwarely"
    desc = "Join the Firmwarely Pro waitlist: unlimited devices, the dashboard and daily alerts at the founding-member price of $4.99 a month, locked in."
    art = "".join(
        f'<a href="{cat_path(key)}" aria-label="{esc(label)}">{icon_svg(icon, "")}<span>{esc(label)}</span></a>'
        for label, key, icon in DEVICE_ART)
    return head(title, desc, "/pro/") + f"""
<div class="wrap">
  <div class="pro-hero">
    <div id="signup">
      <p class="kicker">Good call</p>
      <h1>You're about to stop finding out about firmware the hard way.</h1>
      <p class="lede">Pro opens the moment our payment provider finishes its checks. Leave your email and you're first in line, at the founding-member price, locked in for as long as you stay.</p>
      <p class="pro-price">$4.99<small> /month · founding-member price</small></p>
      <form id="signup-form" novalidate>
        <label class="sr" for="s-email">Email address</label>
        <div class="row">
          <input id="s-email" name="email" type="email" placeholder="you@example.com" autocomplete="email" required>
          <button class="btn" type="submit">Save my place</button>
        </div>
        <input type="hidden" name="plan" value="pro">
        <input type="hidden" name="devices" value="">
        <div id="s-msg" aria-live="polite"></div>
        <p class="fine" style="margin:.25rem 0 0">One email when Pro opens. No card needed today. Unsubscribe any time.</p>
      </form>
    </div>
    <div class="gallery" aria-label="Device families Firmwarely tracks">{art}</div>
  </div>

  <h2 style="margin-top:1.5rem">What you're signing up for</h2>
  <div class="pro-perks">
    <div class="card"><h3>Every device you own</h3><p>No three-device cap. Add the router, both NAS boxes, every camera and the kids' console.</p></div>
    <div class="card"><h3>The dashboard</h3><p>One screen showing what's current, what has an update and what has a security fix waiting, with a button to go apply it.</p></div>
    <div class="card"><h3>One email a day, when it matters</h3><p>Each morning, a single email covering everything of yours that changed in the last 24 hours, security fixes first. Silence otherwise.</p></div>
  </div>

  <h2 style="margin-top:2.5rem">Meanwhile</h2>
  <p style="color:var(--muted);max-width:64ch">The free plan is live today. <a href="/my-devices.html">Save up to three devices</a> and see which need an update, or <a href="/devices/">browse the {'{n}'} devices we watch</a>. When Pro opens, your list carries over.</p>
</div>
""" + FOOT


def not_found_page(devices):
    cats = "".join(f'<a class="chip" href="{cat_path(k)}">{esc(CATS[k])}</a>' for k in CATS)
    recent = by_recent(devices)[:6]
    return head("Page not found | Firmwarely", "That page doesn't exist. Browse the devices Firmwarely tracks.", "/404.html", noindex=True) + f"""
<div class="wrap brandlist" style="padding:3rem 0 4rem;max-width:760px">
  <h1 class="dev-h">That page isn't here</h1>
  <p style="color:var(--muted)">The link may be old, or the device may be listed under a different name. Try a search, or browse by category.</p>
  <form action="/" method="get" class="search" style="margin:1.25rem 0"><label class="sr" for="q">Search devices</label><input id="q" name="q" type="search" placeholder="Search brand or model"></form>
  <div class="browse"><span>Categories</span>{cats}</div>
  <h2>Recently updated</h2>
  {device_list(recent)}
  <p style="margin-top:1.5rem"><a class="btn ghost" href="/devices/">Every device we watch</a></p>
</div>
""" + FOOT


def index_page(devices, brand_pages=()):
    parts = []
    for cat_key, cat_name in CATS.items():
        items = [d for d in devices if d["category"] == cat_key]
        if not items:
            continue
        parts.append(f'<h2 id="{cat_key}"><a href="{cat_path(cat_key)}">{esc(cat_name)}</a></h2><ul>')
        for d in sorted(items, key=lambda x: (x["status"] == "pending", x["brand"], x["model"])):
            v = esc(d["version"]) if d.get("version") and d["status"] != "pending" else "watching soon"
            parts.append(f'<li><a href="/devices/{d["id"]}/">{icon_svg(d.get("icon"))}{esc(d["brand"])} {esc(d["model"])}</a><span>{v}</span></li>')
        parts.append("</ul>")
    title = "Firmware update tracker — every device we watch | Firmwarely"
    desc = f"Latest firmware versions for {len(devices)} routers, NAS, smart home devices, consoles, PCs, TVs, maker gear and self-hosted apps, checked every 30 minutes against manufacturer release pages and project feeds."
    return head(title, desc, "/devices/") + f"""
<div class="wrap brandlist" style="padding-top:2rem">
  <h1 class="dev-h">Every device we watch</h1>
  <p style="color:var(--muted)">Checked every 30 minutes. Tap a device for its latest firmware, release notes and history.</p>
  <div class="browse"><span>Categories</span>{''.join(f'<a class="chip" href="{cat_path(k)}">{esc(v)}</a>' for k, v in CATS.items())}</div>
  <div class="browse"><span>Brands</span>{''.join(f'<a class="chip" href="{brand_path(b)}">{esc(b)}</a>' for b in brand_pages)}</div>
  {''.join(parts)}
</div>
""" + signup() + FOOT


def simple_page(title, desc, path, body, noindex=False):
    return head(title, desc, path, noindex=noindex) + f"""
<div class="wrap" style="padding:3rem 0 4rem;max-width:760px">
{body}
</div>
""" + FOOT


def thanks_page():
    return simple_page("You're on Firmwarely Pro", "Thanks for upgrading to Firmwarely Pro.", "/pro/thanks/", """
<h1 class="dev-h">You're on Pro. Thank you.</h1>
<p style="font-size:1.1rem;margin-top:1rem;color:var(--muted)">Your receipt is on its way from Stripe. Here's what happens next:</p>
<ul style="color:var(--muted);padding-left:1.2rem">
  <li><strong style="color:var(--text)">Daily alerts.</strong> Each morning you get one email covering every device of yours that changed in the last 24 hours, security fixes first.</li>
  <li><strong style="color:var(--text)">Unlimited devices and the dashboard.</strong> Sign in to <a href="/my-devices.html">My devices</a> with the email you paid with, add everything you own, and the <a href="/dashboard.html">dashboard</a> shows what needs attention.</li>
  <li><strong style="color:var(--text)">End-of-life notices.</strong> You'll hear when a manufacturer says updates are stopping for something you own.</li>
</ul>
<p style="color:var(--muted)">Use the same email address you paid with when you sign up for alerts, so we can link them. Manage or cancel any time from the link in your Stripe receipt.</p>
<p style="margin-top:2rem"><a class="btn" href="/devices/">Browse the devices we watch</a></p>
""", noindex=True)


def product_link(d):
    """A GitHub project has no price; call it what it is and don't tag it as sponsored."""
    u = d.get("product_url")
    if not u or not re.match(r"^https?://", u, re.I):
        return ""
    if re.match(r"^https?://(www\.)?github\.com/", u, re.I):
        return f'<p style="margin:1rem 0 0"><a href="{esc(u)}" target="_blank" rel="noopener">Project page ↗</a></p>'
    return f'<p style="margin:1rem 0 0"><a href="{esc(u)}" target="_blank" rel="nofollow sponsored noopener">See current price ↗</a></p>'


def legal_page():
    return simple_page("Privacy & terms — Firmwarely", "Firmwarely privacy policy and terms of service.", "/legal/", """
<h1 class="dev-h">Privacy &amp; terms</h1>
<p style="color:var(--muted)">Last updated September 13, 2026. Firmwarely is an independent service operated by an individual in Iowa, USA. Questions: <a href="mailto:hello@firmwarely.com">hello@firmwarely.com</a>.</p>
<div class="faq">
<h2 style="margin-top:2rem">Privacy policy</h2>
<h3>What we collect</h3><p>Your email address when you subscribe, the device names you choose to tell us about, and standard web server logs. If you buy Pro, Stripe collects your payment details; we never see your card number. We store the email you paid with and whether your subscription is active.</p>
<h3>How we use it</h3><p>To send you the firmware update emails you asked for, to manage your subscription, and to understand which devices people want tracked. We don't sell or rent your data.</p>
<h3>Who we share it with</h3><p>Beehiiv (subscriber list and newsletter delivery), Resend (sign-in links and device alerts), Stripe (payments), Vercel (hosting and sign-in API), and GitHub (where our data pipeline runs). Each is bound by its own privacy policy. We share only what's needed for them to do their job.</p>
<h3>Affiliate links</h3><p>Some product links may earn us a commission at no extra cost to you. They don't affect which updates we report.</p>
<h3>Your choices</h3><p>Every email has an unsubscribe link. To delete your data entirely, email us and we'll remove it within 30 days. We set one cookie, only when you sign in, so you stay signed in for 30 days. Your device list is kept in your browser's local storage and, once you sign in, in your account. There are no advertising or analytics trackers.</p>
<h2 style="margin-top:2.5rem">Terms of service</h2>
<h3>What Firmwarely is</h3><p>An information service that watches manufacturers' public release pages and tells you what changed. It is not affiliated with any manufacturer. Device and brand names belong to their owners.</p>
<h3>What it isn't</h3><p>We don't distribute firmware, and we can't guarantee we catch every release or that release notes are accurate — manufacturers change their pages without notice. Always download firmware from the official source and read the manufacturer's notes before installing. You're responsible for updates you apply to your own devices.</p>
<h3>Pro subscription</h3><p>Pro is billed monthly through Stripe and renews automatically until cancelled. Cancel any time from the link in your receipt; you keep Pro until the end of the period you've paid for. If you're unhappy in the first 30 days, email us for a full refund.</p>
<h3>Liability</h3><p>The service is provided as-is. To the extent permitted by law, we're not liable for any loss arising from use of the service, including from firmware updates you choose to install or not install. Our total liability is limited to what you paid us in the previous 12 months.</p>
<h3>Changes</h3><p>We may update these terms; material changes will be announced by email. Continued use means you accept the updated terms.</p>
</div>
""")


def main():
    global STYLES
    STYLES = styles()
    data = json.loads((ROOT / "devices.json").read_text())
    devices = data["devices"]
    by_brand, by_cat = {}, {}
    for d in devices:
        by_brand.setdefault(d["brand"], []).append(d)
        by_cat.setdefault(d["category"], []).append(d)
    ctx = {"by_brand": by_brand, "by_cat": by_cat}
    brand_counts = {b: len(v) for b, v in by_brand.items()}
    brand_pages = sorted((b for b, n in brand_counts.items() if n >= BRAND_MIN), key=lambda b: (-brand_counts[b], b))

    out = ROOT / "devices"
    out.mkdir(exist_ok=True)
    for d in devices:
        p = out / d["id"]
        p.mkdir(exist_ok=True)
        (p / "index.html").write_text(device_page(d, ctx))
    (out / "index.html").write_text(index_page(devices, brand_pages))
    for key in CATS:
        p = ROOT / "category" / CAT_SLUG[key]
        p.mkdir(parents=True, exist_ok=True)
        (p / "index.html").write_text(category_page(key, devices, brand_counts))
    for b in brand_pages:
        p = ROOT / "brands" / slugify(b)
        p.mkdir(parents=True, exist_ok=True)
        (p / "index.html").write_text(brand_page(b, by_brand[b]))
    for folder, content in (("pro/thanks", thanks_page()), ("legal", legal_page())):
        d = ROOT / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(content)
    (ROOT / "404.html").write_text(not_found_page(devices))

    # a device or brand that left the catalogue must not leave a stale page behind
    keep = {"devices": {d["id"] for d in devices}, "brands": {slugify(b) for b in brand_pages},
            "category": set(CAT_SLUG.values())}
    import shutil
    pruned = 0
    for folder, names in keep.items():
        for child in (ROOT / folder).iterdir():
            if child.is_dir() and child.name not in names:
                shutil.rmtree(child); pruned += 1
    if pruned:
        print(f"pruned {pruned} stale page folder(s)")
    (ROOT / "pro" / "index.html").write_text(pro_page().replace("{n}", str(len(devices))))

    # sitemap: one entry per indexable page, with the date its content last actually moved
    today = datetime.now(timezone.utc).date().isoformat()
    gen = (data.get("generated") or today)[:10]

    def dev_mod(d):
        dates = [x.get("released") for x in (d.get("history") or []) if x.get("released")] + [d.get("released")]
        dates = [x for x in dates if x]
        return max(dates) if dates else gen

    entries = [(f"{SITE}/", gen), (f"{SITE}/devices/", gen), (f"{SITE}/my-devices.html", today),
               (f"{SITE}/pro/", "2026-09-14"), (f"{SITE}/legal/", "2026-09-13")]
    entries += [(f"{SITE}{cat_path(k)}", max([dev_mod(d) for d in by_cat.get(k, [])] or [gen])) for k in CATS]
    entries += [(f"{SITE}{brand_path(b)}", max(dev_mod(d) for d in by_brand[b])) for b in brand_pages]
    entries += [(f"{SITE}/devices/{d['id']}/", dev_mod(d)) for d in devices]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{u}</loc><lastmod>{m}</lastmod></url>" for u, m in entries]
    sm.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(sm) + "\n")
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {SITE}/sitemap.xml\n")
    print(f"built {len(devices)} device pages, {len(CATS)} category pages, {len(brand_pages)} brand pages, "
          f"index, 404, sitemap ({len(entries)} urls)")


if __name__ == "__main__":
    main()
