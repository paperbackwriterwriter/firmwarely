#!/usr/bin/env python3
"""
Self-test for the alert pipeline. No network, no files written, no framework.

    python3 scripts/selftest.py

Covers the logic that decides who gets mailed, because the cost of getting it wrong is
a wrong email to every subscriber rather than a stack trace.
"""
import json, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("BEEHIIV_API_KEY", "test")
os.environ.setdefault("BEEHIIV_PUB_ID", "test")
os.environ.setdefault("RESEND_API_KEY", "test")

import fetch
import build_pages
import user_alerts as ua

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")
        FAILED.append(label)


# ---- version comparison must agree with my-devices.html ----
def test_compare():
    cases = [(("1.0.0", "1.0.1"), -1), (("1.0.1", "1.0.0"), 1), (("1.0.0", "1.0.0"), 0),
             (("v24.10.8", "24.10.8"), 0), (("1.2", "1.2.0"), 0), (("1.9", "1.10"), -1),
             (("", "1.0"), None), (("1.0", ""), None), ((None, "1.0"), None)]
    for (a, b), want in cases:
        check(f"compare({a!r}, {b!r})", ua.compare(a, b), want)


# ---- a device joining the catalog is not a release ----
def test_new_release():
    prev = {"known": {"version": "1.0.0"}, "seen-but-empty": {"version": None}}
    cases = [("first version for a brand-new device", {"id": "new", "tracked": True, "version": "3.2.1"}, False),
             ("same version as last night", {"id": "known", "tracked": True, "version": "1.0.0"}, False),
             ("a genuine bump", {"id": "known", "tracked": True, "version": "1.0.1"}, True),
             ("source resolves for the first time", {"id": "seen-but-empty", "tracked": True, "version": "9.9"}, False),
             ("manual / untracked entry", {"id": "known", "tracked": False, "version": "2.0"}, False),
             ("tracked but the fetch failed", {"id": "known", "tracked": True, "version": None}, False)]
    for label, dev, want in cases:
        check(f"is_new_release: {label}", fetch.is_new_release(dev, prev), want)


# ---- saved-device field written by /api/me, in both shapes ----
def test_saved_devices():
    check("saved_devices: compact pairs", ua.saved_devices('[["a","1"],["b",""]]'),
          [{"id": "a", "version": "1"}, {"id": "b", "version": ""}])
    check("saved_devices: object form", ua.saved_devices('[{"id":"a","version":"1"}]'),
          [{"id": "a", "version": "1"}])
    for junk in ("", "{oops", "null", '"a string"', "[1,2,3]"):
        check(f"saved_devices: junk {junk!r} is empty, not a crash", ua.saved_devices(junk), [])


# ---- routing: exactly one email each, personal when we can, digest otherwise ----
def test_routing():
    changed = {"date": "2026-09-14", "forced": False, "count": 1, "devices": [
        {"id": "dev1", "brand": "Acme", "model": "Router", "status": "critical",
         "version": "2.0", "previous": "1.0", "released": "2026-09-13", "eol": False,
         "notes": "Fixes a thing.", "source_url": "https://e/x",
         "page_url": "https://firmwarely.com/devices/dev1/"}]}
    people = [
        ("behind@e.com", "pro", [["dev1", "1.0"]], "personal"),
        ("blank@e.com", "pro", [["dev1", ""]], "personal"),
        ("current@e.com", "pro", [["dev1", "2.0"]], "digest"),
        ("ahead@e.com", "pro", [["dev1", "2.1"]], "digest"),
        ("other@e.com", "pro", [["dev2", "1.0"]], "digest"),
        ("empty@e.com", "pro", None, "digest"),
        ("free@e.com", "free", [["dev1", "1.0"]], None),
    ]
    tmp = Path(tempfile.mkdtemp()) / "changed.json"
    tmp.write_text(json.dumps(changed))
    orig_changed, orig_send, orig_subs, orig_gap = ua.CHANGED, ua.send, ua.subscribers, ua.SEND_GAP
    sent = {}
    try:
        ua.CHANGED, ua.SEND_GAP = tmp, 0
        ua.PLANS = ["pro"]
        ua.subscribers = lambda k, p: iter([
            {"email": e, "custom_fields": [{"name": "plan", "value": plan}]
             + ([{"name": "devices", "value": json.dumps(d)}] if d is not None else [])}
            for e, plan, d, _ in people])
        ua.send = lambda to, subj, body: (sent.__setitem__(to, subj), (True, ""))[1]
        rc = ua.main()
    finally:
        ua.CHANGED, ua.send, ua.subscribers, ua.SEND_GAP = orig_changed, orig_send, orig_subs, orig_gap

    check("routing: exit code", rc, 0)
    for email, _, _, want in people:
        subj = sent.get(email)
        got = None if subj is None else ("digest" if subj.startswith("Firmware digest") else "personal")
        check(f"routing: {email} -> {want or 'no mail'}", got, want)


