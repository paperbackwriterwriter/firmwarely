const fw = require("../lib/fw");

module.exports = async function (req, res) {
  if (req.method !== "POST") return fw.json(res, 405, { error: "POST only" });   // no <img src=/api/logout> tricks
  fw.clearSession(res);
  return fw.json(res, 200, { ok: true });
};
