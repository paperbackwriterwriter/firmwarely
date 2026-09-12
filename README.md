# Firmwarely

Static marketing site + device catalog for firmwarely.com. One file (`index.html`), no build step.

## Deploy to Vercel (from an iPad)

1. github.com → sign in → **+** → **New repository** → name it `firmwarely`, Public, create.
2. In the repo, **Add file → Upload files** → upload `index.html` and this `README.md` → **Commit changes**.
3. vercel.com → sign up with GitHub → **Add New → Project** → import `firmwarely` → **Deploy**.
   Framework preset: Other. No build command. Output directory: leave blank.
4. Vercel gives you a `*.vercel.app` URL. Then **Settings → Domains → Add** `firmwarely.com`
   and copy the two DNS records Vercel shows into GoDaddy → My Domains → DNS.

To update the site later: edit `index.html` in GitHub (pencil icon) → commit. Vercel redeploys in ~30 seconds.

## Connect the signup form

The form posts to Formspree. Create a free form at formspree.io, then replace `YOUR_FORM_ID`
in `index.html` (search for it) with your form ID. Until then, submissions show a reminder instead of saving.

## Device data

`DEVICES` near the bottom of `index.html` is sample data and the catalog shows a "preview data" notice.
Phase 2 replaces it with a nightly scraper and generated device pages.
