#!/usr/bin/env python3
"""
Self-test for the alert pipeline. No network, no files written, no framework.

    python3 scripts/selftest.py

Covers the logic that decides who gets mailed, because the cost of getting it wrong is
a wrong email to every subscriber rather than a stack trace.
"""
import json, os, re, sys, tempfile
import html as _html
from pathlib import Path

html_unescape = _html.unescape

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


# ---- routing: mail only about your own devices; Pro daily, free weekly ----
def test_routing():
    change = {"id": "dev1", "brand": "Acme", "model": "Router", "status": "critical",
              "version": "2.0", "previous": "1.0", "released": "2026-09-13", "eol": False,
              "notes": "Fixes a thing.", "source_url": "https://e/x",
              "page_url": "https://www.firmwarely.com/devices/dev1/"}
    changed = {"date": "2026-09-14", "forced": False, "count": 1, "devices": [change]}
    people = [   # email, plan, saved devices, what they get on a weekday, what they get on the weekly day
        ("behind@e.com", "pro", [["dev1", "1.0"]], "daily", "daily"),
        ("blank@e.com", "pro", [["dev1", ""]], "daily", "daily"),
        ("current@e.com", "pro", [["dev1", "2.0"]], None, None),
        ("ahead@e.com", "pro", [["dev1", "2.1"]], None, None),
        ("other@e.com", "pro", [["dev2", "1.0"]], None, None),
        # no devices saved (the homepage signup asks only for an address): everything, on their plan's schedule
        ("empty@e.com", "pro", None, "daily digest", "daily digest"),
        ("emptylist@e.com", "pro", [], "daily digest", "daily digest"),
        ("freeempty@e.com", "free", None, None, "weekly digest"),
        ("free@e.com", "free", [["dev1", "1.0"]], None, "weekly"),
        ("freecurrent@e.com", "free", [["dev1", "2.0"]], None, None),
        ("freeother@e.com", "free", [["dev2", "1.0"]], None, None),
    ]
    tmpdir = Path(tempfile.mkdtemp())
    daily_f, weekly_f = tmpdir / "changed.json", tmpdir / "changed_weekly.json"
    daily_f.write_text(json.dumps(changed))

    def run(weekly, plans=("all",)):
        if weekly:
            weekly_f.write_text(json.dumps(dict(changed, weekly=True)))
        elif weekly_f.exists():
            weekly_f.unlink()
        saved = ua.CHANGED, ua.CHANGED_WEEKLY, ua.send, ua.subscribers, ua.SEND_GAP, ua.PLANS
        sent = {}
        try:
            ua.CHANGED, ua.CHANGED_WEEKLY, ua.SEND_GAP, ua.PLANS = daily_f, weekly_f, 0, list(plans)
            ua.subscribers = lambda k, p: iter([
                {"email": e, "custom_fields": [{"name": "plan", "value": plan}]
                 + ([{"name": "devices", "value": json.dumps(d)}] if d is not None else [])}
                for e, plan, d, _, _ in people])
            ua.send = lambda to, subj, body: (sent.__setitem__(to, (subj, body)), (True, ""))[1]
            rc = ua.main()
        finally:
            ua.CHANGED, ua.CHANGED_WEEKLY, ua.send, ua.subscribers, ua.SEND_GAP, ua.PLANS = saved
        check(f"routing: exit code ({'weekly day' if weekly else 'weekday'})", rc, 0)
        kind = lambda subj: ("weekly digest" if subj.startswith("Firmware this week") else
                             "daily digest" if subj.startswith("Firmware digest") else
                             "weekly" if subj.startswith("This week:") else "daily")
        return {e: kind(subj) for e, (subj, _) in sent.items()}, sent

    got, _ = run(weekly=False)
    for email, _, _, want, _ in people:
        check(f"routing: weekday, {email} -> {want or 'no mail'}", got.get(email), want)
    got, sent = run(weekly=True)
    for email, _, _, _, want in people:
        check(f"routing: weekly day, {email} -> {want or 'no mail'}", got.get(email), want)
    check("the weekly email says it's the free plan and points to Pro",
          "once a week" in sent["free@e.com"][1] and "/pro/" in sent["free@e.com"][1], True)
    check("the daily email doesn't", "once a week" in sent["behind@e.com"][1], False)
    digest = sent["freeempty@e.com"][1]
    check("the digest asks them to pick their devices", "/my-devices.html" in digest and "picked your devices" in digest, True)
    check("the digest lists what changed", "Acme Router" in digest and "2.0" in digest, True)
    check("the weekly digest says it's the free plan", "once a week" in digest, True)
    got, _ = run(weekly=True, plans=("pro",))
    check("USER_ALERT_PLANS=pro holds the free weekly back", sorted(got),
          ["behind@e.com", "blank@e.com", "empty@e.com", "emptylist@e.com"])

    # a long week: security fixes and EOL always in full, the rest capped with a pointer
    many = [dict(change, id=f"d{i}", model=f"R{i}", status="update") for i in range(ua.DIGEST_MAX + 15)]
    many += [dict(change, id="sec", model="Secure", status="critical")]
    body = ua.render_digest(many, weekly=True)
    check("a long digest keeps every security fix", "Secure" in body, True)

    # every item's bullet is its status color, as in the GitHub issue
    kinds = [dict(change, id="s", model="Sec", status="critical"), dict(change, id="u", model="Upd", status="update"),
             dict(change, id="c", model="Cur", status="current"), dict(change, id="t", model="Old", status="stale"),
             dict(change, id="e", model="Gone", status="eol", eol=True)]
    colored = ua.render_digest(kinds)
    for model, dot in (("Sec", "🔴"), ("Upd", "🟡"), ("Cur", "⚪"), ("Old", "⚪"), ("Gone", "⚫")):
        check(f"digest bullet for {model} is {dot}", f"{dot}&nbsp;&nbsp;<strong>Acme {model}</strong>" in colored, True)
    check("...replacing the plain list bullet", "list-style:none" in colored and "<ul>" not in colored, True)
    alert = ua.render([{"change": dict(change, status="critical"), "yours": "1.0"},
                       {"change": dict(change, id="u", model="Upd", status="update"), "yours": ""}])
    check("a personal alert's bullets are colored too",
          ("🔴&nbsp;&nbsp;<strong>Acme Router</strong>" in alert, "🟡&nbsp;&nbsp;<strong>Acme Upd</strong>" in alert), (True, True))
    check("the GitHub issue and the emails share one color per status",
          [fetch.status_dot({"status": s}) for s in ("critical", "update", "current", "stale", "eol")],
          ["🔴", "🟡", "⚪", "⚪", "⚫"])
    check("...caps ordinary releases and says how many more", f"and {len(many) - ua.DIGEST_MAX} more" in body, True)
    check("the default is every plan, not just the paying one",
          [p.strip().lower() for p in (os.environ.get("USER_ALERT_PLANS") or "all").split(",") if p.strip()],
          ["all"])


def test_typed_devices():
    """What people type into a signup box has to reach the alert, or they never get one."""
    root = Path(tempfile.mkdtemp())
    (root / "devices.json").write_text(json.dumps({"devices": [
        {"id": "dev1", "brand": "Acme", "model": "Router", "category": "R"},
        {"id": "acme-nas-2", "brand": "Acme", "model": "NAS 2", "category": "N"},
        {"id": "eero-pro-6e", "brand": "eero", "model": "Pro 6E", "category": "R"},
        {"id": "synology-ds923-plus", "brand": "Synology", "model": "DS923+", "category": "N"},
        {"id": "synology-ds220j", "brand": "Synology", "model": "DS220j", "category": "N"}]}))
    (root / "families.json").write_text(json.dumps({"families": [
        {"id": "synology-dsm", "brand": "Synology", "model": "DiskStation Manager (DSM)",
         "members": ["synology-ds923-plus", "synology-ds220j"]}]}))
    cat = ua.load_catalog(root)
    ids = lambda text: [d["id"] for d in ua.typed_devices(text, cat)]
    for text, want in [("Eero Pro 6E", ["eero-pro-6e"]),               # a device page's prefill
                       ("eero pro 6e", ["eero-pro-6e"]),
                       ("Synology DiskStation Manager (DSM)", ["synology-ds220j", "synology-ds923-plus"]),  # a family page
                       ("Synology", ["synology-ds220j", "synology-ds923-plus"]),                            # a brand page
                       ("ds923+", ["synology-ds923-plus"]),
                       ("Acme Router, eero Pro 6E", ["dev1", "eero-pro-6e"]),
                       ("my stuff", []), ("", []), ("[1,2,3]", []), ("null", [])]:
        check(f"typed devices: {text!r}", ids(text), want)
    check("typed devices are matched with no version, so any release counts",
          ua.typed_devices("Eero Pro 6E", cat), [{"id": "eero-pro-6e", "version": ""}])

    # end to end: a subscriber who only ever used a signup box gets the alert
    tmp = Path(tempfile.mkdtemp()) / "changed.json"
    tmp.write_text(json.dumps({"date": "2026-09-28", "forced": False, "count": 1, "devices": [
        {"id": "dev1", "brand": "Acme", "model": "Router", "status": "update", "version": "2.0",
         "released": "2026-09-27", "notes": "", "source_url": "", "page_url": "https://www.firmwarely.com/devices/dev1/"}]}))
    saved = ua.CHANGED, ua.CHANGED_WEEKLY, ua.send, ua.subscribers, ua.SEND_GAP, ua.PLANS, ua.ROOT
    sent = {}
    try:
        ua.CHANGED, ua.CHANGED_WEEKLY, ua.SEND_GAP, ua.PLANS, ua.ROOT = tmp, tmp.parent / "none.json", 0, ["all"], root
        ua.subscribers = lambda k, p: iter([
            {"email": "typed@e.com", "custom_fields": [{"name": "plan", "value": "pro"}, {"name": "devices", "value": "Acme Router"}]},
            {"email": "vague@e.com", "custom_fields": [{"name": "plan", "value": "pro"}, {"name": "devices", "value": "my stuff"}]}])
        ua.send = lambda to, subj, body: (sent.__setitem__(to, subj), (True, ""))[1]
        ua.main()
    finally:
        ua.CHANGED, ua.CHANGED_WEEKLY, ua.send, ua.subscribers, ua.SEND_GAP, ua.PLANS, ua.ROOT = saved
    check("a signup-box subscriber is mailed about the device they typed", sent.get("typed@e.com", "").startswith("New firmware"), True)
    check("typed text that matches nothing counts as no devices: the digest",
          sent.get("vague@e.com", "").startswith("Firmware digest"), True)


