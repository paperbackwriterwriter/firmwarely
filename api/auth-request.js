// POST {email} -> emails a sign-in link.
const fw = require("../lib/fw");
const rl = require("../lib/ratelimit");
const captcha = require("../lib/captcha");

module.exports = async function (req, res) {
  if (req.method !== "POST") return fw.json(res, 405, { error: "POST only" });
  const body = await fw.readBody(req);
  const email = fw.normEmail(body.email);
  if (!fw.validEmail(email)) return fw.json(res, 400, { error: "Enter a valid email address." });

  const check = await captcha.verify(body.captcha, rl.clientIp(req));
  if (!check.ok) {
    console.warn("auth-request: turnstile", check.reason, check.codes || "");
    return fw.json(res, 400, { error: "Please complete the anti-spam check and try again." });
  }

  // The browser applies this too (formguard.js), but anything can skip the browser.
  // Same numbers, enforced per source and per form: one submission every thirty seconds.
  if (!rl.allow("burst:signin:" + rl.clientIp(req), 1, 30000)) {
    return fw.json(res, 429, { error: "One submission every 30 seconds. Give it a moment and try again." });
  }

  // Anyone can type any address here, so this endpoint must not be a way to make us
  // email strangers on demand. Throttle per address and per source before sending.
  if (!rl.allow("email:" + email, 3, 15 * 60 * 1000) || !rl.allow("ip:" + rl.clientIp(req), 12, 15 * 60 * 1000)) {
    return fw.json(res, 429, { error: "Too many sign-in links requested. Check your inbox, or try again in a few minutes." });
  }
  // The account itself is created when the link is clicked (auth-verify) — proof the
  // address is theirs — not here, where a stranger could subscribe anyone to the list.

  const next = fw.safeNext(String(body.next || ""));   // where to land after the click
  let token;
  try {
    token = fw.makeToken(email, "login", 15 * 60, { n: next });
  } catch (e) {
    console.error("auth-request:", e.message);
    return fw.json(res, 500, { error: "Sign-in isn't configured yet." });
  }
  const link = (process.env.SITE_URL || "") + "/api/auth-verify?t=" + encodeURIComponent(token);
  const html =
    '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:#111">' +
    "<p>Here is your Firmwarely sign-in link. It works for 15 minutes.</p>" +
    '<p><a href="' + link + '" style="display:inline-block;background:#F5B342;color:#1A1204;' +
    'font-weight:600;padding:10px 16px;border-radius:6px;text-decoration:none">Sign in to Firmwarely</a></p>' +
    '<p style="color:#666;font-size:14px">If the button does not work, copy this into your browser:<br>' +
    link + "</p>" +
    '<p style="color:#666;font-size:14px">If you did not request this, you can ignore it.</p></div>';

  const sent = await fw.sendEmail(email, "Your Firmwarely sign-in link", html);
  if (!sent.ok) {
    const msg = (sent.data && sent.data.message) || "Couldn't send the email just now.";
    return fw.json(res, 502, { error: msg });
  }
  return fw.json(res, 200, { ok: true });
};
