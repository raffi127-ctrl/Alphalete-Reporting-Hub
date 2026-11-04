# Office admin + Sterling background checks — setup runbook

What has to be done, once per office, for an office admin to press **Send background
checks** on the admin page and have the office's ECO computer send them. Omar first.

## A. Once, on our side
1. **Relay:** paste `resources/icd-alerts-relay.gs` into the relay's Apps Script → Deploy →
   Manage deployments → pencil → Version: **New version** → Deploy (adds 'Office Jobs').
2. **Lucy 1:** `lucy update` (code_answer now answers Sterling code requests, files Sterling
   forward addresses, confirms their Gmail forward).
3. **ECO release** (Eve's usual release) so office computers get office_jobs, sterling_send,
   sterling_setup, sterling_forward.
4. Office row in `automations/office_admin/config.py` `OFFICES` (Omar is there, `bgc_mode="dry"`).

## B. On the ICD's ECO computer (the ICD sits there — ~5 min)
```
python -m automations.icd_alerts.sterling_setup
```
- types their Sterling User ID + password (saved on that computer only)
- walks the Gmail filter that forwards ONLY Sterling's "Authentication Request" code mails
- test sign-in: gets the code through Lucy 1, clicks Yes on "Multiple user alert", reaches
  Client Hub. "ALL SET" = done. (Omar's iMac is macOS 11 — this is where an old-Mac browser
  problem would show.)

## C. On the admin's computer
```
python -m automations.shared.tableau_patchright --appstream-login
python -m automations.office_admin.relay_client --setup omar
python -m automations.office_admin.accounts --add <username> --office omar --name "<Admin name>" --generate
streamlit run office_admin/app.py
```
Hand the admin their username + the generated password. First visit asks the office's
city + state once.

## D. Test, then live
1. Admin page → Find today's offers → tick → Send. With `bgc_mode="dry"` the ECO computer
   signs in, fills everything, uploads, sees "N found", **stops before Send Invites**, and the
   page shows "Test run — would have sent: …".
2. Megan's OK → `bgc_mode="live"` for that office. Watch the first live job (Send Invites is
   the one step not yet seen working by the bot).
