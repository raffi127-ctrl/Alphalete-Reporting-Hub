"""IDs, tab names and column labels for the weekly commission (payroll) run.

JD's Loom 2026-09-03 (his payroll chore, sent to Megan). Two workbooks:

  * the WEEK'S commission workbook — a fresh duplicate named "RH <M.D>" (the
    Sunday / week-ending date), holding the numbered workflow tabs plus one
    payout tab per rep;
  * "All in One Local Office - Raf" — the standing workbook that holds the
    `ATT Sales Transfers` form responses and the `Raf PNL 2026` year grid.

SANDBOX: WORKBOOK_ID points at "RH 8.30 Practice" until Megan says otherwise
(Eve's sandbox-first rule). Nothing here writes without an explicit --write.

Column names are LABELS, never indices — the DD and order-log crosstabs get
re-shaped by Tableau and the workbook's own tabs get columns inserted. Every
lookup goes through `header_index`, which matches case/space-insensitively and
raises with the real header list when a label goes missing.
"""
from __future__ import annotations

# --- workbooks -------------------------------------------------------------
WORKBOOK_ID = "1nIa_S-EX20ejQPHKgTxgiGs8t0G1VpAd4a26lx1Od1Q"   # RH 8.30 Practice
ALL_IN_ONE_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"  # All in One - Raf
COMMISSION_FOLDER_ID = "1-90sJRYFH3HbIuhAAS0O8kCOTrAPZ8lU"      # live weekly copies
#: Raf's folder — finished weeks get MOVED here. Step 1 keeps the two most
#: recent workbooks in COMMISSION_FOLDER_ID and archives everything older
#: (Megan, 2026-09-04). A move, never a copy or a delete.
ARCHIVE_FOLDER_ID = "1EykOnmOmKCmCHUKecj1J9i6fcRiTx8pL"
#: How many workbooks stay in the live folder. JD: "I just want to keep the last two."
KEEP_RECENT = 2

# --- tabs ------------------------------------------------------------------
TAB_DD = "1. Paste the DD"
TAB_ORDER_LOG = "2. Paste the Order Log"
TAB_REPS = "3. Add Reps and Set Commission"
TAB_CONFIRM = "4. Confirm DD Details and Add Bonuses"
TAB_PNL = "PNL"
TAB_TRANSFERS = "ATT Sales Transfers"   # in ALL_IN_ONE
TAB_YEAR_PNL = "Raf PNL 2026"           # in ALL_IN_ONE

# Crosstab tabs carry headers on row 1 and data from row 3 (row 2 is the
# Tableau "Grand Total" band).
DD_HEADER_ROW, DD_FIRST_DATA_ROW = 1, 3
OL_HEADER_ROW, OL_FIRST_DATA_ROW = 2, 3

# --- DD (Tableau "DD DETAIL (ORG)") columns --------------------------------
DD_REP = "REP.Full Name"
DD_CUSTOMER = "cl.Customer Name"
DD_PRODUCTION_LOOKUP = "cl.Production Lookup"   # SPE-######## — joins to the order log
DD_SALE_DATE = "cl.Sale Date"
DD_ACTIVATION_DATE = "cl.Activation Date"
DD_TOTAL_TO_ICD = "Total $ to ICD"

# --- order log (Tableau "A.Order Log" ALLREPS) columns ---------------------
OL_SPM = "sp.SPM Number"
OL_CUSTOMER = "Customer Name"
OL_REP = "Rep"
OL_SPE = "spe.Name"                     # SPE-######## — joins to the DD

# --- ATT Sales Transfers (form responses) columns --------------------------
TR_TIMESTAMP = "Timestamp"
TR_TO_REP = "Your Name"          # substring match — the header carries a BOM + blurb
TR_FROM_REP = "Name that the Sale is under"
TR_SALE_DATE = "Date of Sale"
TR_CUSTOMER = "Customers Name"
TR_SPM = "SPM #"
TR_STATUS = "Status"

#: A transfers row whose `Your Name` cell reads like this is not a transfer at
#: all — it is Eve's per-sale bonus feed, and the rep in `Name that the Sale is
#: under` is the one earning it.
BONUS_MARKER = "bonus"

#: Rows carrying this anywhere in the two name cells are Raf's form tests.
TEST_MARKER = "(test)"
