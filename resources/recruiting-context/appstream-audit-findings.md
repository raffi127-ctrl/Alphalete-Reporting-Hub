# AppStream recruiting audit — method, findings and dead ends

Built 24 Oct – 3 Nov 2026 (Megan + Claude). Read this before starting any new
AppStream funnel audit. Most of it was learned the expensive way and several
sections exist specifically to stop someone repeating a wrong turn.

---

## 1. Where the data actually is

### The Action History tab is the only per-applicant source
Each applicant's dialog ("Applicant History for &lt;name&gt;") has an **Action
History** tab: `Action | Source | At | By`. It is the only place AppStream
records WHAT was done, WHEN, and BY WHOM, per person.

    PYTHONPATH=. .venv/bin/python -m automations.sms_thread_dump.run \
        --office 11280 --dates <MM-DD-YYYY,...> --actions

Writes `Action Dump <office>` (control sheet) and
`output/sms_thread_dump_<office>.json`. ~1.8–3s per applicant.

Action names seen in the wild: `Send to Call List` (pushed/processed),
`Send to AI`, `Assign First Interview`, `Mark Show Up` / `Mark No Show`,
`Assign Second Interview`, `Mark Show Up (2nd)` / `Mark No Show (2nd)`,
`Disqualify 1`, **`Decline 1`** (the APPLICANT withdrew — a different outcome
from Disqualify, and easy to miss), `Bring on Board`, `Offered Position From
Second`, `Follow Up`, `Follow Up (2nd)`, `Reschedule First Interview`,
`Left Message 1/2/3`, `No Answer`, `Edit App`, `Overrule Duplicate`.

### p=704 Activity Report CANNOT do this — do not re-try it
Right columns, but it returns only `First Interview Date` /
`Second Interview Date` off the Calendar. On an office-day where action rows
provably existed it gave 212 rows and none of them were actions. Its
Activity / Source / Owner / Action By filter dropdowns come back with **no
options**, and forcing `summaryVersion=0` changes nothing. Verified
2026-10-24. The `--full` flag added to `pull_activity.py` is a dead end kept
only so the next person sees it was tried.

### Message bodies are a separate pull
`--actions` mode leaves `thread` EMPTY — 0 of 12,727 records had text. For
anything about what was SAID, pull the SMS List Report:

    PYTHONPATH=. .venv/bin/python -m automations.sms_audit.pull_log \
        --office 11580 --dates 10-19-2026,10-23-2026

**It always writes `output/sms_log_<office>.json`, so a multi-week loop
silently keeps only the last week.** Rename after every pull. (This same
overwrite pattern has now bitten three times: ACA tabs, Action Dump tabs, and
this.) A 19-day range fails on 11280 — one week is 15–21k rows. Pull weekly.

---

## 2. THE BIG LIMIT — the dump only contains people who BOOKED

`sms_thread_dump` walks the **Calendar**, so every record already has an
interview: 3,121 of 3,124 on 11280. Anyone pushed to the call list who never
booked is structurally absent.

So this data answers *"among booked applicants, what predicts showing up"*.
It **cannot** produce any applies-to-booked or sent-to-booked conversion.
Don't try — the denominator is not in the file.

---

## 3. RTCL is PUBLISHED — read it, never derive it

Megan 2026-10-26: *"RTCL % is always in the retention details report."*
AppStream → Reports → **Retention Report** (`index.cfm?p=701`), the **yellow
row "Retention Call List"**, per day and as a weekly total. Already mapped as
`pct_apps_booked_first` in `fetch_office.METRICS`. Definition: interviews
booked ÷ sent to call list.

Two ways deriving it goes wrong, both hit in this session:

- The org tracker's **Call List tab "Date and Time" is Entered At, not the
  push date**. Verified on one applicant: entered 10/14, sent to call list
  10/23 — nine days apart. Bucketing by it produced 55/51/39/40 when the
  published truth was 50/50/50.
- AppStream's weekly total is **not** a plain booked÷sent (213/409 = 52% but
  it prints 50%). Quote its number, not your arithmetic.

### Mondays always read low — this is the #1 false alarm
Monday is the big push day (often a third of the week in one go) and those
bookings land Tue–Fri. Daily RTCL divides that day's bookings by that day's
pushes, so **every office reads 38–44% on Monday and 53–61% by Friday**. A
Monday snapshot is the single most common way somebody concludes the call
list is broken when it is flat. Exactly what happened on 19833.

---

## 4. Findings that held up

### Booking speed: the cliff is 24 HOURS, not 4
10 offices, 11,830 pushed+booked pairs, 4 weeks (21 Sep – 24 Oct, Cancun
week 12–16 Oct excluded):

| gap | showed |
|---|---|
| 0–1h | 53.6% |
| 1–4h | 55.4% |
| 4–8h | 54.6% |
| 8–12h | 52.1% |
| 12–24h | 46.2% |
| 24–48h | 41.6% |
| 48h+ | 38.9% |

**Under 24h 52.5% vs 24h+ 40.2%, p=5e-25.** 18% of applicants (2,158) are
carried past a day. Speed WITHIN the day buys nothing — one minute and seven
hours give the same result. Coach *"clear the list the same day"*, never a
response-time SLA. An early single-week read suggested a 4-hour line
(54/42); that did **not** survive the larger sample.

### The AI is faster, not better
| booker | n | median push→book | showed |
|---|---|---|---|
| AI Messaging | 7,124 | **6.1h** | 52.4% |
| a person | 4,706 | 12.3h | 47.0% |

