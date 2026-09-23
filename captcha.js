// Cloudflare Turnstile on every form that posts to us.
//
// Paste your site key below to switch it on. The key is public — it is meant to be read by
// anyone viewing the page — so it belongs in the repository. The matching secret does not:
// that goes in Vercel as TURNSTILE_SECRET, and the endpoints verify tokens against it.
//
// While SITE_KEY is empty nothing is loaded, no widget appears, and the forms behave exactly
// as they did before: unconfigured must never mean broken. The server half is inert until
// TURNSTILE_SECRET is set.
//
// ORDER MATTERS. Site key first, secret second — and to switch it off, the reverse: remove
// the secret, then empty the key. A secret with no key live makes the server demand a token
// no page is sending, and every form is refused. That happened for a few minutes on
// 2026-09-23 when the secret went in before the key had deployed.
var TURNSTILE_SITE_KEY = "0x4AAAAAAFBDZ45f7AUzE4Vk";

(function (w, d) {
  var SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js";
  var FIELD = "cf-turnstile-response";        // the hidden input Turnstile injects into the form

  w.formCaptcha = {
    // Whether a token is expected at all. Handlers use this to decide if a missing token is
    // a problem or simply how the site is configured today.
    required: function () { return !!TURNSTILE_SITE_KEY; },

    // The token for this form, or "" when the widget hasn't finished (or isn't there).
    token: function (form) {
      var input = form && form.querySelector('[name="' + FIELD + '"]');
      return (input && input.value) || "";
    },

    // Tokens are single-use and expire after five minutes, so a form that stays on screen
    // after a send needs a fresh one before the next.
    reset: function (form) {
      var box = form && form.querySelector(".fw-captcha");
      if (box && w.turnstile) { try { w.turnstile.reset(box); } catch (e) {} }
    },

    // What to tell someone whose widget hasn't produced a token yet.
    pending: "Finish the anti-spam check just above the button, then try again."
  };

  if (!TURNSTILE_SITE_KEY) return;

  // Implicit rendering: Turnstile renders into anything carrying the cf-turnstile class once
  // its script loads, and injects the hidden input. The markup ships without the class so an
  // unconfigured site key can't leave a broken widget on the page.
  var boxes = d.querySelectorAll(".fw-captcha");
  if (!boxes.length) return;
  for (var i = 0; i < boxes.length; i++) {
    boxes[i].setAttribute("data-sitekey", TURNSTILE_SITE_KEY);
    boxes[i].setAttribute("data-theme", "dark");
    boxes[i].className += " cf-turnstile";
  }
  var s = d.createElement("script");
  s.src = SCRIPT;
  s.async = true;
  s.defer = true;
  d.head.appendChild(s);
})(window, document);
