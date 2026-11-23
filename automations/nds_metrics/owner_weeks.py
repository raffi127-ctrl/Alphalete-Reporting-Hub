"""Activation Rate by Week Ending for OTHER owners' offices.

Carlos 2026-11-23: "Make me an activation rate by week ending for Khalil
Colten Jairo and Rafael and send to me only on slack".

The same board and counting as the crew's 'NDS Activation Rate by Week
Ending (Tableau)' (activation_by_week.aggregate_tableau + render), for a
WHOLE office: every rep under the owner, no crew filter.

  * An NDS owner (Khalil Mansour, Colten Wright, Jairo Ruiz ...): the NDS-SN
    ORDERLOG export nds_metrics pulls every morning (run.pull: 60-day
    window, every owner on it). Wireless lines by sp.Order Date week;
    activated = Posted or Disconnected; cancelled = Canceled, never posted.
  * An owner who is NOT on that export falls back to the D2D 'A.Order Log'
    (fiber_metrics.pull). Rafael Hidalgo's office (11280) has no NDS code
    (not one of the 67 owners on the 11/15 NDS export) but sells wireless
    phones on its AT&T codes (Carlos 2026-11-23: "Rafael sells wireless
    phones so you should be able to see phones on his order log as well"):
    his WIRELESS lines by order-date week, the same count as the NDS
    boards; fiber / video / voice lines stay out. Posted or Disconnected =
    activated.

One summary picture first (an office-total row per owner, a column per
week ending), then one board per owner with a row per rep. Nothing is
sent without --dm, and --dm sends to those Slack ids only, never a
channel.

    lucy rerun nds_metrics_probe --owner-weeks "Khalil Mansour;Colten Wright;Jairo Ruiz;Rafael Hidalgo"
    lucy rerun nds_metrics_probe --owner-weeks "..." --dm U046G04P5LG
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.nds_metrics import activation_by_week as AW
from automations.nds_metrics.run import OUT_DIR, Cols, _c

LOOKBACK_DAYS = 60          # both pulls' windows (run.pull / fiber_metrics.pull)


def _tokens(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(s or "").lower())


def owner_name(label: str) -> str:
    """'KHALIL MANSOUR\\r [alphalete management group, inc. dba hab]' ->
    'KHALIL MANSOUR' (the Owner & Office cell, business name dropped)."""
    return " ".join(str(label or "").split("[")[0].split())


def match_owner(query: str, labels: Sequence[str]) -> List[str]:
    """The owner labels whose OWNER NAME holds every token of `query`, in any
    order ('Jairo Ruiz' -> 'JAIRO RUIZ\\r [profits management, inc.]')."""
    q = _tokens(query)
    if not q:
        return []
    return sorted({lab for lab in labels
                   if all(t in _tokens(owner_name(lab)) for t in q)})


def collapse_measures(cols: Cols, data: list, log=print) -> list:
    """The NDS-SN export is long-format: every line twice, once per measure
    (Unit Count / Sales (All)). Keep one measure, as load_crew does."""
    i_mn = cols.find("measure names")
    if i_mn is None:
        return data
    measures = sorted({str(r[i_mn]).strip() for r in data if len(r) > i_mn})
    keep = next((m for m in measures if "unit count" in m.lower()),
                measures[0] if measures else "")
    out = [r for r in data if len(r) > i_mn and str(r[i_mn]).strip() == keep]
    log("[owner-weeks] long-format export: kept measure %r (%d -> %d)"
        % (keep, len(data), len(out)))
    return out


def load_export(rows: list, log=print) -> Tuple[Cols, list, int]:
    """Parsed export rows -> (Cols, line rows, owner column index). The
    header is the first row with a Rep column."""
    hdr_i = next(i for i, r in enumerate(rows)
                 if any(str(c).strip().lower() == "rep" for c in r))
    cols = Cols(rows[hdr_i])
    data = [r for r in rows[hdr_i + 1:] if any(str(c).strip() for c in r)]
    data = collapse_measures(cols, data, log=log)
    i_owner = cols.need("owner", "owner name", "owner & office", "owner")
    return cols, data, i_owner


def office_rows(cols: Cols, data: list, i_owner: int, query: str) -> Tuple[list, List[str]]:
    """-> (the owner's line rows, the owner labels matched)."""
    labels = sorted({str(r[i_owner]).strip() for r in data if len(r) > i_owner})
    hit = set(match_owner(query, labels))
    rows = [r for r in data if len(r) > i_owner and str(r[i_owner]).strip() in hit]
    return rows, sorted(hit)


def _counts(cols: Cols, rows: list, *names) -> str:
    i = cols.find(*names)
    if i is None:
        return "n/a"
    c = collections.Counter(_c(cols, r, i) or "(blank)" for r in rows)
    return ", ".join("%s=%d" % kv for kv in c.most_common(8))


class Office:
    """One owner's board inputs: the aggregate plus how it was read."""

    def __init__(self, query: str, label: str, campaign: str, weeks, data,
                 pulled_at=None):
        self.query = query
        self.label = label             # 'Khalil Mansour'
        self.campaign = campaign       # 'NDS' | 'D2D'
        self.weeks = weeks
        self.data = data
        self.pulled_at = pulled_at


def _pretty(label: str) -> str:
    return " ".join(w.capitalize() for w in owner_name(label).split())


def read_offices(queries: Sequence[str], today: dt.date, log=print,
                 nds_path: Optional[Path] = None, d2d_path: Optional[Path] = None
                 ) -> Tuple[List[Office], List[str]]:
    """-> (offices in the asked order, queries found on neither export)."""
    from automations.office_metrics import nds_orderlog as NO
    since = today - dt.timedelta(days=LOOKBACK_DAYS)
    if nds_path is None:
        from automations.nds_metrics.run import pull
        nds_path = pull(today, log=log)
    ncols, ndata, n_owner = load_export(NO._read_csv(nds_path), log=log)
    n_pulled = dt.datetime.fromtimestamp(Path(nds_path).stat().st_mtime)
    log("[owner-weeks] NDS-SN export %s: %d line(s), %d owner(s)"
        % (Path(nds_path).name, len(ndata),
           len({str(r[n_owner]).strip() for r in ndata if len(r) > n_owner})))
    found: Dict[str, Office] = {}
    missing = []
    for q in queries:
        rows, hit = office_rows(ncols, ndata, n_owner, q)
        if len(hit) > 1:
            log("[owner-weeks] %r matches %d NDS owners (%s) -- add the last name"
                % (q, len(hit), " | ".join(owner_name(h) for h in hit)))
            missing.append(q)
            continue
        if not rows:
            missing.append(q)
            continue
        log("[owner-weeks] %s -> %s: %d line(s); products: %s; status: %s"
            % (q, owner_name(hit[0]), len(rows),
               _counts(ncols, rows, "product type (broken out)", "product type"),
               _counts(ncols, rows, "dtr status", "spe.status")))
        weeks, data = AW.aggregate_tableau(ncols, rows, today, since=since)
        found[q] = Office(q, _pretty(hit[0]), "NDS", weeks, data, n_pulled)
    fallback = [q for q in missing]
    missing = []
    if fallback:
        log("[owner-weeks] not on the NDS export: %s -> trying the D2D order log"
            % ", ".join(fallback))
        from automations.commission_sheet.sources import read_crosstab
        if d2d_path is None:
            from automations.fiber_metrics.run import pull as d2d_pull
            d2d_path = d2d_pull(today, log=log)
        dcols, ddata, d_owner = load_export(read_crosstab(Path(d2d_path)), log=log)
        d_pulled = dt.datetime.fromtimestamp(Path(d2d_path).stat().st_mtime)
        log("[owner-weeks] D2D export %s: %d line(s); header: %s"
            % (Path(d2d_path).name, len(ddata), " | ".join(dcols.header)[:900]))
        for q in fallback:
            rows, hit = office_rows(dcols, ddata, d_owner, q)
            if len(hit) != 1 or not rows:
                log("[owner-weeks] %r: %s on the D2D log either"
                    % (q, ("%d owners match (%s)" % (len(hit), " | ".join(owner_name(h) for h in hit)))
                       if hit else "no owner"))
                missing.append(q)
                continue
            log("[owner-weeks] %s -> %s (D2D): %d line(s); products: %s; status: %s"
                % (q, owner_name(hit[0]), len(rows),
                   _counts(dcols, rows, "product type (broken out)", "product type", "product"),
                   _counts(dcols, rows, "dtr status", "spe.status")))
            weeks, data = AW.aggregate_tableau(dcols, rows, today, since=since)
            found[q] = Office(q, _pretty(hit[0]), "D2D", weeks, data, d_pulled)
    for q in missing:
        log("[owner-weeks] %r: NOT FOUND on either export -- left off" % q)
    return [found[q] for q in queries if q in found], missing


# ---------------------------------------------------------------- render ----

def _sub(o: Office, today: dt.date) -> str:
    what = ("wireless lines off the Tableau NDS-SN order log"
            if o.campaign == "NDS" else
            "wireless lines (phones, tablets, watches) off the Tableau D2D order log -- "
            "his own AT&T codes, no NDS code; fiber / video lines left out")
    return ("%s's whole office — %s (of the sales made each Mon–Sun week: "
            "activated/sold %s; activated = Posted or Disconnected; cancels count as sold; "
            "* = week in progress; export pulled %s)"
            % (o.label, today.strftime("%B %d, %Y"), what,
               o.pulled_at.strftime("%m/%d %H:%M") if o.pulled_at else "n/a"))


def board_name(o: Office) -> str:
    """'NDS Activation Rate by Week Ending' / 'Wireless Activation Rate by
    Week Ending' (a D2D office's phones)."""
    return "%s Activation Rate by Week Ending" % ("NDS" if o.campaign == "NDS" else "Wireless")


def owner_png(o: Office, today: dt.date, out_dir: Path = OUT_DIR) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", o.label.lower()).strip("_")
    out = out_dir / ("owner_weeks_%s.png" % slug)
    return AW.render(o.weeks, o.data, out, today=today,
                     title="%s — %s" % (o.label.upper(), board_name(o).upper()),
                     sub=_sub(o, today), total_label="Office Total",
                     active_reps_only=True)


def summary_weeks(offices: Sequence[Office], weeks: int = AW.WEEKS) -> List[dt.date]:
    return sorted({we for o in offices for we in o.weeks})[-weeks:]


def summary_png(offices: Sequence[Office], today: dt.date, out_dir: Path = OUT_DIR) -> Path:
    """One row per owner (office total), one column per week ending."""
    from automations.b2b_metrics.rep_boards import render_table_png
    weeks = summary_weeks(offices)
    this_we = AW.week_ending(today)
    columns = ["WE %s%s" % (we.strftime("%-m/%-d"), "*" if we >= this_we else "")
               for we in weeks]
    col_of = dict(zip(weeks, columns))
    rows = []
    for o in offices:
        rows.append((o.label, "", False, AW.cells_for(o.data.get(AW.TOTAL, {}), weeks,
                                                      col_of, today)))
    d2d = [o.label.split()[0] for o in offices if o.campaign != "NDS"]
    sub = ("Whole offices — %s (of the sales made each Mon–Sun week: activated/sold "
           "wireless lines + rate off Tableau's NDS-SN order log%s; activated = Posted or "
           "Disconnected; cancels count as sold; * = week in progress)"
           % (today.strftime("%B %d, %Y"),
              ("; %s's off the D2D order log (his own AT&T codes)" % " & ".join(d2d))
              if d2d else ""))
    return render_table_png("ACTIVATION RATE BY WEEK ENDING — OWNERS", sub, columns,
                            rows, out_dir / "owner_weeks_summary.png")


def log_office(o: Office, today: dt.date, log=print) -> None:
    log("[owner-weeks] == %s (%s) ==" % (o.label, o.campaign))
    if o.weeks:
        AW.log_rows(AW.rows_from(o.weeks, o.data, today), log=log)
    reps = [k for k in o.data if k != AW.TOTAL
            and any((o.data[k].get(we) or {}).get("lines") for we in o.weeks)]
    log("[owner-weeks] %s: %d rep(s) with a line in the weeks shown" % (o.label, len(reps)))


# ------------------------------------------------------------------ main ----

def run(queries: Sequence[str], dm: Optional[str] = None, log=print,
        today: Optional[dt.date] = None) -> int:
    today = today or dt.date.today()
    offices, missing = read_offices(queries, today, log=log)
    if not offices:
        log("[owner-weeks] nobody found -- nothing built")
        return 1
    for o in offices:
        log_office(o, today, log=log)
    shots = [("summary", summary_png(offices, today))]
    for o in offices:
        if not o.weeks:
            log("[owner-weeks] %s: no lines in the window -- no board" % o.label)
            continue
        shots.append((o.label, owner_png(o, today)))
    for name, path in shots:
        log("[owner-weeks] built %s -> %s" % (name, path))
    if not dm:
        log("[owner-weeks] no --dm: built only, nothing sent")
        return 0
    from automations.shared import slack_metrics_post as smp
    stamp = today.strftime("%B %d, %Y")
    names = ", ".join(o.label.split()[0] for o in offices)
    for name, path in shots:
        if name == "summary":
            comment = ("\U0001F4C6 *Activation Rate by Week Ending — %s* — %s\nSource: Tableau"
                       % (names, stamp))
            if missing:
                comment += "\n(not found on Tableau: %s)" % ", ".join(missing)
        else:
            o = next(x for x in offices if x.label == name)
            comment = ("\U0001F4C6 *%s — %s*\nSource: Tableau" % (o.label, board_name(o)))
        for user in [u.strip() for u in str(dm).split(",") if u.strip()]:
            smp.dm_user_with_file(Path(path), user=user, file_name=Path(path).name,
                                  comment=comment)
        log("[owner-weeks] DM'd %s to %s" % (name, dm))
    return 0


def entry(args: Sequence[str]) -> int:
    """probe.py's --owner-weeks "A;B;C" [--dm U...]."""
    args = list(args)
    i = args.index("--owner-weeks")
    words = []                      # every word up to the next flag, so an
    for a in args[i + 1:]:          # unquoted "Khalil Mansour;Colten ..." works too
        if a.startswith("--"):
            break
        words.append(a.strip("'\""))
    raw = " ".join(words)
    queries = [q.strip() for q in re.split(r"[;,]", raw) if q.strip()]
    if not queries:
        print("[owner-weeks] usage: --owner-weeks \"Khalil Mansour;Colten Wright\" [--dm U...]")
        return 2
    dm = None
    if "--dm" in args:
        j = args.index("--dm")
        dm = args[j + 1] if j + 1 < len(args) else None
    return run(queries, dm=dm, log=lambda m: print(m, flush=True))
