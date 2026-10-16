const fw = require("../lib/fw");

module.exports = async function (req, res) {
  if (req.method !== "POST") return fw.json(res, 405, { error: "POST only" });   // no <img src=/api/logout> tricks
  // ...and no auto-submitting form on another site: the session cookie is SameSite=Lax, so it
  // isn't sent on a cross-site POST, but this response's Set-Cookie would still clear it.
  if (!fw.sameOrigin(req)) return fw.json(res, 403, { error: "Cross-site request refused." });
  fw.clearSession(res);
  return fw.json(res, 200, { ok: true });
};
