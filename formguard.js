// One submission every thirty seconds, per form.
//
// Each form keeps its own window, so writing to support doesn't stop you signing in. The
// budgets are named after the action rather than the element, because the hero and signup
// forms do the same thing and the server can't tell them apart: "subscribe", "contact",
// "signin".
//
// This is the polite half — it stops an impatient person double-posting and tells them how
// long to wait. It is not the enforcement: anything can skip the browser, so /api/subscribe,
// /api/contact and /api/auth-request apply the same one-in-30s limit per source, under the
// matching name. The two halves must agree, so the names and numbers are checked against the
// endpoints in the self-test.
//
// Fails open. If storage is blocked or this file never loads, forms submit as before and the
// server does the limiting — a broken counter must never be the reason someone can't reach us.
(function (w) {
  var MAX = 1;
  var WINDOW_MS = 30000;
  var KEY = "fw_form_submits";
  var memory = {};                       // fallback when localStorage throws (private windows)

  // {name: [timestamps]}. Anything else in there — including the single shared list this
  // used to keep — is treated as nothing rather than migrated.
  function load() {
    try {
      var raw = JSON.parse(w.localStorage.getItem(KEY) || "{}");
      return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    } catch (e) {
      return memory;
    }
  }

  function save(all) {
    memory = all;
    try { w.localStorage.setItem(KEY, JSON.stringify(all)); } catch (e) {}
  }

  // This form's submissions still inside the window. A timestamp in the future is a clock
  // change, not a submission; dropping it stops a wound-forward clock locking someone out.
  function live(all, name, now) {
    var times = all[name];
    if (!Array.isArray(times)) return [];
    return times.filter(function (t) {
      return typeof t === "number" && t <= now && now - t < WINDOW_MS;
    }).sort();
  }

  w.formGuard = {
    max: MAX,
    windowMs: WINDOW_MS,

    // 0 when this form may go through, otherwise whole seconds left to wait.
    wait: function (name, now) {
      now = now || Date.now();
      var times = live(load(), name, now);
      if (times.length < MAX) return 0;
      return Math.max(1, Math.ceil((WINDOW_MS - (now - times[times.length - MAX])) / 1000));
    },

    // Call immediately before the request actually goes out, not on a typo.
    record: function (name, now) {
      now = now || Date.now();
      var all = load();
      var times = live(all, name, now);
      times.push(now);
      all[name] = times;
      save(all);
    },

    message: function (secs) {
      return "One submission every 30 seconds, please. Try again in " + secs +
             (secs === 1 ? " second." : " seconds.");
    },

    // True when this form is being held back. Writes the wait into the form's own message
    // element and counts it down, so the person sees the number shrink rather than a dead form.
    hold: function (name, el, errClass) {
      if (!this.wait(name)) return false;
      var self = this;
      var idle = String(errClass || "err").replace(/\berr\b/, "").trim();
      var tick = function () {
        var left = self.wait(name);
        if (!left) {
          if (el.__fwTimer) { clearInterval(el.__fwTimer); el.__fwTimer = null; }
          el.className = idle;
          el.textContent = "";
          return;
        }
        el.className = errClass || "err";
        el.textContent = self.message(left);
      };
      tick();
      if (!el.__fwTimer) el.__fwTimer = setInterval(tick, 1000);
      return true;
    }
  };
})(window);
