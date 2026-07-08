"""Raf Captainship Bonus — weekly fill of the "Captainship Bonuses" tab in the
*Alphalete Org/Captainship Reports* sheet (the workbook Raf calls his
"all-in-one local office").

Automates the weekly Loom: insert a fresh leftmost week column (cloning last
week's formulas), fill each active rep's **Total Activations** for Raf's team
(pulled live from Tableau ATTTRACKER2_1-D2D / CaptainsBonus, "CB Activations
(Raf)"), fill the team's New Internet 60-day Churn % and Activation %
(Rolling 4 Weeks) from "CB Appr + Churn (Raf)", let the Total Sales / Money
Made / TOTAL MONEY MADE formulas recompute, re-point the performance chart's
series at the Total Sales row, and export the 4-week + chart view to a PDF.

Entry point: ``python -m automations.raf_captainship_bonus.run``
"""