def test_typesafe_shadow():
    """The TypeSafe shadow test only records; it must never change the site or stop the run."""
    import typesafe_shadow as ts, digest, urllib.request, urllib.error, io
    from datetime import datetime, timezone
    rec = lambda i, v, notes: {"id": i, "brand": "Acme", "model": i, "version": v, "previous": "1",
                               "notes": notes, "status": "update"}
    pending = {"since": "t", "forced": False, "devices": {
        "a": rec("a", "2", "Fixes CVE-2026-1 in the login page."),
        "b": rec("b", "3", "Security hardening advice: keep your firmware updated. New dark mode."),
        "c": rec("c", "4", "This product has reached end of life and will receive no further updates.")}}
    seen = []
    def fake(state, key):
        seen.append(state)
        p = {"a": (0.97, 0.01), "b": (0.08, 0.02), "c": (0.45, 0.96)}[state["product"].split()[-1]]
        return {"security_fix": p[0], "security_fix_plain": p[0], "end_of_life": p[1]}, "jev-test"
    log, judged, failed, left = ts.judge_pending("k", pending, {"judged": []}, fake)
    check("every new release is judged once", (judged, failed, left), (3, 0, 0))
    check("the model sees the product, version and notes", sorted(seen[0]), ["previous_version", "product", "release_notes", "version"])
    check("judging again asks nothing new", ts.judge_pending("k", pending, log, fake)[1], 0)
    check("a forced test run is not judged", ts.judge_pending("k", dict(pending, forced=True), {"judged": []}, fake)[1], 0)
    b = next(j for j in log["judged"] if j["id"] == "b")
    check("the regex flags boilerplate security wording (the reason for this test)", b["regex"]["security_fix"], True)
    check("confident disagreements and unsure answers are told apart",
          [(j["id"], q, kind) for j, q, kind in ts.disagreements(log["judged"])],
          [("b", "security_fix", "differs"), ("c", "security_fix", "unsure")])
    check("a Noul reads as yes / no / unsure", [ts.verdict(p) for p in (0.95, 0.5, 0.1)], ["yes", "unsure", "no"])
    def broken(state, key):
        raise RuntimeError("HTTP 529: overloaded")
    check("an API failure skips the release and is retried next run",
          ts.judge_pending("k", pending, {"judged": []}, broken)[1:3], (0, 3))

    # the HTTP call: request shape per docs.typesafe.ai/api, retry on 429, parse the Noul answers
    sent, calls = [], {"n": 0}
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        sent.append(json.loads(req.data))
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, io.BytesIO(b"{}"))
        return Resp(json.dumps({"model": "jev-1.13.0", "answers": {
            "security_fix": {"type": "noul", "noul": 0.93}, "end_of_life": {"type": "noul", "noul": 0.02}},
            "usage": {"input_tokens": 1, "output_tokens": 1}}).encode())
    orig, orig_sleep = urllib.request.urlopen, ts.time.sleep
    try:
        urllib.request.urlopen, ts.time.sleep = fake_urlopen, lambda s: None
        answers, model = ts.ask({"product": "x"}, "k")
    finally:
        urllib.request.urlopen, ts.time.sleep = orig, orig_sleep
    check("a 429 is retried", calls["n"], 2)
    check("answers come back as probabilities by question", (answers, model), ({"security_fix": 0.93, "end_of_life": 0.02}, "jev-1.13.0"))
    check("the request names the model and every question is a Noul",
          (sent[0]["model"], {q: v["type"] for q, v in sent[0]["questions"].items()}),
          ("jev-latest", {"security_fix": "noul", "security_fix_plain": "noul", "end_of_life": "noul"}))
    check("the plain variant is the same question without criteria",
          (sent[0]["questions"]["security_fix_plain"]["instructions"] == sent[0]["questions"]["security_fix"]["instructions"],
           "criteria" in sent[0]["questions"]["security_fix_plain"]), (True, False))

    # the daily issue lists the day's disagreements
    tmp = Path(tempfile.mkdtemp()) / "typesafe_shadow.json"
    now = datetime.now(timezone.utc)
    for j in log["judged"]:
        j["judged_at"] = now.replace(microsecond=0).isoformat()
    tmp.write_text(json.dumps(log))
    orig_log = ts.LOG
    try:
        ts.LOG = tmp
        section = digest.typesafe_section(now)
    finally:
        ts.LOG = orig_log
    check("the daily issue shows where Jev and the rules differ", "Differs: Acme b `3` — security fix: rules say yes, Jev 0.08" in section, True)
    check("...and where Jev is unsure", "Unsure: Acme c" in section, True)
    check("...and never carries a link", "http" in section, False)
    wf = Path(".github/workflows/nightly.yml").read_text()
    check("the hourly run commits the shadow log", "typesafe_shadow.json" in wf, True)
    check("the shadow step can't fail the run", "continue-on-error: true" in wf.split("TypeSafe shadow judgments")[1][:200], True)


def test_weekly_roll():
    import digest, schedule
    from datetime import datetime, timezone
    rec = lambda i, v, st="update": {"id": i, "brand": "B", "model": i, "status": st, "version": v}
    week, today = {"since": None, "devices": {}}, "2026-09-24"
    out, week = digest.roll_week(week, {"forced": False, "devices": [rec("a", "1")]}, today, False)
    check("weekday: nothing to send, the change is kept", (out, list(week["devices"]), week["since"]), (None, ["a"], today))
    out, week = digest.roll_week(week, {"forced": True, "devices": [rec("z", "9")]}, "2026-09-25", False)
    check("a forced run never joins the week", list(week["devices"]), ["a"])
    out, week = digest.roll_week(week, None, "2026-09-26", False)
    check("a day with no changes keeps the week", list(week["devices"]), ["a"])
    out, week = digest.roll_week(week, {"forced": False, "devices": [rec("a", "2"), rec("b", "5", "critical")]}, "2026-09-28", True)
    check("weekly day: the whole week goes out, security first", [c["id"] for c in out["devices"]], ["b", "a"])
    check("a device that moved twice is sent at its newest version", out["devices"][1]["version"], "2")
    check("the weekly email knows when its week began", out["since"], today)
    check("and the week starts over", week, {"since": None, "devices": {}})
    check("an empty week sends nothing", digest.roll_week(week, None, "2026-10-05", True)[0], None)
    d = lambda day: datetime.fromisoformat(day + "T09:00:00+00:00")
    check("Monday is the weekly day", schedule.is_weekly_day(d("2026-09-28"), {}), True)
    check("Tuesday isn't", schedule.is_weekly_day(d("2026-09-29"), {"last_weekly": "2026-09-28"}), False)
    check("a missed Monday is made up the next day", schedule.is_weekly_day(d("2026-10-06"), {"last_weekly": "2026-09-28"}), True)
    check("nothing is sent mid-week before the first Monday", schedule.is_weekly_day(d("2026-09-24"), {}), False)


# ---- a forced run must not reach real subscribers ----
def test_forced_guard():
    tmp = Path(tempfile.mkdtemp()) / "changed.json"
    tmp.write_text(json.dumps({"date": "2026-09-14", "forced": True, "count": 1, "devices": [
        {"id": "d", "brand": "B", "model": "M", "status": "update", "version": "2",
         "previous": "1", "released": "2026-09-13", "notes": "", "source_url": "",
         "page_url": "https://www.firmwarely.com/devices/d/"}]}))
    orig_changed, orig_weekly, orig_subs, orig_test = ua.CHANGED, ua.CHANGED_WEEKLY, ua.subscribers, ua.TEST_TO
    reached = []
    try:
        ua.CHANGED, ua.CHANGED_WEEKLY, ua.TEST_TO = tmp, tmp.parent / "none.json", ""
        ua.subscribers = lambda k, p: reached.append(1) or iter([])
        rc = ua.main()
    finally:
        ua.CHANGED, ua.CHANGED_WEEKLY, ua.subscribers, ua.TEST_TO = orig_changed, orig_weekly, orig_subs, orig_test
    check("forced run without a test address sends nothing", (rc, reached), (0, []))


# ---- every device must end up with usable update instructions ----
def test_update_guides():
    guides = build_pages.GUIDES
    root = Path(__file__).resolve().parent.parent
    devs = json.loads((root / "devices.json").read_text())["devices"]
    # guides are keyed against the catalogue, not against what is published today: a device
    # waiting on its first version is absent from devices.json but still needs steps ready
    # for the run it appears, so existence is checked against sources.json
    # built through device_record so each entry carries the update_url guide() reads, exactly
    # as the pipeline would produce it
    catalogue = [fetch.device_record(x, {}) for x in
                 json.loads((root / "sources.json").read_text())["devices"]]
    brands = {d["brand"] for d in catalogue}
    ids = {d["id"] for d in catalogue}

    missing = [d["id"] for d in catalogue if not build_pages.guide(d)[0]]
    check("every device resolves to update steps", missing, [])
    blank = [d["id"] for d in catalogue if any(not x.strip() for x in build_pages.guide(d)[0])]
    check("no blank step text", blank, [])

    # a guide keyed to a brand or id that is in no catalogue at all is silently dead
    check("no brand guide points at a missing brand",
          sorted(b for b in guides.get("by_brand", {}) if b not in brands), [])
    check("no id guide points at a missing device",
          sorted(i for i in guides.get("by_id", {}) if i not in ids), [])
    check("every flash_id is a real device",
          sorted(i for i in guides.get("flash_ids", []) if i not in ids), [])

    # flashed firmware must not be told to "docker compose pull"
    by_id = {d["id"]: d for d in catalogue}
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


