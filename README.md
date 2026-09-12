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

## Signup form

Both forms send the visitor to the Beehiiv subscribe page (`SUBSCRIBE_URL` in `index.html`) with the
email pre-filled. Each subscriber is tagged in Beehiiv with UTMs: `utm_campaign` = free or pro,
`utm_content` = the devices they typed. View these under Audience → Subscribers in Beehiiv.

## Device data

`DEVICES` near the bottom of `index.html` is sample data and the catalog shows a "preview data" notice.
Phase 2 replaces it with a nightly scraper and generated device pages.
