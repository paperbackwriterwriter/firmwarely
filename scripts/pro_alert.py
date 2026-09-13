#!/usr/bin/env python3
# Send digest.md to the Beehiiv Pro segment as an instant alert.
# Runs after fetch.py in the nightly workflow. Only does anything if
# digest.md exists (at least one tracked device changed version).
#
# Env vars (GitHub repo secrets): BEEHIIV_API_KEY, BEEHIIV_PUB_ID,
# BEEHIIV_PRO_SEG_ID. Optional: PRO_ALERT_TEST=1 prefixes subject with [TEST].
import html
import json
import os
import re
import sys
import urllib.request

DIGEST = "digest.md"


def md_to_html(md):
    out, in_list = [], False
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = min(len(m.group(1)) + 1, 3)
            out.append('<h%d style="margin:18px 0 6px">%s</h%d>' % (lvl, html.escape(m.group(2)), lvl))
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append('<ul style="margin:0 0 12px 18px;padding:0">')
                in_list = True
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(m.group(1)))
            out.append('<li style="margin:4px 0">%s</li>' % text)
            continue
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(line))
        out.append('<p style="margin:0 0 12px">%s</p>' % text)
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def main():
    if not os.path.exists(DIGEST):
        print("No digest.md - nothing changed, no Pro alert.")
        return 0

    api_key = os.environ.get("BEEHIIV_API_KEY")
    pub_id = os.environ.get("BEEHIIV_PUB_ID")
    seg_id = os.environ.get("BEEHIIV_PRO_SEG_ID")
    if not (api_key and pub_id and seg_id):
        print("Missing BEEHIIV_API_KEY / BEEHIIV_PUB_ID / BEEHIIV_PRO_SEG_ID", file=sys.stderr)
        return 1

    md = open(DIGEST, encoding="utf-8").read()
    first = md.splitlines()[0] if md.strip() else "Firmware update alert"
    title = re.sub(r"^#+\s*", "", first).strip() or "Firmware update alert"
    subject = title
    if os.environ.get("PRO_ALERT_TEST") == "1":
        subject = "[TEST] " + subject

    body = (
        '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;'
        'font-size:16px;line-height:1.5;color:#111">'
        + md_to_html(md)
        + '<p style="margin:18px 0 0;color:#666;font-size:14px">'
        'Pro instant alert from <a href="https://firmwarely.com">firmwarely.com</a>. '
        'Full details on each device page.</p></div>'
    )

    payload = {
        "title": title,
        "subtitle": "Pro instant alert",
        "body_content": body,
        "status": "confirmed",
        "recipients": {
            "email": {"tier_ids": ["free", "premium"], "include_segment_ids": [seg_id]},
            "web": {"tier_ids": []},
        },
        "email_settings": {
            "email_subject_line": subject,
            "email_preview_text": "New firmware spotted for a device you track.",
            "display_subtitle_in_email": False,
        },
        "web_settings": {"hide_from_feed": True},
        "content_tags": ["pro-alert"],
    }

    req = urllib.request.Request(
        "https://api.beehiiv.com/v2/publications/%s/posts" % pub_id,
        data=json.dum​​​​​​​​​​​​​​​​