# ---- a forced run must not reach real subscribers ----
def test_forced_guard():
    tmp = Path(tempfile.mkdtemp()) / "changed.json"
    tmp.write_text(json.dumps({"date": "2026-09-14", "forced": True, "count": 1, "devices": [
        {"id": "d", "brand": "B", "model": "M", "status": "update", "version": "2",
         "previous": "1", "released": "2026-09-13", "notes": "", "source_url": "",
         "page_url": "https://firmwarely.com/devices/d/"}]}))
    orig_changed, orig_subs, orig_test = ua.CHANGED, ua.subscribers, ua.TEST_TO
    reached = []
    try:
        ua.CHANGED, ua.TEST_TO = tmp, ""
        ua.subscribers = lambda k, p: reached.append(1) or iter([])
        rc = ua.main()
    finally:
        ua.CHANGED, ua.subscribers, ua.TEST_TO = orig_changed, orig_subs, orig_test
    check("forced run without a test address sends nothing", (rc, reached), (0, []))


# ---- every device must end up with usable update instructions ----
def test_update_guides():
    guides = build_pages.GUIDES
    devs = json.loads((Path(__file__).resolve().parent.parent / "devices.json").read_text())["devices"]
    brands = {d["brand"] for d in devs}
    ids = {d["id"] for d in devs}

    missing = [d["id"] for d in devs if not build_pages.guide(d)[0]]
    check("every device resolves to update steps", missing, [])
    blank = [d["id"] for d in devs if any(not x.strip() for x in build_pages.guide(d)[0])]
    check("no blank step text", blank, [])

    # a guide keyed to a brand or id that no longer exists is silently dead
    check("no brand guide points at a missing brand",
          sorted(b for b in guides.get("by_brand", {}) if b not in brands), [])
    check("no id guide points at a missing device",
          sorted(i for i in guides.get("by_id", {}) if i not in ids), [])
    check("every flash_id is a real device",
          sorted(i for i in guides.get("flash_ids", []) if i not in ids), [])

    # flashed firmware must not be told to "docker compose pull"
    by_id = {d["id"]: d for d in devs}
    for dev_id, want in [("klipper", "flash"), ("qmk-firmware", "flash"),
                         ("betaflight", "flash"), ("sonarr", "app"), ("vaultwarden", "app")]:
        if dev_id not in by_id:
            continue
        steps = " ".join(build_pages.guide(by_id[dev_id])[0]).lower()
        got = "flash" if "board" in steps or "flasher" in steps else ("app" if "docker" in steps else "?")
        check(f"guide kind for {dev_id}", got, want)

    # the update list must render as its own numbered list. ".steps" belongs to the
    # homepage "how it works" grid, which forces three columns and list-style:none onto
    # anything using it — reusing that class silently unnumbers these steps.
    css = build_pages.styles()
    build_pages.STYLES = css          # main() sets this; we render a page without it
    sample = build_pages.device_page(devs[0])
    check("update steps use their own class", 'class="upd-steps"' in sample, True)
    check("update steps don't reuse the homepage .steps grid", 'class="steps"' in sample, False)
    check("the class is actually styled as a numbered list",
          "ol.upd-steps" in css and "list-style:decimal" in css, True)

    # a device with no download page still has to be actionable
    for dev_id in ("ring-battery-doorbell-plus", "dji-mavic-4-pro"):
        if dev_id in by_id:
            steps, url = build_pages.guide(by_id[dev_id])
            check(f"{dev_id}: app-updated, instructions instead of a dead link",
                  (bool(steps), url), (True, None))


# ---- upstream release notes end up in innerHTML on every page ----
def test_clean():
    cases = [
        ("script tag is neutralised", "<script>alert(1)</script>ok", "alert(1) ok"),
        ("entity-hidden tag is stripped", "&lt;img src=x onerror=alert(1)&gt;", ""),
        ("double-encoded tag is stripped", "&amp;lt;b&amp;gt;x", "x"),
        ("markdown link keeps its text", "see [the notes](https://x.y/z) here", "see the notes here"),
        ("markdown headings and bullets drop their markers", "## Fixes\n- one\n* two\n1. three", "Fixes one two three"),
        ("inline code and emphasis lose their fences", "use `foo` and **bar** and _baz_", "use foo and bar and _baz_"),
        ("issue refs can't ping anyone", "fixes #123 and #4", "fixes #\u200b123 and #\u200b4"),
        ("long text is cut with an ellipsis", "x" * 400, "x" * 299 + "…"),
    ]
    for label, raw, want in cases:
        check(f"clean: {label}", fetch.clean(raw), want)


