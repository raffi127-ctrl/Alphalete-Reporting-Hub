# Redeploy the public Streamlit apps from the `site` branch

Written 2026-11-03. Hand this to a new Claude session, or follow it yourself.
Only Megan's Streamlit account (share.streamlit.io, signed in with GitHub
raffi127-ctrl) can do the clicking; Claude's job is to verify before and after.

## Why

Streamlit Community Cloud pulls and restarts an app on EVERY push to the
branch it deploys from. All seven apps deploy from `main`, and `main` takes
about 90 pushes a day from the Claude sessions. Each restart drops the app for
one to two minutes, so people saw endless spinners and "Failed to fetch
dynamically imported module" errors (measured 2026-11-03; memory
`reference_streamlit_site_branch`).

Already done on the repo side (nothing to repeat):
- Branch `site` exists on GitHub and is a copy of `main`.
- `.github/workflows/promote-site.yml` moves `site` up to `main` every day at
  3am Central, or by hand (GitHub → Actions → "Promote site" → Run workflow;
  or locally `git push origin main:site`).
- `streamlit==1.66.1` is pinned in every requirements file.

## The apps (all from repo raffi127-ctrl/Alphalete-Reporting-Hub)

| App URL name | Main file | Notes |
|---|---|---|
| lucyeco | `streamlit_app.py` | the combined site: join page, enrollment page, sales board, dispositions. DO THIS ONE FIRST |
| alphaletedocuments | `document_builder/app.py` | |
| alphaletemetricsintake | `office_onboarding/app.py` | |
| alphaletepaystructure | `pay_structure/app.py` | |
| alphaletetrackerintake | `tracker_onboarding/app.py` | |
| (see dashboard) | `metric_request/app.py` | |
| alphalete-reporting-app-… | `automations/tdb_standings/app.py` | Texas de Brazil standings |

The dashboard at share.streamlit.io lists each app as
`alphalete-reporting-hub · main · <main file>`. After this, each should read
`· site ·`.

## Steps, per app (5 minutes each)

Streamlit Cloud cannot change the branch of a live app, so it is delete and
redeploy under the same name. The URL name frees up the moment the old app is
deleted.

1. **Copy the secrets.** Open the app → three dots → Settings → Secrets. Select
   everything in the box and paste it into a note. (These are the Google
   service-account JSON and Slack tokens; without them the new app cannot
   read a single sheet.)
2. **Delete the app.** Three dots → Delete app → confirm.
3. **New app.** Dashboard → "Create app" / "New app" → "Deploy a public app
   from GitHub":
   - Repository: `raffi127-ctrl/Alphalete-Reporting-Hub`
   - Branch: **`site`**
   - Main file path: from the table above
   - App URL: the same name as before (e.g. `lucyeco`)
   - Branch is case-sensitive: lowercase `site` (autocapitalised `Site`
     reads "This branch does not exist").
   - Advanced settings → Python version: 3.12 if offered (3.14 also works
     today); Secrets: paste what you copied in step 1.
   - If the Secrets box shows a token as dots, the copy is unusable. Deploy
     anyway, then paste the real one in Settings → Secrets afterwards. For
     `slack_user_token` (Lucy Reporting), on the office network:
     `ssh alphalete@alphaletes-mac-mini.local "cat ~/.config/recruiting-report/slack-user-token" | tr -d '\n' | pbcopy`
4b. **Share → "Make this app public" on.** A recreated app can come back
   private.
4. **Deploy.** The first build installs dependencies and takes 3–5 minutes.
5. **Check.** Open the app's URL in a fresh tab. For `lucyeco` also open
   `https://lucyeco.streamlit.app/join-lucy-eco` and
   `https://lucyeco.streamlit.app/lucyeco`.

Do `lucyeco` first. The other six can wait for a quiet moment; their old
links keep working until each one is redone.

## What Claude verifies

Before: `git log --oneline -1 origin/site` equals (or is behind) `origin/main`.

After each redeploy, from the repo on Megan's Mac:

```bash
curl -s -m 20 -L -c /tmp/st -b /tmp/st -o /dev/null -w "%{http_code} %{time_total}s\n" https://lucyeco.streamlit.app/~/+/_stcore/health
```

`-L -c -b` matter: every streamlit.app URL first answers `303` to a
share.streamlit.io cookie hop, public apps included. Without them you get
`303` or a 20s timeout and it looks like the app is down or private. The
first check right after a deploy can still time out while the app wakes.

`200` in well under a second, repeated a few times a minute apart while other
sessions keep pushing to `main`, is the proof: a push to `main` no longer
restarts the app. The app's own log (Manage app, bottom right of the page)
should show no "Pulling code changes" line after a push to `main`.

## From now on

- A change to a public tool is live only after `site` moves. If it matters
  today, promote by hand (Actions → Promote site → Run workflow, or
  `git push origin main:site`). Otherwise it lands at 3am.
- Never deploy an app from `main` again.
- "Failed to fetch dynamically imported module" on an open tab after a
  promote = stale tab; hard refresh (Cmd+Shift+R).

## Rollback

Redeploy from `main` the same way. Nothing on the repo needs undoing; `site`
and the workflow are harmless if unused.
