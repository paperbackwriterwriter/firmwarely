// Self-test for formguard.js — the shared 3-in-30s limit on the site's forms.
//
//     node scripts/selftest_forms.mjs
//
// Runs the real file in a VM with a fake window, so the arithmetic is tested rather than
// re-implemented, and checks that the browser's numbers still match the ones the API
// endpoints enforce. The two drifting apart is the failure that would matter: the browser
// would wave through submissions the server then rejects with a different message.
import { readFileSync } from "node:fs";
import vm from "node:vm";

let failed = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"} ${label}`);
  if (!ok) { console.log(`         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); failed.push(label); }
};

function guard({ storage = {}, breakStorage = false } = {}) {
  const localStorage = {
    getItem: (k) => { if (breakStorage) throw new Error("denied"); return k in storage ? storage[k] : null; },
    setItem: (k, v) => { if (breakStorage) throw new Error("denied"); storage[k] = String(v); },
  };
  const win = { localStorage };
  const ctx = vm.createContext({ window: win, Date, JSON, Array, String, Math,
                                 setInterval: () => 0, clearInterval: () => {} });
  vm.runInContext(readFileSync(new URL("../formguard.js", import.meta.url), "utf8"), ctx);
  return win.formGuard;
}

const T = 1_000_000_000_000;   // a fixed "now" so nothing depends on the wall clock

console.log("\nthe limit itself");
{
  const g = guard();
  check("three submissions go through", [g.wait(T), (g.record(T), g.wait(T + 1)),
                                         (g.record(T + 1), g.wait(T + 2))], [0, 0, 0]);
  g.record(T + 2);
  check("the fourth inside the window is held", g.wait(T + 3) > 0, true);
  check("...and is told to wait the rest of the window", g.wait(T + 3), 30);
  check("...counting down as the window slides", g.wait(T + 20_000), 10);
  check("the window releases exactly when the oldest ages out", g.wait(T + 30_000), 0);
  g.record(T + 30_001);
  check("a fresh burst starts over", g.wait(T + 30_002), 0);
}

console.log("\nit must never lock someone out");
{
  const g = guard({ breakStorage: true });
  g.record(T); g.record(T + 1); g.record(T + 2);
  check("storage that throws (private window) still limits in memory", g.wait(T + 3), 30);
}
{
  const g = guard({ storage: { fw_form_submits: "}{ not json" } });
  check("corrupt storage is ignored rather than fatal", g.wait(T), 0);
}
{
  const g = guard({ storage: { fw_form_submits: JSON.stringify([T + 90_000_000, "x", null]) } });
  check("a clock wound forward can't wedge the form shut", g.wait(T), 0);
}

console.log("\nwhat the person reads");
{
  const g = guard();
  check("plural seconds", g.message(12), "That's three in half a minute. Give it 12 seconds and try again.");
  check("singular second", g.message(1), "That's three in half a minute. Give it 1 second and try again.");
  check("the limit is exposed for anyone reading the page", [g.max, g.windowMs], [3, 30000]);
}

console.log("\nthe browser and the server agree");
{
  const g = guard();
  for (const f of ["api/subscribe.js", "api/contact.js", "api/auth-request.js"]) {
    const src = readFileSync(new URL("../" + f, import.meta.url), "utf8");
    const m = src.match(/allow\("burst:" \+ rl\.clientIp\(req\), (\d+), (\d+)\)/);
    check(`${f} enforces the same numbers`, m && [Number(m[1]), Number(m[2])], [g.max, g.windowMs]);
  }
}

console.log(failed.length ? `\nFAILED: ${failed.join(", ")}` : "\nall checks passed");
process.exit(failed.length ? 1 : 0);