# ---- a source entry that is subtly malformed fails silently in the nightly run ----
def test_sources_well_formed():
    srcs = json.loads((Path(__file__).resolve().parent.parent / "sources.json").read_text())["devices"]
    ids = [s["id"] for s in srcs]
    check("no duplicate source ids", sorted({i for i in ids if ids.count(i) > 1}), [])
    check("every source declares a known type",
          sorted({s["type"] for s in srcs} - {"manual", "github", "feed", "html", "browser"}), [])

    # what each checker actually reads off the entry
    need = {"github": ("repo",), "feed": ("url",), "html": ("url", "version_regex"),
            "browser": ("url", "version_regex")}
    missing = [f"{s['id']}:{f}" for s in srcs for f in need.get(s["type"], ())
               if not s.get(f)]
    check("every source carries the fields its type needs", missing[:5], [])

    # extract_version reads group(1), so a pattern without one raises instead of returning None
    bad = []
    for s in srcs:
        for field in ("version_regex", "item_match", "skip_match"):
            pat = s.get(field)
            if not pat:
                continue
            try:
                rx = re.compile(pat)
            except re.error:
                bad.append(f"{s['id']}:{field}:uncompilable")
                continue
            if field == "version_regex" and rx.groups < 1:
                bad.append(f"{s['id']}:{field}:no capture group")
    check("every pattern compiles, every version_regex captures", bad[:5], [])

    # {version} is substituted with the matched version; a date/notes pattern that forgets
    # it matches the first release on the page instead of the one we just read
    stray = [s["id"] for s in srcs for f in ("date_regex", "notes_regex")
             if s.get(f) and "{version}" not in s[f]]
    check("date and notes patterns anchor to the matched version", sorted(set(stray)), [])



# ---- the site shows devices we have data for, and claims the cadence the cron actually runs ----
def test_site_shows_only_real_data():
    root = Path(__file__).resolve().parent.parent
    devs = json.loads((root / "devices.json").read_text())["devices"]
    blank = [d["id"] for d in devs if not d.get("version") or d["status"] == "pending"]
    check("devices.json carries no device without a version", blank[:5], [])

    # a device with no version is not dropped, it is waiting: it stays a source and joins
    # the site the run its first version lands
    srcs = json.loads((root / "sources.json").read_text())["devices"]
    check("every published device still has its source",
          sorted({d["id"] for d in devs} - {s["id"] for s in srcs})[:5], [])
    meta = json.loads((root / "devices.json").read_text())
    check("the devices held back are counted, not silently dropped",
          meta.get("waiting"), len(srcs) - len(devs))

    # nothing generated may still offer a "coming soon" row
    catalogue = (root / "devices" / "index.html").read_text()
    check("the catalogue has no watching-soon rows", "watching soon" in catalogue, False)

    # the cron and the copy are edited in different files and drifted apart before
    cron = re.search(r'- cron: "([^"]+)"', (root / ".github/workflows/nightly.yml").read_text()).group(1)
    check("the check runs hourly", cron, "0 * * * *")
    stale = [f for f in ("index.html", "scripts/build_pages.py", "README.md")
             if "every 30 minutes" in (root / f).read_text() or "half-hourly" in (root / f).read_text()]
    check("no copy still claims the old cadence", stale, [])
    check("the homepage says what the cron does", "every hour" in (root / "index.html").read_text(), True)


# ---- upstream release notes end up in innerHTML on every page ----
# ---- the support page and the form behind it ----
def test_names_said_once():
    """A brand the model already starts with isn't said twice, and "firmware" isn't either."""
    cases = [("Eero", "Eero Pro 6E", "Eero Pro 6E"), ("Redis", "Redis", "Redis"),
             ("Raspberry Pi", "Pi 5", "Raspberry Pi 5"), ("Stirling PDF", "PDF toolkit", "Stirling PDF toolkit"),
             ("Shadowsocks", "shadowsocks-rust", "shadowsocks-rust"), ("ASUS", "RT-AX58U", "ASUS RT-AX58U"),
             ("OBS", "OBSidian", "OBS OBSidian")]
    for b, m, want in cases:
        check(f"full_name: {b} + {m}", fetch.full_name({"brand": b, "model": m}), want)
    import glob
    ROOT = Path(__file__).resolve().parent.parent
    stutter = []
    for f in glob.glob(str(ROOT / "devices" / "*" / "index.html")):
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", Path(f).read_text(), re.S).group(1)
        if re.search(r"\b(\w+)\s+\1\b", _html.unescape(h1), re.I):
            stutter.append(h1)
    check("no device heading says a word twice", stutter[:5], [])
    for brand, model, cat, icon, want in [("Traefik Labs", "Traefik Proxy", "R", "app", True),
                                          ("EMQX", "MQTTX client", "S", "hub", True),
                                          ("Redis", "Redis", "A", "app", True),
                                          ("M5Stack", "Cardputer", "M", "board", False),
                                          ("Konnected", "ESPHome firmware", "S", "app", False),
                                          ("eero", "Pro 6E", "R", "router", False)]:
        check(f"is_software: {brand} {model}", build_pages.is_software(
            {"brand": brand, "model": model, "category": cat, "icon": icon}), want)
    # a project tracked from GitHub releases is software unless its name says firmware
    gh = {s["id"]: s for s in json.loads((ROOT / "sources.json").read_text())["devices"] if s.get("type") == "github"}
    devs_by_id = {d["id"]: d for d in json.loads((ROOT / "devices.json").read_text())["devices"]}
    called_firmware = [fetch.full_name(devs_by_id[i]) for i in gh if i in devs_by_id and not build_pages.is_software(devs_by_id[i])
                       and not build_pages.FIRMWARE_WORDS.search(fetch.full_name(devs_by_id[i]))]
    check("no GitHub project is called firmware unless its name says so", called_firmware[:5], [])
    for i, want in [("kong", True), ("pcsx2", True), ("valetudo", False), ("ubiquiti-cloud-gateway-ultra", False),
                    ("home-assistant-voice-pe", False)]:
        if i in devs_by_id:
            check(f"is_software: {i}", build_pages.is_software(devs_by_id[i]), want)
    # a software page gets software advice, whatever category it is filed under
    hw_advice = [i for i in ("kong", "pcsx2") if i in devs_by_id and
                 any(x in build_pages.device_page(devs_by_id[i]) for x in ("192.168.1.1", "Consoles update through", '"applicationCategory": "Firmware"'))]
    check("software pages carry no hardware update advice", hw_advice, [])
    check("ChimeraOS is not a doorbell", fetch.icon_for({"brand": "ChimeraOS", "model": "Couch gaming OS", "category": "C"}) != "doorbell", True)
    # the pages that list devices in the browser use the same rule
    for page in ("index.html", "dashboard.html", "my-devices.html"):
        src = (ROOT / page).read_text()
        check(f"{page} names devices with fullName()", "fullName(" in src and 'd.brand + " " + d.model' not in src
              and "esc(d.b)} ${esc(d.m)}" not in src, True)


