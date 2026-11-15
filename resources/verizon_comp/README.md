# Verizon Wireless (Credico / Smart Circle ISO) comp — the source documents

The four Credico PDFs beside this file are the terms every Verizon money board
prices on (`automations/verizon_office/comp.py`). They came from Berna Henci
(Credico) to Nico on 2026-09-30, forwarded to Carlos 2026-10-21 ("Fwd: VZ
Wireless ONLY (FIOS) Incentives + Wireless SOW Schedule A Comp Grid SCI"), and
sit in Carlos's Google Drive too. Saved here 2026-11-15.

## What the SOW Schedule A (6.16.26) says — the parts the boards use

- **Three factors set the fee**: 30-Day Churn, Line Type (Port / New / CPO /
  BYOD), and approval date.
- **30-Day Churn** = "an order for an activated/installed VZW product and/or
  service in which the customer drops (i.e., cancels) within thirty (30) days
  of activation/installation. Churn will be calculated based on Compensable
  Sales of VZW Equipment that is activated/installed and shows approval date."
- **One churn rate, no BYOD split.** The SOW has a single Table 1 (eight
  tiers) and speaks of "Subcontractor's 30-Day Churn Rate for VZW Products /
  Line". BYOD, CPO and no-port lines count in that rate like any other
  activated line that shows an approval date; they differ only in PAY (flat
  $25, Table 2). This is unlike the AT&T NDS SOW, which has separate non-BYOD
  and BYOD churn charts.
- **Tiers (Table 1)**: 1 = 0–4.99%, 2 = 5–6.99%, 3 = 7–8.99%, 4 = 9–14.99%
  (neutral), 5 = 15–19.99%, 6 = 20–26.99%, 7 = 27–33.99%, 8 = 34%+.
- **Pay (Table 2)**: NEW–PORT smartphone by tier $237 / $222 / $206 / $190 /
  $174 / $159 / $143 / $127; NEW–NO PORT, CPO–PORT, CPO–NO PORT and BYOD a flat
  $25. Plans: Unlimited Welcome / Simplicity $0, Unlimited Plus / Ultimate +$35;
  Mobile Protect / Secure +$35. AutoPay +$60 (AutoPay Bonus PDF).
- **The window is by APPROVAL date.** The Churn Schedule's columns are
  "ApprovalStartDate / ApprovalEndDate": for each 4-week block of sales weeks
  the office's churn is measured over the lines APPROVED in that ~30-day
  window (e.g. sales weeks 10/25–11/21 use lines approved 8/25–9/23; 11/22–
  12/19 use 9/22–10/21), processed ~5 weeks before. Tiers are set at the
  office level by Sales Date, locked for the four weeks.
- **New office**: neutral Tier 4 until 15 activations in the lookback.
- **Weekly activation bonus** (Activation Bonus PDF, 4.19.26–12.31.26): per
  rep by unique customer orders in the Sun–Sat week, 4 / 5–6 / 7–8 / 9+ ->
  $30 / $50 / $75 / $110 per activated line showing approval date (Option 1,
  wireless-only mix 75%+); a rep with a 90-day cancel rate of 40%+ is
  disqualified.
- **Compensable sale**: activated/installed, shows approval date, not
  cancelled within 90 days; a line cancelled inside 90 days is not paid (or is
  charged back), as are number swaps and equipment downgrades inside 90 days.
- **Pay runs** about two weeks behind the sales week (Churn Schedule "Pay
  Week" column; the ARC Commissions workbook's SaleWeek vs CommissionWeek).
