"""select_product: the 2026-08-30 expanded-view change.

Shapes here are the REAL ones, read off a live --probe-columns run that morning
(rerun-2026-08-30-103628 for ALLTEAMSEXP, -105021 for the old ALLTEAMWireless),
not invented — the whole reason att_churn broke is that the export moved and the
code was guessing about it.
"""
import sys
import tempfile
from pathlib import Path

from automations.att_order_log import churn_shape as cs

EXPANDED_HDR = ["Owner & Office", "Rep",
                "Product Type (Broken Out) (BYOD/Non BYOD)",
                "30-60 Color Churn (copy)", "",
                "0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]

def _row(owner, rep, prod, measure="Activated SPE/SP", v="5"):
    return [owner, rep, prod, "Red", measure, v, v, v, v, v]

EXPANDED = [EXPANDED_HDR,
            _row("Grand Total", "Total", "Total"),
            _row("CARLOS HIDALGO [alphalete]", "Hamid Asim", "BYOD WIRELESS"),
            _row("CARLOS HIDALGO [alphalete]", "Hamid Asim", "NON BYOD WIRELESS"),
            _row("CARLOS HIDALGO [alphalete]", "Hamid Asim", "AIR/AWB"),
            _row("CARLOS HIDALGO [alphalete]", "Hamid Asim", "NEW INTERNET"),
            _row("CARLOS HIDALGO [alphalete]", "Hamid Asim", "Total"),
            _row("ATEF CHOUDHURY [domin8]", "Olivia Dittmer", "BYOD WIRELESS")]

ok = True
def check(label, got, want):
    global ok
    good = got == want
    ok &= good
    print(("  ok   " if good else "  FAIL ") + label
          + ("" if good else "\n         got {!r}\n         want {!r}".format(got, want)))

def test_wireless_takes_both_halves():
    out = cs.select_product(EXPANDED, cs.PRODUCT_TYPES["wireless"])
    check("wireless keeps BYOD + NON BYOD (and nothing else)", len(out) - 1, 3)
    check("product column is dropped", out[0], [h for h in EXPANDED_HDR
                                                if h != cs.PRODUCT_COL])
    check("no Total roll-up survives",
          any("TOTAL" == str(c).upper() for r in out[1:] for c in r), False)

def test_single_product_families():
    for key, n in (("air", 1), ("new_int", 1)):
        out = cs.select_product(EXPANDED, cs.PRODUCT_TYPES[key])
        check("{} selects exactly its own rows".format(key), len(out) - 1, n)

def test_a_per_product_view_is_untouched():
    # The old ALLTEAMWireless shape has no product column at all.
    legacy = [["Owner & Office", "Rep", "30-60 Color Churn (copy)", "",
               "0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"],
              ["CARLOS HIDALGO [x]", "Hamid Asim", "Red", "Churn Rate",
               "1", "2", "3", "4", "5"]]
    check("no product column -> returned as-is",
          cs.select_product(legacy, cs.PRODUCT_TYPES["wireless"]), legacy)

def test_renamed_product_values_fail_loud():
    moved = [EXPANDED_HDR, _row("CARLOS HIDALGO [x]", "A", "WIRELESS-BYOD")]
    try:
        cs.select_product(moved, cs.PRODUCT_TYPES["wireless"])
        check("a renamed product value RAISES", "no raise", "ValueError")
    except ValueError as e:
        check("a renamed product value RAISES", "WIRELESS-BYOD" in str(e), True)

def test_adapt_end_to_end_gives_the_d2d_shape():
    with tempfile.TemporaryDirectory() as d:
        src, dest = Path(d) / "raw.csv", Path(d) / "adapted.csv"
        cs.write_crosstab(EXPANDED, src)
        info = cs.adapt(src, dest, keep=cs.PRODUCT_TYPES["wireless"])
        hdr = cs.read_crosstab(dest)[0]
        check("adapt renames Rep -> Rep Name", "Rep Name" in hdr, True)
        check("adapt drops the product column", cs.PRODUCT_COL in hdr, False)
        check("periods survive", info["periods"],
              ["0-30 Day Churn", "30 Day Churn", "60 Day Churn", "90 Day Churn"])
        check("owner normalized to the bare name",
              "CARLOS HIDALGO" in info["owners"], True)

for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
    print(fn.__name__)
    fn()
print("all green" if ok else "FAILURES")
sys.exit(0 if ok else 1)
