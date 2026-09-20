// One rolling limit shared by every form on the site: one submission every thirty seconds.
//
// This is the polite half — it stops an impatient person double-posting and tells them how
// long to wait. It is not the enforcement: anything can skip the browser, so /api/subscribe,
// /api/contact and /api/auth-request apply the same one-in-30s limit per IP. The two halves
// must agree, so MAX and WINDOW_MS are checked against the endpoints in the self-test.
//
// Fails open. If storage is blocked or this file never loads, forms submit as before and the
// server does the limiting — a broken counter must never be the reason someone can't reach us.
(function (w) {
  var MAX = 1;
  var WINDOW_MS = 30000;
  var KEY = "fw_form_submits";
  var memory = [];                       // fallback when localStorage throws (private windows)

  function load() {
    try {
      var raw = JSON.parse(w.localStorage.getItem(KEY) || "[]");
      return Array.isArray(raw) ? raw.filter(function (t) { return typeof t === "number"; }) : [];
    } catch (e) {
      return memory;
    }
  }

  function save(times) {
    memory = times;
    try { w.localStorage.setItem(KEY, JSON.stringify(times)); } catch (e) {}
  }

  // Submissions still inside the window. A timestamp in the future is a clock change, not a
  // submission; dropping it stops a wound-forward clock locking someone out for good.
  function live(now) {
    return load().filter(function (t) { return t <= now && now - t < WINDOW_MS; }).sort();
  }

  w.formGuard = {
    max: MAX,
    windowMs: WINDOW_MS,

    // 0 when the form may go through, otherwise whole seconds left to wait.
    wait: function (now) {
      now = now || Date.now();
      var times = live(now);
      if (times.length < MAX) return 0;
      return Math.max(1, Math.ceil((WINDOW_MS - (now - times[times.length - MAX])) / 1000));
    },

    // Call immediately before the request actually goes out, not on a typo.
    record: function (now) {
      now = now || Date.now();
      var times = live(now);
      times.push(now);
      save(times);
    },

    message: function (secs) {
      return "One submission every 30 seconds, please. Try again in " + secs +
             (secs === 1 ? " second." : " seconds.");
    },

    // True when the form is being held back. Writes the wait into the form's own message
    // element and counts it down, so the person sees the number shrink rather than a dead form.
    hold: function (el, errClass) {
      if (!this.wait()) return false;
      var self = this;
      var idle = String(errClass || "err").replace(/\berr\b/, "").trim();
      var tick = function () {
        var left = self.wait();
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
