"""Show-up rate by WHO BOOKED IT, and what moved.

Megan 2026-10-01: "also need to analise retention from people / ai - what's
changing".

This is the analysis that explained Tuesday 2026-09-29. Office 11280 ran 30%
first-round retention against 45% the day before, with the same volume. Pull
was up, delivery was clean (1.7% failures, zero dead links), reminders went
out. Split by booker it was one line:

    A. Messaging (the AI)   Mon 52%  ->  Tue 26%   on 103 of the day's 200
    every human booker      flat or better

The AI books half the day, so its show rate IS the office's show rate. A
whole-office number can halve without a single human doing anything
differently, and nothing in a daily total tells you that.

So: rate per booker per period, each against their OWN trailing average,
because bookers differ from each other permanently and only a change is
news. A booker who always runs 30% is not a problem to raise on Tuesday.

  python -m automations.sms_audit.retention --office 11280
  ... retention.py --office 11280 --by day
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.sms_audit import analyze as A

OUTPUT = Path(__file__).resolve().parents[2] / "output"
WEEKS = ["w0821", "w0828", "w0904", "w0911", "w0918", "w0925"]
# A booker needs this many in a period before a swing means anything. Five
# bookings at 20% is one person's bad morning, not a trend.
MIN_N = 10
# How far it has to fall below its own trailing average to be called out.
DROP = 12.0


def shown(r):
    return bool(r.get("status") and "No Show" not in r["status"])


def load(office, weeks=None, extra=()):
    """[(period, booker, shown)] from the weekly pulls plus any extra files."""
    rows, seen_src = [], set()
    for tag in (weeks or WEEKS):
        recs, src = A.load_office(office, tag)
        # load_office falls back to the UNSUFFIXED file when a week's pull is
        # missing, so an office with one week of data reported six identical
        # weeks and looked flat. Identical is not the same as unchanged: a
        # source already counted is a week we do not have.
        if src in seen_src:
            continue
        seen_src.add(src)
        for r in recs or []:
            rows.append((tag, r.get("date", ""),
                         r.get("booked_by") or "(not recorded)", shown(r)))
    for path in extra:
        p = Path(path)
        if not p.exists():
            continue
        for r in json.loads(p.read_text(encoding="utf-8")):
            rows.append(("recent", r.get("date", ""),
                         r.get("booked_by") or "(not recorded)", shown(r)))
    return rows


def table(rows, by="week"):
    """{period: {booker: (booked, showed)}} in period order."""
    out = collections.OrderedDict()
    key = (lambda w, d: w) if by == "week" else (lambda w, d: d)
    for w, d, who, ok in rows:
        k = key(w, d)
        if not k:
            continue
        out.setdefault(k, collections.Counter())
        out[k][(who, "n")] += 1
        out[k][(who, "s")] += ok
    def sortkey(k):
        try:
            return (0, dt.datetime.strptime(k, "%m-%d-%Y"))
        except ValueError:
            return (1, k)
    return collections.OrderedDict(sorted(out.items(), key=lambda kv: sortkey(kv[0])))


def changes(tab):
    """What moved: each booker's latest period against its own trailing
    average. Returns [(booker, latest_rate, trailing, n)] worst first."""
    periods = list(tab)
    if len(periods) < 2:
        return []
    latest = periods[-1]
    bookers = {b for p in tab for (b, k) in tab[p] if k == "n"}
    out = []
    for b in bookers:
        n = tab[latest][(b, "n")]
        if n < MIN_N:
            continue
        rate = 100.0 * tab[latest][(b, "s")] / n
        prior_n = sum(tab[p][(b, "n")] for p in periods[:-1])
        prior_s = sum(tab[p][(b, "s")] for p in periods[:-1])
        if prior_n < MIN_N:
            continue
        trailing = 100.0 * prior_s / prior_n
        out.append((b, rate, trailing, n))
    return sorted(out, key=lambda x: x[1] - x[2])


def is_ai(booker):
    return "messaging" in (booker or "").lower()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280")
    ap.add_argument("--by", choices=["week", "day"], default="week")
    ap.add_argument("--extra", default="",
                    help="comma list of extra booking json files")
    a = ap.parse_args(argv)
    extra = [x.strip() for x in a.extra.split(",") if x.strip()]
    rows = load(a.office, extra=extra)
    if not rows:
        print("[retention] nothing on disk for {}".format(a.office))
        return 1
    tab = table(rows, a.by)

    print("[retention] {} — show rate by who booked, per {}".format(
        a.office, a.by))
    bookers = sorted({b for p in tab for (b, k) in tab[p] if k == "n"},
                     key=lambda b: -sum(tab[p][(b, "n")] for p in tab))
    head = "{:<22}".format("booker") + "".join(
        "{:>11}".format(str(p)[:10]) for p in tab)
    print(head)
    for b in bookers:
        line = "{:<22}".format(b[:22])
        for p in tab:
            n = tab[p][(b, "n")]
            line += "{:>11}".format(
                "{:.0f}% /{}".format(100.0 * tab[p][(b, "s")] / n, n)
                if n else "-")
        print(line)

    # AI against everyone else — the split that explained 2026-09-29
    print("\n{:<22}".format("AI vs people"), end="")
    for p in tab:
        ai = [(b, k) for (b, k) in tab[p] if is_ai(b)]
        an = sum(tab[p][(b, "n")] for b, k in ai if k == "n")
        a_s = sum(tab[p][(b, "s")] for b, k in ai if k == "s")
        hn = sum(v for (b, k), v in tab[p].items() if k == "n" and not is_ai(b))
        hs = sum(v for (b, k), v in tab[p].items() if k == "s" and not is_ai(b))
        print("{:>11}".format("{:.0f}/{:.0f}".format(
            100.0 * a_s / an if an else 0, 100.0 * hs / hn if hn else 0)),
            end="")
    print("   (AI% / people%)")

    moved = changes(tab)
    if moved:
        print("\nWHAT MOVED in the latest {} (own trailing average):".format(a.by))
        for b, rate, trail, n in moved:
            d = rate - trail
            flag = "  <-- DOWN {:.0f} POINTS".format(-d) if d <= -DROP else ""
            print("   {:<22} {:>5.0f}%  was {:>5.0f}%  on {:>4}{}".format(
                b[:22], rate, trail, n, flag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
