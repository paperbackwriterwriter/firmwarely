// Shared helpers for the Firmwarely API functions.
const crypto = require("crypto");

const BH = "https://api.beehiiv.com/v2/publications/" + process.env.BEEHIIV_PUB_ID;
const SECRET = process.env.AUTH_SECRET || "";
const FROM = process.env.RESEND_FROM || "Firmwarely <onboarding@resend.dev>";

function b64(s) {
  return Buffer.from(s).toString("base64url");
}
function unb64(s) {
  return Buffer.from(s, "base64url").toString();
}
function sign(payload) {
  return crypto.createHmac("sha256", SECRET).update(payload).digest("base64url");
}

// Where a sign-in link may land afterwards. Anything else falls back to My devices,
// so a crafted link can never bounce someone off-site.
const NEXT_OK = ["/my-devices.html", "/dashboard.html"];
function safeNext(n) {
  return NEXT_OK.indexOf(n) >= 0 ? n : NEXT_OK[0];
}

// token = base64(json).signature ; json = {e: email, x: expiry, p: purpose, ...extra}
// Without AUTH_SECRET every token verifies as invalid, so signing one would email a
// sign-in link that can never work. Fail here instead, where the caller can say so.
function makeToken(email, purpose, ttlSec, extra) {
  if (!SECRET) throw new Error("AUTH_SECRET is not set");
  const body = JSON.stringify(Object.assign({}, extra || {}, { e: email, x: Date.now() + ttlSec * 1000, p: purpose }));
  const enc = b64(body);
  return enc + "." + sign(enc);
}
// The whole verified payload, or null. readToken is the common case of just the email.
function readTokenData(token, purpose) {
  if (!token || !SECRET) return null;
  const i = token.lastIndexOf(".");
  if (i < 0) return null;
  const enc = token.slice(0, i), sig = token.slice(i + 1);
  // Compare bytes, not characters: a crafted signature with multi-byte characters has the
  // right string length but a different byte length, and timingSafeEqual throws on that.
  const a = Buffer.from(sig), b = Buffer.from(sign(enc));
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  let data;
  try { data = JSON.parse(unb64(enc)); } catch (e) { return null; }
  if (!data || typeof data !== "object" || data.p !== purpose || !(data.x >= Date.now())) return null;
  return data;
}
function readToken(token, purpose) {
  const data = readTokenData(token, purpose);
  return data ? data.e : null;
}

function cookies(req) {
  const out = {};
  (req.headers.cookie || "").split(";").forEach(function (c) {
    const i = c.indexOf("=");
    if (i <= 0) return;
    // Any other cookie on the domain can hold a stray "%"; one bad value must not throw and
    // sign the person out (URIError) — keep it raw instead.
    let v = c.slice(i + 1).trim();
    try { v = decodeURIComponent(v); } catch (e) {}
    out[c.slice(0, i).trim()] = v;
  });
  return out;
}
function sessionEmail(req) {
  return readToken(cookies(req).fw_session, "session");
}
function setSession(res, email) {
  const t = makeToken(email, "session", 30 * 24 * 3600);
  res.setHeader("Set-Cookie",
    "fw_session=" + t + "; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000");
}
function clearSession(res) {
  res.setHeader("Set-Cookie",
    "fw_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0");
}

// A browser sends Origin on every POST. Missing (curl, old clients) is allowed; a different
// site is not.
function sameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === req.headers.host; } catch (e) { return false; }
}

function normEmail(e) {
  return String(e || "").trim().toLowerCase();
}
// The length check comes first: the pattern backtracks quadratically on a long string with
// many dots, and a request body can be megabytes. No real address is over 254 characters.
function validEmail(e) {
  return typeof e === "string" && e.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
}

async function bh(path, method, body) {
  const r = await fetch(BH + path, {
    method: method || "GET",
    headers: {
      "Authorization": "Bearer " + process.env.BEEHIIV_API_KEY,
      "Content-Type": "application/json",
      "Accept": "application/json"
    },
    body: body ? JSON.stringify(body) : undefined
  });
  let data = null;
  try { data = await r.json(); } catch (e) {}
  return { ok: r.ok, status: r.status, data: data };
}

