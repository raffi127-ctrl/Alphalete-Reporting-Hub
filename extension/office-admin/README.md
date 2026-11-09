# Lucy BG✔️ Send — Chrome extension

One button on the admin's own ApplicantStream calendar: **🛡️ Send background checks**.
It reads today's second interviews marked **Offer Position = Yes** off the page the admin is
already logged into (old calendar or V2), marks who was already sent, and sends the ticked
people to the office's ECO computer, which signs in to Sterling and bulk-uploads them.

## Install (per admin computer, ~1 min)
1. Chrome → `chrome://extensions` → turn on **Developer mode** (top right).
2. **Load unpacked** → pick this `extension/office-admin` folder.
3. Pin it (puzzle icon → pin **Lucy BG✔️ Send**).
4. Click the icon → sign in **once** (this computer stays signed in 90 days; turning the
   login off with `relay_admins --disable` ends it at once). Logins come from
   `python -m automations.office_admin.relay_admins --add <username> --office <office>`.
5. **Several offices, one admin:** run `--add` again with the same username and another
   `--office` — same password. Each office shows as its own card in the icon.
6. First time per office: enter its **ApplicantStream account number**, **state** and
   **city** (changeable any time with "Change account number or location").

## Use
Open the ApplicantStream calendar (today) → **🛡️ Send background checks** (bottom right) →
check the ticks → **Send**. The panel shows the ICD's Lucy ECO machine's answer (it checks every ~3 min).

## Safety
- Picks the office by the account number on the calendar ("Office ID: 11280" / "#11280");
  a calendar whose number isn't on any of the admin's offices = nothing sent.
- Test mode (`relay_admins --mode <user> dry`) = the ICD's Lucy ECO machine fills everything in
  Sterling and stops before Send Invites.
- Needs the relay version with the `office_admin` calls (resources/icd-alerts-relay.gs).
