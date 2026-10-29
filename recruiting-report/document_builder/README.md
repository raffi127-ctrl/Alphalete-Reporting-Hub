# Alphalete Document Builder

A public, self-serve web page. You send an ICD one link; they fill in their
company name, owner, location, brand colors, and upload their logo, then
download a finished, branded PDF. A copy is emailed to them and to you, and
each submission is logged to a Google Sheet. No back-and-forth, nothing to do
on your end.

It's built as a **document library**: `registry.py` lists the documents it can
make. Today that's the Orientation Packet; adding another document later is one
new entry there — it shows up in the dropdown on the same link automatically.

---

## Run it locally (to test)

```bash
.venv/bin/streamlit run document_builder/app.py
```

Opens at http://localhost:8501. With no secrets set it skips the access code,
email, and logging — you can still fill the form and download a PDF.

---

## Put it live (Streamlit Community Cloud — free)

1. Go to **share.streamlit.io** and sign in with the GitHub account that owns
   `raffi127-ctrl/Alphalete-Reporting-Hub`.
2. **Create app → Deploy a public app from GitHub.**
   - Repository: `raffi127-ctrl/Alphalete-Reporting-Hub`
   - Branch: `main`
   - Main file path: `document_builder/app.py`
3. Open **Advanced settings → Secrets** and paste the block below (filled in).
4. **Deploy.** You'll get a permanent link like
   `https://alphalete-orientation.streamlit.app` — that's what you send ICDs.

To update the app later, just push to `main`; the site redeploys itself.

---

## Secrets

Paste this into the **Secrets** box (Streamlit Cloud) or into
`.streamlit/secrets.toml` locally. Every section is optional — leave one out
and that feature is simply off.

```toml
# ---- gates ----------------------------------------------------------------
access_code = "pick-a-code"    # ICDs type this to open the builder
admin_code  = "pick-an-admin-code"   # you type this to open the admin panel
app_url     = "https://alphalete-orientation.streamlit.app"  # the live link

# ---- email a copy of each PDF (uses a Gmail app password) -----------------
[smtp]
host = "smtp.gmail.com"
port = 587
user = "alphaletereporting@gmail.com"
password = "your-16-char-app-password"     # Google account → App passwords
from = "Alphalete Marketing <alphaletereporting@gmail.com>"
team = "alphaletereporting@gmail.com"       # gets a copy of every packet + notice

# ---- log every submission to a Google Sheet -------------------------------
log_sheet_id = "the-id-from-the-sheet-url"
[gcp_service_account]                        # paste a service-account JSON
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "builder@your-project.iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

Delivery goes to the ICD (To) with a copy to `team` (Bcc) — so every packet
also lands in **alphaletereporting@gmail.com**.

**Logging setup:** create a Google Sheet, copy its ID from the URL, and
**share the sheet (Editor)** with the `client_email` above. Rows logged:
timestamp, document, company, owner, location, primary, accent, email.

**Email setup:** in the sending Gmail account, turn on 2-step verification,
then create an **App password** and use that as `password` above.

---

## Editing the master + notifying ICDs

The **master** is the shared content every ICD's copy is built from (they only
change branding — name, colors, logo). To change what the document *says*:

1. Update the content (today: tell Claude the change, or edit
   `automations/orientation_packet/content.py`) and push to `main`. Streamlit
   redeploys the live link within ~a minute.
2. Open the **admin panel**: add `?admin=1` to the app URL and enter your
   `admin_code`.
3. It lists everyone who has generated the document. Type a short note on what
   changed and hit **Send update notice** — it emails those ICDs (Bcc, so they
   don't see each other) plus alphaletereporting@, with a link to regenerate.

Only people who already generated get pinged; regenerating is their choice.

## Add another document later

In `registry.py`, write a `build(inputs, out_path)` for the new doc and append
a `Generator(...)` to `GENERATORS`, declaring its `fields`. It appears in the
dropdown with its own form automatically — no changes to `app.py`.
