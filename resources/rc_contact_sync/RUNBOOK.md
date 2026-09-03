# B2B Customer Contacts (RingCentral) — runbook

Built 2026-09-02 from Carlos's 3 Looms. **Not armed yet** — it needs the two
credentials in §1 before it can run at all.

Module: `automations/rc_contact_sync/` · Hub card: **B2B Customer Contacts
(RingCentral)** · Runs on **Lucy 2** · Scheduler key: `rc_contact_sync`
(`on_scheduler: false` until §3 is done).

---

## What it does, in order

1. **SaraPlus** (Carlos's login) → Analytics → Detail Reports → **Sales Order
   History** → date range set to yesterday on both ends, Customer Type
   **Both**, Submit.
2. For each order it takes the **rep** (`User Name` column) and the **business**
   (`Business Name` column), then clicks that row's **View Customer** and reads
   the **Primary Phone** and the customer's name off the card.
3. **RingCentral** (signed in as **Taylor**) → one contact in her address
   book per customer:
   `Company` = business name · phone = primary phone (Mobile) ·
   `Notes` = `Rep Name: <rep>`.
4. **RingCentral** → reads that same line's texts for yesterday. Customers
   with no message on it are posted, grouped by rep, into the day's metrics
   thread in **#a-players-b2b** and **#alphalete-gp-sales**.

---

## 1. The two credentials it still needs

### a) Carlos's SaraPlus login

`~/.config/recruiting-report/saraplus-creds-b2b.json` on Lucy 2:

```json
{"email": "carhi1816@gmail.com", "password": "..."}
```

Its **own** file on purpose. `saraplus-creds.json` is
`alphaletemarketing@gmail.com` — the Alphalete Sales Board sweep's login, a
different dealer. Megan, 2026-09-02: *"make sure you're ONLY using Carlos'
sara plus login to access."* Reusing that file would return rows — just not
these rows, and nothing would look wrong.

Push it to Lucy 2 with:

```bash
lucy push_cred_file saraplus-creds-b2b "Lucy 2" --machine "<the box that has it>"
```

### b) A RingCentral app + JWT for **Taylor's** login

`~/.config/recruiting-report/ringcentral-b2b-creds.json` on Lucy 2:

```json
{
  "client_id": "...",
  "client_secret": "...",
  "jwt": "<JWT minted on taylormkmiller7@gmail.com>"
}
```

That is the whole file. **One identity does both jobs** (Megan, 2026-09-02:
*"the ring central account we're using is with this email
taylormkmiller7@gmail.com"*): the contacts go into Taylor's address book — the
line that texts these customers, so a reply arrives with a name on it — and her
message store is the one the follow-up check reads. Both calls address
extension `~`, whoever the token is, rather than a hardcoded extension number.

**This is not the RingCentral account already wired into the Hub.** The app
baked into `automations/rc_autoread/run.py` belongs to a *different* company
account (main +1 207-464-7960 — Dylan Twaddle, AIsha Ceron, Jonathan Reyes,
Camilo Ovalle, Camila Hornos Kraschinsky, HR Department). Verified 2026-09-02:
**Taylor Miller has no extension in it.** The B2B account is *Alphalete
Specialized Marketing* — Carlos ext 101, Mayra Cruz ext 113, Taylor Miller
ext 134.

To create it: RingCentral Developer Console (an admin on that account) → new
**REST API / Server-only (JWT)** app → scopes **Contacts** (read + write) and
**Read Messages** → mint the JWT for **Taylor's** user.

**The report checks who the token is before it writes anything.** A JWT for
Carlos, or for anyone in the other account, authenticates perfectly well and
would file every customer in the wrong address book while reading the wrong
inbox — a run that looks completely green. It stops instead, naming who the
token turned out to be. If Taylor's RingCentral email ever changes, put the new
one in `expected_email` in that same file (`""` turns the check off).

Optional keys, normally absent: `watch_jwt` and `watch_extension_id`, for the
day the texts move to a line the contacts don't live on.

---

## 2. First run on Lucy 2 (in this order)

```bash
python -m automations.rc_contact_sync.run --probe
```

Read-only. Dumps the login it used, the tabs it found, the date-picker ids, the
grid's column headers, and the first customer card. **Do this before anything
else** — it is what confirms the Detail Reports page looks the way the Loom
showed it, on Carlos's login, without writing anything.

```bash
python -m automations.rc_contact_sync.run
```

Dry run (the default). Prints every contact it *would* create and the exact
Slack post it *would* send. Writes nothing, posts nothing.

```bash
python -m automations.rc_contact_sync.run --live --limit 1
```

One customer, for real. Check the contact in the RingCentral app **signed in
as Taylor**: business name in Company, number under Mobile, `Rep Name: …` in
Notes.

---

## 3. Arming it

Once `--live --limit 1` is verified, set `on_scheduler: true` on
`rc_contact_sync` in `automations/day_orchestrator/schedule_config.json` and
`lucy update` Lucy 2. The wrapper passes `--live`; the module is dry-run by
default, so `lucy rerun rc_contact_sync` will always preview rather than write.

---

## Things that will bite

- **A dry run is the default and that is deliberate.** A RingCentral contact
  is not un-created from this API, and the Slack post names reps who didn't
  follow up. Nothing writes without `--live`.
- **Duplicates can't happen by accident.** The address book is indexed by
  phone number (every phone field, not just Mobile) before anything is
  created, and each order id is recorded in
  `~/.config/recruiting-report/rc_contact_sync_state.json` the moment its
  contact lands — so a crash halfway through re-runs cleanly.
- **A customer with no Primary Phone is skipped and counted as a failure**, so
  the Hub card goes orange instead of the customer silently vanishing.
- **Columns are found by header label, never by position.** If SaraPlus renames
  a column the report stops with the headers it actually saw — it does not read
  whatever sits where `Business Name` used to be.
- **The date pickers are Telerik.** `fill()` does not work on them; the report
  reuses `alphalete_sales_board.sara._set_telerik_date`, which writes all four
  pieces the control reads. Their element ids on this tab are discovered at run
  time, not hardcoded.
- **Chrome profile**: its own (`automations/uploaded/.saraplus_b2b_profile`),
  never the sales-board sweep's.

---

## Open questions for Carlos

1. **What time in the morning?** Currently slotted in the Lucy 2 4am batch
   (order 11.5). Anything before the reps start texting works.
2. **Taylor's personal contacts, or shared with the team?** Built as personal
   contacts on Taylor's login, matching the Loom (Source: *RingCentral
   (default)*). If Carlos, Mayra and the reps should all see them too, they
   need to go to the company directory instead — different endpoint, different
   permissions, and an admin has to grant it.
