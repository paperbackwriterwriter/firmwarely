// GET  ?e=address -> a page with one "Unsubscribe" button, the address filled in
// POST e=address  -> unsubscribes it in Beehiiv, which stops every Firmwarely email:
//                    scripts/user_alerts.py only mails status=active subscribers.
// POST ?e=address with body "List-Unsubscribe=One-Click" -> the same, for mail apps' own
//                    unsubscribe button (RFC 8058; Gmail and Yahoo expect it from senders).
//
// The link carries the address, not a signed token: the emails are sent from GitHub Actions,
// which has no signing secret. So anyone could unsubscribe an address they know. That only
// stops mail the owner can re-start from a sign-in link, and it is rate limited; a working
// unsubscribe matters more. The answer never says whether an address was on the list.
const fw = require("../lib/fw");
const rl = require("../lib/ratelimit");

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function page(res, status, inner) {
  res.statusCode = status;
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Unsubscribe | Firmwarely</title>
<style>body{margin:0;background:#0C1117;color:#E3E9EE;font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:460px;margin:12vh auto;padding:0 1.25rem}h1{font-size:1.5rem;margin:0 0 1rem}p{color:#8A98A5}
input{font:inherit;width:100%;box-sizing:border-box;color:#E3E9EE;background:#121A23;border:1px solid #22303C;border-radius:6px;padding:.6rem .8rem;margin:0 0 .8rem}
button{font:inherit;font-weight:600;border:1px solid #F5B342;background:#F5B342;color:#1A1204;padding:.6rem 1.2rem;border-radius:6px;cursor:pointer}
a{color:#E3E9EE}</style></head><body><main>${inner}</main></body></html>`);
}

async function readForm(req) {
  if (req.body && typeof req.body === "object" && !Buffer.isBuffer(req.body)) return new URLSearchParams(req.body);
  let raw = Buffer.isBuffer(req.body) ? req.body.toString() : typeof req.body === "string" ? req.body : "";
  if (!raw && typeof req.on === "function") for await (const chunk of req) raw += chunk;
  return new URLSearchParams(raw.slice(0, 2000));
}

module.exports = async function (req, res) {
  const url = new URL(req.url, "http://x");
  if (req.method === "GET") {
    const e = fw.normEmail(url.searchParams.get("e"));
    return page(res, 200, `<h1>Unsubscribe from Firmwarely</h1>
<p>This stops every email from us: device alerts, digests and announcements.</p>
<form method="post" action="/api/unsubscribe"><label for="e" style="display:block;margin:0 0 .3rem">Email address</label>
<input id="e" name="e" type="email" required autocomplete="email" value="${esc(fw.validEmail(e) ? e : "")}">
<button type="submit">Unsubscribe</button></form>`);
  }
  if (req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    return fw.json(res, 405, { error: "GET or POST only" });
  }

  const form = await readForm(req);
  const oneClick = form.get("List-Unsubscribe") === "One-Click";
  // A mail app's one-click POST comes from its own servers (no Origin); a page on another
  // site must not be able to submit our form.
  if (!oneClick && !fw.sameOrigin(req)) return fw.json(res, 403, { error: "Cross-site request refused." });
  const email = fw.normEmail(oneClick ? url.searchParams.get("e") : form.get("e"));
  if (!fw.validEmail(email)) return page(res, 400, `<h1>That doesn't look like an email address</h1><p><a href="/api/unsubscribe">Try again</a>.</p>`);

  const ip = rl.clientIp(req);
  if (!rl.allow("unsub:" + email, 5, 15 * 60 * 1000) || !rl.allow("unsub-ip:" + ip, 20, 15 * 60 * 1000)) {
    return page(res, 429, `<h1>Too many requests</h1><p>Try again in a few minutes, or email <a href="mailto:hello@firmwarely.com">hello@firmwarely.com</a>.</p>`);
  }

  const look = await fw.lookupSubscriber(email).catch(() => ({ error: "unreachable" }));
  if (look.error) {
    console.error("unsubscribe: lookup failed", look.error);
    return page(res, 502, `<h1>Couldn't do that just now</h1><p>Please try again in a minute, or email <a href="mailto:hello@firmwarely.com?subject=Unsubscribe">hello@firmwarely.com</a> and we'll remove you by hand.</p>`);
  }
  if (look.found && !(await fw.unsubscribe(look.sub.id))) {
    console.error("unsubscribe: update failed");
    return page(res, 502, `<h1>Couldn't do that just now</h1><p>Please try again in a minute, or email <a href="mailto:hello@firmwarely.com?subject=Unsubscribe">hello@firmwarely.com</a> and we'll remove you by hand.</p>`);
  }
  if (oneClick) return fw.json(res, 200, { ok: true });
  return page(res, 200, `<h1>You're unsubscribed</h1>
<p>${esc(email)} won't get any more email from Firmwarely. Changed your mind? <a href="/my-devices.html">Sign in on My devices</a> to start again.</p>`);
};