def test_support_page():
    build_pages.STYLES = build_pages.styles()
    page = build_pages.support_page()
    api = Path("api/contact.js").read_text()

    check("the support page shows the contact address",
          'href="mailto:hello@firmwarely.com"' in page, True)
    check("the form posts to the endpoint that exists",
          '"/api/contact"' in page and Path("api/contact.js").exists(), True)
    check("the support page is indexable", 'content="noindex"' in page, False)

    # The footer script drives #signup-form. A second form with that id on the page would
    # be hijacked by it and post to /api/subscribe instead.
    check("the contact form has its own id", 'id="signup-form"' in page, False)

    # Every field the page posts has to be a field the endpoint reads, or it is dropped
    # silently and the message arrives incomplete.
    payload = re.search(r'"/api/contact".*?JSON\.stringify\((\{.*?\})\)', page, re.S).group(1)
    sent = sorted(set(re.findall(r"(\w+):", payload)))
    check("the message the form sends is the one the endpoint reads",
          [k for k in sent if f'body.{k}' not in api], [])
    # HTMLFormElement's own name/method/action properties shadow inputs called that, so
    # f.name is the form's name attribute and f.name.value would throw.
    check("the script doesn't read a field through a shadowed form property",
          [w for w in ("f.name", "f.method", "f.action", "f.target", "f.elements") if w + "." in page], [])
    check("the form carries the honeypot the endpoint checks",
          'name="website"' in page and "body.website" in api, True)
    check("the honeypot is hidden from sight", ".contact .hp{position:absolute" in build_pages.STYLES, True)
    check("the textarea is styled like the other inputs", ".contact textarea" in build_pages.STYLES, True)

    check("contact is POST-only", 'req.method !== "POST"' in api, True)
    check("contact is throttled per address and per source",
          'rl.allow("contact:' in api and 'rl.allow("contact-ip:' in api, True)
    check("replies go to the sender, not into our own From header",
          "replyTo: email" in api and "reply_to" in Path("lib/fw.js").read_text(), True)
    check("the message body is escaped on the way into the email html",
          "esc(message)" in api, True)

    # the link belongs at the bottom of every page, and only there
    dev = json.loads(Path("devices.json").read_text())["devices"][0]
    pages = {"device": build_pages.device_page(dev), "legal": build_pages.legal_page(),
             "404": build_pages.not_found_page([dev]), "support": page,
             "index.html": Path("index.html").read_text(),
             "my-devices.html": Path("my-devices.html").read_text(),
             "dashboard.html": Path("dashboard.html").read_text()}
    check("every page's footer links to support",
          [n for n, h in pages.items() if 'href="/support/"' not in h.split("<footer")[-1]], [])
    check("support is a footer link, not a second nav item",
          [n for n, h in pages.items() if 'href="/support/"' in h.split("<footer")[0]], [])
    # Search Console reports every apex URL it finds as "Page with redirect": the apex is a
    # 308 to www, so anything we hand out on the bare host is a link Google will not index
    # and a redirect hop for the person who clicked it.
    apex = "://" + "firmwarely.com"     # spelled this way so this line isn't its own match
    offenders = []
    for f in sorted(Path(".").glob("*.html")) + sorted(Path("scripts").glob("*.py")) + \
             sorted(Path("api").glob("*.js")) + sorted(Path("lib").glob("*.js")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if apex in line and "www." + "firmwarely.com" not in line and "@" not in line:
                offenders.append(f"{f}:{i}")
    check("nothing we publish points at the redirecting apex host", offenders[:5], [])
    check("the canonical host is the one with www", build_pages.SITE, "https://www.firmwarely.com")

    check("the support page is in the sitemap",
          "/support/" in build_pages.sitemap_paths(), True)


# ---- a date on the site is either the manufacturer's or labelled as ours ----
def test_dates_are_honest():
    build_pages.STYLES = build_pages.styles()
    srcs = {x["id"]: x for x in json.loads(Path("sources.json").read_text())["devices"]}
    devs = json.loads(Path("devices.json").read_text())["devices"]

    missing = [d["id"] for d in devs if not isinstance(d.get("date_known"), bool)]
    check("every published device says whether its date is real", missing[:5], [])
    wrong = [d["id"] for d in devs
             if d["id"] in srcs and d["date_known"] != fetch.date_known_default(srcs[d["id"]], {})]
    check("the flag matches what the source can actually tell us", wrong[:5], [])
    hist_missing = [d["id"] for d in devs
                    for h in (d.get("history") or []) if "date_known" not in h]
    check("every history row says the same", hist_missing[:5], [])

    # a page in each state: the claim has to change with the flag, not just the label
    guessed = next((d for d in devs if not d["date_known"] and d.get("released")), None)
    real = next((d for d in devs if d["date_known"] and d.get("released")), None)
    check("both date states exist in the catalogue", bool(guessed and real), True)

    page = build_pages.device_page(guessed)
    check("a date we guessed is labelled as first seen", "<dt>First seen</dt>" in page, True)
    check("...and is not called Released", "<dt>Released</dt>" in page, False)
    check("...and is not fed to crawlers as a publish date", "datePublished" in page, False)
    check("...and the prose doesn't claim a ship date", "shipped on" in page, False)
    desc = re.search(r'<meta name="description" content="(.*?)">', page).group(1)
    check("...and the search snippet doesn't either", "released" in desc.lower(), False)
    check("...and neither does the FAQ answer Google may quote",
          "released" in re.search(r"What is the latest.*?</p>", page, re.S).group(0).lower(), False)
    check("...while the date itself is still shown, marked",
          'class="seen">first seen' in page and build_pages.fmt(guessed["released"]) in page, True)

    page = build_pages.device_page(real)
    check("a real publish date is still called Released", "<dt>Released</dt>" in page, True)
    check("...and still reaches crawlers", "datePublished" in page, True)

    # the status column is the same claim in another field: a first sighting on a dateless
    # page is not evidence that anything shipped recently
    base = {"id": "x", "tracked": True, "version": "1.2.3", "notes": "security fix",
            "released": fetch.TODAY.isoformat()}
    check("a first sighting with a guessed date is not a new version",
          fetch.classify({**base, "date_known": False, "history": [{"version": "1.2.3"}]}), "current")
    check("...not even with security wording in the vendor's boilerplate",
          fetch.classify({**base, "date_known": False, "history": []}), "current")
    check("a version we watched change on that same page is",
          fetch.classify({**base, "date_known": False,
                          "history": [{"version": "1.2.3"}, {"version": "1.2.2"}]}), "critical")
    check("a real publish date is unaffected",
          fetch.classify({**base, "date_known": True, "history": [{"version": "1.2.3"}]}), "critical")
    old_seen = (fetch.TODAY - __import__("datetime").timedelta(days=fetch.STALE_DAYS + 30)).isoformat()
    check("...and one we've watched go nowhere for a year still reads as stale",
          fetch.classify({**base, "released": old_seen, "date_known": False, "history": []}), "stale")
    check("no published device is called a new version on a date we guessed",
          [d["id"] for d in devs if not d["date_known"] and len(d.get("history") or []) <= 1
           and d["status"] in ("update", "critical")][:5], [])

    # the homepage renders from devices.json in the browser, so it needs the same treatment
    home = Path("index.html").read_text()
    check("the homepage carries the flag through", "k:x.date_known !== false" in home, True)
    check("the homepage table marks a first-seen date", '"first seen"' in home or "first seen</span>" in home, True)
    check("the homepage dialog switches the label", 'd.k ? "Released" : "First seen"' in home, True)
    check("the mark has somewhere to get its styling from", ".seen{" in build_pages.STYLES, True)


# ---- a device with no page still lands somewhere useful ----
def test_withdrawn_devices_redirect():
    cfg = json.loads(Path("vercel.json").read_text())
    rules = cfg.get("redirects") or []
    devs = json.loads(Path("devices.json").read_text())["devices"]
    live = {d["id"] for d in devs}
    waiting = {s["id"] for s in json.loads(Path("sources.json").read_text())["devices"]} - live

    check("the security headers survived the rewrite", bool(cfg.get("headers")), True)
    fams = json.loads(Path("families.json").read_text())["families"]
    fam_pages = {f"/devices/{f['id']}/" for f in fams}
    listed_moves = {p for k in json.loads(Path("redirects.json").read_text()) for p in (k.rstrip("/"), k.rstrip("/") + "/")}
    family_rules = [r for r in rules if r["destination"] in fam_pages and r["source"] not in listed_moves]
    rules = [r for r in rules if r not in family_rules]
    moves = [r for r in rules if r.get("permanent")]
    brand_rules = [r for r in rules if not r.get("permanent") and r["source"].startswith("/brands/:b(")]
    rules = [r for r in rules if not r.get("permanent") and r not in brand_rules]
    covered = set()
    for r in rules:
        covered |= set(re.search(r"\(([^)]*)\)", r["source"]).group(1).split("|"))
    check("every device we don't publish has somewhere to land", sorted(waiting - covered)[:5], [])

    # a brand with no page (its old page was in the sitemap once) lands on its category
    brand_covered = set()
    for r in brand_rules:
        brand_covered |= set(re.search(r"\(([^)]*)\)", r["source"]).group(1).split("|"))
    pageless = {build_pages.slugify(s["brand"]) for s in json.loads(Path("sources.json").read_text())["devices"]
                if not (Path("brands") / build_pages.slugify(s["brand"]) / "index.html").exists()}
    elsewhere = {r["source"].rstrip("/").rsplit("/", 1)[-1] for r in family_rules + moves if r["source"].startswith("/brands/")}
    check("every brand without a page has somewhere to land", sorted(pageless - brand_covered - elsewhere)[:5], [])
    check("no brand page that exists is redirected away", sorted(b for b in brand_covered if (Path("brands") / b / "index.html").exists())[:5], [])
    check("brand pages go to a category, temporarily",
          sorted({(r["destination"].startswith("/category/"), r["permanent"]) for r in brand_rules}), [(True, False)])
    check("the old dji brand page is one of them", "dji" in brand_covered, True)
    # the rules must not change from one build to the next (string hashing is randomized per process)
    import subprocess, sys
    runs = {subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); import build_pages, json;"
                            "build_pages.write_redirects(json.load(open('devices.json'))['devices'], [], ());"
                            "print(open('vercel.json').read())"], capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout for seed in ("1", "2", "3")}
    subprocess.run([sys.executable, "scripts/build_pages.py"], capture_output=True)   # put the real rules back
    check("the redirect rules come out the same on every build", len(runs), 1)

    # Vercel redirects before it serves a file, so a stale rule would shadow a real page.
    check("no published device is redirected away from its own page",
          sorted(live & covered)[:5], [])

    dests = {r["destination"] for r in rules}
    missing = [d for d in dests if not (Path(d.strip("/")) / "index.html").exists()]
    check("every destination is a page that exists", missing[:5], [])
    check("the redirects are temporary — these devices can come back",
          [r["source"][:40] for r in rules if r.get("permanent")][:3], [])
    srcs = {r["source"] for r in rules}
    check("both spellings of the path are covered — /devices/x and /devices/x/",
          [x[:40] for x in sorted(srcs) if not x.endswith("/") and x + "/" not in srcs][:3], [])
    check("comfortably inside Vercel's 1024-rule ceiling", len(rules) + len(moves) < 900, True)

    # permanent moves: a duplicate folded into its original (redirects.json)
    wanted = json.loads(Path("redirects.json").read_text())
    wanted = {k: v for k, v in wanted.items() if not (Path(k.strip("/")) / "index.html").exists()}
    check("every entry in redirects.json becomes a permanent rule, both spellings",
          sorted(r["source"] for r in moves), sorted(p for k in wanted for p in (k.rstrip("/"), k.rstrip("/") + "/")))
    check("a permanent move lands on a page that exists",
          [r["destination"] for r in moves if not (Path(r["destination"].strip("/")) / "index.html").exists()][:3], [])
    check("a permanent move never hides a live page",
          [r["source"] for r in moves if (Path(r["source"].strip("/")) / "index.html").exists()
           or (r["source"].startswith("/devices/") and r["source"].rstrip("/").rsplit("/", 1)[-1] in live)][:3], [])
    check("a folded duplicate is gone from the catalogue",
          sorted({k.strip("/").rsplit("/", 1)[-1] for k in wanted if k.startswith("/devices/")}
                 & {s["id"] for s in json.loads(Path("sources.json").read_text())["devices"]}), [])

    # the hourly run has to commit the file it regenerates, or the rules drift from the pages
    wf = Path(".github/workflows/nightly.yml").read_text()
    check("the check commits vercel.json with the pages it rebuilt", "vercel.json" in wf, True)


