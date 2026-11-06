# New office → AppStream "Lucy ECO" login (before enrollment / with the dry run)

Megan, 2026-11-06: every ECO office gets its own AppStream admin login
**before** they enroll, made from a Lucy, not by a person clicking.

## The format (always)

| Field      | Value                      | Example (Nigel Marshall) |
|------------|----------------------------|--------------------------|
| First Name | `Lucy ECO`                 | Lucy ECO                 |
| Last Name  | owner's first + last name  | Nigel Marshall           |
| Username   | `LucyECO<First>`           | LucyECONigel             |
| Password   | `<First>123!`              | Nigel123!                |

Code: `automations.shared.appstream_provision.eco_login("Nigel Marshall")`.

## One command, run with the metrics dry run

**Run it on YOUR Mac (Megan or Eve), as your own AppStream login.** The
office list on the admin form depends on who is signed in: Lucy Reports on a
Lucy is offered 173 offices (Nigel's 20034 was not one), your login offers
every office. A window opens the first time so you sign in; the profile keeps
the session after that.

```bash
.venv/bin/python -m automations.shared.appstream_admins "Nigel Marshall" --office-id 20034 --local
```

Add `--verify` to prove the sign-in on a login that already existed. The
Lucy-queue version below still works for offices Lucy Reports can see.


```bash
python -m automations.day_orchestrator.mini_control --by Megan --enqueue provision_appstream "Nigel Marshall" --office-id 20034 --machine "Lucy 2"
```

- `--machine` must be an **AppStream holder** (Lucy 1, 2 or 3). Lucy 4 is
  deliberately not one (a fourth holder churns the shared Lucy Reports token),
  so the command exits 4 there. Lucy 2 or 3 by default; Lucy 1 is the busiest.
- `--office-id` = their OwnerVille/AppStream office number (same one as
  `ov_account` in `office_metrics/onboarded_offices.json`). Needed when an
  owner has more than one office; otherwise the name is enough.
- Add `--check` first if you only want to know what would happen (read-only).
- Result: the queue row's result + `lucy logtail appstream-provision.log`.

## What it does (Settings → Admins)

1. Opens Settings → Admins as that Lucy's `Lucy Reports` session. No
   "Add New Admin" button → exit 4, nothing touched (that account can't
   manage admins; use a Lucy whose session can).
2. If `Lucy ECO <Owner>` is already in the list it opens it; otherwise
   Add New Admin + fills the four fields above.
3. Ticks the owner's office under **Offices Not Assigned** (right), clicks
   **Save Changes**, re-opens the admin and checks the office now sits
   under **Offices Already Assigned** (left). That is the only office the
   login can see.
4. Signs in once as the new login in a scratch profile to prove it works.
5. Writes the row to the **AppStream Logins** tab of the Lucy Access App
   workbook (owner, username, password, office id, assigned, verified).

## Owner not in the office list

The login is **still created**. Whoever ran it gets a Slack DM: "either
<Owner> isn't in our call center, or your login doesn't have access to it —
check, then assign it manually or request access." Once that is done, run the
same command again with `--verify` — it finds the admin, does the assignment
if it can, and proves the sign-in.

## Then the ICD gets a DM from Lucy

When the office is assigned (and the sign-in did not fail) Lucy DMs the ICD:
what Lucy ECO is, their login, that the sign-up form is done together on the
Zoom call, the Python download to do before the call, and the logins to have
ready (OwnerVille, the SaraPlus-code email, the Sterling email, anything else
the installer asks). Slack id comes from `resources/owner-slack-ids.md`, then
the ICD Signup tab, else `--slack-id`; no id = no DM, said in the summary.

## On the office's machine

`finish_setup` and the installer try this standard login first (derived
from the owner's name on the install) and only ask for a login if that
sign-in fails. Nobody types it any more.
