"""Carlos Captainship Headcount — weekly Monday fill of the "Captainship Head
count" tab in the *All In One - CARLOS* sheet.

Automates the Monday Loom: reconcile the owner rows against Carlos' captainship
(read from the Org Sales Board — see ``roster.py``), insert a fresh leftmost week
column, fill each active owner's **Rep Count** (pulled live from Tableau
ATTTRACKER-B2B / D2D1-PAGERV3, the "B2B One Pager V3"), recompute the Total (SUM
formula) and sort the active owners high->low.

Entry point: ``python -m automations.carlos_captainship_headcount.run``
"""
