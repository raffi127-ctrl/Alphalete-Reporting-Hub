# Local Office Sales Call Outs — session README (Sep 29 → Oct 19, 2026)

What this chat did, in order, and where things stand. The living how-it-works
doc is `LOCAL-OFFICE-SALES-CALLOUTS-README.md` (same folder); this one is the
story and the decisions. All code: `~/recruiting-report/automations`.

---

## 1. Where it ended up (current state)

**Carlos's five places:** texts to Box B2B, NEW A Players, ATT B2B Leaders;
Slack #alphalete-gp-sales and #a-players-b2b.

| Label | Report | Where | How often | Hours |
|---|---|---|---|---|
| BOX-1 | Box Knocks Board (picture) | Slack: morning "Box Metrics" thread + a-players-b2b thread · Text: Box B2B once at 6pm (Sat 4pm) | Every 2 hrs | 12–6pm (Sat 12–4) |
| BOX-2 | Box Today's Activity | Slack: Box Metrics thread | Once | 6pm (Sat 4pm) |
| BOX-3 | Box 15 min gaps (typed) | Slack: Box Metrics thread · Text: Box B2B | Every 30 min | 12–6pm (Sat 12–4) |
| BOX-4 | Box Territory Stats (one picture per territory) | Slack: Box Metrics thread | Once | 6pm (Sat 4pm) |
| BOX-5 | Weekly Knocks (Box + AT&T) | Slack gp-sales + a-players-b2b | Sundays | morning |
| NDS-1 | NDS Knocks Board (picture) | Slack: "NDS Knocks Board" thread · Text: NEW A Players + ATT B2B Leaders | Every hour | 2–9pm (Sat 10:30–5:30) |
| NDS-3 | NDS 15 min gaps (typed) | Slack: "NDS 15 Min Gaps" thread · same texts | Every 15 min | 2–9pm (Sat 10:30–5:30) |
| NDS-2 | "NDS — …" call-outs (no dispo + no credit check) | Slack gp-sales, own post | Every hour | field hours |
| SAL-1 | Box Live Sales standings | Text: Box B2B | Every Box sale | 12pm–midnight |
| SAL-2 | AT&T Live Sales standings | Text: NEW A Players + ATT B2B Leaders | Every AT&T sale | 12pm–midnight |
| SAL-3/4 | "Box — …" / "AT&T — …" sale shout-outs | Slack gp-sales | Every sale | 12pm–midnight |
| SAL-5 | "AT&T — 🔍 … credit check" | Slack gp-sales | Every new check | 10am–9:30pm |
| SAL-6 | Wrap-up text report | Slack gp-sales + a-players-b2b | Daily | ~4am |

**Off:** all Fiber reports (FIB-1/2/3, SAL-7/8) and the B2B AT&T daily boards
(ATT-1/2/3). The weekly AT&T board inside BOX-5 stays.

**Machines:** Lucy 1 (Raf's mini) sends all texts except BOX-3 and makes
BOX-1 + SAL-1..5 from Carlos's office-mini relay. Lucy 2 (MacBook, logged in
as Carlos) makes BOX-2/3/4/5, NDS-1/2/3, the 7:30 threads + pins, and the
BOX-3 / NDS texts. Carlos's office Mac mini only relays (SaraPlus, My
Service Cloud, Ownerville) to Lucy 1.

---

## 2. Timeline

**Sep 29** — Audited what reaches Carlos's chats. Found reports the first
pass missed (the ICD office boards, call-outs, weekly). Carlos's rules set:
knocks boards and gap lists are separate reports; confirm destinations
before deploying. Labels D1–D10, then BOX / ATT / FIB / SAL by team.
- B2B hourly post → once a day at 6pm, Box only; AT&T hourly and AT&T
  territories stopped; territories one picture each in a "Territory Stats"
  thread.
- Box 15-min gaps became its own typed report (no picture) every 30 min, to
  Slack and Box B2B.
- Fiber: board hourly, typed gaps every 15 min, to NEW A Players + ATT B2B
  Leaders and a Slack copy.
