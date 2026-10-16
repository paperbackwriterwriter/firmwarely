// GET  ?t=token -> a page with one "Sign in" button (nothing happens yet)
// POST t=token  -> sets the session cookie and redirects to My devices.
//
// Why two steps: mail providers and link scanners open every link in an email to check it.
// If opening the link signed you in, a scanner would create the account and set a cookie
// nobody asked for. And a link someone else sent you would sign you into *their* account
// without a word; the page names the account, so that can't happen silently.
const fw = require("../lib/fw");

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function page(res, status, title, inner) {
  res.statusCode = status;
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Referrer-Policy", "no-referrer");   // the token is in this page's URL
  res.end(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>${esc(title)} | Firmwarely</title>
<style>body{margin:0;background:#0C1117;color:#E3E9EE;font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:460px;margin:12vh auto;padding:0 1.25rem}h1{font-size:1.5rem;margin:0 0 1rem}p{color:#8A98A5}
button{font:inherit;font-weight:600;border:1px solid #F5B342;background:#F5B342;color:#1A1204;padding:.6rem 1.2rem;border-radius:6px;cursor:pointer}
a{color:#E3E9EE}</style></head><body><main>${inner}</main></body></html>`);
}

function expired(res) {
  res.statusCode = 302;
  res.setHeader("Location", "/my-devices.html?signin=expired");
  return res.end();
}

async function readToken(req) {
  if (req.method === "POST") {
    if (!fw.sameOrigin(req)) return null;
    let raw = "";
    if (req.body && typeof req.body === "object" && !Buffer.isBuffer(req.body)) return req.body.t || null;
    if (Buffer.isBuffer(req.body)) raw = req.body.toString();
    else if (typeof req.body === "string") raw = req.body;
    else for await (const chunk of req) raw += chunk;
    return new URLSearchParams(raw).get("t");
  }
  return new URL(req.url, "http://x").searchParams.get("t");
}

module.exports = async function (req, res) {
  if (req.method !== "GET" && req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    return fw.json(res, 405, { error: "GET or POST only" });
  }
  const token = await readToken(req);
  const data = fw.readTokenData(token, "login");
  const email = data && data.e;
  if (!email) return expired(res);

  if (req.method === "GET") {
    return page(res, 200, "Sign in",
      `<h1>Sign in to Firmwarely</h1>
<p>You're signing in as <strong style="color:#E3E9EE">${esc(email)}</strong>. If that isn't your address, close this page.</p>
<form method="post" action="/api/auth-verify"><input type="hidden" name="t" value="${esc(token)}">
<button type="submit">Sign in</button></form>`);
  }

  // First sign-in creates the account: they clicked a link we sent to this address, and
  // pressed the button, which is the consent auth-request deliberately doesn't assume.
  if (!(await fw.getSubscriber(email))) await fw.createSubscriber(email);
  fw.setSession(res, email);
  res.statusCode = 303;
  res.setHeader("Location", fw.safeNext(data.n) + "?signin=ok");
  res.end();
};
