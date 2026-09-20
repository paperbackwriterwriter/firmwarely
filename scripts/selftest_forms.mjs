// Self-test for formguard.js — the per-form one-in-30s limit on the site's forms.
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
  check("the first submission goes through", g.wait("contact", T), 0);
  g.record("contact", T);
  check("the next one is held", g.wait("contact", T + 1) > 0, true);
  check("...and is told to wait the rest of the window", g.wait("contact", T + 1), 30);
  check("...counting down as the window slides", g.wait("contact", T + 20_000), 10);
  check("...still held one second before the window is up", g.wait("contact", T + 29_000), 1);
  check("the window releases exactly 30s after the send", g.wait("contact", T + 30_000), 0);
  g.record("contact", T + 30_001);
  check("and the next send starts its own window", g.wait("contact", T + 30_002), 30);
}

console.log("\neach form has its own window");
{
  const g = guard();
  g.record("contact", T);
  check("writing to support doesn't hold up signing in", g.wait("signin", T + 1), 0);
  check("...nor signing up for alerts", g.wait("subscribe", T + 1), 0);
  check("...while support itself is still held", g.wait("contact", T + 1), 30);
  g.record("signin", T + 5_000);
  check("each window runs on its own clock",
        [g.wait("contact", T + 25_000), g.wait("signin", T + 25_000)], [5, 10]);
  check("one form releasing doesn't release another",
        [g.wait("contact", T + 30_000), g.wait("signin", T + 30_000)], [0, 5]);
}

console.log("\nit must never lock someone out");
{
  const g = guard({ breakStorage: true });
  g.record("contact", T);
  check("storage that throws (private window) still limits in memory", g.wait("contact", T + 1), 30);
}
{
  const g = guard({ storage: { fw_form_submits: "}{ not json" } });
  check("corrupt storage is ignored rather than fatal", g.wait("contact", T), 0);
}
{
  const g = guard({ storage: { fw_form_submits: JSON.stringify({ contact: [T + 90_000_000, "x", null] }) } });
  check("a clock wound forward can't wedge the form shut", g.wait("contact", T), 0);
}
{
  // what a browser still holds from the previous, site-wide version of this file
  const g = guard({ storage: { fw_form_submits: JSON.stringify([T, T + 1]) } });
  check("the old shared list is ignored, not mistaken for a form", g.wait("contact", T + 2), 0);
}
{
  const g = guard();
  check("a form nobody has submitted is free", g.wait("never-used", T), 0);
}

console.log("\nwhat the person reads");
{
  const g = guard();
  check("plural seconds", g.message(12), "One submission every 30 seconds, please. Try again in 12 seconds.");
  check("singular second", g.message(1), "One submission every 30 seconds, please. Try again in 1 second.");
  check("the limit is exposed for anyone reading the page", [g.max, g.windowMs], [1, 30000]);
}

console.log("\nthe browser and the server agree");
{
  const g = guard();
  // name in the browser -> the endpoint that must enforce the same window under that name
  for (const [name, f] of [["subscribe", "api/subscribe.js"], ["contact", "api/contact.js"],
                           ["signin", "api/auth-request.js"]]) {
    const src = readFileSync(new URL("../" + f, import.meta.url), "utf8");
    const m = src.match(/allow\("burst:([a-z-]+):" \+ rl\.clientIp\(req\), (\d+), (\d+)\)/);
    check(`${f} enforces the same form and numbers`,
          m && [m[1], Number(m[2]), Number(m[3])], [name, g.max, g.windowMs]);
  }
}

console.log(failed.length ? `\nFAILED: ${failed.join(", ")}` : "\nall checks passed");
process.exit(failed.length ? 1 : 0);
