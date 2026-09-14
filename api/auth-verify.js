// GET ?t=token -> sets session cookie and redirects to My devices.
const fw = require("../lib/fw");

module.exports = async function (req, res) {
  const url = new URL(req.url, "http://x");
  const data = fw.readTokenData(url.searchParams.get("t"), "login");
  const email = data && data.e;
  if (!email) {
    res.statusCode = 302;
    res.setHeader("Location", "/my-devices.html?signin=expired");
    return res.end();
  }
  // First sign-in creates the account: they clicked a link we sent to this address,
  // which is the consent auth-request deliberately doesn't assume.
  if (!(await fw.getSubscriber(email))) await fw.createSubscriber(email);
  fw.setSession(res, email);
  res.statusCode = 302;
  res.setHeader("Location", fw.safeNext(data.n) + "?signin=ok");
  res.end();
};
