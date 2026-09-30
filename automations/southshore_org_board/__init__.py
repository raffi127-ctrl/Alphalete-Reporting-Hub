"""Southshore Org Sales Board — Colten Wright's daily org scoreboard, by text.

Colten asked (2026-09-29, Slack) to automate the org report he texts to his
Southshore Org chat every morning. Megan + Rafael: reuse the sales-board look,
scoped to his org, with the last 4 weeks and the deltas. Colten approved the
preview 2026-09-30.

ONE image: his 12 market managers by day (Mon–Sun), Units / Last Week / Prev
Week, the Org Total, the last 4 weeks by day, then vs Prior Week and vs 4 Week
AVG. Units = WIRELESS + AIR — that is what his own report counts (it matched
his numbers to the unit on 9/28, Monday AND last week, all 10 NDS owners).

Sources (all Tableau, pulled by THIS report — no reuse of the board's files):
  * 10 NDS owners — NDS-SN (RES-ATT-OOF) Workbook → Product Sales Summary(Rep)
    → custom view 'Thisweekandlast' → sheet 'Sales By ICD (Weekly View)',
    WIRELESS + AIR rows. It serves this week AND last week by day.
  * Eveliz Wright + Valeria Tristan (B2B) — the Org Sales Board's B2B spec
    (ATTTRACKER-B2B → 'Sales By ICD (ATT) (V2)'), week-pinned to the reporting
    week.

History: Tableau only serves 'This Week' / 'Last Week' here, so each run saves
the weeks it sees into history.json. The 3 weeks before 9/27 (and 9/27's
by-day row) were seeded from Colten's own report (Megan 2026-09-30: "use his
numbers"). From W.E. 10.4 on, every closed week is Tableau's.
"""
