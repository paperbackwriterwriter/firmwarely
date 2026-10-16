// In-memory rate limiter. Each Vercel function instance keeps its own window, so this
// throttles a single source hammering one warm instance; a distributed attacker or a cold
// start gets a fresh window. It is a speed bump, not a wall — a shared store (Vercel KV,
// Upstash) is what makes it a wall. Kept here so the call sites don't change when that lands.
const hits = new Map();
const LONGEST_WINDOW_MS = 15 * 60 * 1000;   // the per-address windows in api/*.js

// true if `key` has been seen fewer than `max` times in the last `windowMs`
function allow(key, max, windowMs) {
  const now = Date.now();
  const arr = (hits.get(key) || []).filter(function (t) { return now - t < windowMs; });
  if (arr.length >= max) { hits.set(key, arr); return false; }
  arr.push(now); hits.set(key, arr);
  // Bound the map without wiping it: clearing everything would let a flood of throwaway keys
  // reset every per-address limit. A Map iterates oldest-first, so drop the oldest keys.
  if (hits.size > 5000) {
    // first forget sources quiet for longer than the longest window any caller uses
    for (const [k, ts] of hits) { if (now - ts[ts.length - 1] > LONGEST_WINDOW_MS) hits.delete(k); }
    // then the sources with the fewest recent hits: a flood is many one-hit keys, while the
    // keys worth keeping are the ones close to (or at) their limit
    for (let n = 1; hits.size > 4000; n++) {
      for (const [k, ts] of hits) { if (hits.size <= 4000) break; if (k !== key && ts.length <= n) hits.delete(k); }
    }
  }
  return true;
}

function clientIp(req) {
  const xf = String(req.headers["x-forwarded-for"] || "");
  return xf.split(",")[0].trim() || req.socket?.remoteAddress || "unknown";
}

module.exports = { allow, clientIp };
