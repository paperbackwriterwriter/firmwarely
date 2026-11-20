// Where the API code reads its configuration (BEEHIIV_API_KEY, AUTH_SECRET, ...).
//
// On Vercel that is process.env, as it always was. On Cloudflare Pages the variables arrive
// per request as context.env, so lib/pages-adapter.js runs each handler inside withEnv() and
// env() hands back that object for the length of the request, across every await.
// Nothing reads configuration at load time any more: on Workers there is none until a request.
let store = null;
try {
  const { AsyncLocalStorage } = require("node:async_hooks");
  store = new AsyncLocalStorage();
} catch (e) {}

function env() {
  const scoped = store && store.getStore();
  if (scoped) return scoped;
  return (typeof process !== "undefined" && process.env) || {};
}

function withEnv(vars, fn) {
  if (!store) throw new Error("AsyncLocalStorage is unavailable (Cloudflare needs the nodejs_compat flag)");
  return store.run(vars || {}, fn);
}

module.exports = { env, withEnv };
