// In-memory rate limiter. Each Vercel function instance keeps its own window, so this
// throttles a single source hammering one warm instance; a distributed attacker or a cold
// start gets a fresh window. It is a speed bump, not a wall — a shared store (Vercel KV,
// Upstash) is what makes it a wall. Kept here so the call sites don't change when that lands.
const hits = new Map();

// true if `key` has been seen fewer than `max` times in the last `windowMs`
function allow(key, max, windowMs) {
  const now = Date.now();
  const arr = (hits.get(key) || []).filter(function (t) { return now - t < windowMs; });
  if (arr.length >= max) { hits.set(key, arr); return false; }
  arr.push(now); hits.set(key, arr);
  if (hits.size > 5000) hits.clear();          // don't let a flood grow the map without bound
  return true;
}

function clientIp(req) {
  const xf = String(req.headers["x-forwarded-for"] || "");
  return xf.split(",")[0].trim() || req.socket?.remoteAddress || "unknown";
}

module.exports = { allow, clientIp };
