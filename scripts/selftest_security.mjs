// 2026-10-16 QA: the API's security fixes, against fake Beehiiv/Stripe/Resend; no network.
import { createRequire } from "module";
import crypto from "node:crypto";
const require = createRequire(import.meta.url);
process.env.BEEHIIV_API_KEY = "k";
process.env.BEEHIIV_PUB_ID = "pub";
process.env.AUTH_SECRET = "test-secret";
process.env.STRIPE_WEBHOOK_SECRET = "whsec_test";
process.env.STRIPE_SECRET_KEY = "sk_test";
delete process.env.TURNSTILE_SECRET;

const failed = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}`);
  if (!ok) { failed.push(label); console.log(`         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); }
};

// ---- a fake outside world ----
let beehiiv = { lookup: 404, sub: null, patchOk: true }, calls = [];
let stripeActive = [];
const reply = (status, body) => ({ ok: status < 300, status, json: async () => body, text: async () => JSON.stringify(body),
                                   clone() { return this; } });
globalThis.fetch = async (url, opts = {}) => {
  url = String(url);
  calls.push({ url, method: opts.method || "GET", body: opts.body ? JSON.parse(opts.body) : null });
  if (url.includes("api.stripe.com")) return reply(200, { data: stripeActive });
  if (url.includes("api.resend.com")) return reply(200, { id: "e1" });
  if (url.includes("/subscriptions/by_email/")) {
    if (beehiiv.lookup === 404) return reply(404, {});
    if (beehiiv.lookup !== 200) return reply(beehiiv.lookup, {});
    return reply(200, { data: beehiiv.sub });
  }
  if ((opts.method || "GET") === "PATCH") return reply(beehiiv.patchOk ? 200 : 500, {});
  if ((opts.method || "GET") === "POST") return reply(beehiiv.postStatus || 201, beehiiv.postBody || {});
  return reply(200, {});
};

let ipN = 0;
function res() {
  return { statusCode: 0, code: 0, headers: {}, body: null,
    status(c) { this.code = this.statusCode = c; return this; },
    json(b) { this.body = b; return this; }, setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
    end(b) { if (b) this.body = b; this.code = this.code || this.statusCode; } };
}
function req(method, opts = {}) {
  return { method, url: opts.url || "/", headers: { host: "www.firmwarely.com", "x-forwarded-for": `10.1.0.${++ipN}`, ...(opts.headers || {}) },
           socket: {}, body: opts.body };
}

const fw = require("../lib/fw.js");

console.log("tokens and cookies never throw");
const good = fw.makeToken("a@e.com", "login", 60);
const [enc] = good.split(".");
let threw = false;
try {
  fw.readTokenData(enc + "." + "é".repeat(43), "login");             // right length in characters, not bytes
  fw.readTokenData(Buffer.from("null").toString("base64url") + ".x", "login");
} catch (e) { threw = true; }
check("a crafted signature is just invalid, not a crash", threw, false);
const nullTok = Buffer.from("null").toString("base64url");
check("a signed 'null' payload is invalid", fw.readTokenData(nullTok + "." + crypto.createHmac("sha256", "test-secret").update(nullTok).digest("base64url"), "login"), null);
check("a good token still reads", fw.readToken(good, "login"), "a@e.com");
check("a stray % in another cookie doesn't sign anyone out",
      fw.sessionEmail({ headers: { cookie: "other=50%; fw_session=" + fw.makeToken("a@e.com", "session", 60) } }), "a@e.com");

console.log("email check is bounded");
const t0 = Date.now();
fw.validEmail("a@" + ".".repeat(50000) + " ");
check("a huge dotted string is rejected fast", Date.now() - t0 < 200, true);
check("an ordinary address still passes", fw.validEmail("pat@example.com"), true);

console.log("logout");
const logout = require("../api/logout.js");
let r = res(); await logout(req("POST", { headers: { origin: "https://evil.example" } }), r);
check("another site can't sign you out", r.statusCode, 403);
r = res(); await logout(req("POST", { headers: { origin: "https://www.firmwarely.com" } }), r);
check("our own page can", r.statusCode, 200);

console.log("sign-in link");
const verify = require("../api/auth-verify.js");
const token = fw.makeToken("pat@example.com", "login", 900, { n: "/my-devices.html" });
calls = []; beehiiv = { lookup: 404 };
r = res(); await verify(req("GET", { url: "/api/auth-verify?t=" + encodeURIComponent(token) }), r);
check("opening the link (or a scanner opening it) only shows a page",
      [r.statusCode, r.headers["set-cookie"] || null, calls.length], [200, null, 0]);
check("the page names the account", String(r.body).includes("pat@example.com"), true);
r = res(); await verify(req("POST", { body: "t=" + encodeURIComponent(token), headers: { origin: "https://www.firmwarely.com" } }), r);
check("pressing Sign in signs in", [r.statusCode, /^fw_session=/.test(r.headers["set-cookie"] || ""), r.headers.location],
      [303, true, "/my-devices.html?signin=ok"]);
r = res(); await verify(req("POST", { body: "t=" + encodeURIComponent(token), headers: { origin: "https://evil.example" } }), r);
check("another site can't submit it for you", [r.statusCode, r.headers["set-cookie"] || null], [302, null]);

