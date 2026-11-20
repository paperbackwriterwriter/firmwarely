# Moving firmwarely.com from Vercel to Cloudflare Pages

The repo now deploys on both. Vercel keeps using `vercel.json` and `api/` exactly as before;
Cloudflare Pages uses the files added next to them. Nothing changes for the hourly GitHub
workflows: they still rewrite and commit `vercel.json`, and the Cloudflare build turns that
into Cloudflare's own files on every deploy.

| Vercel | Cloudflare Pages | How it stays in sync |
| --- | --- | --- |
| `vercel.json` → `headers` | `dist/_headers` | generated from vercel.json at build time |
| `vercel.json` → `redirects` | `dist/_redirects` | generated from vercel.json at build time |
| every file in the repo is public | only `dist/` is public | `scripts/cf_pages.py` copies the public files |
| `api/<name>.js` | `functions/api/<name>.js` | each function runs the same handler (see below) |
| Project env vars | Pages env vars / secrets | copy them by hand, once (list below) |

## Cloudflare dashboard settings

Workers & Pages → Create → Pages → Connect to Git → `paperbackwriterwriter/firmwarely`.

- **Production branch:** `main`
- **Framework preset:** None
- **Build command:** `python3 scripts/cf_pages.py dist`
- **Build output directory:** `dist`
- **Root directory:** (leave empty, the repo root)
- **Compatibility flags:** `nodejs_compat`, **compatibility date** `2025-09-01`. Both are set
  in `wrangler.toml`, which Pages reads at build time; that file is then the source of truth
  for them, and the dashboard shows them read-only.

`wrangler.toml` has no `[vars]` on purpose: variables there would override the dashboard.

### Environment variables (Settings → Variables and Secrets, Production and Preview)

Copy the values from Vercel (Project → Settings → Environment Variables). Mark the keys as
**Secret** (encrypted).

| Name | Used by | Secret? |
| --- | --- | --- |
| `AUTH_SECRET` | sign-in links and the session cookie (lib/fw.js) | yes |
| `BEEHIIV_API_KEY` | subscribe, me, auth-verify, unsubscribe, stripe-webhook | yes |
| `BEEHIIV_PUB_ID` | same | no |
| `RESEND_API_KEY` | auth-request, contact (email) | yes |
| `RESEND_FROM` | sender address (optional, has a default) | no |
| `SITE_URL` | base of the emailed sign-in link (`https://www.firmwarely.com`) | no |
| `SUPPORT_TO` | contact form inbox (optional, defaults to hello@firmwarely.com) | no |
| `TURNSTILE_SECRET` | server half of the anti-spam check (lib/captcha.js) | yes |
| `STRIPE_WEBHOOK_SECRET` | Stripe signature check (`whsec_…`) | yes |
| `STRIPE_SECRET_KEY` | Stripe lookups in the webhook | yes |

Use the **same** `AUTH_SECRET` on both platforms: a sign-in link emailed by one then works
on the other, and nobody is signed out when DNS moves. Same for `STRIPE_WEBHOOK_SECRET`: the
Stripe endpoint URL (`/api/stripe-webhook`) does not change, so nothing changes in Stripe.

The GitHub Actions secrets are separate and untouched.

### After the first deploy, before DNS

Try `https://<project>.pages.dev/`: a device page, `/devices/<unpublished-id>/` (redirects),
`/sources.json` (must be 404), and sign-in. The emailed link uses `SITE_URL`, so during the
trial it lands on the live (Vercel) site; set `SITE_URL` to the pages.dev address in the
**Preview** environment if you want to try the whole loop there.

