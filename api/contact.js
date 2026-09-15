// POST {name, email, subject, message} -> emails the support inbox.
// The public form on /support/ posts here. Nothing is stored: the message is relayed to
// SUPPORT_TO and answered by hitting Reply, which lands in the sender's inbox.
const fw = require("../lib/fw");
const rl = require("../lib/ratelimit");

const TO = process.env.SUPPORT_TO || "hello@firmwarely.com";
const MAX = { name: 120, subject: 160, message: 5000 };

function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}

module.exports = async function (req, res) {
  if (req.method !== "POST") return fw.json(res, 405, { error: "POST only" });
  const body = await fw.readBody(req);

  // Honeypot: the field is off-screen, so a person never fills it in and a bot fills in
  // everything. Answer 200 so the bot has nothing to learn from the difference.
  if (String(body.website || "").trim()) return fw.json(res, 200, { ok: true });

  const email = fw.normEmail(body.email);
  const name = String(body.name || "").trim().slice(0, MAX.name);
  const subject = String(body.subject || "").trim().slice(0, MAX.subject) || "Support request";
  const message = String(body.message || "").trim().slice(0, MAX.message);

  if (!fw.validEmail(email)) return fw.json(res, 400, { error: "Enter a valid email address so we can reply." });
  if (message.length < 10) return fw.json(res, 400, { error: "Tell us a bit more about what you need — a sentence is plenty." });

  // This endpoint puts mail in our own inbox, so the risk is flooding rather than
  // spamming strangers. Throttle per address and per source either way.
  if (!rl.allow("contact:" + email, 3, 15 * 60 * 1000) || !rl.allow("contact-ip:" + rl.clientIp(req), 10, 15 * 60 * 1000)) {
    return fw.json(res, 429, { error: "That's a few messages in a row. Give it a few minutes, or email hello@firmwarely.com directly." });
  }

  const html =
    '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#111">' +
    "<p><strong>From:</strong> " + esc(name || "(no name given)") + " &lt;" + esc(email) + "&gt;<br>" +
    "<strong>Topic:</strong> " + esc(subject) + "</p><hr>" +
    "<p style=\"white-space:pre-wrap\">" + esc(message) + "</p><hr>" +
    '<p style="color:#666;font-size:13px">Sent from the form on firmwarely.com/support/. Reply to this email to answer them.</p></div>';

  const sent = await fw.sendEmail(TO, "[Firmwarely] " + subject, html, { replyTo: email });
  if (!sent.ok) {
    console.error("contact: send failed", sent.data && sent.data.message);
    return fw.json(res, 502, { error: "Couldn't send that just now. Please email hello@firmwarely.com directly." });
  }
  return fw.json(res, 200, { ok: true });
};
