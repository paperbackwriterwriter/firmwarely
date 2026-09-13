#!/usr/bin/env python3
# Render JS-heavy pages with headless Chromium so fetch.py can
# regex them like normal HTML. Runs before fetch.py.
# Handles sources.json entries with type "browser".
# Optional per-device fields: wait_for (CSS selector),
# click (CSS selector to click before reading), wait_ms.
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources.json"
OUT = ROOT / "rendered"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)


def render(page, src):
    page.goto(src["url"], wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    if src.get("click"):
        try:
            page.click(src["click"], timeout=10000)
        except Exception as e:
            print("  click failed:", e)
    if src.get("wait_for"):
        page.wait_for_selector(src["wait_for"], timeout=20000)
    page.wait_for_timeout(int(src.get("wait_ms", 1500)))
    return page.content()


def main():
    cfg = json.loads(SOURCES.read_text())
    todo = [d for d in cfg["devices"] if d.get("type") == "browser"]
    if not todo:
        print("browser: nothing to render")
        return 0
    OUT.mkdir(exist_ok=True)
    ok = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA, locale="en-US")
        page = ctx.new_page()
        for src in todo:
            try:
                html = render(page, src)
                (OUT / (src["id"] + ".html")).write_text(
                    html, encoding="utf-8"
                )
                ok += 1
                print("  rendered", src["id"], len(html), "bytes")
            except Exception as e:
                msg = str(e).splitlines()[0][:120]
                print("  FAIL    ", src["id"], msg)
        browser.close()
    print("browser: rendered %d of %d" % (ok, len(todo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
