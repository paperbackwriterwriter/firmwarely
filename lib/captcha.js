// Server half of the Turnstile check. See captcha.js for the browser half.
//
// Inert until TURNSTILE_SECRET is set, so the site keeps working between deploying this and
// creating the keys. Once set, a request without a valid token is refused.
const ENDPOINT = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const TIMEOUT_MS = 5000;

// { ok, reason }. reason is only meaningful when ok is false: "missing" (no token supplied)
// or "failed" (Cloudflare says no).
async function verify(token, ip) {
  const secret = process.env.TURNSTILE_SECRET;
  if (!secret) return { ok: true, reason: "not configured" };
  if (!token) return { ok: false, reason: "missing" };

  const body = { secret, response: String(token).slice(0, 2048) };
  if (ip) body.remoteip = ip;

  const control = new AbortController();
  const timer = setTimeout(() => control.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: control.signal,
    });
    const data = await r.json();
    if (data && data.success) return { ok: true, reason: "verified" };
    return { ok: false, reason: "failed", codes: (data && data["error-codes"]) || [] };
  } catch (e) {
    // Cloudflare unreachable is our infrastructure failing, not evidence about the visitor.
    // Refusing here would take signups and sign-ins down with it, so the request goes through
    // and the rate limit and honeypot carry it. Logged, because a run of these matters.
    console.error("turnstile unreachable:", e.name === "AbortError" ? "timed out" : e.message);
    return { ok: true, reason: "unreachable" };
  } finally {
    clearTimeout(timer);
  }
}

module.exports = { verify, ENDPOINT, TIMEOUT_MS };
