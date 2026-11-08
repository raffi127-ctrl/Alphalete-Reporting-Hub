# Onboarding a Verizon ICD (Credico / Verizon Wireless) onto Lucy

First office done: Nico Murrugarra / High Value Acquisitions (2026-11-06). Repeat per ICD.

## 1. Logins (on Megan's laptop, in Chrome)
- **Credico Outlook** (the mailbox Credico gives each ICD, e.g. "MOBONLY_Dallas TX")
- **Credico ARC** — arc.credico.com (DD + reports)
- **Optix** — optixtogo.verizon.com (knocks); profile = the ICD's own (e.g. NicMurCr0)

## 2. Email forwarding (Outlook → Hub inbox)
Outlook → ⚙️ Settings → Mail → Rules → **Add rule**:
- Name: `Lucy - Credico reports to Hub`
- Condition: **From** `vzreports@credicousa.com`
- Action: **Forward to** `alphaletereporting@gmail.com` (FORWARD, not Redirect: company Microsoft 365 mail drops a rule redirect to an outside address with no bounce -- Nico 11/8. Lucy accepts the forwarded file by its office-named attachment.)
- **UNTICK "Stop processing more rules"**
- Save, then use the ↑ arrow to keep it **at the top** — ICDs often already have their own forward rules
  that end in "stop processing", which would block a rule below them.

What arrives: Sales Verification (daily xlsx, per rep), Compliance Flags (weekly xlsx, Wed),
Dynamic Churn Report, Daily/Quality Scorecards, Fios Weekly Bulletin (Mon), Bonus Incentive.
File names carry the office name (`… - <Office>, Inc. - YYYYMMDD.xlsx`) → one Hub inbox serves every Verizon ICD.

## 3. ECO machine
Install ECO with campaign `verizon`; sign in to Optix once on that machine (the profile IS the session).
Knocks come from Optix → Smart Leads → Lead Details (`automations/icd_alerts/optix_read.py`).

## 4. Credico DD
Add the ICD's Credico account to `automations/credico/session.py` ACCOUNTS if their office is not visible
from an existing login, then sign in on Lucy 1.

## 5. Room + approval
Slack room, text group, hours → office row (`campaign="verizon"`) → approve.

Data map for reference: output/nico-verizon-data-map-2026-11-06.md · build status: output/verizon-program-build-plan-2026-11-06.md
