// POST {email} -> emails a sign-in link.
const fw = require("../lib/fw");

module.exports = async function (req, res) {
  if (req.method !== "POST") return fw.json(res, 405, { error: "POST only" });
  const body = await fw.readBody(req);
  const email = fw.normEmail(body.email);
  if (!fw.validEmail(email)) return fw.json(res, 400, { error: "Enter a valid email address." });

  let sub = await fw.getSubscriber(email);
  if (!sub) {
    await fw.createSubscriber(email);
    sub = await fw.getSubscriber(email);
  }
  if (!sub) return fw.json(res, 502, { error: "Couldn't set up your account just now. Try again in a minute." });

  const next = fw.safeNext(String(body.next || ""));   // where to land after the click
  let token;
  try {
    token = fw.makeToken(email, "login", 15 * 60, { n: next });
  } catch (e) {
    console.error("auth-request:", e.message);
    return fw.json(res, 500, { error: "Sign-in isn't configured yet." });
  }
  const link = (process.env.SITE_URL || "") + "/api/auth-verify?t=" + encodeURIComponent(token);
  const html =
    '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:#111">' +
    "<p>Here is your Firmwarely sign-in link. It works for 15 minutes.</p>" +
    '<p><a href="' + link + '" style="display:inline-block;background:#F5B342;color:#1A1204;' +
    'font-weight:600;padding:10px 16px;border-radius:6px;text-decoration:none">Sign in to Firmwarely</a></p>' +
    '<p style="color:#666;font-size:14px">If the button does not work, copy this into your browser:<br>' +
    link + "</p>" +
    '<p style="color:#666;font-size:14px">If you did not request this, you can ignore it.</p></div>';

  const sent = await fw.sendEmail(email, "Your Firmwarely sign-in link", html);
  if (!sent.ok) {
    const msg = (sent.data && sent.data.message) || "Couldn't send the email just now.";
    return fw.json(res, 502, { error: msg });
  }
  return fw.json(res, 200, { ok: true });
};