# ---- status badges must not call a 2020 release "current" ----
def test_classify():
    from datetime import timedelta
    day = lambda n: (fetch.TODAY - timedelta(days=n)).isoformat()
    cases = [("no version yet", {"version": None, "released": None}, "pending"),
             ("security fix this month", {"version": "1.1", "released": day(10), "notes": "Fixes a security vulnerability (CVE-2026-1)"}, "critical"),
             ("plain release this month", {"version": "1.1", "released": day(10), "notes": "bug fixes"}, "update"),
             ("release last spring", {"version": "1.1", "released": day(200), "notes": ""}, "current"),
             ("nothing for two years", {"version": "1.1", "released": day(730), "notes": ""}, "stale"),
             ("explicitly end of life", {"version": "1.1", "released": day(10), "eol": True}, "eol")]
    for label, dev, want in cases:
        check(f"classify: {label}", fetch.classify(dev), want)
    check("every status has a label on the site", all(f'{k}:"' in Path("index.html").read_text() for k in
          ("critical", "update", "current", "pending", "eol", "stale")), True)
    check("every status has a label on device pages",
          set(build_pages.LABEL) >= {"critical", "update", "current", "pending", "eol", "stale"}, True)


# ---- the homepage shows live data or says it can't, never invented rows ----
def test_homepage_honesty():
    html = Path("index.html").read_text()
    check("no seed/placeholder device list", "SEED" in html, False)
    check("failure state is spelled out", "Couldn't load the live device list" in html, True)
    check("upstream strings are escaped on the way into innerHTML", "const esc =" in html, True)
    for field in ("d.b", "d.m", "d.v", "d.n"):
        check(f"no raw ${{{field}}} interpolation", "${" + field + "}" in html, False)
    check("[hidden] beats .btn display", "[hidden]{display:none!important}" in html, True)
    check("no 'weekly' promise left in the copy", "weekly" in html.lower(), False)
    for f in ("index.html", "my-devices.html", "dashboard.html"):
        check(f"{f} has a favicon", 'rel="icon"' in Path(f).read_text(), True)


# ---- generated pages: titles that fit, links that describe their target ----
def test_generated_pages():
    long_name = {"id": "x", "brand": "Ubiquiti", "model": "UniFi Access Points & Switches (device firmware, all models)",
                 "category": "R", "version": "8.0.76", "released": "2026-08-01", "status": "update", "notes": "", "source_url": "https://example.com"}
    build_pages.STYLES = build_pages.styles()
    import re
    for dev in (long_name, dict(long_name, version=None, status="pending")):
        page = build_pages.device_page(dev)
        title = re.search(r"<title>(.*?)</title>", page, re.S).group(1).replace("&amp;", "&")
        check(f"title fits ({dev['status']}): {title!r}", len(title) <= build_pages.TITLE_MAX, True)
    check("GitHub product link is a project page, not sponsored",
          build_pages.product_link({"product_url": "https://github.com/a/b"}),
          '<p style="margin:1rem 0 0"><a href="https://github.com/a/b" target="_blank" rel="noopener">Project page ↗</a></p>')
    check("store link is marked sponsored", 'rel="nofollow sponsored noopener">See current price' in
          build_pages.product_link({"product_url": "https://store.example.com/x"}), True)
    check("non-http product link is dropped", build_pages.product_link({"product_url": "javascript:alert(1)"}), "")
    check("canonicals use the www host the apex redirects to", build_pages.SITE, "https://www.firmwarely.com")


