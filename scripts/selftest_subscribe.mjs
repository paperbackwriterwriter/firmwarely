// A signup box must not overwrite the device list someone keeps on My devices.
// Runs api/subscribe.js against a fake Beehiiv; no network.
import { createRequire } from "module";
const require = createRequire(import.meta.url);
process.env.BEEHIIV_API_KEY = "k";
process.env.BEEHIIV_PUB_ID = "pub";
delete process.env.TURNSTILE_SECRET;

const failed = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}`);
  if (!ok) { failed.push(label); console.log(`         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); }
};

let existingField = null, posted = [];
globalThis.fetch = async (url, opts = {}) => {
  if (String(url).includes("/subscriptions/by_email/")) {
    if (existingField === null) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ data: { id: "sub_1", email: "a@e.com", status: "active",
      custom_fields: [{ name: "devices", value: existingField }] } }) };
  }
  posted.push(JSON.parse(opts.body));
  return { ok: true, status: 201, text: async () => "", json: async () => ({}) };
};

const handler = require("../api/subscribe.js");
let n = 0;
async function signup(devices) {
  posted = [];
  const res = { code: 0, headers: {}, status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; },
                setHeader() {} };
  // a new address each time so the per-source limits don't get in the way
  await handler({ method: "POST", headers: { "x-forwarded-for": `10.0.0.${++n}` }, socket: {},
                  body: { email: "a@e.com", devices, plan: "free" } }, res);
  return { code: res.code, fields: posted[0] && posted[0].custom_fields };
}

console.log("signup boxes and saved lists");
existingField = null;
check("a new subscriber's typed devices are kept", await signup("Eero Pro 6E"),
      { code: 200, fields: [{ name: "devices", value: "Eero Pro 6E" }] });
existingField = '[["synology-ds923-plus",""]]';
check("a saved My devices list is not replaced", await signup("Eero Pro 6E"), { code: 200, fields: undefined });
existingField = "Traefik";
check("an earlier typed list can be replaced by a newer one", await signup("Eero Pro 6E"),
      { code: 200, fields: [{ name: "devices", value: "Eero Pro 6E" }] });
existingField = null;
check("no devices typed, no field written", await signup(""), { code: 200, fields: undefined });

console.log(failed.length ? `\nFAILED: ${failed.join(", ")}` : "\nall checks passed");
process.exit(failed.length ? 1 : 0);
