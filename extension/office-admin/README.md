# Lucy Office Admin — Chrome extension

One button on the admin's own ApplicantStream calendar: **🛡️ Send background checks**.
It reads today's second interviews marked **Offer Position = Yes** off the page the admin is
already logged into (old calendar or V2), marks who was already sent, and sends the ticked
people to the office's ECO computer, which signs in to Sterling and bulk-uploads them.

## Install (per admin computer, ~1 min)
1. Chrome → `chrome://extensions` → turn on **Developer mode** (top right).
2. **Load unpacked** → pick this `extension/office-admin` folder.
3. Pin it (puzzle icon → pin **Lucy Office Admin**).
4. Click the icon → sign in with the username + password from
   `python -m automations.office_admin.relay_admins --add <username> --office <office>`.
5. First time only: set the office's **state + city**.

## Use
Open the ApplicantStream calendar (today) → **🛡️ Send background checks** (bottom right) →
check the ticks → **Send**. The panel shows the office computer's answer (it checks every ~3 min).

## Safety
- Refuses if the calendar on screen is another office than the admin's.
- Test mode (`relay_admins --mode <user> dry`) = the office computer fills everything in
  Sterling and stops before Send Invites.
- Needs the relay version with the `office_admin` calls (resources/icd-alerts-relay.gs).
