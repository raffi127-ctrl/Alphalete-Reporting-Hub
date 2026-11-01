# Vantura Reps → Google Contacts (alphaletegp) — how it works

_Written 2026-10-31 (Carlos: "where is the README for the vantura reps → google contacts? … somewhere
all Lucy devices can access"). Published to every device through the `readmes` branch of
Alphalete-Reporting-Hub by the 7:30am / 8pm README sync; the code itself is on `main`, which every
Lucy pulls with `lucy update`._

## 1. What it does

Keeps a **"Vantura Reps"** contact group in **alphaletegp@gmail.com**'s Google Contacts equal to the
people currently on the Vantura Master Sales Board.

- **Who**: every row of the **Daily Update** tab whose Status is **Active** or **Orientation
  Scheduled** (the same two statuses `vantura_du_status` treats as live). Orientation-Scheduled
  people are usually not on the Roll Call yet, so they come from the Daily Update alone.
- **Name**: `<Daily Update name> (<CAMPAIGN>)`. The campaign comes from the **Roll Call** (newest
  week wins, matched through the master's **Name Aliases** both ways); if the person is not on the
  Roll Call yet, the Daily Update's own Campaign column is used. Campaigns are canonicalised to the
  Roll Call vocabulary — **NDS / BOX / BASE / JE** — so "Box", "nds", "B2B", "B2B ATT" never create a
  second spelling (B2B folds onto NDS since the 10/03 rename).
- **Matching an existing contact**: by phone (last 10 digits) first, then by normalised base name
  (its own parenthetical stripped). An existing contact is only ever **renamed** to append or fix the
  parenthetical — the base name is kept, so a hand-curated fuller name is never overwritten. New
  people are created with name + phone + email and added to the group. Contacts the sync made carry
  the note marker `— Vantura sync —`.
- It never deletes contacts.

## 2. Where it runs and when

- Code: `~/recruiting-report/automations/vantura_contacts_sync/run.py` (repo
  https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub, branch `main`).
- Machine: **Lucy 2**, its own LaunchAgent `com.alphalete.vantura-contacts-sync`, **daily 9:30pm**
  (`deploy/com.alphalete.vantura-contacts-sync.plist`, wrapper `deploy/vantura_contacts_sync_daily.sh`).
  It is deliberately NOT on the 4am orchestrator (schedule_config `on_scheduler: false`).
- (Re)install the agent: `lucy rerun install_vantura_contacts_sync_agent`.
- One-off run: `lucy rerun vantura_contacts_sync` is a **dry run** (prints the plan, writes nothing);
  `lucy rerun vantura_contacts_sync --write` applies.
- Credentials: a read+write Contacts OAuth token for alphaletegp, authorised once on the office mini
  and pushed to Lucy 2 as `contacts-rw-token-alphaletegp` (`~/.config/recruiting-report/
  contacts-rw-token-alphaletegp.json`). Lives outside the repo; `lucy update` never carries it.

## 3. What breaks it

- The **"Vantura Reps" group must exist** in alphaletegp's Contacts — the run aborts if it cannot find
  it (it never creates the group).
- **Daily Update column positions** are read by header, but the status words matter: a new status
  spelling other than "Active" / "Orientation Scheduled" is simply not synced.
- A rep with **no phone and no email** on the Daily Update cannot be matched or created.
- An expired/revoked alphaletegp token → the run fails at login; re-authorise on the mini and push
  the token again.
- Renaming a campaign on the Roll Call renames the parenthetical on the next run — that is intended.

## 4. Related

- `rc_contact_sync` — CUSTOMER contacts into Taylor's RingCentral address book + the daily
  "never texted" post (different account, different purpose).
- `linkedin_2nd_round_contacts` / `applicant_contacts` — applicants into alphaletereception's Google
  Contacts (Raf's org).
