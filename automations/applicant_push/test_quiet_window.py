"""Fri 1pm → Sun 1pm is quiet for live pushes."""
def q(wd, hr): return (wd == 4 and hr >= 13) or wd == 5 or (wd == 6 and hr < 13)
assert not q(4, 12)   # Friday morning: on
assert q(4, 13)       # Friday 1pm: off
assert q(5, 9)        # Saturday: off
assert q(6, 12)       # Sunday morning: off
assert not q(6, 13)   # Sunday 1pm: back on
assert not q(0, 9)    # Monday: on
print("ok: quiet window Fri13->Sun13")
