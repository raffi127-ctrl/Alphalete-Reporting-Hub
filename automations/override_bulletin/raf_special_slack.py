"""Raf's Special Override, once a week in his Slack DM (Raf, 2026-11-06).

Ask: "For my special over ride for the att program, can I get a slack from
Lucy of what it is and what the last 4 weeks are? Once a week slack message
whenever it updates."

Source: Tableau `ResATTSpecialDealOverride-Raf` -> sheet `Payout- Raf wow`
(the same view the Override Bulletin reads his special from). Per Processed
Week it has four rows, found BY LABEL:
    New Fiber Estimate  -> picks the tier
    Override Estimate   -> the units he is paid on
    Raf Bonus Payout    -> $ per unit ($4 / $5 / $6)
    Raf Payout Total    -> Override Estimate x rate = his special
The tier table comes from the sibling sheet `Payouts Raf` (live, so a tier
change in Tableau shows up in the message without a code change).

"Whenever it updates": the agent checks every day; it posts ONLY when a week
newer than the last one sent shows up, so Raf gets one message per new week.

LUCY 1 (Raf's Tableau login; its Slack token posts as Lucy).

  python -m automations.override_bulletin.raf_special_slack           # dry: prints it
  python -m automations.override_bulletin.raf_special_slack --preview # DM to Eve only
  python -m automations.override_bulletin.raf_special_slack --send    # DM to Raf (new week only)

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RAF = "U045Z8N0ZQC"            # resources/owner-slack-ids.md
EVE = "U088E2KJEV8"            # preview goes ONLY here
TIER_SHEET = "Payouts Raf"
WEEKS_SHOWN = 4
OUT_DIR = REPO / "output" / "override_bulletin" / "raf_special_slack"
STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "raf_special_slack_sent.json")

LABELS = {
    "new fiber estimate": "fiber",
    "override estimate": "units",
    "raf bonus payout": "rate",
    "raf payout total": "total",
}
_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_TIER = re.compile(r"tier\s*(\d+)\s*:\s*\$?\s*([\d.]+)\s*\|\s*([\d,]+)", re.I)


def _num(s):
    from automations.override_bulletin.pulls import _num_locale
    return _num_locale(s)


def parse_weeks(rows) -> dict:
    """{date: {'fiber','units','rate','total'}} from a `Payout- Raf wow` crosstab.

    Week columns come from the row holding m/d/yyyy dates; values are read from
    the label rows at those same columns. No fixed row or column numbers."""
    cols = {}
    for r in rows[:8]:
        for i, c in enumerate(r):
            m = _DATE.match(str(c).strip())
            if m:
                cols[i] = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if cols:
            break
    out = {}
    for r in rows:
        key = None
        for c in r[:2]:
            key = LABELS.get(str(c).strip().lower())
            if key:
                break
        if not key:
            continue
        for i, day in cols.items():
            v = _num(r[i]) if i < len(r) else None
            if v is not None:
                out.setdefault(day, {})[key] = v
    return out


def parse_tiers(rows) -> list:
    """[(tier, rate, threshold)] from the `Payouts Raf` sheet, e.g.
    'Tier 2 : $5 | 2,800'. Empty list if the sheet changed shape."""
    out = []
    for r in rows:
        for c in r:
            m = _TIER.search(str(c))
            if m:
                out.append((int(m.group(1)), float(m.group(2)),
                            int(m.group(3).replace(",", ""))))
    return sorted(set(out))


def last_weeks(weeks: dict, n: int = WEEKS_SHOWN) -> list:
    """Newest `n` weeks that have a payout, oldest first."""
    done = sorted(d for d, v in weeks.items() if v.get("total") is not None)
    return [(d, weeks[d]) for d in done[-n:]]


def _money(x) -> str:
    return "$%s" % format(int(round(x)), ",")


def _md(d: dt.date) -> str:
    return "%d/%d" % (d.month, d.day)


def build_message(shown: list, tiers: list) -> str:
    newest = shown[-1][0]
    lines = [
        "*Your AT&T Special Override — WE %s is in*" % _md(newest),
        "",
        "*What it is:* every week you get paid a rate on the org's "
        "*Override Estimate*. The rate depends on the org's *New Fiber Estimate* "
        "that week:",
    ]
    if tiers:
        lines += ["• Tier %d: *$%g* per unit at %s+ New Fiber" % (t, rate, format(th, ","))
                  for t, rate, th in tiers]
    lines += ["", "*Last %d weeks:*" % len(shown)]
    rows = [("Week", "New Fiber", "Rate", "Override Est.", "Payout")]
    for d, v in shown:
        rows.append(("WE " + _md(d),
                     format(int(v.get("fiber") or 0), ","),
                     "$%g" % (v.get("rate") or 0),
                     format(int(v.get("units") or 0), ","),
                     _money(v["total"])))
    rows.append(("Total", "", "", "", _money(sum(v["total"] for _, v in shown))))
    w = [max(len(r[i]) for r in rows) for i in range(5)]
    table = ["  ".join(r[i].ljust(w[i]) if i == 0 else r[i].rjust(w[i])
                       for i in range(5)) for r in rows]
    table.insert(len(table) - 1, "-" * len(table[0]))
    lines += ["```"] + table + ["```"]
    if len(shown) >= 2:
        prev, cur = shown[-2][1]["total"], shown[-1][1]["total"]
        diff = cur - prev
        lines.append("vs last week: %s%s" % ("+" if diff >= 0 else "-", _money(abs(diff))))
    lines.append("_Source: Tableau → ResATTSpecialDealOverride-Raf → Payout- Raf wow._")
    return "\n".join(lines)


def _periods(today: dt.date) -> list:
    """Retail periods to read: last month's, this month's, next month's number.
    Retail periods don't line up with months (P11 held 10/11), so a window of
    three always covers the newest 4 weeks. Empty ones are skipped."""
    m = today.month
    return ["Period %d" % p for p in sorted({max(1, m - 1), m, min(13, m + 1)})]


def pull(today: dt.date, verbose=True):
    from automations.override_bulletin import pulls as P
    from automations.shared.tableau_patchright import tableau_session
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    weeks, tiers = {}, []
    with tableau_session(headless=True, verbose=verbose) as page:
        for period in _periods(today):
            out = OUT_DIR / ("wow_%s.csv" % period.replace(" ", "_"))
            try:
                got, used = P._download_first_nonempty(
                    P.RAF_BONUS_VIEW, P.RAF_BONUS_SHEET, out,
                    P.period_candidates(period), page=page, verbose=verbose,
                    accept=lambda rs: parse_weeks(rs) or None)
            except Exception as e:  # noqa: BLE001 -- an empty future period is normal
                print("  %s: nothing (%s)" % (period, type(e).__name__))
                continue
            print("  %s (%s): weeks %s" % (period, used,
                                           ", ".join(_md(d) for d in sorted(got or {}))))
            weeks.update(got or {})
            if not tiers and used:
                try:
                    tout = OUT_DIR / "tiers.csv"
                    from automations.shared.tableau_patchright import                         download_crosstab_patchright
                    download_crosstab_patchright(
                        P._with_filter(P.RAF_BONUS_VIEW, "Period", used),
                        TIER_SHEET, tout, page=page, verbose=verbose)
                    tiers = parse_tiers(P.read_crosstab(tout))
                except Exception as e:  # noqa: BLE001 -- message still goes, without tiers
                    print("  tier table: not read (%s)" % type(e).__name__)
    return weeks, tiers


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(d: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(d, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--send", action="store_true", help="DM Raf (only when a new week is in)")
    g.add_argument("--preview", action="store_true", help="DM Eve only, always")
    ap.add_argument("--force", action="store_true", help="--send even if this week went already")
    a = ap.parse_args(argv)

    try:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001
        today = dt.date.today()

    weeks, tiers = pull(today)
    shown = last_weeks(weeks)
    if not shown:
        print("no weeks with a Raf Payout Total -- nothing to send")
        return 1
    newest = shown[-1][0].isoformat()
    text = build_message(shown, tiers)
    print(text)

    if not (a.send or a.preview):
        print("\n(dry run -- nothing posted)")
        return 0
    state = _state()
    if a.send and not a.force and state.get("last_week") == newest:
        print("WE %s already sent to Raf on %s -- nothing to do"
              % (newest, state.get("sent_at")))
        return 0

    from automations.shared import slack_metrics_post as smp
    to = EVE if a.preview else RAF
    r = smp._client().chat_postMessage(channel=to, text=text)
    print("posted to %s: ok=%s ts=%s" % ("Eve (preview)" if a.preview else "Raf",
                                         r.get("ok"), r.get("ts")))
    if a.send:
        _save_state({"last_week": newest,
                     "sent_at": dt.datetime.now().isoformat(timespec="seconds"),
                     "ts": r.get("ts")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