# ---- landing pages and the SEO plumbing around them ----
def test_landing_pages():
    import re
    data = json.loads(Path("devices.json").read_text())
    devs = data["devices"]
    build_pages.STYLES = build_pages.styles()
    by_brand = {}
    for d in devs:
        by_brand.setdefault(d["brand"], []).append(d)
    counts = {b: len(v) for b, v in by_brand.items()}
    ctx = {"by_brand": by_brand, "by_cat": {}}

    def meta(page):
        t = re.search(r"<title>(.*?)</title>", page, re.S).group(1)
        d = re.search(r'<meta name="description" content="(.*?)">', page).group(1)
        return html_unescape(t), html_unescape(d)
    html_unescape = __import__("html").unescape

    for key in build_pages.CATS:
        page = build_pages.category_page(key, devs, counts)
        t, d = meta(page)
        check(f"category {key}: title fits", len(t) <= build_pages.TITLE_MAX, True)
        check(f"category {key}: description fits", len(d) <= build_pages.DESC_MAX, True)
        check(f"category {key}: has prose and a device list", ("<h1" in page and "<ul>" in page and "ItemList" in page), True)
    big = max(by_brand, key=lambda b: counts[b])
    page = build_pages.brand_page(big, by_brand[big])
    t, d = meta(page)
    check(f"brand page {big}: title fits", len(t) <= build_pages.TITLE_MAX, True)
    check(f"brand page {big}: description fits", len(d) <= build_pages.DESC_MAX, True)
    check("brand page: canonical uses the slug", f'href="{build_pages.SITE}/brands/{build_pages.slugify(big)}/"' in page, True)
    check("slugify handles punctuation", build_pages.slugify("Bambu Lab / X1-Carbon (2nd gen)"), "bambu-lab-x1-carbon-2nd-gen")
    check("NAS keeps its case in prose", build_pages.CAT_PHRASE["N"], "NAS & storage")

    # every device page: description fits, dates are machine-readable, schema parses
    over, no_time, bad_ld = [], [], []
    for d in devs:
        page = build_pages.device_page(d, ctx)
        _, desc = meta(page)
        if len(desc) > build_pages.DESC_MAX:
            over.append(d["id"])
        if build_pages.is_live(d) and "<time datetime=" not in page:
            no_time.append(d["id"])
        for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
            try:
                json.loads(m)
            except Exception:
                bad_ld.append(d["id"])
    check("no device description over the limit", over[:3], [])
    check("live device pages carry <time datetime>", no_time[:3], [])
    check("structured data on every device page parses", bad_ld[:3], [])
    check("404 page is noindex", 'content="noindex"' in build_pages.not_found_page(devs), True)
    check("thanks page is noindex", 'content="noindex"' in build_pages.thanks_page(), True)
    check("social image exists", Path("og.png").exists(), True)

    pro = build_pages.pro_page()
    check("pro waitlist page signs people up as pro", 'name="plan" value="pro"' in pro, True)
    check("pro waitlist page has the email form the footer script drives", 'id="signup-form"' in pro and 'name="email"' in pro, True)
    check("pro waitlist page shows every device illustration", pro.count('viewBox="0 0 64 64"'), len(build_pages.DEVICE_ART))

    # icons: one file, parsed by both the browser and the page builder; every device maps to it
    check("icons.js has every family the pro gallery and the rules use",
          sorted(set(k for _, _, k in build_pages.DEVICE_ART) | set(k for k, _ in fetch.ICON_RULES) | set(fetch.ICON_BY_CATEGORY.values()) | {"app"}) <= sorted(build_pages.ICONS), True)
    unknown = sorted({d.get("icon") for d in devs} - set(build_pages.ICONS))
    check("every device in devices.json has a known icon", unknown, [])
    for name, cat, want in [("Nintendo Switch", "C", "console"), ("Ubiquiti UniFi Access Points & Switches (device firmware)", "R", "router"),
                            ("Reolink RLC-810A", "S", "camera"), ("Paperless-ngx Document scanner and archive", "N", "app"),
                            ("Synology DiskStation DS923+", "N", "nas"), ("Amazon Ring Video Doorbell Pro 2", "S", "doorbell"),
                            ("Ubiquiti UniFi Protect G4 Doorbell Pro", "S", "doorbell"), ("DJI Mini 4 Pro", "C", "drone"),
                            ("Klipper 3D printer firmware", "M", "printer"), ("grbl CNC motion controller firmware", "M", "board")]:
        b, m = name.split(" ", 1)
        check(f"icon_for: {name}", fetch.icon_for({"brand": b, "model": m, "category": cat}), want)
    check("homepage loads the shared icon file", '<script src="/icons.js" defer></script>' in Path("index.html").read_text(), True)
    check("homepage Pro button falls back to /pro/, not the footer form", 'pb.href = "/pro/"' in Path("index.html").read_text(), True)


for t in (test_compare, test_new_release, test_saved_devices, test_routing, test_forced_guard,
          test_update_guides, test_clean, test_classify, test_homepage_honesty, test_generated_pages,
          test_landing_pages):
    print(f"\n{t.__name__}")
    t()

print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
