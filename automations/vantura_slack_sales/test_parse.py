"""Regression tests for the Vantura Slack sales parser.

Every message body below is a REAL post from #alphalete-gp-sales (2026-07-17
through 07-23), trimmed of shout-outs. Each one broke, or nearly broke, an
earlier version of the parser, or was confirmed by Megan directly.

  python -m automations.vantura_slack_sales.test_parse
"""
from __future__ import annotations

import datetime as dt

from automations.vantura_slack_sales import parse as P

CDT = dt.timezone(dt.timedelta(hours=-5))


def _post(text, hh=18, mm=0, day=22, author="Rep"):
    return P.read_post("1.0", dt.datetime(2026, 7, day, hh, mm, tzinfo=CDT),
                       author, "U1", text)


def _tallied(text, campaign, **kw):
    """What one post contributes to the day's count. Not the same as
    PostRead.count, which is 0 for an unnumbered post — the day tally is what
    turns that into 1."""
    p = _post(text, **kw)
    rec = P.tally([p], p.sales_day, campaign)
    return p, (rec[p.author]["count"] if rec else 0)


CASES = [
    # (label, text, campaign, sales it contributes to the day)

    # --- Base: residential energy, door-to-door ---------------------------
    ("base numbered", "D2D :door::zap:\n\n1,390 kwh\n\nBase #1", "Base", 1),
    ("base three in one post",
     "2,528 kwh\n\nBase #1\n\nBase # 2\n\nBase # 3", "Base", 3),
    ("base no space no hash", "BASE1\nD2D :door::zap:\n\n1,000 kwh", "Base", 1),
    ("base cx counter", "D2D\n\nBase\n\nCX2\n\n2112 kwh", "Base", 2),
    ("base flag emoji", "D2D\n\n:us:BASE:us:\n\n1,560 KWH\n\n#1", "Base", 1),
    ("base no base word", "D2D\n\n1998 kwh\n\nCx2", "Base", 2),
    # Megan 2026-07-23: "this would be 1 Base sale"
    ("base cx hash", "D2D :door::zap:\n\n23591 Kwh\n\nBase Cx #1", "Base", 1),
    ("base address only",
     "Base :zap:\n\n220 PALOMINO DR\nSAGINAW, TX 76179", "Base", 1),

    # --- BOX: business energy ---------------------------------------------
    ("box numbered", "B2B :package::zap:\nBill Submitted :white_check_mark:\n\n"
     "BF 1\n\n36 month term\n5,304KWH\nCX 3\nBox #3", "BOX", 3),
    # Megan 2026-07-23: "this would be 1 box sale" — BF 2 but ONE sale, so BF
    # is a bill reference, NOT the counter. CX is the counter.
    ("box bf is not the counter",
     "B2B :package::zap:\nBill Submitted :white_check_mark:\n\nBF 2\n\n"
     "36 month term\n51,840 KWH\nCX 1", "BOX", 1),
    ("box two in one post", "B2B :package::zap:\nBill Submitted\n\nBF 3\n"
     "60 month term\n116,568 KWH\nCX 2\nBox #2\nBox #3", "BOX", 3),
    ("box header spelled out", "BOX \n\nCX 1\n\nBF 1\n\nTerms 36 months\n"
     "Annual Usage 111,660kWh", "BOX", 1),

    # --- B2B: AT&T lines and fiber ----------------------------------------
    # Megan 2026-07-23: "this would be 3 at&t sales" / "NL=At&t sale".
    ("att three lines", "B2B(consumer)\nAutopay yes\nWrap up text sent\n\n"
     "CX1\nNL 1\nNL 2\nNL3", "B2B", 3),
    ("att lines plus fiber", "B2B (Business)\nAuto Pay on\n\nCx 1\n\nNL 1\n"
     "NL 2\n\nNL 3\n\nNL 4\n\nNL 5\n\nCX 2\n\nFiber 1000 #6", "B2B", 6),
    ("att inseego counts", "B2B (Business)\nAuto Pay on\n\nCx 1\n\nNL 1\n"
     "NL 2\n\nNL 3\n\nInseego", "B2B", 4),
    ("att fiber only", "B2B (consumer)\nAuto pay :white_check_mark:\n\n"
     "Fiber 1g", "B2B", 1),
    ("att byod lines", "B2B (Business)\n\nCx 1\n\nNL 1 (BYOD)\n\nNL 2 (BYOD)\n\n"
     "NL 3 (BYOD)\n\nNL 4 (BYOD)", "B2B", 4),

    # --- not sales at all --------------------------------------------------
    ("goals post", "Todays Goals:bangbang:\nA&T - 9/20\nBox - 7/8\nBase -4/15",
     None, 0),
    ("hype", "WHOSSS FIRST (BASE ):eyes:!!", None, 0),
    ("line up", "LINE UP", None, 0),
]


def test_cases():
    bad = []
    for label, text, want_campaign, want_count in CASES:
        p = _post(text)
        count = _tallied(text, want_campaign)[1] if want_campaign else 0
        if p.campaign != want_campaign or count != want_count:
            bad.append(f"{label}: got campaign={p.campaign} count={count}, "
                       f"want {want_campaign}/{want_count}")
    return bad


