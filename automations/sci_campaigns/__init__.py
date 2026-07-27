"""SCI Campaigns report.

Adriana Nowrouzi (anowrouzi@aptel.com, previously anowrouzi580@gmail.com) emails
"Residential Telecom Tracker – RANKED • Week Ending M.D.YYYY" to
alphaletereporting@gmail.com most Fridays. It carries FOUR attachments — a JPG
and a PDF of each of two reports — and the PDFs are the machine-readable copy:

  1. "…W.E. <M.D> - Campaign Totals By Day.pdf"  — 9-10 campaign rows x 7 day
     columns, then a 'LW Week Ending' total and a 'Previous Week Ending' total.
  2. "…W.E. <M.D>.pdf"  — the RANKED per-office tracker (3 side-by-side
     trackers). Its FOOTER carries the AT&T NDS + the four "… Selling …
     Wireless" totals, which the by-day PDF does NOT break out.

Both are needed: the tab's 13 campaign rows are fed from BOTH PDFs (see
parse.py's BYDAY_MAP / FOOTER_RULES). Verified 2026-07-27 against every week the
VAs filled by hand — where both PDFs parse, all 13 rows match exactly.

We write the matching `MM/DD/YY` column of the 'SCI Campaigns' tab in the
Alphalete Org/Captainship workbook. Row 15 'Total Units' is a sheet formula and
is never written.

Runs FRIDAY, gated on the week's email having landed (readiness._probe_email).
"""
