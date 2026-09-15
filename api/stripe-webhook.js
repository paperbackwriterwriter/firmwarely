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

// Buffers, not a string. Appending a chunk to a string decodes that chunk on its own, so a
// multi-byte character split across a chunk boundary comes back as replacement characters
// and the HMAC no longer matches the bytes Stripe signed — a valid event rejected.
export const readRaw = (req) =>
  new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c)));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });

export function verify(raw, header, secret) {
  const pairs = (header || "").split(",").map((p) => p.split("="));
  const t = pairs.find(([k]) => k === "t")?.[1];
  // Stripe signs with every active secret, so while a signing secret is being rotated the
  // header carries several v1 values and only one of them is ours. Taking just the last
  // would reject real events for the length of the rotation.
  const sigs = pairs.filter(([k]) => k === "v1").map(([, v]) => v).filter(Boolean);
  if (!t || !sigs.length) return false;
  if (Math.abs(Date.now() / 1000 - Number(t)) > 300) return false; // 5-minute tolerance
  const expected = crypto.createHmac("sha256", secret).update(`${t}.`).update(raw).digest("hex");
  const mine = Buffer.from(expected);
  return sigs.some((v) => v.length === expected.length && crypto.timingSafeEqual(mine, Buffer.from(v)));
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

// Which plan an event implies, or null for the events we do not act on.
export function planFor(type, obj) {
  if (type === "checkout.session.completed" && obj.mode === "subscription") return "pro";
  if (type === "customer.subscription.deleted") return "free";
  if (type === "customer.subscription.updated") {
    if (["canceled", "unpaid", "incomplete_expired"].includes(obj.status)) return "free";
    if (obj.status === "active") return "pro";
  }
  return null;
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

  let plan = planFor(event.type, obj);

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