def test_running_counter():
    """Base/BOX numbers are cumulative for the day — max, never sum."""
    posts = [_post("D2D\n\n998 kWh\n\nBase\n\nCX1", hh=15),
             _post("D2D\n\n1998 kwh\n\nCx2", hh=16),
             _post("D2D\n\n1299kwh\n\nCx3", hh=16, mm=30)]
    got = P.tally(posts, dt.date(2026, 7, 22), "Base")["Rep"]["count"]
    return [] if got == 3 else [f"running counter: got {got}, want 3"]


def test_units_sum():
    """AT&T line numbering RESTARTS each post, so units sum. Jacob Ortega
    2026-07-22: NL1-5, then a Fiber, then another 'NL 1' = 7, and the board
    had him at 7. max() would have said 5."""
    posts = [_post("B2B (consumer)\n\nNL 1\nNL 2\nNL 3\nNL 4\nNL 5", hh=13),
             _post("B2B (consumer)\n\nFiber 1g", hh=13, mm=44),
             _post("B2B (business)\n\nNL 1", hh=17)]
    got = P.tally(posts, dt.date(2026, 7, 22), "B2B")["Rep"]["count"]
    return [] if got == 7 else [f"units sum: got {got}, want 7"]


def test_run_on_address():
    """'Cx210810 HERMOSA DR' is customer 2 at 10810, not customer 21."""
    _p, count = _tallied("*Base*:zap:\n\n*Cx1 1403 Rio hondo drive 75218*\n\n"
                         "*Cx210810 HERMOSA DR, DALLAS, TX 75218*", "Base")
    return [] if count == 2 else [f"run-on address: got {count}, want 2"]


def test_campaigns_dont_poach():
    """The three campaigns all quote kWh and/or CX — none may claim another's
    post."""
    bad = []
    box = _post("B2B :package::zap:\nBill Submitted\n\nBF 1\n36 month term\n"
                "45,000KWH\nCX 1\nBox #1")
    if box.campaign != "BOX":
        bad.append(f"BOX post read as {box.campaign}")
    base = _post("D2D :door::zap:\n\n2,226 KWH\n\nBase #1")
    if base.campaign != "Base":
        bad.append(f"Base post read as {base.campaign}")
    att = _post("B2B (Business)\nWrap Text sent\nAuto Pay on\n\nCx 1\nNL 1")
    if att.campaign != "B2B":
        bad.append(f"AT&T post read as {att.campaign}")
    return bad


def test_day_rollover():
    """Late-night posts stay on their own day; 'YESTERDAY' moves one back."""
    bad = []
    late = _post("D2D\n\n1000 kwh\n\nBase #1", hh=22, day=22)
    if late.sales_day != dt.date(2026, 7, 22):
        bad.append(f"22:00 post landed on {late.sales_day}")
    early = _post("D2D\n\n1000 kwh\n\nBase #1", hh=2, day=23)
    if early.sales_day != dt.date(2026, 7, 22):
        bad.append(f"02:00 post landed on {early.sales_day}")
    tagged = _post("B2B :package::zap:\nYESTERDAY\n\nBill Submitted\nBF 1\n"
                   "36 month term\n32,568KWH\nCX 1\nBox #1", hh=8, day=23)
    if tagged.sales_day != dt.date(2026, 7, 22):
        bad.append(f"YESTERDAY post landed on {tagged.sales_day}")
    return bad


def test_fill_only_raises():
    """The fill raises a number, never lowers one (Megan 2026-07-23): sales
    reach the board by routes that aren't the channel, and those stand."""
    from automations.vantura_slack_sales import run as R

    # Minimal grid: row 4 day headers, row 5 a Base rep, row 6 the totals
    # anchor so campaign_rows() stops there.
    def grid(cell_value):
        g = [[""] * 12 for _ in range(6)]
        g[3][1], g[3][4] = "REP", "Monday"
        g[4][1], g[4][4], g[4][11] = "Some Rep", cell_value, "Base"
        g[5][1] = R.TOTALS_TOP
        return g

    bad = []
    for on_board, count, want in [("2", 5, [("2", "5")]),   # higher -> raise
                                  ("5", 2, []),             # lower  -> keep
                                  ("5", 5, []),             # equal  -> no-op
                                  ("", 3, [("(blank)", "3")]),
                                  ("0", 3, [("0", "3")]),
                                  ("X", 1, [("X", "1")])]:  # marker -> replace
        g = grid(on_board)
        res = {"col": 5, "rows": {"some rep": 5},
               "matched": {"some rep": {"count": count, "posts": [],
                                        "flags": []}}}
        got = [(p[2], p[3]) for p in R.fill_plan(g, res)]
        if got != want:
            bad.append(f"fill_plan board={on_board!r} count={count}: "
                       f"got {got}, want {want}")
    return bad


def main() -> int:
    checks = [test_cases, test_running_counter, test_units_sum,
              test_run_on_address, test_campaigns_dont_poach, test_day_rollover,
              test_fill_only_raises]
    bad = [b for chk in checks for b in chk()]
    for b in bad:
        print("FAIL", b)
    total = len(CASES) + 13
    print(f"{total - len(bad)}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