- Fiber sales + credit checks off Raf's SaraPlus (SAL-7/8) for the crew.
- Bug fixed: "2 PM" matched "12 PM" in the Slack dedupe, skipping 2pm posts.

**Sep 30** — Jacob Ortega added to the crew. Explained what breaks when
Carlos's office mini is down (BOX-1 and the sales alerts).

**Oct 3** — Saturdays start 10:30 for the crew. Threads: one per report,
opened 7:30am after the metrics threads, pinned, yesterday's unpinned
(unpin needs the Slack scope `pins:read`, still missing). Campaign first on
every post. Box board thread. Fiber board in its own thread; call-outs
hourly. Sebastian Avellaneda added. Loose pre-thread posts deleted (only
Lucy's own). "Local Office Sales Call Outs" became the report's name.
Crew last-week sales pulled from Lucy 1's state (52 for 9/28–10/4).

**Oct 4** — Sunday run as Saturday, one-off (`shared/day_override.py`).

**Oct 8** — Yesterday's final Fiber board at the top of the morning thread
(it already did that for Box). Payroll week 10.4: $100 bonus (Yariel),
$600 guarantees (Luis Valenciano, Jayden Willingham, Edgar Camunez, William
Bautista), no-pay (Luis Enrique Servellon) → Adjustments tab, refreshed with
`vantura_payroll --refresh-only`. README written.

**Oct 19** — **Fiber → NDS.** The crew's reports now read CARLOS'S
Ownerville (office 11580), campaign **RES AT&T OOF** (id 1, found via
`b2b_dispositions --probe-picker`; the id scan can't see it), labelled NDS.
New module `automations/nds_oof/` on Lucy 2, agent every 15 min. Fiber
switched off after NDS posted (first board 2:30pm). Then: BOX-1..4 moved
out of their own threads into the morning "Box Metrics — <date>" thread.
Also: SaraPlus on the office mini had been locked out since 10:01am
(emailed-code wall); Carlos switched the saved login to the NDS account
with `python -m automations.icd_alerts.run --set-login` (email box first,
password second).

---

## 3. Decisions to remember

- Knocks board ≠ gap list. Always separate messages and separate lines.
- Campaign name first on every post (Box —, NDS —, AT&T —).
- Confirm destinations with Carlos before deploying anything that sends.
- Saturday: no disposition posts after 5:30pm; sales posts exempt.
- NDS reads the whole OOF campaign — no name list. The 16-name crew list
  (`total_knocks/guests.py`) now only keeps them off Raf's sales board.
- Raf's rooms are never touched by Carlos's changes.
- Never post blank: no gaps → no gaps message.

---

## 4. Open items

- **`pins:read` scope** on the Lucy Reporting Slack app (Megan) so
  yesterday's pins clear each morning.
- **Office mini SaraPlus login** must show "signed in" as the NDS account;
  until then no AT&T sales / credit checks (and no NDS call-outs).
- Lucy 1 can be slow (10-min passes); Lucy 2's queue sometimes wedges behind
  a long job.
- `shared/day_override.py` still lists 2026-10-04 (harmless).

---

## 5. Hand commands (queue `rerun …`)

| Command | Machine | Does |
|---|---|---|
| `nds_oof --force --board` | Lucy 2 | Dry run of NDS (add `--send` to post) |
| `b2b_dispositions --morning --send` | Lucy 2 | Open today's NDS threads, fill, pin |
| `b2b_dispositions --backfill-yesterday "NDS Knocks Board" --send` | Lucy 2 | Yesterday's final board into today's thread |
| `b2b_dispositions --delete-loose "<prefix>" --send` | Lucy 2 | Delete today's loose Lucy posts with that prefix |
| `b2b_dispositions --probe-picker --headless` | Lucy 2 | List the Ownerville campaign picker (label + id) |
| `sales_board_standings` / `… --week A B` | Lucy 1 | Raf's board + crew standings / crew sales per day |
| `vantura_payroll --refresh-only` | Lucy 2 | Rebuild the payroll Commission tab |
| `install_nds_oof_agent`, `install_b2b_dispositions_<gaps|hourly|morning>_agent` | Lucy 2 | Reload an agent after a plist change |
