"""DD without captainship -> iMessage "Knocking Chat A-Players".

Ask (Rafael, #l10 thread + 1-min video, 2026-10-14): "In our A-players chat,
can we get an automated message from Lucy on what the direct deposit is not
counting the captainship money." In the video he opens Tableau DD BY REP
(cl.DD Week 10/10/2026, owner Rafael Hidalgo): Grand Total to ICD $115,093.50,
of which the REP.Name = Null block's "Captain Bonus" is $21,039.50 -> he wants
the $94,054.00 left over texted to the room once the DD posts (Tue night).

Source: Tableau DirectDepositICDVIEWVersion2_0 > DDDETAILORG > "ORG DD Detail"
crosstab (the same download pulls.dd_captain_overrides uses). Per owner, newest
cl.DD Week: sum of Total $ to ICD = the DD; rows matching 'Captain('s) Bonus' =
the captainship money. LUCY 1 only (Raf's Tableau login sees the whole org, and
it is the machine whose Messages app texts the room).

Sends ONCE per DD week (lock file). Does nothing while Tableau still shows last
week's DD, so the Wednesday run waits and Thursday's catches a late post.

  python -m automations.dd_no_captain.run              # dry run: prints the text
  python -m automations.dd_no_captain.run --send       # really texts the room
  python -m automations.dd_no_captain.run --csv FILE   # parse a saved crosstab
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from automations.override_bulletin import pulls  # noqa: E402

TEXT_GROUP = "Knocking Chat A-Players"
# Whose DD goes in the text. Raf asked for his own; another captain = one more name.
OWNERS = ["Rafael Hidalgo"]

OUT_DIR = REPO / "output" / "dd_no_captain"
STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "dd_no_captain_sent.json")


def _parse_week(s):
    try:
        return dt.datetime.strptime(str(s).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def split_dd(rows, owner):
    """(dd_week, total, captain) for `owner`'s newest DD week, or None.

    total   = every Total $ to ICD row of that owner + week (= Grand Total to ICD
              on DD BY REP), captain = the Captain('s) Bonus rows among them.
    Subtotal / Grand Total rows carry 'Total' in the DD Week cell, so the date
    parse drops them and nothing is counted twice."""
    if not rows:
        return None
    hdr = rows[0]
    oc = pulls._hdr_col(hdr, "cl.ICD Owner Name")
    wc = pulls._hdr_col(hdr, "cl.DD Week")
    tc = pulls._hdr_col(hdr, "Total $ to ICD")
    if None in (oc, wc, tc):
        raise SystemExit("DD Detail crosstab is missing a column "
                         "(cl.ICD Owner Name / cl.DD Week / Total $ to ICD): %r" % hdr)
    want = pulls._norm_name(owner)
    weeks = {}
    for r in rows[1:]:
        if len(r) <= max(oc, wc, tc) or pulls._norm_name(r[oc]) != want:
            continue
        wk = _parse_week(r[wc])
        if wk is None:
            continue
        amt = pulls._num_locale(r[tc]) or 0.0
        e = weeks.setdefault(wk, {"total": 0.0, "cap": 0.0})
        e["total"] += amt
        if any(pulls._CAP_RE.search(str(c)) for c in r):
            e["cap"] += amt
    if not weeks:
        return None
    wk = max(weeks)
    return wk, round(weeks[wk]["total"], 2), round(weeks[wk]["cap"], 2)


def is_current(dd_week, today=None):
    """True once Tableau shows the DD for the week that just ended. cl.DD Week
    is the SATURDAY (10/10) of the week that ended Sunday 10/11."""
    from automations.override_bulletin.dd_data import week_just_ended
    return dd_week >= week_just_ended(today) - dt.timedelta(days=1)


def _money(v):
    return "${:,.2f}".format(v)


def build_text(owner, dd_week, total, cap):
    return "\n".join([
        "%s - DD for week ending %d/%d" % (owner, dd_week.month, dd_week.day),
        "Total DD: %s" % _money(total),
        "Captainship (Captain Bonus): -%s" % _money(cap),
        "DD without captainship: %s" % _money(total - cap),
    ])


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="really text the room (default: dry run)")
    ap.add_argument("--csv", help="parse this saved crosstab instead of downloading")
    ap.add_argument("--force", action="store_true",
                    help="send even if this DD week was already sent")
    a = ap.parse_args(argv)

    if a.csv:
        path = Path(a.csv)
    else:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "org_dd_detail.csv"
        download_crosstab_patchright(pulls.DD_DETAIL_VIEW, pulls.DD_DETAIL_SHEET, path)
    rows = pulls.read_crosstab(path)
    print("source: Tableau > DirectDepositICDVIEWVersion2_0 > DDDETAILORG > "
          "'%s' (%d rows, %s)" % (pulls.DD_DETAIL_SHEET, len(rows) - 1, path))

    state = _load_state()
    texts = []
    for owner in OWNERS:
        got = split_dd(rows, owner)
        if not got:
            print("%s: no DD rows in the download - nothing to send" % owner)
            continue
        wk, total, cap = got
        key = "%s|%s" % (owner, wk.isoformat())
        print("%s: DD week %s  total %s  captain %s  without %s"
              % (owner, wk, _money(total), _money(cap), _money(total - cap)))
        if not is_current(wk):
            print("  newest DD week is %s - this week's DD is not posted yet; "
                  "waiting for the next run" % wk)
            continue
        if key in state and not a.force:
            print("  already texted %s - skipping" % state[key])
            continue
        texts.append((key, build_text(owner, wk, total, cap)))

    if not texts:
        return 0
    from automations.alphalete_sales_board.notify import text_group
    for key, body in texts:
        print("-" * 40 + "\n" + body + "\n" + "-" * 40)
        text_group(TEXT_GROUP, body, dry_run=not a.send)
        if a.send:
            state[key] = dt.datetime.now().replace(microsecond=0).isoformat()
            _save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
