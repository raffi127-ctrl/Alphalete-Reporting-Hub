# Texas de Brazil — Live Standings page

`app.py` is the team-facing **"Steak on the Line"** standings page. It reads the
auto-filled per-day scoring-log Sheet (current-month tab) and renders the
steakhouse board — ranked high→low, each rep's daily swings, losses in red,
a "these eat steak" line, and a find-your-name box. It updates on every load, so
there is nothing to refresh by hand.

This is what should get linked with the daily PDF (NOT the raw Sheet).

## Run locally (to preview)

```
streamlit run automations/tdb_standings/app.py
```

On Lucy 1 it uses the report's existing Google OAuth token automatically.

## Host it (one-time — gives a stable public URL)

The page needs somewhere to run 24/7 with a public URL. Options, easiest first:

1. **Streamlit Community Cloud (free, recommended)**
   - Go to share.streamlit.io → "New app" → pick this repo → main file
     `automations/tdb_standings/app.py`.
   - Under **Advanced → Secrets**, paste the reporting Google OAuth token as
     `gcp_oauth` (the same JSON at `~/.config/recruiting-report/oauth-token.json`):
     ```toml
     [gcp_oauth]
     client_id = "…"
     client_secret = "…"
     refresh_token = "…"
     token = "…"
     token_uri = "https://oauth2.googleapis.com/token"
     type = "authorized_user"
     ```
   - Deploy → you get a stable `…streamlit.app` URL.

2. **Run on Lucy 1 + a tunnel** (cloudflared / ngrok) if you'd rather self-host.

Once the URL exists, set `STANDINGS_URL` in the report so it posts with the PDF
(the report already has the hook — `log_url`).
