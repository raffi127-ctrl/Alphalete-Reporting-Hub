# Funnel Board — what we built and why

Notes from the build session (2026-08-07/08, Carlos + Claude). Written down
because several of these were found the hard way and would cost the same time
again.

---

## Where the data comes from

**ApplicantStream → Report → Retention - Details (new)** — page `p=783`. Not the
older "Retention - Details". Verified against Carlos's live Focus Report.

### Driving that page (three traps)

1. **The visible Week datepicker is decorative.** The server echoes `weekStart`
   back and ignores it. The hidden **`startDate2`** field (MM/DD/YYYY, defaults
   to today) is what selects the period. Posting only `weekStart` silently
   returns the *current* week — which looks exactly like success if your test
   date happens to be in the current week. This cost an hour.
2. **`form.submit()` is shadowed.** The form contains `<input name="submit">`,
   so `HTMLFormElement.prototype.submit.call(f)` is required.
3. **Every URL needs `&rqst=<TOKEN>`.** A bare `index.cfm?p=104` returns
   "Valid User ID Not Obtained!" and leaves a page with no `#searchMC`, which
   then poisons every office after it in a loop.

Also: the jQuery datepicker's `setDate` is unreachable from patchright's
isolated world (`window.jQuery` is invisible), so it no-ops silently. Native
form POST sidesteps it.

---

## Metric mapping — calibrated, not guessed

Matched against the live Focus Report (Rafael Hidalgo, week 7/27–8/2) by summing
every row on the report and finding which one equals the published figure.

| Focus Report | AppStream row |
|---|---|
| 1ST BOOKED | `Total First Interviews` — **not** `First Interviews Booked` (645 vs 689) |
| 1ST SHOWED | `First Interviews Showed Up` |
| 2ND BOOKED | `Total Second Interviews` |
| 2ND SHOWED | `Second Interviews Showed Up` |
| Job Offered | `Offered Job From Second Round` — **not** `Position Offered from Second Calendar` (54 vs 52) |
| BOB | `Brought on Board Booked` |
| New Starts Scheduled / Showed | `Total New Starts Scheduled` / `New Starts Showed Up` |

Worth knowing what "1ST BOOKED" actually means: `Total First Interviews` filters
on *First Interview Date* — interviews **scheduled to occur** that week. It is
not bookings **taken** that week. The label has always been misleading.

---

## Things we got wrong and corrected

These are recorded because each one changed a conclusion.

**Weekends are not idle.** An early assumption that Sat/Sun were ~0 was wrong.
Measured across four complete weeks: weekends are 4.7% of all activity, and
Sunday alone is 5.6% of applies. Carlos caught this.

**Pace differs sharply per metric.** New Starts are ~79% done on Monday
(training starts Monday); applies only ~29%. A single "days elapsed" divisor
badly misjudges both. The pace curves are measured per metric from completed
weeks.

**Email is not the only intake path — the biggest correctness bug of the
build.** `Email Apps Sent to Call List` alone understated the call list badly.
Applicants also arrive via `Manual Apps Entry`, `Sent To Call List Resume
Scooper` and `Sent To Call List File Import`; removals also happen on the
scooper path. Full-year impact:

| Manager | Sent (email only) | Sent (all paths) | Ret to CL was | now |
|---|---|---|---|---|
| Rashad Reed | 1,716 | 3,823 | 110.8% | 49.8% |
| Salik Mallick | 11,495 | 16,245 | 70.9% | 50.1% |
| Atef Choudhury | 3,231 | 3,956 | 74.6% | 60.9% |

**A bookings/sends ratio over 100% is the tell.** Rashad took in more via the
scooper than via email. Two published conclusions had to be retracted: Salik was
never the top converter, and Cyrus Wade's removal rate is far less of an outlier
than email-only maths implied.

**New Starts Scheduled = BOB, one-for-one.** A single week suggested NS ran ~25%
above BOB; the full year says **99%** across 7,493 people. Carlos's instinct was
right and the one-week reading was wrong.

**AppStream's `Retention Call List` is a cohort stat, not a period ratio.** It
answers "of the people saved to the call list this period, what share got a
first interview booked" — filtered on *when Save to Call List happened*. It does
**not** equal bookings/sends for the same period, and the two diverge by 14
points for managers whose sends and bookings are out of phase. Its denominator
is the *full* call list, not the email path.

---

## Design decisions

**Daily Log is the single source; the three view tabs are `SUMIFS` over it.**
Nothing is pasted into a view, so a re-run can't corrupt layout or formatting.

**History lives in the sheet, not the repo.** The run reads Daily Log back and
merges. A daily-changing data file in git would eventually collide with Lucy 2's
`git pull --ff-only`.

**Goals: you type the rates, the counts compute.** 18 columns but only ~9 real
degrees of freedom. Typing both a rate and the count it implies lets them
contradict; deriving the counts makes the funnel self-consistent by construction.

**Two visual languages, deliberately.** A filled cell means a rate vs its goal; a
coloured number means a count vs pace. Filling both turns the board into one
wash.

**Only goal-bearing metrics are coloured.** Colouring a derived count as well as
the input behind it says the same thing twice.

---

## Operational gotchas

- **Run headed.** `headless=True` trips a Cloudflare re-challenge on the
  rcaptain login.
- **`fetch_office._switch_office` is flaky** — the autocomplete click raises a
  30s "waiting for scheduled navigations" timeout perhaps 1 run in 3 even though
  the click landed. Retry, and verify by reading `Office ID: (\d+)` off the page
  rather than trusting the return value.
- **Lucy 2 drops more offices than the mini** (5 of 14 on her first run, 0 on
  the mini) — she's slower and runs a dozen other agents. Hence two retry passes.
- **Rafael (11280) and Khalil (11901) render slowest.** 60s is not enough; the
  wait is 240s.
- **Big offices time out inside a long multi-office loop** but succeed in a short
  dedicated run. Pull them first, or separately.
- **Parallel workers are fine.** Three concurrent sessions on separate browser
  profiles ran without conflict; a full-year 14-office pull takes ~20–30 min that
  way.

---

## Office IDs

| Manager | Office | Listed in AppStream as |
|---|---|---|
| Atef Choudhury | 23467 | |
| Carlos Hidalgo | 11580 | CARLOS HIDALGO |
| Cody Cannon | 21151 | |
| Cyrus Wade | 22815 | |
| Haytham Nagi | 22524 | |
| Isaiah Revelle | 19717 | |
| Jacob Dover | 23607 | |
| Kash Rai | 22177 | **Akashdeep Rai** |
| Khalil Mansour | 11901 | KHALIL MANSOUR |
| Maxamad-Amin Aden | 23066 | **Maxamad Aden** (not 22480 Aden Berhane) |
| Rafael Hidalgo | 11280 | |
| Rashad Reed | 23411 | |
| Roshan Amin | 19833 | **Roshan Amin Ahmad** |
| Salik Mallick | 21328 | **Muhammad UI Haque** |

---

## Open items

- **Lucy 2's Sheets account needs edit access to the tracker.** Her live run
  fails with `"The caller does not have permission"` on write. She can read it
  (the dry run read 3,122 rows fine) but not write. The Hub's Sheets identity is
  `alphaletereporting@gmail.com` — share the tracker with that address as an
  **Editor**.
- **Offer % has no fixed threshold** — it grades against the typed goal only.
