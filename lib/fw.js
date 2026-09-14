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

// token = base64(json).signature ; json = {e: email, x: expiry, p: purpose}
function makeToken(email, purpose, ttlSec) {
  const body = JSON.stringify({ e: email, x: Date.now() + ttlSec * 1000, p: purpose });
  const enc = b64(body);
  return enc + "." + sign(enc);
}
function readToken(token, purpose) {
  if (!token || !SECRET) return null;
  const i = token.lastIndexOf(".");
  if (i < 0) return null;
  const enc = token.slice(0, i), sig = token.slice(i + 1);
  const good = sign(enc);
  if (sig.length !== good.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(good))) return null;
  let data;
  try { data = JSON.parse(unb64(enc)); } catch (e) { return null; }
  if (data.p !== purpose || data.x < Date.now()) return null;
  return data.e;
}

function cookies(req) {
  const out = {};
  (req.headers.cookie || "").split(";").forEach(function (c) {
    const i = c.indexOf("=");
    if (i > 0) out[c.slice(0, i).trim()] = decodeURIComponent(c.slice(i + 1).trim());
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

function normEmail(e) {
  return String(e || "").trim().toLowerCase();
}
function validEmail(e) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
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

// Returns {id, email, plan, devices:[{id,version}]} or null.
async function getSubscriber(email) {
  const r = await bh("/subscriptions/by_email/" + encodeURIComponent(email)
    + "?expand=custom_fields");
  if (!r.ok || !r.data || !r.data.data) return null;
  const s = r.data.data;
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

// devices: [{id, version}] -> stored compactly as [["id","ver"],...]
async function saveDevices(subId, devices) {
  const compact = devices.map(function (d) { return [d.id, d.version || ""]; });
  const r = await bh("/subscriptions/" + subId, "PATCH", {
    custom_fields: [{ name: "devices", value: JSON.stringify(compact) }]
  });
  return r.ok;
}

async function sendEmail(to, subject, html) {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + process.env.RESEND_API_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ from: FROM, to: [to], subject: subject, html: html })
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
  makeToken, readToken, sessionEmail, setSession, clearSession,
  normEmail, validEmail, getSubscriber, createSubscriber, saveDevices,
  sendEmail, json, readBody
};
