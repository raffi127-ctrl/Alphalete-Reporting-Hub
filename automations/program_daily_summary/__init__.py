"""Program Daily Summary — COUNTRY sales per program, per day, in one picture.

Ask (Maud for Raf, #l10 thread 2026-11-20): every day, Lucy sends ONE image with
the daily sales of Fiber, NDS, B2B, Frontier and Fios — COUNTRY totals (all of
SCI), not our org — into the daily Tableau trackers thread and as a DM to Raf.

Sources, one per program (country = the source's own grand-total row):
  Fiber / NDS / B2B  -> Tableau country trackers (pulled on a Lucy; see probe.py)
  Frontier / Fios    -> Credico's daily scorecard PDFs in the reporting inbox
                        (credico_pdf.py), red totals row, Sun..Sat weeks.

Status 2026-11-20: Credico parser built + tested; Tableau worksheet names for
NDS/B2B still unknown -> probe.py runs on a Lucy first. First posts go to Eve's
DM only.
"""
