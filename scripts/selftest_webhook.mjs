// The Stripe webhook is the difference between someone paying and actually getting Pro,
// and it is only exercised by real money, so its two decisions are tested here instead:
// is this event genuinely from Stripe, and what plan does it imply.
//
//   node scripts/selftest_webhook.mjs
//
// The handler is loaded from source through a data: URL because the repo has no
// package.json, so Node would otherwise read a .js file as CommonJS and refuse its imports.
import crypto from "node:crypto";
import { readFile } from "node:fs/promises";
import { Readable } from "node:stream";

const src = await readFile(new URL("../api/stripe-webhook.js", import.meta.url), "utf8");
const wh = await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"));

const FAILED = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}` + (ok ? "" : `\n       got ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`));
  if (!ok) FAILED.push(label);
};

const SECRET = "whsec_testsecret";
const sign = (raw, secret = SECRET, t = Math.floor(Date.now() / 1000)) =>
  `t=${t},v1=${crypto.createHmac("sha256", secret).update(`${t}.`).update(raw).digest("hex")}`;

console.log("a forged or stale event never reaches Beehiiv");
const body = Buffer.from(JSON.stringify({ id: "evt_1", type: "checkout.session.completed" }));
check("a correctly signed event passes", wh.verify(body, sign(body), SECRET), true);
check("a different secret is rejected", wh.verify(body, sign(body, "whsec_other"), SECRET), false);
check("a tampered body is rejected",
      wh.verify(Buffer.from(body.toString().replace("evt_1", "evt_2")), sign(body), SECRET), false);
check("a replay outside the 5-minute window is rejected",
      wh.verify(body, sign(body, SECRET, Math.floor(Date.now() / 1000) - 600), SECRET), false);
check("a missing header is rejected", wh.verify(body, "", SECRET), false);
check("a header with no v1 is rejected", wh.verify(body, "t=123", SECRET), false);

console.log("\nduring a signing-secret rotation Stripe sends one v1 per active secret");
const t = Math.floor(Date.now() / 1000);
const mine = crypto.createHmac("sha256", SECRET).update(`${t}.`).update(body).digest("hex");
const other = crypto.createHmac("sha256", "whsec_rotating").update(`${t}.`).update(body).digest("hex");
check("ours first, theirs second", wh.verify(body, `t=${t},v1=${mine},v1=${other}`, SECRET), true);
check("theirs first, ours second", wh.verify(body, `t=${t},v1=${other},v1=${mine}`, SECRET), true);
check("neither is ours", wh.verify(body, `t=${t},v1=${other}`, SECRET), false);

console.log("\nthe raw body survives a chunk boundary inside a multi-byte character");
const utf8 = Buffer.from(JSON.stringify({ name: "Café Müller ✓", type: "x" }), "utf8");
const cut = utf8.indexOf(Buffer.from("é")[0]) + 1;          // mid-character on purpose
const req = Readable.from([utf8.subarray(0, cut), utf8.subarray(cut)]);
const reassembled = await wh.readRaw(req);
check("bytes are identical to what was sent", reassembled.equals(utf8), true);
check("and its signature still verifies", wh.verify(reassembled, sign(utf8), SECRET), true);

console.log("\nwhich events grant Pro, which take it away, and which are ignored");
const cases = [
  ["a subscription checkout grants pro", "checkout.session.completed", { mode: "subscription" }, "pro"],
  ["a one-off payment grants nothing", "checkout.session.completed", { mode: "payment" }, null],
  ["a deleted subscription drops to free", "customer.subscription.deleted", {}, "free"],
  ["a cancelled subscription drops to free", "customer.subscription.updated", { status: "canceled" }, "free"],
  ["an unpaid subscription drops to free", "customer.subscription.updated", { status: "unpaid" }, "free"],
  ["an expired incomplete drops to free", "customer.subscription.updated", { status: "incomplete_expired" }, "free"],
  ["an active subscription is pro", "customer.subscription.updated", { status: "active" }, "pro"],
  ["a trialing subscription is left alone", "customer.subscription.updated", { status: "trialing" }, null],
  ["a past_due subscription is left alone", "customer.subscription.updated", { status: "past_due" }, null],
  ["an invoice event is ignored", "invoice.paid", {}, null],
];
for (const [label, type, obj, want] of cases) check(label, wh.planFor(type, obj), want);

console.log("\nthe function still tells Vercel not to parse the body for us");
check("bodyParser stays off", wh.config?.api?.bodyParser, false);

console.log(`\n${FAILED.length ? "FAILED: " + FAILED.join(", ") : "all checks passed"}`);
process.exit(FAILED.length ? 1 : 0);