But inside each speed band: under 24h AI 54.0% vs person 49.7%; **24h+ AI
40.2% vs person 40.2% — identical**. The AI's entire advantage is getting
there sooner.

### The whole funnel (10 offices, 4 weeks)
    booked a 1st round   12,422
    showed up             6,169   49.7%
    advanced to a 2nd     2,968   48.1%
    showed to the 2nd     1,629   54.9%
    brought on board        732   44.9%

**Half of everyone booked never arrives** — the biggest single loss in the
funnel, and the one the 24-hour rule moves.

### Same-day OFFERS do not help (null result)
Carlos asked whether the AI tries to book same-day or jumps to tomorrow.
Week 19–23 Oct, offices 11280+11580, 501 AI offer messages, 372 joined:

- Before 1pm, **92% of AI offers included a same-day slot**; only 5% went
  straight to next day. The behaviour flips at lunchtime: 1–4pm is 56%
  same-day, after 4pm just 1%.
- **But it made no difference to attendance: 47.4% (same-day offered) vs
  47.0% (next day only), p=1.00.** Afternoon only, 50% vs 48%, p=0.85.

So the 3–6 hour template work is fine for applicant experience but should
not be expected to lift show-up. Classifier: outbound SMS matching
offer-words + a clock time, then same-day vs next-day by language in English
and Spanish (today / hoy / tomorrow / mañana).

---

## 5. Reading a funnel drop — the right split

Split 1st-round show-ups into **advanced / disqualified / declined / still
being worked / no outcome after**. Definitions that matter:

- **still being worked** — no decision recorded, but chased since the
  interview (104 of 105 had a follow-up or call attempt logged). Live, not
  forgotten.
- **no outcome after** — `Mark Show Up` is the last thing on the record. They
  were worked hard up to the interview (6–14 actions) and the trail stops.
  Only ~5% org-wide.

On 19833 the "2nd round retention fell" story was really **disqualified
12%→23% AND declined 7%→14% doubling together** while show-ups grew 59% —
i.e. a sourcing question, not an interview or staffing one.

---

## 6. Wrong turns — do not repeat these

1. **"Mass SMS = cold list."** No. `Mass SMS` means the message was SENT IN
   BULK; it says nothing about the applicants. 762 of one week's sends were
   "Thanks for applying…" to brand-new applicants and 1,410 were day-2
   follow-ups; 46% of that group had a bulk send as their first ever contact.
   The real distinction is **bulk-sent vs messaged one-to-one** — a method
   the office controls. The ACA rows were renamed to "Texted in bulk" /
   "Texted one by one" on 2026-10-26 (commit `db4bc3d`).
2. **"One person is the 2nd-round bottleneck."** Booking a 2nd round costs
   seconds; it is not effort-limited. Somebody doing 92% of an action is not
   evidence of a capacity constraint.
3. **"There is a recording gap."** 95% of show-ups get an outcome logged, and
   the unlogged share FELL from 14% to 2% as volume grew. Check `Decline 1`
   before calling anything unrecorded.
4. **Deriving RTCL.** See §3.
5. **Trusting a single week.** The 4-hour line came from n=675 and died at
   n=11,830.

---

## 7. Where things are

- `output/sms_thread_dump_<office>.json` — action histories, 10 offices,
  4 weeks. 12,431 applicants / 125,079 actions / 0 read errors.
  Offices: 11280, 11580, 11901, 19717, 19833, 22177, 22524, 22815, 22820,
  22992.
- `output/action_runs/<office>.log` — per-office scrape logs
- `output/sms_log_<office>_w1019.json` — SMS bodies, 11280 + 11580, wk 19 Oct
- `output/icd-audit-10-offices.txt` — the full analysis tables
- `output/icd-audit-overall.png` / `.html` — org-level summary chart
- `output/ai-booking-audit.png` / `.html` — Carlos's same-day question
- `output/carlos-chart-19833.png` / `.html` — the 19833 audit
- `output/roshan-19833-rtcl-audit.md`, `output/rtcl-audit-scripts/`

Charts are built as HTML then screenshotted with patchright (no matplotlib on
this machine):

    .venv/bin/python -c "from patchright.sync_api import sync_playwright; ..."

---

## 8. Running it again

Megan's laptop can reach everything but stores no AppStream credentials, so
it needs a human login — **ask her, don't route the work elsewhere**:

    PYTHONPATH=. .venv/bin/python -m automations.shared.tableau_patchright --appstream-login

The session file lands at `automations/shared/.appstream_storage_state.json`
(NOT the repo root — a watcher looking in the wrong place silently waits
forever). Session life has been erratic: 2h+ on 26 Oct, ~6 minutes on 28 Oct.
Write long runs to checkpoint per office and to park-and-wait on auth failure
rather than failing through the remaining work.

Lucy 1/2/3 each hold their own AppStream console; **Lucy 4 does not**
(`holds_appstream=False`). `sms_thread_dump` and `sms_activity` are pinned to
Lucy 2, so `--machine` is needed to spread them.

---

## 9. Open

- Second week of SMS bodies for 11280/11580 (session died mid-pull).
- The same-day-offer null result is one week / two offices — worth a second
  week before it is treated as settled.
- Why disqualified + declined doubled on 19833 — the data locates it but
  cannot explain it. Needs the sourcing question answered.
- `output/` is gitignored, so none of the data files above are in the repo.