# ---- an address that was ever listed keeps leading somewhere ----
def test_no_dead_addresses():
    rules = [{"source": "/devices/:id(alpha|beta)/", "destination": "/category/makers/", "permanent": False},
             {"source": "/brands/:b(gamma)", "destination": "/category/routers/", "permanent": False},
             {"source": "/devices/moved/", "destination": "/devices/", "permanent": True}]
    for path, want in [("/", True), ("/devices/", True), ("/support/", True), ("/devices/alpha/", True),
                       ("/devices/beta", True), ("/brands/gamma/", True), ("/devices/moved", True),
                       ("/devices/alphabet/", False), ("/devices/nowhere/", False), ("/brands/delta/", False)]:
        check(f"resolves {path}", build_pages.resolves(path, rules), want)
    listed = build_pages.sitemap_paths()
    check("every address in the sitemap leads somewhere", [p for p in listed if not build_pages.resolves(p)][:5], [])
    for old in ("/brands/dji/", "/brands/sonos/", "/devices/gotosocial/", "/devices/pikvm-os/"):
        check(f"once-listed {old} still leads somewhere", build_pages.resolves(old), True)
    wf = Path(".github/workflows/nightly.yml").read_text()
    check("the hourly run commits redirects.json, where the safety net writes", "redirects.json" in wf, True)


# ---- sitemap.xml is an index of one sitemap per kind of page ----
def test_sitemap_index():
    top = Path("sitemap.xml").read_text()
    children = re.findall(r"<loc>https://www\.firmwarely\.com/(sitemaps/[a-z-]+\.xml)</loc>", top)
    check("sitemap.xml is a sitemap index", "<sitemapindex" in top and "<urlset" not in top, True)
    check("it lists each kind of page", sorted(Path(c).stem for c in children),
          ["brands", "categories", "devices-hardware", "devices-software", "families", "pages"])
    check("every child it lists exists", [c for c in children if not Path(c).is_file()], [])
    check("...and nothing stale is left beside them",
          sorted(str(p) for p in Path("sitemaps").glob("*.xml") if str(p) not in children), [])
    check("every child carries a lastmod", top.count("<lastmod>"), len(children))
    paths = build_pages.sitemap_paths()
    check("no page is listed twice", len(paths), len(set(paths)))
    built = {f"/devices/{p.parent.name}/" for p in Path("devices").glob("*/index.html")}
    check("every device page is in exactly one section", sorted(built - set(paths))[:5], [])
    hw = Path("sitemaps/devices-hardware.xml").read_text()
    sw = Path("sitemaps/devices-software.xml").read_text()
    fam = Path("sitemaps/families.xml").read_text()
    check("Redis is filed as software, the eero family as a family, a Cardputer as hardware",
          ("/devices/redis/" in sw, "/devices/eero/" in fam, "/devices/m5stack-cardputer/" in hw), (True, True, True))
    check("each child is within Google's 50,000-URL limit",
          all(Path(c).read_text().count("<url>") <= 50000 for c in children), True)
    wf = Path(".github/workflows/nightly.yml").read_text()
    check("the hourly run commits the sitemaps folder", " sitemaps " in wf, True)
    check("robots.txt still points at sitemap.xml", "Sitemap: https://www.firmwarely.com/sitemap.xml" in Path("robots.txt").read_text(), True)


# ---- models on one firmware line share one page ----
def test_families():
    fams = json.loads(Path("families.json").read_text())["families"]
    devs = {d["id"]: d for d in json.loads(Path("devices.json").read_text())["devices"]}
    src_ids = {s["id"] for s in json.loads(Path("sources.json").read_text())["devices"]}
    rules = json.loads(Path("vercel.json").read_text())["redirects"]
    sitemap = "".join(f"<loc>{build_pages.SITE}{p}</loc>" for p in build_pages.sitemap_paths())
    cat_html = "".join(p.read_text() for p in Path("category").glob("*/index.html"))
    check("a family id is new, or one of its own members", [f["id"] for f in fams if f["id"] in src_ids and f["id"] not in f["members"]], [])
    check("no model is in two families", len([m for f in fams for m in f["members"]]), len({m for f in fams for m in f["members"]}))
    built = [f for f in fams if len([m for m in f["members"] if m in devs and build_pages.is_live(devs[m])]) >= 2]
    check("the catalogue has families to build", len(built) >= 10, True)
    for f in built:
        page = Path("devices") / f["id"] / "index.html"
        check(f"family {f['id']}: page exists", page.exists(), True)
        html = page.read_text() if page.exists() else ""
        live = [m for m in f["members"] if m in devs and build_pages.is_live(devs[m])]
        check(f"family {f['id']}: every model has a row and a track link",
              [m for m in live if f'/my-devices.html#d={m}"' not in html], [])
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S).group(1)
        check(f"family {f['id']}: heading reads once and says firmware",
              (bool(re.search(r"\b(\w+)\s+\1\b", _html.unescape(h1), re.I)), "releases" in h1), (False, False))
        check(f"family {f['id']}: in the sitemap", f"/devices/{f['id']}/</loc>" in sitemap, True)
        for m in live:
            if m == f["id"]:
                continue
            check(f"family {f['id']}: {m} has no page of its own", (Path("devices") / m).exists(), False)
            check(f"family {f['id']}: {m} redirects to it, both spellings",
                  sorted(r["source"] for r in rules if r["destination"] == f"/devices/{f['id']}/"
                         and r["source"] in (f"/devices/{m}", f"/devices/{m}/") and r.get("permanent")),
                  [f"/devices/{m}", f"/devices/{m}/"])
            check(f"family {f['id']}: {m} left the sitemap and the category lists",
                  (f"/devices/{m}/</loc>" in sitemap, f'href="/devices/{m}/"' in cat_html), (False, False))
    # a brand redirected to its family must not also have a page
    for r in rules:
        if r["source"].startswith("/brands/") and ":" not in r["source"]:
            check(f"{r['source']} redirects only because its page is gone",
                  (Path(r["source"].strip("/")) / "index.html").exists(), False)

def test_workflows_pinned():
    """Every workflow runs on one pinned Ubuntu, so a label move can't change it under us."""
    found = {}
    for f in sorted(Path(".github/workflows").glob("*.yml")):
        found[f.name] = re.findall(r"runs-on:\s*(\S+)", f.read_text())
    check("every job names its runner", all(found.values()), True)
    check("no workflow follows ubuntu-latest", [n for n, r in found.items() if "ubuntu-latest" in r], [])
    check("all workflows are on the same Ubuntu", sorted({x for r in found.values() for x in r}), ["ubuntu-24.04"])



def test_rebase_data():
    """A change merging mid-run must not fail the hourly push (2026-10-07 11:17): the run's
    data goes on top of the moved branch and the pages are rebuilt, never hand-merged."""
    import tempfile, rebase_data
    root, saved = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    w = lambda p, o: p.write_text(json.dumps(o))
    w(root / "sources.json", {"_readme": "branch", "devices": [{"id": "a"}, {"id": "hand-added"}]})
    w(root / "devices.json", {"tracked": 2, "devices": [{"id": "a", "version": "1.0"}, {"id": "hand-added", "version": "3"}]})
    w(root / "pending_changes.json", {"devices": {}})
    w(saved / "sources.json", {"_readme": "run", "devices": [{"id": "a"}, {"id": "discovered"}]})
    w(saved / "devices.json", {"tracked": 3, "devices": [{"id": "a", "version": "2.0"}, {"id": "discovered", "version": "1"}]})
    w(saved / "pending_changes.json", {"devices": {"a": {"version": "2.0"}}})
    rebase_data.rebase(saved, root)
    src = json.loads((root / "sources.json").read_text())
    devs = json.loads((root / "devices.json").read_text())
    check("sources keep the branch's hand edits and add what the run discovered",
          ([d["id"] for d in src["devices"]], src["_readme"]), (["a", "hand-added", "discovered"], "branch"))
    check("devices keep the run's fresh versions and the branch's new devices",
          [(d["id"], d["version"]) for d in devs["devices"]], [("a", "2.0"), ("discovered", "1"), ("hand-added", "3")])
    check("files only the run writes are the run's", json.loads((root / "pending_changes.json").read_text())["devices"], {"a": {"version": "2.0"}})
    wf = Path(".github/workflows/nightly.yml").read_text()
    step = wf[wf.index("Commit data and pages"):wf.index("Open an issue")]
    check("the hourly push recovers from a moved branch by rebuilding",
          all(x in step for x in ("git rebase --abort", "scripts/rebase_data.py", "scripts/catalog_edits.py",
                                  "scripts/build_pages.py", "git reset -q --hard FETCH_HEAD")), True)
    check("...and no longer stops at a plain pull --rebase", "git pull --rebase" in step, False)
    check("the data it saves is the data rebase_data merges",
          all(f in step for f in rebase_data.DATA), True)

