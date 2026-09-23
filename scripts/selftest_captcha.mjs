// Self-test for lib/captcha.js — the Turnstile check on the site's forms.
//
//     node scripts/selftest_captcha.mjs
//
// The logic runs against a stubbed fetch, so the decisions are tested without the network.
// The last section then calls the real siteverify with Cloudflare's documented test secrets,
// which is what catches the contract changing under us. That part needs network; without it
// it says so and moves on rather than failing the build for the wrong reason.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);

let failed = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}`);
  if (!ok) { console.log(`         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); failed.push(label); }
};

const captcha = require("../lib/captcha.js");
const realFetch = globalThis.fetch;
const stub = (impl) => { globalThis.fetch = impl; };
const withSecret = async (secret, fn) => {
  const had = process.env.TURNSTILE_SECRET;
  if (secret === null) delete process.env.TURNSTILE_SECRET; else process.env.TURNSTILE_SECRET = secret;
  try { return await fn(); } finally {
    if (had === undefined) delete process.env.TURNSTILE_SECRET; else process.env.TURNSTILE_SECRET = had;
  }
};

console.log("\nbefore the keys exist, the site must keep working");
await withSecret(null, async () => {
  let called = false;
  stub(async () => { called = true; });
  const r = await captcha.verify("", "1.2.3.4");
  check("no secret configured: the request goes through", r.ok, true);
  check("...and Cloudflare is never called", called, false);
});

console.log("\nonce configured");
await withSecret("test-secret", async () => {
  stub(async () => { throw new Error("should not be called"); });
  check("a missing token is refused", await captcha.verify("", "1.2.3.4"),
        { ok: false, reason: "missing" });

  let sent = null;
  stub(async (url, opt) => { sent = { url, body: JSON.parse(opt.body) };
                             return { json: async () => ({ success: true }) }; });
  const good = await captcha.verify("a-token", "9.9.9.9");
  check("a good token passes", good.ok, true);
  check("...posted to the documented endpoint", sent.url, captcha.ENDPOINT);
  check("...with the secret, the token and the caller's IP",
        sent.body, { secret: "test-secret", response: "a-token", remoteip: "9.9.9.9" });

  stub(async () => ({ json: async () => ({ success: false, "error-codes": ["invalid-input-response"] }) }));
  const bad = await captcha.verify("forged", null);
  check("a token Cloudflare rejects is refused", [bad.ok, bad.reason], [false, "failed"]);
  check("...and the reason is kept for the log", bad.codes, ["invalid-input-response"]);

  // Cloudflare being unreachable is our infrastructure failing, not evidence about the
  // visitor. Refusing would take signups and sign-ins down with it.
  stub(async () => { throw new Error("getaddrinfo ENOTFOUND"); });
  const down = await captcha.verify("a-token", null);
  check("an unreachable Cloudflare does not lock the forms", [down.ok, down.reason], [true, "unreachable"]);

  stub(async (u, opt) => new Promise((_, rej) => opt.signal.addEventListener("abort",
        () => rej(Object.assign(new Error("aborted"), { name: "AbortError" })))));
  const slow = await captcha.verify("a-token", null);
  check("...nor does one that hangs", [slow.ok, slow.reason], [true, "unreachable"]);
  check("the timeout is short enough to not hold a request open", captcha.TIMEOUT_MS <= 5000, true);
});

console.log("\nagainst the real siteverify (Cloudflare's documented test keys)");
globalThis.fetch = realFetch;
// https://developers.cloudflare.com/turnstile/troubleshooting/testing/
const ALWAYS_PASSES = "1x0000000000000000000000000000000AA";
const ALWAYS_FAILS = "2x0000000000000000000000000000000AA";
try {
  const probe = await withSecret(ALWAYS_PASSES, () => captcha.verify("XXXX.DUMMY.TOKEN.XXXX", null));
  if (probe.reason === "unreachable") {
    console.log("  --   skipped: no network to challenges.cloudflare.com");
  } else {
    check("the always-passes test secret passes", [probe.ok, probe.reason], [true, "verified"]);
    const fail = await withSecret(ALWAYS_FAILS, () => captcha.verify("XXXX.DUMMY.TOKEN.XXXX", null));
    check("the always-fails test secret is refused", [fail.ok, fail.reason], [false, "failed"]);
  }
} catch (e) {
  console.log("  --   skipped:", e.message);
}

console.log(failed.length ? `\nFAILED: ${failed.join(", ")}` : "\nall checks passed");
process.exit(failed.length ? 1 : 0);
