"""READ-ONLY: print the row labels the Retention Report actually uses.

WHY THIS EXISTS. `config.LABEL_BOB` is the string we look for, and on
2026-11-17 and 11-18 it came back empty for all five owners -- every office,
every day read -- which tripped the safety stop and removed nobody. Two
explanations fit that equally well and they need opposite fixes:

  * the mark really is absent (nobody has BOB'd anyone), or
  * the row is worded differently from `LABEL_BOB`, so we have been asking
    for a row that does not exist.

Megan's screenshot of the SECOND INTERVIEWS page says "BOB - Booked", which
looks like the second explanation -- but that is a different page from the one
we read, and the two are allowed to word things differently. Guessing from the
screenshot would be exactly the "plausible story is not evidence" mistake
([[feedback_dont_explain_away_a_zero]]).

So this asks the page. It matches how `detail_href` finds a row -- the first
cell's text, which it compares with `startsWith` -- so what this prints is
what that comparison sees.

CHANGES NOTHING. One office, one page load, no writes, no contacts touched.

    PYTHONPATH=. .venv/bin/python -m automations.second_round_contacts.label_probe \\
        --office 11280
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.second_round_contacts import config as C


def row_labels(app) -> list:
    """Every row's first-cell text on the report as it stands, in order.

    `detail_href` finds a row with `norm(firstCell).startsWith(norm(label))`,
    so the first cell is the only text that matters and the comparison is
    whitespace-collapsed and lower-cased. Returned verbatim, because the
    POINT is to see the real spelling.
    """
    return app.page.evaluate(
        """() => {
            const seen = [];
            for (const tr of document.querySelectorAll('tr')) {
                const first = tr.querySelector('td,th');
                if (!first) continue;
                const text = (first.innerText || '').replace(/\\s+/g, ' ').trim();
                if (text) seen.push(text);
            }
            return seen;
        }"""
    )


def date_headers(app) -> list:
    """The column headers, so a missing DAY can be told from a missing ROW.

    The other way this read comes back empty: the row is right but the date
    column we ask for is not on the page at all. A forward-dated BOB column
    only exists if the report actually shows future days.
    """
    return app.page.evaluate(
        """() => {
            for (const tr of document.querySelectorAll('tr')) {
                const cells = [...tr.children].map(
                    c => (c.innerText || '').replace(/\\s+/g, ' ').trim());
                if (cells.filter(Boolean).length > 2
                    && cells.some(c => /\\d/.test(c))) return cells;
            }
            return [];
        }"""
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="11280",
                    help="ApplicantStream office id (default: Raf's, 11280)")
    args = ap.parse_args(argv)

    from automations.applicant_tracker.applicantstream import session

    with session() as app:
        owner = app.select_office(args.office)
        print("office %s -> %s" % (args.office, owner))
        # Exactly the page `read_lists` reads, opened the same way.
        app.open_retention_details()

        labels = row_labels(app)
        headers = date_headers(app)

    print("\n=== ROW LABELS on office %s ===" % args.office)
    for text in labels:
        print("   %r" % text)

    print("\n=== DATE HEADERS ===")
    print("   %s" % (headers or "(none found)"))

    print("\n=== WHAT WE ASK FOR ===")
    norm = lambda s: " ".join(str(s or "").split()).lower()   # noqa: E731
    have = [norm(t) for t in labels]
    for name in ("LABEL_SHOWED", "LABEL_OFFERED", "LABEL_BOB",
                 "LABEL_BOOKED", "LABEL_HELD", "LABEL_NS_SCHED",
                 "LABEL_NS_SHOWED"):
        want = getattr(C, name)
        hit = [t for t, n in zip(labels, have) if n.startswith(norm(want))]
        if hit:
            print("   OK       %-14s %r  ->  %r" % (name, want, hit[0]))
        else:
            # The one thing worth printing loudly: what we would have used
            # instead, so the fix is a string edit and not another probe.
            close = [t for t, n in zip(labels, have)
                     if any(w in n for w in norm(want).split() if len(w) > 3)]
            print("   MISSING  %-14s %r" % (name, want))
            for c in close[:4]:
                print("                           closest on the page: %r" % c)

    today = dt.date.today()
    print("\n(today is %s; a BOB is dated for the day somebody STARTS, so a "
          "future column is the one that matters)" % today.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
