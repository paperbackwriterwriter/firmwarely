#!/usr/bin/env python3
"""
Builds static pages from devices.json:

  devices/<id>/index.html   one page per device  → firmwarely.com/devices/<id>
  devices/index.html        all devices, grouped by brand
  pro/thanks/index.html     post-checkout page
  legal/index.html          privacy + terms
  sitemap.xml, robots.txt

Reuses the <style> block from index.html so pages match the site. Run after fetch.py.
"""
import json, re, html
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://firmwarely.com"
CATS = {"R": "Routers & networking", "N": "NAS & storage", "S": "Smart home & cameras",
        "C": "Consoles, drones & e-bikes", "M": "Makers & open firmware"}
LABEL = {"critical": "critical fix", "update": "new version", "current": "current",
         "pending": "watching soon", "eol": "end of life", "stale": "no recent release"}
GUIDES = json.loads((ROOT / "update_guides.json").read_text()) if (ROOT / "update_guides.json").exists() else {}


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
  .brandlist li span{font-family:var(--mono);font-size:.85rem;color:var(--muted)}
"""


def head(title, desc, path, extra=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}{path}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE}{path}">
<meta property="og:type" content="website">
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


def device_page(d):
    name = f"{d['brand']} {d['model']}"
    path = f"/devices/{d['id']}/"
    cat = CATS.get(d["category"], "")
    live = d.get("version") and d["status"] != "pending"
    # plenty of names already end in "firmware" ("Klipper 3D printer firmware"), so only
    # add the word when it isn't there — otherwise the title stutters
    fw = "" if "firmware" in name.lower() else " firmware"
    if live:
        title = f"{name}{fw} — latest version {d['version']} ({month(d['released'])}) | Firmwarely"
        desc = f"Latest {name} version is {d['version']}, released {fmt(d['released'])}. Release notes, version history, and email alerts when a new or critical update ships."
    else:
        title = f"{name}{fw} updates — alerts & release tracking | Firmwarely"
        desc = f"Track {name}{fw} updates. Firmwarely watches manufacturer release pages and emails you when a new or security update ships."

    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Devices", "item": f"{SITE}/devices/"},
        {"@type": "ListItem", "position": 2, "name": name, "item": f"{SITE}{path}"}]}
    extra = f'<script type="application/ld+json">{json.dumps(ld)}</script>'

    notes = d.get("notes") or ""
    hist = list(d.get("history") or [])
    if hist and hist[0].get("version") == d.get("version") and d.get("released"):
        hist[0] = {**hist[0], "released": d["released"]}
    rows = "".join(f"<tr><td>{esc(h['version'])}</td><td>{fmt(h.get('released'))}</td></tr>" for h in hist[:6]) \
           or (f"<tr><td>{esc(d['version'])}</td><td>{fmt(d.get('released'))}</td></tr>" if live else "")

    steps, upd = guide(d)
    step_html = "".join(f"<li>{esc(x)}</li>" for x in steps)
    # the page's whole point: one click to the place that actually updates the thing
    cta = (f'<a class="btn" href="{esc(upd)}" target="_blank" rel="noopener">Open update page ↗</a>'
           if upd else "")
    how = f"""
      <h2 id="update" style="margin-top:2rem">How to update the {esc(name)}</h2>
      <div class="card">
        {cta}
        <ol class="upd-steps">{step_html}</ol>
        <p class="fine" style="margin:.75rem 0 0">Always download firmware from the manufacturer or project itself.
        Firmwarely links out; it never hosts firmware.</p>
      </div>"""

    body = head(title, desc, path, extra)
    body += f"""