Then add the custom domains (`www.firmwarely.com`, and the apex with a redirect rule to
www, which Vercel's domain settings do today).

## How the functions are shared

- `lib/env.js`: the API code reads configuration through `env()`. On Vercel that is
  `process.env`, as before. On Cloudflare, `lib/pages-adapter.mjs` runs each request inside
  `withEnv(context.env, …)` (AsyncLocalStorage), so `env()` returns `context.env`.
  Nothing reads configuration at load time any more.
- `lib/pages-adapter.mjs` gives the Vercel handler the Node-style `req`/`res` it was written
  for (method, url, lower-case headers, `req.body` parsed like Vercel does, the raw body as a
  stream, `res.setHeader/status/json/end`) and turns the result into a `Response`. Status
  codes, JSON bodies, `Set-Cookie` attributes and redirects are therefore the handler's own.
- `functions/api/stripe-webhook.js` calls `handleEvent()` exported from
  `api/stripe-webhook.js` (the same code the Vercel function now calls) with the request's
  exact bytes (`arrayBuffer()` → `Buffer`) and `context.env`.
- `node:crypto`, `Buffer`, `node:stream` and AsyncLocalStorage come from `nodejs_compat`.

Local run: `python3 scripts/cf_pages.py dist && npx wrangler pages dev`, with dummy values in a
`.dev.vars` file (gitignored; never put real keys in it on a shared machine).

## What behaves differently

- **Redirect status codes.** Vercel answers `permanent: true` with 308 and `false` with 307.
  `_redirects` uses 301 and 302 as asked; same effect for GET. To match Vercel exactly, change
  the `code =` line in `scripts/cf_pages.py` to 308/307.
- **Redirect count.** Spelling every `/devices/:id(a|b|…)` and `/brands/:b(…)` alternative out
  with and without the trailing slash comes to about 2,800 lines, over Cloudflare's 2,000
  static-rule limit. So group rules get only their `/x/` line, and one dynamic line per folder
  (`/devices/:name /devices/:name/ 301`, same for `/brands/`) adds the slash first. A slashless
  unpublished device therefore takes two hops (301 then 302) instead of one. Exact rules
  (permanent moves, family models) keep both spellings and one hop. Today: about 1,470 static
  and 2 dynamic lines. The build fails, keeping the previous deploy live, if the catalogue
  ever pushes it past 2,000; the hourly Vercel build only prints a warning.
- **Trailing slashes and `.html`.** Vercel serves `/devices/x` and `/devices/x/` both with
  200; Cloudflare redirects `/devices/x` to `/devices/x/` (the canonical form the sitemap
  uses). Cloudflare also drops `.html` (`/foo.html` → 308 `/foo`); `_redirects` rewrites
  `/my-devices.html`, `/dashboard.html` and `/devices/index.html` with 200 so those addresses
  still answer directly. `/index.html`, `/404.html` and `/<folder>/index.html` get a 308 to
  the clean address instead of a 200.
- **Files that are no longer public.** Vercel served every file in the repo (no build
  output directory, no `.vercelignore`): `README.md`, `scripts/`, `lib/`, `.github/`,
  `vercel.json`, `sources.json`, `pending_changes.json`, `typesafe_shadow.json`,
  `digest_state.json`, `weekly_changes.json`, `families.json`, `update_guides.json`,
  `redirects.json`. On Cloudflare they are 404. Only `/devices.json` stays public, because
  index.html, my-devices.html and dashboard.html fetch it. If something outside the site
  reads one of the others, add it to `PUBLIC_JSON` in `scripts/cf_pages.py`.
- **CORS.** Pages adds `Access-Control-Allow-Origin: *` to static files by default;
  `_headers` removes it so `devices.json` stays same-origin as on Vercel.
- **Headers on the API.** `_headers` does not apply to Functions, so the adapter adds the
  same six security headers to API responses. A header the handler sets wins (auth-verify's
  `Referrer-Policy: no-referrer`).
- **Rate limiting.** `lib/ratelimit.js` keeps its counts in memory. On Vercel that is per
  warm function instance; on Workers it is per isolate, and there are many isolates across
  Cloudflare's locations, evicted at any time, so it throttles even less. It remains a speed
  bump. For a real limit, add a Cloudflare rate-limiting rule on `/api/*` (Security → WAF →
  Rate limiting rules), or move the counts to KV / a Durable Object.
- **Client address.** Cloudflare appends to an `X-Forwarded-For` the client sent, so the
  adapter replaces it with `CF-Connecting-IP` before the handler sees it (Vercel overwrites it
  the same way).
- **Bad JSON.** A malformed JSON body gets `400 Invalid JSON` (plain text), as Vercel's body
  parser answers. An uncaught error is `500 A server error has occurred`.
- **Vercel Web Analytics.** Every page loads `/_vercel/insights/script.js`, which only exists
  on Vercel; on Cloudflare it is a 404 and analytics stop. Remove the tag from
  `scripts/build_pages.py` after the move, or switch to Cloudflare Web Analytics (it needs
  `static.cloudflareinsights.com` in the CSP's `script-src` and `cloudflareinsights.com` in
  `connect-src`).
- **Logs.** `console.log/error` from the functions show in the Pages project's real-time
  logs (Functions → Logs), not Vercel's.
- **Limits.** Pages Functions on the free plan: 100,000 requests a day and 10 ms CPU per
  request (waiting on Beehiiv/Stripe/Resend doesn't count). Only `/api/*` runs a function;
  static pages don't.