# ---- counting visits, and saying so ----
def test_analytics_and_its_disclosure():
    build_pages.STYLES = build_pages.styles()
    tag = "/_vercel/insights/script.js"
    devs = json.loads(Path("devices.json").read_text())["devices"]

    pages = {"device": build_pages.device_page(devs[0]), "legal": build_pages.legal_page(),
             "support": build_pages.support_page(), "pro": build_pages.pro_page(),
             "index.html": Path("index.html").read_text(),
             "my-devices.html": Path("my-devices.html").read_text(),
             "dashboard.html": Path("dashboard.html").read_text()}
    check("every page counts its own visits", [n for n, h in pages.items() if tag not in h], [])
    check("the tag is loaded once per page", [n for n, h in pages.items() if h.count(tag) != 1], [])
    check("it loads deferred, so it can't block the page",
          [n for n, h in pages.items() if "<script defer src=\"" + tag not in h], [])

    # first-party path, so the existing CSP already allows it and no third party sees the request
    csp = json.loads(Path("vercel.json").read_text())["headers"][0]["headers"][0]["value"]
    check("the script is same-origin under the CSP we already ship",
          "script-src 'self'" in csp and tag.startswith("/"), True)
    check("its beacon is same-origin too", "connect-src 'self'" in csp, True)

    # the policy has to describe what the site actually does
    legal = pages["legal"]
    check("the policy no longer claims there is no analytics",
          "no advertising or analytics trackers" in legal, False)
    check("the policy says who does the counting", "Vercel Web Analytics" in legal, True)
    check("...and what it does and doesn't see",
          all(w in legal for w in ("no cookies", "rotates daily", "advertising")), True)
    check("...and Vercel is listed among the processors for it",
          "Vercel (hosting, sign-in API and page analytics)" in legal, True)
    # deliberately pinned: change the policy and this fails until the date is bumped with it
    check("the policy is dated the day it changed", "Last updated September 23, 2026" in legal, True)


# ---- no single form can be fired twice in half a minute ----
def test_form_rate_limit():
    build_pages.STYLES = build_pages.styles()
    devs = json.loads(Path("devices.json").read_text())["devices"]
    tag = "/formguard.js"

    # every page that carries a form has to load the guard
    pages = {"index.html": Path("index.html").read_text(),
             "my-devices.html": Path("my-devices.html").read_text(),
             "dashboard.html": Path("dashboard.html").read_text(),
             "support": build_pages.support_page(),
             "device": build_pages.device_page(devs[0])}
    check("every page with a form loads the guard", [n for n, h in pages.items() if tag not in h], [])
    check("it is deferred like the rest",
          [n for n, h in pages.items() if '<script defer src="' + tag + '">' not in h], [])
    check("the file it points at exists", Path("formguard.js").exists(), True)

    # every handler that posts has to ask first and count after
    posting = {"index hero": ("index.html", "heroBtn.disabled = true"),
               "index signup": ("index.html", "await subscribe(email,"),
               "my-devices sign-in": ("my-devices.html", 'fetch("/api/auth-request"'),
               "dashboard sign-in": ("dashboard.html", 'fetch("/api/auth-request"')}
    missing = []
    for label, (f, _) in posting.items():
        src = Path(f).read_text()
        if src.count("formGuard.hold(") < 1 or src.count("formGuard.record(") < 1:
            missing.append(label)
    check("the hand-written forms check the limit and count the send", missing, [])
    for label, page in (("footer signup", pages["device"]), ("contact", pages["support"])):
        check(f"the generated {label} form checks the limit",
              "formGuard.hold(" in page and "formGuard.record(" in page, True)

    # each form carries its own budget, and the name it uses has to be one the server knows
    names = {"subscribe", "contact", "signin"}
    used = set()
    for h in list(pages.values()):
        used |= set(re.findall(r'formGuard\.(?:hold|record)\("([a-z-]+)"', h))
    check("every call names a form", bool(used), True)
    check("and only names ones the endpoints enforce", sorted(used - names), [])
    check("the sign-in and contact forms don't share a budget",
          'formGuard.hold("signin"' in pages["my-devices.html"]
          and 'formGuard.hold("contact"' in pages["support"], True)
    check("both signup forms share one, since the server can't tell them apart",
          Path("index.html").read_text().count('formGuard.hold("subscribe"'), 2)

    # a guard that throws must not be able to block a legitimate submission
    check("every call is guarded, so a failed load can't break the forms",
          [n for n, h in pages.items()
           if re.search(r"(?<!window\.formGuard && window\.)formGuard\.hold\(", h)], [])

    # the server enforces the same thing, because the browser can be skipped
    for f, name in (("api/subscribe.js", "subscribe"), ("api/contact.js", "contact"),
                    ("api/auth-request.js", "signin")):
        src = Path(f).read_text()
        check(f"{f} enforces its own form's limit",
              f'rl.allow("burst:{name}:" + rl.clientIp(req), 1, 30000)' in src, True)
    check("subscribe still caps a source over a longer window too",
          "subscribe-ip:" in Path("api/subscribe.js").read_text(), True)

    # adding a device to your own list is not a submission to throttle
    check("the my-devices add form is left alone",
          "formGuard" in Path("my-devices.html").read_text().split('id="addForm"')[1][:400], False)

    wf = Path(".github/workflows/check-sources.yml").read_text()
    check("CI runs the limiter's own test", "selftest_forms.mjs" in wf, True)


# ---- every form that posts carries the anti-spam check ----
def test_captcha():
    build_pages.STYLES = build_pages.styles()
    devs = json.loads(Path("devices.json").read_text())["devices"]
    pages = {"index.html": Path("index.html").read_text(),
             "my-devices.html": Path("my-devices.html").read_text(),
             "dashboard.html": Path("dashboard.html").read_text(),
             "support": build_pages.support_page(),
             "device": build_pages.device_page(devs[0])}

    check("every page with a form loads the captcha script",
          [n for n, h in pages.items() if '<script defer src="/captcha.js">' not in h], [])
    check("every posting form has somewhere for the widget to render",
          [n for n, h in pages.items() if 'class="fw-captcha"' not in h], [])
    check("the homepage's two forms each have their own slot",
          pages["index.html"].count('class="fw-captcha"'), 2)
    # the pro page only shows a form while checkout is closed, so render that state
    was, build_pages.pro_link = build_pages.pro_link, lambda: ""
    try:
        closed = build_pages.pro_page()
    finally:
        build_pages.pro_link = was
    check("the pro waitlist form has a slot when it's the one on show",
          'name="plan" value="pro"' in closed and 'class="fw-captcha"' in closed, True)

    # the token has to reach the endpoint, and the widget has to be reset after: it is single-use
    for n, h in pages.items():
        check(f"{n}: sends the token", "formCaptcha.token(" in h, True)
    for n in ("index.html", "my-devices.html", "dashboard.html", "support", "device"):
        check(f"{n}: resets the widget once the token is spent",
              "formCaptcha.reset(" in pages[n], True)
    check("a missing token is explained rather than silently dropped",
          [n for n, h in pages.items() if "formCaptcha.pending" not in h], [])
    check("every call is guarded, so an unconfigured key can't break the forms",
          [n for n, h in pages.items()
           if re.search(r"(?<!window\.)(?<!window\.formCaptcha && window\.)formCaptcha\.", h)], [])

    # the server half
    for f in ("api/subscribe.js", "api/contact.js", "api/auth-request.js"):
        src = Path(f).read_text()
        check(f"{f} verifies the token", "captcha.verify(" in src, True)
        check(f"{f} refuses when verification fails", "if (!check.ok)" in src, True)
    lib = Path("lib/captcha.js").read_text()
    check("the endpoint is the documented one",
          "https://challenges.cloudflare.com/turnstile/v0/siteverify" in lib, True)
    check("it stays inert until a secret is configured", "if (!secret) return { ok: true" in lib, True)

    # shipping with a key but a CSP that blocks the widget would be a silently broken form
    csp = json.loads(Path("vercel.json").read_text())["headers"][0]["headers"][0]["value"]
    for part in ("script-src", "frame-src", "connect-src"):
        check(f"the CSP lets Cloudflare through in {part}",
              re.search(part + r"[^;]*challenges\.cloudflare\.com", csp) is not None, True)

    # The site key is public and belongs here; the secret never does. Empty is the shipped
    # state, a real key is the configured one — both are fine, anything else is a typo.
    src = Path("captcha.js").read_text()
    key = re.search(r'var TURNSTILE_SITE_KEY = "(.*?)"', src).group(1)
    check("the site key lives in exactly one place",
          key == "" or re.fullmatch(r"[0-9]x[A-Za-z0-9_-]{10,}", key) is not None, True)
    # A Turnstile secret looks much like a site key, so shape can't tell them apart — what
    # can is someone assigning one here at all. The file may name the env var in a comment.
    check("and no secret has been pasted in beside it",
          re.search(r'(?i)secret\s*=\s*["\'][^"\']+["\']', src) is None, True)
    wf = Path(".github/workflows/check-sources.yml").read_text()
    check("CI checks the captcha too", "selftest_captcha.mjs" in wf, True)

    # The widget is 300px wide and the hero form is one flex row capped at 460px: without its
    # own line it crushed the email field to 29px (measured), so pin the rules that prevent it.
    css = build_pages.STYLES
    check("the hero form wraps", "flex-wrap:wrap" in re.search(r"\.hero form\{[^}]*\}", css).group(0), True)
    check("...and the widget takes a line of its own",
          ".hero form .fw-captcha{order:3;flex-basis:100%}" in css, True)

    legal = build_pages.legal_page()
    check("the policy names who runs the check", "Cloudflare Turnstile" in legal, True)
    check("...and lists them as a processor",
          "Cloudflare (the anti-spam check on our forms)" in legal, True)


# ---- every page keeps its side margin on a phone ----
def test_side_gutter():
    build_pages.STYLES = build_pages.styles()
    devs = json.loads(Path("devices.json").read_text())["devices"]
    pages = {"index.html": Path("index.html").read_text(),
             "my-devices.html": Path("my-devices.html").read_text(),
             "dashboard.html": Path("dashboard.html").read_text(),
             "support": build_pages.support_page(), "legal": build_pages.legal_page(),
             "404": build_pages.not_found_page(devs), "device": build_pages.device_page(devs[0])}
    # .wrap supplies the 1.25rem side gutter. A padding shorthand on the same element —
    # "padding:3rem 0 4rem" — silently sets the sides to 0 and the page touches the screen
    # edge on a phone. It happened in four places at once, so check every one.
    # Each page against its own stylesheet: the dashboard has a padded .hero card of its own
    # that never sits on a .wrap, and must not be confused with the homepage's .hero.
    shorthand = r"(?<![-\w])padding\s*:"
    inline, wiping = [], []
    for name, html in pages.items():
        css = "".join(re.findall(r"<style>(.*?)</style>", html, re.S))
        for cls, style in re.findall(r'class="([^"]*\bwrap\b[^"]*)"(?:\s+style="([^"]*)")?', html):
            if style and re.search(shorthand, style):
                inline.append(name)
            for c in set(cls.split()) - {"wrap"}:
                if any(re.search(shorthand, rule)
                       for rule in re.findall(r"(?<![-\w])\." + re.escape(c) + r"\{([^}]*)\}", css)):
                    wiping.append(f"{name}: .{c}")
    check("no .wrap carries an inline padding shorthand", sorted(set(inline)), [])
    check("no class sharing an element with .wrap resets its padding", sorted(set(wiping)), [])
    css = build_pages.STYLES

    # a bare URL in release notes has nowhere to break and pushed device pages sideways
    check("the device column can shrink below its content",
          "grid-template-columns:minmax(0,1fr)" in css, True)
    check("...and long words in it wrap", re.search(r"\.dev\{[^}]*overflow-wrap:anywhere", css) is not None, True)


