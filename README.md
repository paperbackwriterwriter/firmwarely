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

Both forms POST to `/api/subscribe` (a Vercel serverless function in `api/subscribe.js`), which creates the
subscriber in Beehiiv via its API. The visitor never leaves firmwarely.com.

Setup (one time), in Vercel → Project → Settings → Environment Variables:
- `BEEHIIV_API_KEY` — Beehiiv → Settings → Integrations → API → Create new API key
- `BEEHIIV_PUB_ID` — Beehiiv → Settings → Publication → the ID starting with `pub_`

Then redeploy. Subscribers are tagged `utm_campaign` = free or pro. If you create a custom field named
`devices` in Beehiiv (Audience → Subscribers → Custom fields), the devices they typed are stored there too.

## Device data (nightly pipeline)

- `sources.json` — the watch list. One entry per device: where its release notes live and how to read them.
- `scripts/fetch.py` — checks every tracked source and writes `devices.json`. Standard library only.
- `.github/workflows/nightly.yml` — runs the fetcher at 3:15 AM Central every night (and on demand from the
  Actions tab → Nightly firmware check → Run workflow) and commits `devices.json` if anything changed.
  Each commit triggers a Vercel redeploy, so the site is always current.
- `scripts/build_pages.py` — renders `devices/<id>/index.html` for every device, `devices/index.html`, `sitemap.xml` and `robots.txt`. Runs in the workflow right after the fetch; the pages are committed, so never edit them by hand.
- `index.html` fetches `/devices.json` on load; if that fails it falls back to the `SEED` sample data.

Adding a device: add an entry to `sources.json`.
- `type: "github"` for a project with tagged releases: set `repo: "owner/name"`. Uses the API's
  latest-stable-release endpoint, so pre-releases are ignored. This is the most reliable type.
- `type: "feed"` for RSS/Atom (GitHub releases, community.ui.com). `item_match` filters items by title; `version_regex` needs one capture group.
- `type: "html"` for a support page. `version_regex` runs over the raw page. The release date becomes the day the version first changed.
- `type: "manual"` puts the device in the catalog as "watching soon" with no data.

Keep `model` describing *what the thing is* rather than repeating the brand — "Jellyfin / Media
server", not "Jellyfin / Jellyfin". Brand and model are joined for the page title and `<h1>`.

### GitHub API limit

The catalog leans on `type: "github"`, and GitHub allows only **60 API calls an hour**
unauthenticated. The workflow passes `GITHUB_TOKEN` (automatic, no setup) to raise that to 1,000.
Running `scripts/fetch.py` by hand without a token will fail most GitHub sources with
`GitHub API rate limit reached` — export a token first:
`GITHUB_TOKEN=$(gh auth token) python3 scripts/fetch.py`.

### Pruning sources that don't resolve

A source that 404s never erases anything: the device stays in the catalog as "watching soon" and
gets `source_status: "error: ..."`. After a run, `devices.json` lists them under `failed`:

```
python3 -c "import json;print(json.load(open('devices.json'))['failed'])"
```

For each one, fix the `repo`/`url` in `sources.json`, or change its `type` to `manual` to keep the
catalog entry without the failing fetch.

A failing source never erases data: the device keeps its last version and gets `source_status: "error: ..."` in `devices.json`.
Check the Actions log after a run to see which sources succeeded.

Status rules: `critical` = security-flavoured release notes within 60 days · `update` = any release within 45 days · `current` = older · `eol` = release notes mention end-of-life · `pending` = no data yet.

## Digest / alerts

Each run compares tonight's versions with last night's. A device we had no version for yet — one
just added to `sources.json`, or whose source resolved for the first time — is *not* a change: it
joined the catalog, it didn't ship an update, so adding a batch of devices never mails anybody.
If anything did change, `fetch.py` writes `digest.md`
(grouped: security fixes, new firmware, end-of-life) and the workflow opens a GitHub issue with it, which
emails you. If the repo has the secrets `BEEHIIV_API_KEY` and `BEEHIIV_PUB_ID` (GitHub → Settings → Secrets and
variables → Actions), it also creates a **draft** post in Beehiiv with the same content for you to review and send.
To test without waiting for a real change: Actions → Run workflow → tick *force_digest*.

### Per-user alerts

The same run also writes `changed.json` — the night's changes as data rather than prose — and
`scripts/user_alerts.py` emails each subscriber about **only the devices they saved** on
`/my-devices.html`. Someone already on tonight's version is left alone; someone with no version
recorded still gets told. Mail goes out through Resend, the same sender as the sign-in links.

Repo secrets it needs (GitHub → Settings → Secrets and variables → Actions):
`RESEND_API_KEY`, plus `BEEHIIV_API_KEY` and `BEEHIIV_PUB_ID` (already set for the digest).
Without them the step prints a line and does nothing, so the nightly run stays green.

Optional repo *variables*: `RESEND_FROM` (a verified sender — the default `onboarding@resend.dev`
only delivers to your own address), `SITE_URL`, and `USER_ALERT_PLANS` — which plans get personal
mail, default `pro` (`pro,free` or `all` widens it). Optional secret `USER_ALERT_TEST_EMAIL`
redirects every alert to one address with `[TEST]` in the subject.

A *force_digest* run marks every tracked device as changed, so `user_alerts.py` refuses to mail
real subscribers on one unless `USER_ALERT_TEST_EMAIL` is set. To rehearse locally:
`python3 scripts/fetch.py --offline --force-digest && python3 scripts/user_alerts.py --dry-run`
(dry run prints who would get what and sends nothing).

Note that Pro subscribers with saved devices currently get both this personal email and the
Beehiiv Pro segment blast from `scripts/pro_alert.py`. Drop the *Send Pro instant alert* step from
the workflow once the personal mail is doing the job.

Neither `digest.md` nor `changed.json` is committed — both are rebuilt from scratch each night,
and their presence is what tells the workflow that something changed.
