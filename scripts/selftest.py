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

    # a device with no download page still has to be actionable
    for dev_id in ("ring-battery-doorbell-plus", "dji-mavic-4-pro"):
        if dev_id in by_id:
            steps, url = build_pages.guide(by_id[dev_id])
            check(f"{dev_id}: app-updated, instructions instead of a dead link",
                  (bool(steps), url), (True, None))


for t in (test_compare, test_new_release, test_saved_devices, test_routing, test_forced_guard,
          test_update_guides):
    print(f"\n{t.__name__}")
    t()

print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all checks passed'}")
sys.exit(1 if FAILED else 0)