def test_clean():
    cases = [
        ("script tag is neutralised", "<script>alert(1)</script>ok", "alert(1) ok"),
        ("entity-hidden tag is stripped", "&lt;img src=x onerror=alert(1)&gt;", ""),
        ("double-encoded tag is stripped", "&amp;lt;b&amp;gt;x", "x"),
        ("markdown link keeps its text", "see [the notes](https://x.y/z) here", "see the notes here"),
        ("markdown headings and bullets drop their markers", "## Fixes\n- one\n* two\n1. three", "Fixes: one two three"),
        ("a heading the next line repeats is read once", "### Added\n- Added a theme\n### Security\n- Security: fix CVE", "Added a theme Security: fix CVE"),
        ("section names flattened by earlier runs are read once", "Added Added a theme. Fixed Fixed a crash", "Added a theme. Fixed a crash"),
        ("badge images are dropped", "[![Docs](https://img.shields.io/x.svg)](https://docs) ![logo](https://x/logo.png) Real notes", "Real notes"),
        ("an image cut off by the length limit is dropped", "Notes ![Documentation](https://github.com/x/y/tree/2026.08.1…", "Notes"),
        ("bot links and handles are dropped", "Bump pako (#717) @[dependabot[bot]](https://github.com/apps/dependabot) Bump x", "Bump pako (#\u200b717) Bump x"),
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
    check("the copy promises what user_alerts.py sends: free weekly, Pro daily",
          ("once a week on the free plan" in html and "weekly on the free plan" in html
           and "daily on Pro" in html), True)
    for f in ("index.html", "my-devices.html", "dashboard.html"):
        check(f"{f} has a favicon", 'rel="icon"' in Path(f).read_text(), True)
    import re as _re
    dm = _re.search(r'<meta name="description" content="(.*?)">', html)
    desc = html_unescape(dm.group(1)) if dm else ""
    check("index.html meta description fits a search snippet", len(desc) <= 155, True)
    # the catalog had two near-identical chip rows around the search box (a "Browse" nav and
    # the filter buttons). One row now does both jobs, so guard against the duplicate coming back.
    check("catalog has exactly one row of category chips", html.count('class="browse"') + html.count('class="filters"'), 1)
    for slug in ("routers", "nas", "smart-home", "consoles-drones-ebikes", "makers",
                 "pcs-tvs-gadgets", "self-hosted"):
        check(f"category chip still links to /category/{slug}/", f'href="/category/{slug}/"' in html, True)
    check("filter chips are links, not buttons", "<button class=\"chip\"" in html, False)


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
    # the catalogue index (/devices/) is hand-tuned static copy, not built through fit_desc's
    # candidate list like device/category/brand pages — check it directly so it can't drift
    devs_page = build_pages.index_page([long_name])
    idx_dm = re.search(r'<meta name="description" content="(.*?)">', devs_page, re.S)
    idx_desc = idx_dm.group(1).replace("&amp;", "&") if idx_dm else ""
    check("/devices/ meta description fits a search snippet", len(idx_desc) <= 155, True)


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

    # /pro/ follows the checkout link in index.html. Both states have to be right: the page
    # must not still say "leave your email, Pro opens soon" once cards are being charged, and
    # it must not show a dead Subscribe button if checkout is ever pulled.
    link = build_pages.pro_link()
    real = Path("index.html").read_text()
    check("the page builder reads the same link the homepage button uses",
          link and f'const PRO_LINK = "{link}"' in real, True)
    check("the checkout link is never a test-mode link",
          "buy.stripe.com/test_" in link, False)

    def pro_with(url):
        was = build_pages.pro_link
        build_pages.pro_link = lambda: url
        try:
            return build_pages.pro_page()
        finally:
            build_pages.pro_link = was

    live = pro_with("https://buy.stripe.com/EXAMPLE")
    check("open: the page sends people to checkout", "https://buy.stripe.com/EXAMPLE" in live, True)
    check("open: nothing still calls Pro unreleased",
          [w for w in ("waitlist", "Pro opens", "No card needed", "first in line") if w in live], [])
    check("open: no dead signup form left behind", 'id="signup-form"' in live, False)

    soon = pro_with("")
    check("closed: back to collecting emails as pro", 'name="plan" value="pro"' in soon, True)
    check("closed: the email form the footer script drives",
          'id="signup-form"' in soon and 'name="email"' in soon, True)
    check("closed: no checkout button with nowhere to go", "buy.stripe.com" in soon, False)

    pro = build_pages.pro_page()
    check("pro page shows every device illustration", pro.count('viewBox="0 0 64 64"'), len(build_pages.DEVICE_ART))
    check("pro page never leaves a duplicate element id",
          [i for i in set(re.findall(r'id="([^"]+)"', pro)) if pro.count(f'id="{i}"') > 1], [])

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


# ---- the hourly pipeline: one daily run, changes pooled until then, discovery vetting ----
def test_schedule_and_digest():
    from datetime import datetime, timezone
    import schedule, digest, discover
    d = lambda h, day="2026-09-15": datetime.fromisoformat(f"{day}T{h:02d}:30:00+00:00")
    check("before 08:00 UTC is never the daily run", schedule.is_daily_due(d(7), {}), False)
    check("first run after 08:00 UTC is the daily run", schedule.is_daily_due(d(8), {}), True)
    check("a later run the same day is not", schedule.is_daily_due(d(14), {"last_daily": "2026-09-15"}), False)
    check("next day it is due again", schedule.is_daily_due(d(9, "2026-09-16"), {"last_daily": "2026-09-15"}), True)
    check("a manual dispatch forces it", schedule.is_daily_due(d(3), {"last_daily": "2026-09-15"}, force=True), True)

    rec = {"id": "x", "brand": "Acme", "model": "Router", "category": "R", "status": "critical", "version": "2.0",
           "previous": "1.0", "released": "2026-09-14", "eol": False, "notes": "Fixes CVE-2026-1", "source_url": "https://e.com/r",
           "page_url": "https://www.firmwarely.com/devices/x/"}
    other = dict(rec, id="y", brand="Beta", model="NAS", status="update", notes="bug fixes")
    issue, payload, title, html_body = digest.build({"since": "t", "forced": False, "devices": {"y": other, "x": rec}},
                                                    {"added": [{"brand": "New", "model": "Thing", "category": "A"}]})
    check("digest pools every pending change", payload["count"], 2)
    check("digest puts security fixes first", payload["devices"][0]["id"], "x")
    check("digest issue never carries links", "http" in issue, False)
    check("digest issue lists what discovery added", "New Thing — Self-hosted apps & servers" in issue, True)
    check("digest of an empty pending set is nothing", digest.build({"devices": {}}), (None, None, None, None))
    check("forced flag survives into changed.json", digest.build({"forced": True, "devices": {"x": rec}})[1]["forced"], True)

    base = {"full_name": "acme/widget-server", "name": "widget-server", "fork": False, "archived": False, "disabled": False,
            "is_template": False, "stargazers_count": 5000, "description": "Self-hosted widget server for the whole family.",
            "license": {"key": "mit"}, "pushed_at": "2026-09-01T00:00:00Z", "topics": ["self-hosted", "docker"],
            "html_url": "https://github.com/acme/widget-server", "owner": {"login": "acme"}}
    check("a real product passes vetting", discover.vet(base, set(), set()), None)
    check("already tracked repos are skipped", discover.vet(base, {"acme/widget-server"}, set()), "already tracked")
    check("awesome lists are not products", discover.vet(dict(base, name="awesome-selfhosted", description="A curated list of self-hosted services"), set(), set()),
          "not a product (list/library/tutorial)")
    check("libraries are not products", discover.vet(dict(base, description="A Python library for talking to widgets"), set(), set()),
          "not a product (list/library/tutorial)")
    check("unlicensed repos are skipped", discover.vet(dict(base, license=None), set(), set()), "no license")
    check("small repos are skipped", discover.vet(dict(base, stargazers_count=200), set(), set()), "too few stars")
    check("stale repos are skipped", discover.vet(dict(base, pushed_at="2024-01-01T00:00:00Z"), set(), set()), "not pushed in a year")
    for label, repo, want in [
        ("a Chinese-only description", dict(base, description="插件化、无广告的免费音乐服务器"), "description not in English"),
        ("a generic repo name", dict(base, full_name="BruceDevices/firmware", name="firmware",
                                     description="Predatory ESP32 firmware for security testing"), "repo name too generic to be a brand"),
        ("a project that moved owners", dict(base, full_name="netalertx/NetAlertX", name="NetAlertX",
                                             description="Network intruder and presence detector"), "already tracked under its old owner"),
        ("a slogan", dict(base, name="floci", description="Light, fluffy, and always free"), "description is a slogan, not a product line"),
        ("a sentence", dict(base, name="btcpayserver", description="Accept Bitcoin payments. Free, open-source and self-hosted"),
         "description is a slogan, not a product line"),
        ("an 'X is a' line", dict(base, name="esp32-div", description="ESP32DIV is a multi-purpose wireless offensive toolkit"),
         "description is a slogan, not a product line"),
        ("'Tool for' opener", dict(base, name="dive", description="Tool for exploring each layer in a docker image"),
         "description is a slogan, not a product line"),
    ]:
        check(f"discovery skips {label}", discover.vet(repo, {"jokob-sk/netalertx"}, set()), want)
    check("...but not a plain product line", discover.vet(dict(base, name="smartdns", description="A local DNS server"), set(), set()), None)
    # 2026-10-07 QA: what discovery had added that a reader could not make sense of
    for label, repo, want in [
        ("a phone app named after its platform", dict(base, full_name="home-assistant/android", name="android",
                                                     description="Home Assistant Companion for Android"), "repo name too generic to be a brand"),
        ("a one-word model", dict(base, name="openccu", description="House: a smart home central for HomeMatic"), "model line too vague to name a product"),
        ("a generic model", dict(base, name="gobackup", description="CLI tool for backup your databases, files to cloud storages in schedully"), "model line too vague to name a product"),
        ("a model that repeats the repo", dict(base, name="passforios", description="Pass for iOS - an iOS client compatible with Pass command line application"), "model line just repeats the repo name"),
        ("a model that opens on a symbol", dict(base, name="ldr", description="~95% on SimpleQA (e.g. with a local model)"),
         "model line does not start with a word"),
        ("a feature list", dict(base, name="arkime", description="Open source, large scale, full packet capturing, indexing, and database system"),
         "model line is a feature list"),
        ("a 'This card' opener", dict(base, name="map-card", description="This card provides a user-friendly way to fully control vacuums"),
         "description is a slogan, not a product line"),
        ("a React router", dict(base, name="wouter", description="Minimalist-friendly ~2.2KB routing for React and Preact"),
         "not a product (list/library/tutorial)"),
        ("a Laravel package", dict(base, name="laravel-backup", description="A package to backup your Laravel app"),
         "not a product (list/library/tutorial)"),
        ("a Go router by its topics", dict(base, name="chi", description="Lightweight, idiomatic and composable router for building Go HTTP services",
                                           topics=["go", "golang", "router", "http-router", "middleware"]), "not a product (list/library/tutorial)"),
        ("a project removed by hand", dict(base, name="twisted", description="Asynchronous networking engine"), "removed from the catalogue before"),
    ]:
        check(f"discovery skips {label}", discover.vet(repo, set(), set(), {"twisted"}), want)
    check("...a library topic with a self-hosted topic is still a product",
          discover.vet(dict(base, topics=["self-hosted", "react"]), set(), set()), None)
    check("removed projects are read from redirects.json", {"wouter", "path-to-regexp"} <= discover.declined_ids(), True)
    check("brand takes the casing of an org named after it", discover.humanize("rpcs3", "RPCS3"), "RPCS3")
    check("brand spells abbreviations in capitals", discover.humanize("hickory-dns"), "Hickory DNS")
    for desc, want in [(":dog: Command-line DNS client for humans", "Command-line DNS client for humans"),
                       ("\U0001F1FA\U0001F1F8Secure remote browsing", "Secure remote browsing"),
                       ("Comfortably monitor your network traffic \u200d\U0001F575\ufe0f\u200d\u2642\ufe0f", "Comfortably monitor your network traffic"),
                       ("Spotify Connect client that mostly Just Works\u2122", "Spotify Connect client that mostly Just Works")]:
        check(f"model drops what can't be read: {want}", discover.short_model(desc, "X"), want)
    # nothing in the catalogue carries emoji, invisible characters or a cut-off parenthesis
    devs_now = json.loads(Path("devices.json").read_text())["devices"]
    unreadable = [d["id"] for d in devs_now for v in (d["brand"], d["model"])
                  if discover.INVISIBLE.search(v) or v.count("(") != v.count(")") or not re.match(r"[A-Za-z0-9.]", v)]
    check("every catalogue name is plain readable text", unreadable[:5], [])
    check("brand from repo name", discover.humanize("uptime-kuma"), "Uptime Kuma")
    check("brand keeps deliberate casing", discover.humanize("NocoDB"), "NocoDB")
    check("model drops marketing and the project's own name",
          discover.short_model("Immich - High performance self-hosted photo and video management solution", "Immich"),
          "High performance self-hosted photo and video management solution"[:60].rsplit(" ", 1)[0].rstrip(",;:- ") if len("High performance self-hosted photo and video management solution") > 60 else "High performance self-hosted photo and video management solution")
    check("model is capped at 60 characters", len(discover.short_model("x" * 30 + " " + "y" * 40 + " tail", "Z")) <= 60, True)
    # a model line becomes the device page <title> and meta description, so a cut that leaves
    # a dangling fragment ("…build and manage the") is visible on the live site
    for desc, brand, want in [
        ("Docker-powered PaaS that helps you build and manage the lifecycle of applications", "Dokku", "Docker-powered PaaS"),
        ("Fully autonomous AI Agents system capable of performing complex penetration tests", "Pentagi", "Fully autonomous AI Agents system"),
        ("Networking and security platform providing secure access to internal resources", "Pangolin", "Networking and security platform"),
        ("Privacy first, AI meeting assistant with 4x faster processing", "Meetily", "Privacy first, AI meeting assistant"),
        ("Build your personal knowledge base with Trilium Notes", "Trilium", "Personal knowledge base"),
        ("Your Personal AI Assistant", "QwenPaw", "Personal AI Assistant"),
    ]:
        check(f"model reads as a whole phrase: {brand}", discover.short_model(desc, brand), want)
    # "X and Y" is a compound, not an incomplete tail — cutting there would lose half the meaning
    check("compound descriptions keep both halves",
          discover.short_model("Immich - High performance self-hosted photo and video management solution", "Immich"),
          "High performance self-hosted photo and video management")
    # nothing already in the catalogue ends on a dangling word
    devs_all = json.loads(Path("devices.json").read_text())["devices"]
    dangling = [d["id"] for d in devs_all
                if d["model"].split() and re.sub(r"[^\w]", "", d["model"].split()[-1]).lower() in discover.DANGLING]
    check("no catalogue model line ends on a dangling word", dangling[:5], [])
    check("router topics land in R", discover.category_for(["openwrt", "linux"], ""), "R")
    check("home automation lands in S", discover.category_for(["home-assistant", "python"], ""), "S")
    check("plain software lands in A", discover.category_for(["docker", "nodejs"], ""), "A")
    check("a day's topics are a fixed handful", len(discover.todays_topics(100)), discover.TOPICS_PER_DAY)
    # conditional GitHub requests: 304 keeps last data and costs nothing; a spent budget is a skip
    import urllib.request, urllib.error, io, email
    prev = {"version": "1.0", "released": "2026-09-01", "notes": "n", "source_url": "https://g/r", "etag": "W/\"abc\""}
    calls = []
    def fake_304(req, timeout=30):
        calls.append(req.get_header("If-none-match"))
        raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", email.message.Message(), io.BytesIO())
    def fake_limit(req, timeout=30):
        h = email.message.Message(); h["X-RateLimit-Remaining"] = "0"
        raise urllib.error.HTTPError(req.full_url, 403, "rate limited", h, io.BytesIO())
    real = urllib.request.urlopen
    try:
        urllib.request.urlopen = fake_304
        res, err = fetch.check_source({"id": "x", "type": "github", "repo": "a/b"}, prev)
        check("304 sends the stored ETag", calls, ['W/"abc"'])
        check("304 keeps last run's data", (err, res["version"], res["etag"]), (None, "1.0", 'W/"abc"'))
        urllib.request.urlopen = fake_limit
        res, err = fetch.check_source({"id": "x", "type": "github", "repo": "a/b"}, prev)
        check("a spent API budget is a skip, not a failure", (res, err), (None, "skipped: GitHub API rate limit reached"))
    finally:
        urllib.request.urlopen = real
    check("device records carry the etag forward", fetch.device_record({"id": "x", "brand": "b", "model": "m", "category": "A", "type": "github"}, prev)["etag"], 'W/"abc"')

    # browser sources render once a day; on the other 23 runs there is nothing to read, and
    # that is a skip. But if the render DID run and this one page is missing, that is a failure.
    import tempfile as _tf
    real_rendered = fetch.RENDERED
    src_browser = {"id": "zz", "type": "browser", "url": "https://e.com", "version_regex": r"(\d+\.\d+)"}
    try:
        fetch.RENDERED = Path(_tf.mkdtemp()) / "does-not-exist"
        res, err = fetch.check_source(src_browser, {})
        check("browser source on a non-render run is a skip", (res, err.startswith("skipped:")), (None, True))
        d = Path(_tf.mkdtemp())
        fetch.RENDERED = d          # directory exists, but zz.html was not rendered
        res, err = fetch.check_source(src_browser, {})
        check("browser source that failed to render is a failure", (res, err.startswith("error:")), (None, True))
    finally:
        fetch.RENDERED = real_rendered

    check("fetch shares its record builders with discovery",
          all(hasattr(fetch, f) for f in ("device_record", "check_source", "apply_result", "finish_record", "load_pending")), True)


for t in (test_compare, test_new_release, test_saved_devices, test_routing, test_typed_devices, test_typesafe_shadow, test_weekly_roll, test_forced_guard,
          test_update_guides, test_sources_well_formed, test_site_shows_only_real_data, test_names_said_once, test_support_page, test_dates_are_honest, test_withdrawn_devices_redirect, test_no_dead_addresses, test_sitemap_index, test_families, test_workflows_pinned, test_rebase_data, test_analytics_and_its_disclosure, test_form_rate_limit, test_captcha, test_side_gutter, test_clean, test_classify, test_homepage_honesty, test_generated_pages,
          test_landing_pages, test_schedule_and_digest):
    print(f"\n{t.__name__}")
    t()

print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
