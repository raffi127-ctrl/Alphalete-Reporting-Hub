# Focus Report — Tableau pull walkthrough (video transcript, Eve)

Reference only. This describes the CURRENT manual process for filling the
sales / metrics / wireless sections of the Focus Report from Tableau. We are
rebuilding this as a fully-automated phase — no manual downloads.

---

00:03 — Recording to show what pulling opportunities for the people looks
like. This is the Cloud Practice Focus Report spreadsheet. The focus report
(recruiting) part is the same for everyone. The sales-data section is pulled
every Monday for the latest update.

00:46 — Sales data: need the **D2D workbook** — open the "D2D tracker"
workbook. Find each owner (example: Marcellus). From a given line:
  - 17 = rep count → "Active Headcount on Tableau"
  - sales: new internet → new lines (example values 5, 6, 0, 1, 3, 2)
  - two of those are formulas
  - national average (6) — saves to everyone in the spreadsheet
  - wireless rep count (47 in this case)
  - score ranking (27) from the owner's vis-lead
  - the "GIG" number — pulled Mondays, lives in the metrics section

02:42 — From the **AT&T Traveller D2D** tracker (internet only): find the
owner, the "new Internet sales per rep average" column = his new Internet
average. National new-internet average = same column at the end (same for
everyone). The per-owner one changes; needs the major internet-only tracker.

03:51 — Personal production: **ATD workbook → Product Summary** → select the
correct recording → look for the owner *as a rep* → see personal sales
(example: 1 new internet, 1 DTV). Make sure all products are selected.

04:46 — Metrics section: same root **metrics workbook**, set to "this week",
find the owner:
  - install schedule 6 days out → hover the numbers for the average (26)
  - cancel rate → scroll all the way left (5.6)
  - activation rate (86%)

05:22 — Activation/Approval: same route but "capture bonus" → select the
correct week-ending → find owner → scroll all the way right (80.9).
  - 30-60 activation rate is a formula (complementary to activation rate;
    the two sum to 100).

06:54 — Churn: same root workbook, "churn" view. Make sure the churn view is
set to New Internet for this section; wireless churn is right under it.
Owner = Marcellus → fill all the buckets (0-30, 30-60, etc.).

07:42 — Penetration rate: **Lead Performance** view → find by whole name →
pick the number (1.16). Total Leads = "lead count". Expected Fiber Sales =
same as lead count (a formula).

08:34 — Direct Deposit: **Program Summary** → select the dropdown → select a
captain → it's in the Excel. (Financials have a separate video.)

09:17 — Wireless metrics: same workbooks, change the dropdowns to "wireless":
  - BYOD lines (7), BYOD average (22), new lines (0), new lines average (0)
  - activation rate (92.6)
  - wireless cancels (0)
  - insurance — never confirmed where to pull it; leaving empty for now
  - churn — change the churn-view setting to wireless

11:16 — "All of this JD got to semi-automate by running scripts + a button.
For now I just pull the data from the different Tableau workbooks, download
them as CSV, copy-paste, and run the automation. Ideally it would be great
not to have to do anything manually."

12:01 — Known issues with JD's current system: some values aren't pulled
accurately — e.g. New Lines wasn't being pulled for anyone; Edgar and Carissa
weren't getting their metrics/cells filled. Eve duplicates the tab and
double-checks/corrects by hand. Fully automating should remove these gaps.

13:00 — Almost all tabs have the same skeleton; any extra owner-specific info
goes at the very bottom.
