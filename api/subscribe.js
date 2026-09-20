// Vercel serverless function: POST /api/subscribe
// Creates a Beehiiv subscriber without sending the visitor off-site.
// Needs two environment variables in Vercel: BEEHIIV_API_KEY and BEEHIIV_PUB_ID.

const rl = require("../lib/ratelimit");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }

  const key = process.env.BEEHIIV_API_KEY;
  const pub = process.env.BEEHIIV_PUB_ID;
  if (!key || !pub) {
    return res.status(500).json({ ok: false, error: "Signup isn't configured yet." });
  }

  // The browser applies this too (formguard.js), but anything can skip the browser.
  // Same numbers, enforced per source and per form: one submission every thirty seconds.
  if (!rl.allow("burst:subscribe:" + rl.clientIp(req), 1, 30000)) {
    return res.status(429).json({ ok: false, error: "One submission every 30 seconds. Give it a moment and try again." });
  }
  // A signup writes to the mailing list, so also cap a single source over a longer window.
  if (!rl.allow("subscribe-ip:" + rl.clientIp(req), 10, 15 * 60 * 1000)) {
    return res.status(429).json({ ok: false, error: "Too many signups from here. Try again in a few minutes." });
  }

  let body = req.body;
  if (typeof body === "string") { try { body = JSON.parse(body); } catch { body = {}; } }
  const email = String(body?.email || "").trim().toLowerCase();
  const plan = body?.plan === "pro" ? "pro" : "free";
  const devices = String(body?.devices || "").trim().slice(0, 300);

  if (!EMAIL_RE.test(email)) {
    return res.status(400).json({ ok: false, error: "Enter a valid email address." });
  }

  const payload = {
    email,
    reactivate_existing: true,
    send_welcome_email: true,
    utm_source: "firmwarely.com",
    utm_medium: "site",
    utm_campaign: plan,
    referring_site: "https://www.firmwarely.com"
  };
  if (devices) payload.custom_fields = [{ name: "devices", value: devices }];

  const call = async (p) => fetch(`https://api.beehiiv.com/v2/publications/${pub}/subscriptions`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(p)
  });

  try {
    let r = await call(payload);
    // If the "devices" custom field doesn't exist yet in Beehiiv, retry without it.
    if (!r.ok && payload.custom_fields) {
      delete payload.custom_fields;
      r = await call(payload);
    }
    if (!r.ok) {
      const text = await r.text();
      console.error("beehiiv error", r.status, text);
      return res.status(502).json({ ok: false, error: "Couldn't save that just now. Try again in a minute." });
    }
    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error(e);
    return res.status(502).json({ ok: false, error: "Couldn't save that just now. Try again in a minute." });
  }
};
