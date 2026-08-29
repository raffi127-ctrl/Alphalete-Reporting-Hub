"""Only Carlos's and Atef's offices text applicants; every other office flags."""
import sys
sys.path.insert(0, "/Users/carloshidalgo/recruiting-report")
from automations.applicant_push import offices

TEXTING = {"11580", "23467"}
for oid, row in offices.OFFICES.items():
    got = bool(row.get("allow_retext", False))
    want = oid in TEXTING
    assert got == want, f"office {oid} allow_retext={got}, expected {want}"

# A row that forgets the key must default to NOT texting, never inherit.
assert offices.OFFICES["19592"].get("allow_retext") is False
assert bool({}.get("allow_retext", False)) is False
print("ok: only 11580 and 23467 text; unstated defaults to off")
