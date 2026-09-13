"""Only Carlos's and Atef's offices text applicants; every other office flags."""
import sys
sys.path.insert(0, "/Users/carloshidalgo/recruiting-report")
from automations.applicant_push import offices

TEXTING = {"11580"}  # Atef's texting OFF 9/12 (Carlos)
for oid, row in offices.OFFICES.items():
    got = bool(row.get("allow_retext", False))
    want = oid in TEXTING
    assert got == want, f"office {oid} allow_retext={got}, expected {want}"

# Khalil joined the LIVE rotation 9/8 and still must NEVER text (Carlos, 9/8:
# "texting should still be off for him") — pinned so a later edit can't drift.
assert offices.OFFICES["11901"].get("allow_retext") is False
# A row that forgets the key must default to NOT texting, never inherit.
assert offices.OFFICES["19592"].get("allow_retext") is False
assert bool({}.get("allow_retext", False)) is False
print("ok: only 11580 texts; unstated defaults to off")

# 2026-09-13, Carlos: "No one should be getting removed for no contact info."
# Every office, both flavors, forever — and the run.py branches are dead-coded.
for _oid, _row in offices.OFFICES.items():
    assert _row.get("remove_no_phone") is False, _oid
    assert _row.get("remove_blocked_read") is False, _oid
print("ok: no-contact removals banned for every office")