<div class="wrap">
  <div class="crumbs"><a href="/devices/">Devices</a> / <a href="/devices/#{d['category']}">{esc(cat)}</a> / {esc(name)}</div>
  <div class="dev">
    <div>
      <h1 class="dev-h">{esc(name)} firmware</h1>
      <span class="status {d['status']}">{LABEL.get(d['status'], d['status'])}</span>
      <div class="card" style="margin-top:1.25rem">
        <dl class="kv">
          <dt>Latest firmware</dt><dd>{esc(d['version']) if live else "—"}</dd>
          <dt>Released</dt><dd>{fmt(d.get('released')) if live else "—"}</dd>
          <dt>Category</dt><dd>{esc(cat)}</dd>
          <dt>Last checked</dt><dd>{fmt((d.get('checked') or '')[:10]) if d.get('checked') else "—"}</dd>
        </dl>
      </div>
      {how}
      <h2 style="margin-top:2rem">What changed</h2>
      <p style="color:var(--muted)">{esc(notes) if notes else ("Not tracked yet. Sign up below and we'll prioritise this device." if not live else "See the manufacturer's release notes for details.")}</p>
      {f'<p><a href="{esc(d["source_url"])}" target="_blank" rel="noopener">Manufacturer release notes ↗</a></p>' if d.get("source_url") and live else ""}
      {f'<h2 style="margin-top:2rem">Version history</h2><table class="hist">{rows}</table>' if rows else ""}
      <div class="faq">
        <h2 style="margin-top:2rem">FAQ</h2>
        <h3>How do I update the {esc(name)}?</h3>
        <p><a href="#update">See the step-by-step above.</a> {esc(HOWTO.get(d['category'], ''))}</p>
        <h3>How does Firmwarely know when there's a new version?</h3>
        <p>Every night we read the manufacturer's official release page{(" for the " + esc(name)) if live else ""} and record the version, date and changelog. If anything changed, subscribers watching this device get an email.</p>
        <h3>Is this an official {esc(d['brand'])} page?</h3>
        <p>No. Firmwarely is independent. Device and brand names belong to their manufacturers; always download firmware from the official source.</p>
      </div>
    </div>
    <aside>
      <div class="card">
        <h2 style="margin:0 0 .5rem;font-size:1.05rem">Watch this device</h2>
        <p style="color:var(--muted);font-size:.95rem;margin:0 0 .75rem">Get one email when {esc(d['brand'])} ships a new or security firmware for the {esc(d['model'])}.</p>
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


def index_page(devices):
    parts = []
    for cat_key, cat_name in CATS.items():
        items = [d for d in devices if d["category"] == cat_key]
        if not items:
            continue
        parts.append(f'<h2 id="{cat_key}">{esc(cat_name)}</h2><ul>')
        for d in sorted(items, key=lambda x: (x["status"] == "pending", x["brand"], x["model"])):
            v = esc(d["version"]) if d.get("version") and d["status"] != "pending" else "watching soon"
            parts.append(f'<li><a href="/devices/{d["id"]}/">{esc(d["brand"])} {esc(d["model"])}</a><span>{v}</span></li>')
        parts.append("</ul>")
    title = "Firmware update tracker — every device we watch | Firmwarely"
    desc = f"Latest firmware versions for {len(devices)} routers, NAS, smart home devices, consoles and maker gear, checked nightly against manufacturer release pages."
    return head(title, desc, "/devices/") + f"""
<div class="wrap brandlist" style="padding-top:2rem">
  <h1 class="dev-h">Every device we watch</h1>
  <p style="color:var(--muted)">Checked every night. Tap a device for its latest firmware, release notes and history.</p>
  {''.join(parts)}
</div>
""" + signup() + FOOT


def simple_page(title, desc, path, body):
    return head(title, desc, path) + f"""
<div class="wrap" style="padding:3rem 0 4rem;max-width:760px">
{body}
</div>
""" + FOOT


def thanks_page():
    return simple_page("You're on Firmwarely Pro", "Thanks for upgrading to Firmwarely Pro.", "/pro/thanks/", """
<h1 class="dev-h">You're on Pro. Thank you.</h1>
<p style="font-size:1.1rem;margin-top:1rem;color:var(--muted)">Your receipt is on its way from Stripe. Here's what happens next:</p>
<ul style="color:var(--muted);padding-left:1.2rem">
  <li><strong style="color:var(--text)">Instant alerts.</strong> When a security fix or new firmware ships for a device you watch, you'll get an email the same day instead of waiting for the weekly digest.</li>
  <li><strong style="color:var(--text)">Unlimited devices.</strong> Reply to any Firmwarely email with the devices you own and we'll add them to your watch list.</li>
  <li><strong style="color:var(--text)">End-of-life warnings.</strong> You'll hear when a manufacturer stops updating something you own.</li>
</ul>
<p style="color:var(--muted)">Use the same email address you paid with when you sign up for alerts, so we can link them. Manage or cancel any time from the link in your Stripe receipt.</p>
<p style="margin-top:2rem"><a class="btn" href="/devices/">Browse the devices we watch</a></p>
""")


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
    out = ROOT / "devices"
    out.mkdir(exist_ok=True)
    for d in devices:
        p = out / d["id"]
        p.mkdir(exist_ok=True)
        (p / "index.html").write_text(device_page(d))
    (out / "index.html").write_text(index_page(devices))
    for folder, content in (("pro/thanks", thanks_page()), ("legal", legal_page())):
        d = ROOT / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(content)

    today = datetime.now(timezone.utc).date().isoformat()
    urls = ([f"{SITE}/", f"{SITE}/devices/", f"{SITE}/my-devices.html", f"{SITE}/legal/"]
            + [f"{SITE}/devices/{d['id']}/" for d in devices])
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls]
    sm.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(sm) + "\n")
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    print(f"built {len(devices)} device pages + index, sitemap ({len(urls)} urls)")


if __name__ == "__main__":
    main()
