// Vercel serverless function: POST /api/stripe-webhook
// Stripe calls this when someone buys or cancels Pro. We then set the subscriber's
// "plan" custom field in Beehiiv to "pro" or "free" so you can segment sends.
//
// Env vars (Vercel → Settings → Environment Variables):
//   STRIPE_WEBHOOK_SECRET  — from Stripe → Developers → Webhooks → your endpoint → Signing secret (whsec_…)
//   STRIPE_SECRET_KEY      — Stripe → Developers → API keys → Secret key (sk_test_… or sk_live_…)
//   BEEHIIV_API_KEY, BEEHIIV_PUB_ID — already set for /api/subscribe
//
// Beehiiv needs a custom field named exactly  plan  (Audience → Subscribers → Custom fields → Add).
// No npm packages: the Stripe signature is verified with Node's crypto module.
//
// Idempotency: there is no event store, so a redelivered event is simply re-applied. That is
// safe because every handler is a plain "set plan to X" write with the same result each time.
// The one ordering hazard — a late "deleted"/"canceled" for an old subscription arriving after
// the customer already started a new one — is covered by asking Stripe whether the customer
// still has an active subscription before downgrading anyone.

import crypto from "node:crypto";

export const config = { api: { bodyParser: false } };

const readRaw = (req) =>
  new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });

function verify(raw, header, secret) {
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const t = parts.t, v1 = parts.v1;
  if (!t || !v1) return false;
  if (Math.abs(Date.now() / 1000 - Number(t)) > 300) return false; // 5-minute tolerance
  const expected = crypto.createHmac("sha256", secret).update(`${t}.${raw}`).digest("hex");
  return expected.length === v1.length && crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(v1));
}

async function stripeGet(path, key) {
  const r = await fetch(`https://api.stripe.com/v1${path}`, {
    headers: { Authorization: `Basic ${Buffer.from(key + ":").toString("base64")}` },
  });
  return r.ok ? r.json() : null;
}

async function setPlan(email, plan) {
  const key = process.env.BEEHIIV_API_KEY, pub = process.env.BEEHIIV_PUB_ID;
  const base = `https://api.beehiiv.com/v2/publications/${pub}/subscriptions`;
  const headers = { Authorization: `Bearer ${key}`, "Content-Type": "application/json", Accept: "application/json" };
  const fields = [{ name: "plan", value: plan }];

  let r = await fetch(`${base}/by_email/${encodeURIComponent(email)}`, { headers });
  if (r.status === 404) {
    // paid before ever subscribing — create them
    r = await fetch(base, { method: "POST", headers, body: JSON.stringify({
      email, reactivate_existing: true, send_welcome_email: true,
      utm_source: "stripe", utm_campaign: plan, custom_fields: fields }) });
    return `created ${r.status}`;
  }
  const j = await r.json().catch(() => ({}));
  const id = j?.data?.id;
  if (!id) return `lookup failed ${r.status}`;
  for (const method of ["PATCH", "PUT"]) {
    const u = await fetch(`${base}/${id}`, { method, headers, body: JSON.stringify({ custom_fields: fields }) });
    if (u.ok) return `${method} ok`;
    if (u.status !== 404 && u.status !== 405) return `${method} ${u.status}: ${(await u.text()).slice(0, 150)}`;
  }
  return "update failed";
}

export default async function handler(req, res) {
  if (req.method !== "POST") { res.setHeader("Allow", "POST"); return res.status(405).end(); }
  const raw = await readRaw(req);
  const sig = req.headers["stripe-signature"] || "";
  if (!process.env.STRIPE_WEBHOOK_SECRET || !verify(raw, sig, process.env.STRIPE_WEBHOOK_SECRET)) {
    return res.status(400).json({ error: "bad signature" });
  }
  const event = JSON.parse(raw);
  const obj = event.data?.object || {};
  let email = obj.customer_details?.email || obj.customer_email || null;
  if (!email && obj.customer && process.env.STRIPE_SECRET_KEY) {
    const c = await stripeGet(`/customers/${obj.customer}`, process.env.STRIPE_SECRET_KEY);
    email = c?.email || null;
  }

  let plan = null;
  if (event.type === "checkout.session.completed" && obj.mode === "subscription") plan = "pro";
  else if (event.type === "customer.subscription.deleted") plan = "free";
  else if (event.type === "customer.subscription.updated") {
    if (["canceled", "unpaid", "incomplete_expired"].includes(obj.status)) plan = "free";
    else if (obj.status === "active") plan = "pro";
  }

  // Never downgrade someone who still has a live subscription (events can arrive out of order,
  // and a customer can cancel one subscription and start another).
  if (plan === "free" && obj.customer && process.env.STRIPE_SECRET_KEY) {
    const live = await stripeGet(`/subscriptions?customer=${encodeURIComponent(obj.customer)}&status=active&limit=1`,
      process.env.STRIPE_SECRET_KEY);
    if (live && Array.isArray(live.data) && live.data.length) plan = "pro";
  }

  let result = "ignored";
  if (plan && email) result = await setPlan(email.toLowerCase(), plan);
  console.log(`stripe ${event.type} → ${email || "no email"} → ${plan || "-"} → ${result}`);
  return res.status(200).json({ received: true, plan, result });
}
