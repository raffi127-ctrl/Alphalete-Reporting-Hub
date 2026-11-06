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

```bash
python -m automations.day_orchestrator.mini_control --by Megan --enqueue provision_appstream "Nigel Marshall" --office-id 20034 --machine "Lucy 4"
```

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

The login is **still created**. Megan gets a Slack DM saying the owner has
to be added to Alphalete Marketing Call Center (23981) in AppStream. Once
that is done, run the same command again — it finds the admin and only does
the assignment.

## On the office's machine

`finish_setup` and the installer try this standard login first (derived
from the owner's name on the install) and only ask for a login if that
sign-in fails. Nobody types it any more.
