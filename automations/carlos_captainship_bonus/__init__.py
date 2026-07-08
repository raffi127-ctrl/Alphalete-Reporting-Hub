"""Carlos B2B Captainship Bonus — weekly fill of the "Carlos B2B Captainship"
tab in the *All In One - CARLOS* sheet.

Automates the weekly Loom (a sibling of raf_captainship_bonus): insert a fresh
leftmost week column (cloning last week's formulas), fill each active rep's
**Total Activations** for Carlos' B2B team (pulled live from Tableau
ATTTRACKER-B2B / Captain Team), fill the four team/personal metric cells
(team 0-30 churn %, personal 0-30 churn %, 31-60 activation %, non-payment %),
let the Total Activations / Money Made / TOTAL AMOUNT formulas recompute,
re-point the performance chart's series at the Total - All Units row, and
export the 5-week + chart view to a PDF.

Entry point: ``python -m automations.carlos_captainship_bonus.run``
"""
