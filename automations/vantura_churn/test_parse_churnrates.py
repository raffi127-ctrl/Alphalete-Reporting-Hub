"""parse_churnrates against the product-broken-out CHURNRATES export.

Geometry is the real one, from a live --probe-columns of ALLTEAMCHURN on
2026-08-30: Owner & Office | Product Type | 30-60 Color Churn | <measure> |
0-30 Day | 30 | 60 | 90 | 120. The 0-30 reading lands in exactly ONE colour
block per owner/product and is blank in the others.
"""
import sys
import tempfile
from pathlib import Path

from automations.vantura_churn import pull

HDR = ["Owner & Office", pull.PRODUCT_COL, "30-60 Color Churn (copy)", "",
       "0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]

def row(owner, prod, colour, measure, v030):
    return [owner, prod, colour, measure, v030, "", "", "", ""]

def block(owner, prod, activated, disc):
    """One product's rows: the real reading in Red, blanks in the other bands."""
    return [row(owner, prod, "Red", "Activated SPE/SP", activated),
            row(owner, prod, "Red", "Disconnect count (SPE/SP)", disc),
            row(owner, prod, "Green", "Activated SPE/SP", ""),
            row(owner, prod, "Green", "Disconnect count (SPE/SP)", "")]

OWNER = "CARLOS HIDALGO [alphalete specialized marketing inc(tx]"
GRID = ([HDR]
        + block("Grand Total", "Total", "19084", "814")
        + block(OWNER, "AIR/AWB", "27", "3")
        + block(OWNER, "BYOD WIRELESS", "182", "14")
        + block(OWNER, "NON BYOD WIRELESS", "185", "9")
        + block(OWNER, "NEW INTERNET", "23", "1")
        # the owner's own roll-up — must never be added to its parts
        + block(OWNER, "Total", "417", "27"))

ok = True
def check(label, got, want):
    global ok
    good = got == want
    ok &= good
    print(("  ok   " if good else "  FAIL ") + label
          + ("" if good else "  got {!r} want {!r}".format(got, want)))

def _parse(grid, owner="CARLOS HIDALGO"):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "cr.csv"
        # encoding="utf-16" so Python writes the BOM _load_grid expects,
        # exactly like a real Tableau crosstab download.
        with open(f, "w", encoding="utf-16", newline="") as fh:
            import csv
            csv.writer(fh, delimiter="\t").writerows(grid)
        return pull.parse_churnrates(f, owner)

def test_base_sums_the_products_not_the_rollup():
    got = _parse(GRID)
    check("base = 27+182+185+23 (roll-up excluded)", got["base"], 417)

def test_rate_is_derived_not_a_single_bucket():
    got = _parse(GRID)
    check("disc/base = 27/417", round(got["rate"], 6), round(27 / 417, 6))

def test_the_old_last_wins_bug_is_gone():
    # Pre-fix this returned NEW INTERNET's 23 — the last product block.
    check("base is not the last product bucket", _parse(GRID)["base"] != 23, True)

def test_a_view_without_the_breakout_still_works():
    legacy_hdr = ["Owner & Office", "30-60 Color Churn (copy)", "",
                  "0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]
    grid = [legacy_hdr,
            [OWNER, "Red", "Activated SPE/SP", "401", "", "", "", ""],
            [OWNER, "Red", "Disconnect count (SPE/SP)", "27", "", "", "", ""]]
    got = _parse(grid)
    check("no product column -> base reads straight through", got["base"], 401)
    check("no product column -> rate still derived",
          round(got["rate"], 6), round(27 / 401, 6))

def test_unknown_owner_still_raises():
    try:
        _parse(GRID, owner="NOBODY AT ALL")
        check("an owner with no rows RAISES", "no raise", "RuntimeError")
    except RuntimeError:
        check("an owner with no rows RAISES", True, True)

for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
    print(fn.__name__)
    fn()
print("all green" if ok else "FAILURES")
sys.exit(0 if ok else 1)
