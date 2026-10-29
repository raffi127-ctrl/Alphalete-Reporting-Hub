# Tracker Onboarding

Megan/Eve tool to add an office to the daily **Tableau tracker screenshots**.
Parallel to `office_onboarding/`, but simpler: the trackers are universal boards
(the same images post to every channel), so onboarding is just a Slack channel +
which trackers to post, in what order.

## What a submission sets up

1. **Config → source of truth.** The form appends the office to the **Tracker
   Onboarding** tab of the AUTOMATION MASTER sheet
   (`1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw`).
2. **Into the tracker run.** `python -m automations.tracker_onboarding.apply
   --write` reads that tab → writes a committed
   `automations/tableau_screenshots/onboarded_trackers.json` that
   `tableau_screenshots.slack_post` merges into `ORG_CHANNELS` / `ORG_LABEL` /
   `ORG_TRACKERS` at import.
3. **Auto-pickup.** The existing daily `tableau_screenshots` run loops every org
   in `ORG_CHANNELS`, and the Hub trackers card reads it — so the new office
   posts + shows up with **no schedule entry, no machine choice, no `dashboard.py`
   edit**. Strict no-op until an office is onboarded.

`apply` is dry-run by default; `--write` applies it; nothing is committed/pushed
(review `git diff`, then commit).

## Run

```bash
TRACKER_ONBOARDING_LOCAL_ONLY=1 .venv/bin/streamlit run tracker_onboarding/app.py
```

Deploy to Streamlit Community Cloud with `tracker_onboarding/app.py` as the entry
point, subdomain `alphaletetrackerintake` (matches the Hub button).

## Secrets

```toml
[gcp_service_account]   # OR [gcp_oauth] — creds for the master sheet
```

No access-code gate — internal tool. Without creds it saves to a local draft
(sandbox); `TRACKER_ONBOARDING_LOCAL_ONLY=1` forces that.