function fieldsToMap(sub) {
  const m = {};
  ((sub && sub.custom_fields) || []).forEach(function (f) {
    m[f.name] = f.value;
  });
  return m;
}

// Returns {id, email, plan, devices:[{id,version}]} or null. null means "no such subscriber"
// only when lookupSubscriber says found:false; on an error it is null too, so a caller about
// to overwrite something should use lookupSubscriber and stop on error.
async function getSubscriber(email) {
  return (await lookupSubscriber(email)).sub;
}

// {found: true, sub} | {found: false, sub: null} (404) | {error: status, sub: null}
async function lookupSubscriber(email) {
  const r = await bh("/subscriptions/by_email/" + encodeURIComponent(email)
    + "?expand=custom_fields");
  if (r.status === 404) return { found: false, sub: null };
  if (!r.ok || !r.data || !r.data.data) return { error: r.status || "unreachable", sub: null };
  return { found: true, sub: toSubscriber(r.data.data) };
}

function toSubscriber(s) {
  const f = fieldsToMap(s);
  let devices = [];
  try {
    const parsed = JSON.parse(f.devices || "[]");
    if (Array.isArray(parsed)) {
      devices = parsed.map(function (d) {
        if (Array.isArray(d)) return { id: String(d[0]), version: String(d[1] || "") };
        if (d && d.id) return { id: String(d.id), version: String(d.version || "") };
        return null;
      }).filter(Boolean);
    }
  } catch (e) {}
  return { id: s.id, email: s.email, status: s.status,
    plan: (f.plan || "free").toLowerCase(), devices: devices };
}

// Stop all email to this address. Beehiiv's own unsubscribe, so its welcome and newsletter
// mail stops too, and user_alerts.py (which only lists status=active) skips them.
async function unsubscribe(subId) {
  const r = await bh("/subscriptions/" + subId, "PATCH", { unsubscribe: true });
  return r.ok;
}

async function createSubscriber(email) {
  const r = await bh("/subscriptions", "POST", {
    email: email,
    reactivate_existing: true,
    send_welcome_email: true,
    utm_source: "firmwarely.com",
    utm_campaign: "my-devices"
  });
  return r.ok;
}

// Short fingerprint of a device list. Clients send back the one they last saw so a
// stale tab can't overwrite a list edited elsewhere (see /api/me).
function devicesRev(devices) {
  const compact = (devices || []).map(function (d) { return [d.id, d.version || ""]; });
  return crypto.createHash("sha256").update(JSON.stringify(compact)).digest("hex").slice(0, 12);
}

// devices: [{id, version}] -> stored compactly as [["id","ver"],...]
async function saveDevices(subId, devices) {
  const compact = devices.map(function (d) { return [d.id, d.version || ""]; });
  const r = await bh("/subscriptions/" + subId, "PATCH", {
    custom_fields: [{ name: "devices", value: JSON.stringify(compact) }]
  });
  return r.ok;
}

// opts.replyTo lets a message we send on someone's behalf (the support form) be answered
// by hitting Reply, without ever putting their address in From — that would fail DMARC.
async function sendEmail(to, subject, html, opts) {
  const body = { from: FROM, to: [to], subject: subject, html: html };
  if (opts && opts.replyTo) body.reply_to = [opts.replyTo];
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + process.env.RESEND_API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });
  let data = null;
  try { data = await r.json(); } catch (e) {}
  return { ok: r.ok, data: data };
}

function json(res, status, obj) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(obj));
}

async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  let raw = "";
  for await (const chunk of req) raw += chunk;
  try { return JSON.parse(raw || "{}"); } catch (e) { return {}; }
}

module.exports = {
  makeToken, readToken, readTokenData, safeNext, sessionEmail, setSession, clearSession,
  normEmail, validEmail, sameOrigin, getSubscriber, lookupSubscriber, createSubscriber, unsubscribe, saveDevices, devicesRev,
  sendEmail, json, readBody
};
