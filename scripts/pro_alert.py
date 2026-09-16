#!/usr/bin/env python3
# NOT WIRED UP. scripts/user_alerts.py now sends Pro subscribers one email each -- their
# own devices when something of theirs moved, this same digest otherwise -- so running
# both sent two copies to the same people. Kept as a fallback: nothing calls it.
#
# Send digest.md to the Beehiiv Pro segment as an instant alert.
# Only runs if digest.md exists (something changed).
# Env: BEEHIIV_API_KEY, BEEHIIV_PUB_ID, BEEHIIV_PRO_SEG_ID
# Optional: PRO_ALERT_TEST=1 adds [TEST] to the subject.
import html
import json
import os
import re
import sys
import urllib.request

DIGEST = "digest.md"
API = "https://api.beehiiv.com/v2/publications/"
BOLD = r"\*\*(.+?)\*\*"
CODE = r"`([^`]+)`"
SKIP = "Beehiiv draft"


def fmt(text):
    text = html.escape(text)
    text = re.sub(BOLD, r"<strong>\1</strong>", text)
    text = re.sub(CODE, r"<code>\1</code>", text)
    return text


def md_to_html(md):
    out = []
    in_list = False
    lines = md.splitlines()[1:]
    for raw in lines:
        line = raw.rstrip()
        if not line or SKIP in line:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<h3>%s</h3>" % fmt(m.group(2)))
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % fmt(m.group(1)))
            continue
        out.append("<p>%s</p>" % fmt(line))
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def main():
    if not os.path.exists(DIGEST):
        print("No digest.md - no Pro alert.")
        return 0

    api_key = os.environ.get("BEEHIIV_API_KEY")
    pub_id = os.environ.get("BEEHIIV_PUB_ID")
    seg_id = os.environ.get("BEEHIIV_PRO_SEG_ID")
    if not (api_key and pub_id and seg_id):
        print("Missing Beehiiv env vars", file=sys.stderr)
        return 1

    md = open(DIGEST, encoding="utf-8").read()
    lines = md.splitlines()
    first = lines[0] if lines else "Firmware update alert"
    title = re.sub(r"^#+\s*", "", first).strip()
    if not title:
        title = "Firmware update alert"
    subject = title
    if os.environ.get("PRO_ALERT_TEST") == "1":
        subject = "[TEST] " + subject

    intro = (
        "<p>New firmware or security releases were spotted "
        "for the devices below. Version details and links "
        "are on each device page at "
        '<a href="https://www.firmwarely.com">firmwarely.com</a>.'
        "</p>"
    )
    footer = (
        "<p>You are receiving this because you are a "
        "Firmwarely Pro subscriber.</p>"
    )
    body = "<div>" + intro + md_to_html(md) + footer + "</div>"

    payload = {
        "title": title,
        "subtitle": "Pro instant alert",
        "body_content": body,
        "status": "confirmed",
        "recipients": {
            "email": {
                "include_segment_ids": [seg_id],
            },
            "web": {"tier_ids": []},
        },
        "email_settings": {
            "email_subject_line": subject,
            "email_preview_text": "New firmware spotted.",
            "display_subtitle_in_email": False,
        },
        "web_settings": {"hide_from_feed": True},
        "content_tags": ["pro-alert"],
    }

    url = API + pub_id + "/posts"
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read())
            post_id = res.get("data", {}).get("id")
            print("Pro alert sent, post id:", post_id)
            return 0
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:500]
        print("Beehiiv error", e.code, msg, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
