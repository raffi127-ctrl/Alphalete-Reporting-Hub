# Second-round contacts for new owners — how it works

_Built 2026-10-31 for Raf's ask in #l10-alphalete ("Daily Update / Google Contacts / Lucy ECHO for New
Owners", 10/30). Megan and Eve run the setup per owner; this is the reference. Published to every device
through the `readmes` branch; code on `main` (`automations/second_round_contacts/`)._

## 1. What it does

Every second round of a new owner's office lands in that owner's **reception Gmail contacts**
automatically, and a nightly audit removes the ones that went nowhere, so the phone doesn't fill up.

- **Source**: ApplicantStream → Reports → Retention Details for the owner's office, rows
  "Second Interviews Booked" and "Total Second Interviews", every day of this week (Sunday's run also
  reads Saturday). The daily cells open the p=715 list: first name, last name, email, phone.
- **Target**: the owner's reception Google account, contact group **"2nd Rounds"**, card named
  **"First Last (2R m/d)"** (m/d = the day they were booked or held), mobile + email, note =
  "2nd round m/d/yyyy - Owner (AppStream office) - second_round_contacts".
- **Never doubled**: "already there" = the same phone or email anywhere in that account. Reading the
  whole week again every pass is what makes late ApplicantStream updates harmless.
- **Twice a day** (Carlos: owners mark ApplicantStream late): **12:00 and 15:30** Central, from Lucy 1's
  scheduler. Anything marked after 15:30 goes in at noon the next day.
- **Audit at 06:00** (Raf's rules, state in `output/second_round_contacts/state.json` on Lucy 1):
  | situation | after | result |
  |---|---|---|
  | second round but not offered / booked for a start ("not hired or left as a message") | 7 days | contact removed |
  | start scheduled (Offered / Brought on Board / New Start Scheduled) but never showed | 21 days | contact removed |
  | showed up to the start but OwnerVille View Progress under 100% | 21 days after showing | contact removed |
  | showed up and View Progress = 100% ("fully badged") | — | kept for good, terminated later or not (rehires) |
  If OwnerVille can't be read, nobody is removed on that rule that day.

## 2. The roster Megan / Eve keep — "2R Contacts" tab on the Org workbook

Next to Eve's "New Owners" tab. One row per owner:

| column | what to put |
|---|---|
| Owner | the owner's name |
| ApplicantStream Office ID | the office number (the `office=` in ApplicantStream's URL) |
| Reception Email | the reception Gmail created for them on the new-owner checklist |
| Active | Yes to sync, No to pause |
| OwnerVille Campaign | blank = RES-AT&T; set it only if the owner's View Progress campaign differs |
| Start Date / Notes | yours |
| Last Run / Last Result | written by the job — "3 added, 12 already there…", or why it skipped |

A row runs only when its Contacts token exists on Lucy 1 (see §3); until then Last Result says
"SKIPPED: no Contacts token".

## 3. Per-owner setup (one time, after the reception Gmail exists)

1. Add the row on "2R Contacts" (Active = Yes).
2. Authorise Google Contacts for that Gmail, on the machine that runs the job (Lucy 1, Raf's mini):
   ```
   cd ~/recruiting-report   # (the repo folder on that machine)
   .venv/bin/python -m automations.fiber_owners_distro.contacts_write --authorize --account <reception email>
   ```
   A browser opens: sign in as that reception Gmail and approve "Contacts (edit)". It saves
   `~/.config/recruiting-report/contacts-rw-token-<local>.json`. Done once per account.
   Authorised on another Mac instead? Push it: `lucy push_cred_file contacts-rw-token-<local> "Lucy 1"`
   (the key is the token's file name without .json).
3. The owner adds the reception Gmail to their phone (checklist step) so the "2nd Rounds" group syncs.
4. First pass is the next 12:00 / 15:30. Check Last Result on the row.

## 4. By hand / checks

- `lucy rerun second_round_contacts` → dry run (what it would add); `--write` applies;
  `--owner "Name"` one row; `--date YYYY-MM-DD` one day.
- `lucy rerun second_round_contacts_audit` → `--audit --write` is what the card runs; without
  `--write` it only prints the verdicts; `--no-ownerville` skips the badging check.
- Logs: `lucy logtail second_round_contacts`.

## 5. What breaks it / to know

- ApplicantStream office not visible to Lucy 1's login → row fails with "office not available".
- Two people with the same phone or email in one account = one card (by design).
- Removing a card by hand is fine: the audit notices it's gone and stops tracking it.
- OwnerVille's View Progress table is server-side: one name is searched at a time, so the audit's
  badging check costs a few seconds per new start. Names must match OwnerVille's spelling.

## 6. The editable doc for Megan / Eve

https://docs.google.com/document/d/17fc_Y5pcJ1JlOukCM9wAsyAs-ZBP4HJ5Ixo1nFJxJPg/edit — plain-language setup
steps per owner, the rules table, and the roster link. In Carlos's Drive; he shares it. When they change
a rule there, mirror it in `config.py` (NOT_HIRED_DAYS / NO_SHOW_DAYS / BADGE_DAYS) and here.
