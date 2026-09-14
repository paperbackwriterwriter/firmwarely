// GET  -> {email, plan, devices}
// PUT  {devices:[{id,version}]} -> saves (free plan capped at 3)
const fw = require("../lib/fw");

const FREE_LIMIT = 3;
const MAX_DEVICES = 200;

module.exports = async function (req, res) {
  const email = fw.sessionEmail(req);
  if (!email) return fw.json(res, 401, { error: "Not signed in." });

  const sub = await fw.getSubscriber(email);
  if (!sub) return fw.json(res, 404, { error: "Account not found." });

  if (req.method === "GET") {
    return fw.json(res, 200, { ok: true, email: sub.email, plan: sub.plan, devices: sub.devices });
  }
  if (req.method === "PUT") {
    const body = await fw.readBody(req);
    let devices = Array.isArray(body.devices) ? body.devices : [];
    devices = devices.map(function (d) {
      return { id: String((d && d.id) || "").slice(0, 80),
               version: String((d && d.version) || "").slice(0, 60) };
    }).filter(function (d) { return /^[a-z0-9-]+$/.test(d.id); }).slice(0, MAX_DEVICES);
    if (sub.plan !== "pro" && devices.length > FREE_LIMIT) {
      return fw.json(res, 403, { error: "Free accounts can save up to " + FREE_LIMIT +
        " devices. Upgrade to Pro for unlimited.", limit: FREE_LIMIT });
    }
    const ok = await fw.saveDevices(sub.id, devices);
    if (!ok) return fw.json(res, 502, { error: "Couldn't save just now. Try again." });
    return fw.json(res, 200, { ok: true, plan: sub.plan, devices: devices });
  }
  return fw.json(res, 405, { error: "GET or PUT only" });
};
