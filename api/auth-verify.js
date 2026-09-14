// GET ?t=token -> sets session cookie and redirects to My devices.
const fw = require("../lib/fw");

module.exports = async function (req, res) {
  const url = new URL(req.url, "http://x");
  const email = fw.readToken(url.searchParams.get("t"), "login");
  if (!email) {
    res.statusCode = 302;
    res.setHeader("Location", "/my-devices.html?signin=expired");
    return res.end();
  }
  fw.setSession(res, email);
  res.statusCode = 302;
  res.setHeader("Location", "/my-devices.html?signin=ok");
  res.end();
};