console.log("unsubscribe");
const unsub = require("../api/unsubscribe.js");
beehiiv = { lookup: 200, sub: { id: "sub_9", email: "pat@example.com", status: "active", custom_fields: [] }, patchOk: true };
calls = [];
r = res(); await unsub(req("GET", { url: "/api/unsubscribe?e=pat%40example.com" }), r);
check("the link opens a page with the address filled in", [r.statusCode, String(r.body).includes('value="pat@example.com"'), calls.length], [200, true, 0]);
r = res(); await unsub(req("POST", { body: "e=pat%40example.com", headers: { origin: "https://www.firmwarely.com" } }), r);
const patch = calls.find((c) => c.method === "PATCH");
check("the button unsubscribes them in Beehiiv", [r.statusCode, patch && patch.url.endsWith("/subscriptions/sub_9"), patch && patch.body], [200, true, { unsubscribe: true }]);
calls = [];
r = res(); await unsub(req("POST", { url: "/api/unsubscribe?e=pat%40example.com", body: "List-Unsubscribe=One-Click" }), r);
check("a mail app's one-click unsubscribe works", [r.statusCode, calls.some((c) => c.method === "PATCH")], [200, true]);
r = res(); await unsub(req("POST", { body: "e=pat%40example.com", headers: { origin: "https://evil.example" } }), r);
check("another site's form is refused", r.statusCode, 403);
beehiiv = { lookup: 404 }; calls = [];
r = res(); await unsub(req("POST", { body: "e=nobody%40example.com", headers: { origin: "https://www.firmwarely.com" } }), r);
check("an unknown address gets the same answer (no list lookup by the public)", [r.statusCode, calls.some((c) => c.method === "PATCH")], [200, false]);
beehiiv = { lookup: 500 };
r = res(); await unsub(req("POST", { body: "e=pat%40example.com", headers: { origin: "https://www.firmwarely.com" } }), r);
check("if Beehiiv is down it says so instead of claiming success", r.statusCode, 502);

console.log("signup form");
const subscribe = require("../api/subscribe.js");
async function signup(devices) {
  calls = [];
  const r = res();
  await subscribe(req("POST", { body: { email: "pat@example.com", devices, plan: "free" } }), r);
  return { code: r.code, posts: calls.filter((c) => c.method === "POST").map((c) => c.body) };
}
beehiiv = { lookup: 404 };
let s = await signup("Eero Pro 6E");
check("an anonymous form never re-subscribes someone who left", s.posts[0].reactivate_existing, false);
beehiiv = { lookup: 500 };
s = await signup("Eero Pro 6E");
check("if we can't see their saved list, typed devices don't overwrite it", s.posts[0].custom_fields, undefined);
beehiiv = { lookup: 404, postStatus: 503 };
s = await signup("Eero Pro 6E");
check("a Beehiiv outage is not retried without the devices (and says it failed)", [s.code, s.posts.length], [502, 1]);

console.log("Stripe webhook");
const hook = await import("../api/stripe-webhook.js");
function signed(event) {
  const raw = Buffer.from(JSON.stringify(event)), t = Math.floor(Date.now() / 1000);
  const sig = crypto.createHmac("sha256", "whsec_test").update(`${t}.`).update(raw).digest("hex");
  return { raw, header: `t=${t},v1=${sig}` };
}
async function deliver(event, extraHeader) {
  const { raw, header } = signed(event);
  const r = res();
  const q = { method: "POST", headers: { "stripe-signature": extraHeader || header },
              on(ev, fn) { if (ev === "data") fn(raw); if (ev === "end") fn(); return this; } };
  await hook.default(q, r);
  return r;
}
let threw2 = false;
try { await deliver({ type: "x" }, "t=" + Math.floor(Date.now() / 1000) + ",v1=" + "é".repeat(64)); } catch (e) { threw2 = true; }
check("a forged signature header is a 400, not a crash", threw2, false);
const checkout = { type: "checkout.session.completed", data: { object: { mode: "subscription", customer_details: { email: "pat@example.com" } } } };
beehiiv = { lookup: 200, sub: { id: "sub_9" }, patchOk: false };
r = await deliver(checkout);
check("a failed plan write answers 500 so Stripe retries", r.code, 500);
beehiiv = { lookup: 200, sub: { id: "sub_9" }, patchOk: true };
r = await deliver(checkout);
check("a good write answers 200", [r.code, r.body.plan], [200, "pro"]);
stripeActive = [];
r = await deliver({ type: "customer.subscription.updated", data: { object: { status: "active", customer: "cus_1", customer_email: "pat@example.com" } } });
check("a late 'active' for a cancelled customer doesn't give Pro back", r.body.plan, "free");
stripeActive = [{ id: "sub_live" }];
r = await deliver({ type: "customer.subscription.updated", data: { object: { status: "active", customer: "cus_1", customer_email: "pat@example.com" } } });
check("...while a real one still does", r.body.plan, "pro");

console.log("rate limiter under a flood");
const rl = require("../lib/ratelimit.js");
for (let i = 0; i < 3; i++) rl.allow("email:victim@e.com", 3, 900000);
for (let i = 0; i < 20000; i++) rl.allow("junk" + i, 1, 30000);
check("throwaway keys can't wipe a per-address limit", rl.allow("email:victim@e.com", 3, 900000), false);

console.log(failed.length ? `\nFAILED: ${failed.join(", ")}` : "\nall checks passed");
process.exit(failed.length ? 1 : 0);
