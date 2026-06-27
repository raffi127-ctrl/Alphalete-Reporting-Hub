"""Residential Rep Count report.

Robert Archey (rarchey@thesmartcircle.com) emails "Residential Rep Counts WE
M/D" weekly on Thursday night to alphaletereporting@gmail.com, with an .xlsx
attachment. We read the attachment's `ICD Headcount (by Campaign)` tab and fill
each ICD's `Unique Headcount` into the matching Saturday week column on the
`Rep Count 24-26` tab of the "Alphalete Org/Captainship Reports" sheet, then
recompute the TOTAL row + the Org Ongoing Data block.

Pull EARLY FRIDAY AM so the Thursday-night email has landed.
"""
