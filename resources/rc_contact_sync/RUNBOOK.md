# B2B Customer Contacts (RingCentral) — runbook

Built 2026-09-02 from Carlos's 3 Looms. **Not armed yet** — it needs the two
credentials in §1 before it can run at all.

Module: `automations/rc_contact_sync/` · Hub card: **B2B Customer Contacts
(RingCentral)** · Runs on **Lucy 2** · Scheduler key: `rc_contact_sync`
(`on_scheduler: false` until §3 is done).

---

## What it does, in order

0. **Signs in through the emailed verification code.** SaraPlus asks for a code
   at login; Carlos has it filtered to **alphaletereporting@gmail.com**, so the
   report submits the password, polls that inbox for a code that arrived
   *after* the submit, types it, and continues. An older code is somebody
   else's login or an expired one — it would be entered confidently and fail as
   "wrong password", so anything predating the attempt is ignored.
   Read-only: the mailbox is opened readonly and nothing is marked or moved.
1. **SaraPlus** (Carlos's login) → Analytics → Detail Reports → **Sales Order
   History** → date range set to yesterday on both ends, Customer Type
   **Both**, Submit.
2. Each row gives everything: the **rep** (`User Name`), the **business**
   (`Business Name`), the **customer** (`Customer Name`) and the **phone**
   (`Phone`). No "View Customer" click — see below.
3. **RingCentral** (signed in as **Taylor**) → one contact in her address
   book per customer:
   `Company` = business name · phone = primary phone (Mobile) ·
   `Notes` = `Rep Name: <rep>`.
4. **RingCentral** → reads that same line's texts for yesterday and asks, per
   customer, **did the wrap up go out to them?** — not "were they texted at
   all". The ones missing it are posted, grouped by rep, into the **B2B
   metrics thread in #a-players-b2b** (that channel only). No text message —
   Carlos: *"we dont need a text. slack works."*

---

## 1. The two credentials it still needs

### a) Carlos's SaraPlus login

On a Mac that has the password, run:

```bash
python -m automations.rc_contact_sync.set_credentials --push "Lucy 2"
```

It asks for the email (Enter keeps `carhi1816@gmail.com`), then the password
twice at a **hidden** prompt — a terminal prompt if there is a terminal, a
native macOS dialog if there isn't. It writes
`~/.config/recruiting-report/saraplus-creds-b2b.json` at mode 600 and `--push`
hands it to Lucy 2 through mini_control's redacted transit. The password is
never echoed, never a command-line argument, and so never reaches shell
history, a log, a chat, or the Mini Control sheet (`set_cred_file` is in
`SECRET_ACTIONS`, so the Args cell is blanked the moment the row finishes).

Already on another runner? Move it without retyping:

```bash
lucy push_cred_file saraplus-creds-b2b "Lucy 2" --machine "Lucy 1"
```

**Its own file, on purpose.** `saraplus-creds.json` is
`alphaletemarketing@gmail.com` — the Alphalete Sales Board sweep's login, a
different dealer. Megan, 2026-09-02: *"make sure you're ONLY using Carlos'
sara plus login to access."* Reusing that file would return rows — just not
these rows, and nothing would look wrong.

**The code email matters as much as the password.** SaraPlus's verification
code has to keep landing in alphaletereporting@gmail.com, and Lucy 2 needs
`~/.config/recruiting-report/gmail-app-password` — that app password is how the
report reads the inbox. Push it with:

```bash
lucy push_cred_file gmail-app-password "Lucy 2"
```

If the code arrives from a sender or with wording the search misses, the run
stops with "no SaraPlus verification code reached …" and types nothing in; open
the mailbox, find the real email, and tighten `VERIFY_QUERY` in `config.py`
(e.g. `from:noreply@saraplus.com`).

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

## The wrap-up phrase list — check this before arming

Carlos, asked what the post should say (2026-09-02): *"Customers who didn't
receive wrap up text."* That is the spec, not just the wording — the check is
for the **wrap-up**, not for any message.

What counts as a wrap-up is `rc_autoread.WRAP_UP_PHRASES` — the 96-phrase list
Dylan's RingCentral auto-read already matches on, reused rather than
re-derived. **It is residential-flavoured** (AT&T fiber, DirecTV, self-install
kits). If the B2B wrap-up is worded differently, every customer comes back as
"no wrap up text" and the post chases every rep.

So a dry run prints `N of them wrap-ups` for the day, and shouts if there were
messages but **not one** matched. If that shout appears, get one real B2B
wrap-up text from Carlos and add its distinctive phrase to
`B2B_WRAP_UP_PHRASES` in `automations/rc_contact_sync/config.py` — it is
checked *in addition to* the shared list, never instead of it.

The log also separates "texted but never wrapped up" from "never contacted at
all" (it prints how many other messages exist with that customer). The post
treats both as owed a follow-up; the log is there for when a rep says "but I
did text them".

---

## How the SaraPlus page actually behaves

Read off the live page on 2026-09-03, in a real browser, with Megan signed in
as Carlos. Nearly all of this contradicts what the Loom appeared to show, and
every item cost a failed run to find:

- **The panel is opened by POSTBACK, not by clicking.** "Detail Reports" is a
  *container* tab (its `pageView` is null — nothing happens on the server), and
  its child isn't in the DOM until the parent is expanded. Meanwhile patchright
  evaluates in an isolated world, so Telerik's `$find` and the page's
  `__doPostBack` are both unreachable. A real mouse click sets Telerik's
  `rtsClicked` class and changes nothing else, so it reads as working. The
  report therefore sets `__EVENTTARGET` / `__EVENTARGUMENT` and submits the
  form — values captured off the wire from a human's click:
  `ctl00$MainContent$rtsReportOptions` / `{"type":0,"index":"3:0"}`.
  That `3:0` is a hierarchical index and the one positional thing here, which
  is why every run verifies `MainContent_rpvOrderHistory` actually appeared.
- **Customer Type defaults to `Residential`.** Leave it and the report finds no
  B2B customers and looks like a quiet day. It is set to `Both` and re-checked
  after the selection, which **autoposts back** — that re-render also resets
  the dates, so they are written again afterwards.
- **No `View Customer` needed.** The grid returns ~146 columns and the Report
  View toggle only changes which are *visible*; every column stays in the DOM,
  `Phone` included. One page load for the whole day instead of one per
  customer.
- **The grid is two tables.** RadGrid renders its header (`…_ctl00_Header`)
  separately from its rows (`…_ctl00`). "The table whose first row holds the
  headers" finds the header table, which has no data in it.
- **Submit is an async postback.** `networkidle` returns before a 146-column
  grid has rendered, so the run waits for the grid element itself — otherwise
  a real day reads as empty.
- **Login lands in two different places.** A remembered browser lands on
  `DealerPages/`; a login that just cleared the passcode challenge lands on
  `Reports/ReportingHub.aspx`. Both are accepted.

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

2. **Should the rep be @-mentioned?** Megan floated *"@repname, please reach
   out to your customer…"*. Built with the rep in **bold text**, not an
   @mention: there is no rep-name → Slack-user-id map for the B2B reps, and
   this workspace has enough duplicate first names that a name lookup
   eventually tags the wrong person in a leaders' channel. Wiring real
   mentions needs a one-time list of rep → Slack id.

3. **Dylan Twaddle already has something adjacent.** Megan flagged it in the
   thread: his RingCentral auto-read (`automations/rc_autoread/`) scans the
   same extension for unread SMS and marks a thread read once it hits a
   wrap-up. This report *reuses that module's phrase list* but does not
   overlap with it — one marks threads read, the other reports who never got
   a wrap-up. If Carlos wants Dylan's responding tool too, that is a separate
   piece.
4. **Taylor's personal contacts, or shared with the team?** Built as personal
   contacts on Taylor's login, matching the Loom (Source: *RingCentral
   (default)*). If Carlos, Mayra and the reps should all see them too, they
   need to go to the company directory instead — different endpoint, different
   permissions, and an admin has to grant it.
