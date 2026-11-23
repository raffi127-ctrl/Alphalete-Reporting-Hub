"""How many signed packets carry a date of birth that cannot be true?

    python -m automations.blueink_docs.dob_audit

READ-ONLY. It lists bundles and their field data and prints names with the
bad date -- no Socials, no addresses, nothing written anywhere.

WHY IT EXISTS. On 2026-11-23, 11 of 116 packets (about one in ten) had a
date of birth in 2026: the I-9's date picker opens on today, so a signer
who sets month and day but not the year saves the current one, and one who
does not touch it saves the signing date. The field is mapped correctly --
other people's read real birth years off the very same field -- so this
measures a data-entry trap, not a bug of ours.

Re-run it after Blue Ink changes the field, to see whether it worked.
`resources/applicantstream-asks.md` carries the ask.
"""
import datetime as dt
import sys
from automations.blueink_docs import blueink as B
from automations.apex_new_starts.blueink_data import _impossible_dob

DOB_KEY = "dat010-QaqD0"
bundles = []
for page in range(1, 5):
    rows = B._results(B._request("GET", "/bundles/",
                                 params={"page": page, "per_page": 50})) or []
    if not rows:
        break
    bundles += rows
print("looked at %d bundles" % len(bundles))

bad, good, none = [], 0, 0
for b in bundles:
    bid = b.get("id")
    if not bid:
        continue
    try:
        data = B._request("GET", "/bundles/%s/data/" % bid) or []
    except Exception:
        continue
    who = ""
    for p in (b.get("packets") or []):
        who = p.get("name") or who
    hit = None
    for f in data:
        if str(f.get("field_key")) == DOB_KEY:
            hit = str(f.get("value") or "").strip()
    if not hit:
        none += 1
        continue
    why = _impossible_dob(hit)
    if why:
        bad.append((who or bid, hit))
    else:
        good += 1

print("usable birth dates : %d" % good)
print("no DOB field       : %d" % none)
print("IMPOSSIBLE         : %d" % len(bad))
for who, val in bad:
    print("   %-26s %s" % (who[:26], val))
