const fw = require("../lib/fw");

module.exports = async function (req, res) {
  fw.clearSession(res);
  return fw.json(res, 200, { ok: true });
};
