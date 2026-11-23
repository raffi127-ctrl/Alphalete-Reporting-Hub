"""Wireless churn by owner -- ICD totals in Tableau's churn buckets.

Carlos 2026-11-23, right after the owners' activation summary ("I like this
one. Add me to it"): "And then do the same table for wireless churn. Include
airs and BYODs. Just the table that shows ICD totals 0-30 day 31 day 60 day
90 day Churn What tableau churn reports look at".

ONE picture: a row per owner (the whole office, every rep), a column per
Tableau churn bucket -- 0-30 Day = activated 0-30 days ago, 30 Day = 31-60,
60 Day = 61-90, 90 Day = 91-120 (the 'Churn Buckets' the order log and the
CHURNRATES views use) -- each cell disconnected/activated + churn %.

Counting = the NDS CHURN report's All Orders row (nds_churn.compute.box_class
+ rep_churn): distinct lines ACTIVATED (Posted, or Disconnected -- it was
active first) by their posted date; non-BYOD phones + BYOD phones + Internet
Air; no upgrades, tablets, watches or fiber Internet; churned = Disconnected.
Smart Circle's own CHURNRATES view counts port phone lines only and has no
Air, so these can run a little off it by design ("Include airs and BYODs").

Source: the NDS-SN ORDERLOG export (every NDS owner); an owner with no NDS
code (Rafael Hidalgo, 11280) comes off the D2D 'A.Order Log' by the same
rules. Both pulled with a 150-day ORDER-date window so a line activated up to
120 days ago (the 90 Day bucket) is on it.

    lucy rerun nds_metrics_probe --owner-churn "Carlos Hidalgo;Khalil Mansour;Colten Wright;Jairo Ruiz;Rafael Hidalgo" [--dm U046G04P5LG]

Run it on LUCY 1: Lucy 2's Tableau login sees only 5 NDS owners. Nothing is
sent without --dm, and --dm goes to those Slack ids only.
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.nds_metrics import owner_weeks as OW
from automations.nds_metrics.run import OUT_DIR

LOOKBACK_DAYS = 150
BUCKETS = (("0-30 Day", 0, 30), ("30 Day", 31, 60), ("60 Day", 61, 90), ("90 Day", 91, 120))
CLASSES = ("wireless", "byod", "air")          # the churn report's All Orders row
# A 150-day D2D crosstab never renders in Tableau (2026-11-23: the viz timed
# out at 120s, twice). Today's 60-day pull (fiber_metrics.pull, cached) plus
# these two older order-date chunks (days back, from -> to) cover the same
# window, each smaller than the 60 days that work.
D2D_CHUNKS = ((105, 61), (150, 106))
# A bucket is only shown when the order window reaches this far past its
# oldest activation (installs and shipments lag the sale) -- a shorter pull
# leaves it blank ("n/a"), never undercounted.
ACTIVATION_LAG_DAYS = 15


def office_churn(header: Sequence[str], rows: list, today: dt.date
                 ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, Dict[str, int]]]]:
    """-> (ICD total {bucket: {'act', 'disc'}}, per class {cls: {bucket: ...}})
    for one owner's order-log rows."""
    from automations.nds_churn import compute as NCC
    lines = NCC.records_from_rows(list(header), rows)
    rc = NCC.rep_churn(lines, today, buckets=BUCKETS)
    total = {b: {"act": 0, "disc": 0} for b, _lo, _hi in BUCKETS}
    per_cls = {}
    for cls in CLASSES:
        d = rc.get((cls, NCC.TOTAL)) or {}
        per_cls[cls] = d
        for b, _lo, _hi in BUCKETS:
            c = d.get(b) or {}
            total[b]["act"] += c.get("act", 0)
            total[b]["disc"] += c.get("disc", 0)
    return total, per_cls


class OfficeChurn:
    def __init__(self, label: str, source: str, total: dict, per_cls: dict, lines: int,
                 covered: int = LOOKBACK_DAYS):
        self.label = label
        self.source = source          # 'NDS' | 'D2D'
        self.total = total
        self.per_cls = per_cls
        self.lines = lines
        self.covered = covered        # days of order dates the export reached


def pull_d2d_long(today: dt.date, log=print) -> Tuple[List[Path], int]:
    """-> (D2D crosstab paths, days of order dates covered): today's 60-day
    pull + the D2D_CHUNKS before it. A chunk that fails stops the walk back;
    the coverage is what did come back."""
    from automations.fiber_metrics.run import OUT_DIR as FOUT, pull as d2d_pull
    from automations.shared.tableau_patchright import download_crosstab_patchright
    from automations.uploaded import order_log as _ol
    paths, covered = [d2d_pull(today, log=log)], 60
    for back_from, back_to in D2D_CHUNKS:
        start = today - dt.timedelta(days=back_from)
        end = today - dt.timedelta(days=back_to)
        out = FOUT / ("d2d_orderlog_%s_%s.csv" % (start.isoformat(), end.isoformat()))
        try:
            if not (out.exists() and out.stat().st_size > 1000):
                url = _ol.ALLREPS_VIEW_URL_TMPL.format(start=start.isoformat(),
                                                       end=end.isoformat())
                download_crosstab_patchright(url, _ol.CROSSTAB_SHEET, out)
            paths.append(out)
            covered = back_from
            log("[owner-churn] D2D chunk %s..%s: %s bytes" % (start, end, format(out.stat().st_size, ",")))
        except Exception as e:  # noqa: BLE001 -- the shorter window still counts
            log("[owner-churn] D2D chunk %s..%s FAILED (%s: %s) -- covered %d days"
                % (start, end, type(e).__name__, str(e)[:120], covered))
            break
    return paths, covered


def load_merged(paths: Sequence[Path], log=print):
    """Several crosstabs of the same view -> one (Cols, rows, owner index),
    columns lined up by header name."""
    from automations.commission_sheet.sources import read_crosstab
    cols = data = i_owner = None
    for p in paths:
        c, d, io = OW.load_export(read_crosstab(Path(p)), log=log)
        if cols is None:
            cols, data, i_owner = c, list(d), io
            continue
        if c.header == cols.header:
            data.extend(d)
            continue
        idx = [c.header.index(h) if h in c.header else None for h in cols.header]
        data.extend([[(r[i] if i is not None and i < len(r) else "") for i in idx] for r in d])
    return cols, data, i_owner


def read_offices(queries: Sequence[str], today: dt.date, log=print,
                 nds_path: Optional[Path] = None, d2d_path: Optional[Path] = None
                 ) -> Tuple[List[OfficeChurn], List[str]]:
    """-> (offices in the asked order, queries found on neither export)."""
    from automations.office_metrics import nds_orderlog as NO
    if nds_path is None:
        from automations.nds_metrics.run import pull
        nds_path = pull(today, log=log, days=LOOKBACK_DAYS)
    ncols, ndata, n_owner = OW.load_export(NO._read_csv(nds_path), log=log)
    log("[owner-churn] NDS-SN export %s: %d line(s), %d owner(s)"
        % (Path(nds_path).name, len(ndata),
           len({str(r[n_owner]).strip() for r in ndata if len(r) > n_owner})))
    found: Dict[str, OfficeChurn] = {}
    fallback = []
    for q in queries:
        rows, hit = OW.office_rows(ncols, ndata, n_owner, q)
        if len(hit) != 1 or not rows:
            if len(hit) > 1:
                log("[owner-churn] %r matches %d NDS owners (%s)"
                    % (q, len(hit), " | ".join(OW.owner_name(h) for h in hit)))
            fallback.append(q)
            continue
        total, per_cls = office_churn(ncols.header, rows, today)
        found[q] = OfficeChurn(OW._label(q, hit[0]), "NDS", total, per_cls, len(rows))
    missing = []
    if fallback:
        log("[owner-churn] not on the NDS export: %s -> the D2D order log" % ", ".join(fallback))
        d_covered = LOOKBACK_DAYS
        try:
            if d2d_path is None:
                d2d_paths, d_covered = pull_d2d_long(today, log=log)
            else:
                d2d_paths = [d2d_path]
            dcols, ddata, d_owner = load_merged(d2d_paths, log=log)
        except Exception as e:  # noqa: BLE001 -- the NDS rows still go out
            log("[owner-churn] D2D log unavailable (%s: %s)" % (type(e).__name__, str(e)[:160]))
            dcols = ddata = d_owner = None
        for q in fallback:
            if dcols is None:
                missing.append(q)
                continue
            rows, hit = OW.office_rows(dcols, ddata, d_owner, q)
            if len(hit) != 1 or not rows:
                missing.append(q)
                continue
            total, per_cls = office_churn(dcols.header, rows, today)
            found[q] = OfficeChurn(OW._label(q, hit[0]), "D2D", total, per_cls, len(rows),
                                   covered=d_covered)
    for q in missing:
        log("[owner-churn] %r: NOT FOUND -- left off" % q)
    return [found[q] for q in queries if q in found], missing


def _band(rate: float) -> str:
    from automations.nds_metrics.run import _churn_band
    return _churn_band(rate)


def cells(total: dict, covered: int = LOOKBACK_DAYS) -> dict:
    out = {}
    for b, _lo, hi in BUCKETS:
        if hi + ACTIVATION_LAG_DAYS > covered:
            out[b] = {"rate": "n/a", "color": ""}       # the pull did not reach back far enough
            continue
        c = total.get(b) or {}
        if not c.get("act"):
            out[b] = {}
            continue
        rate = c["disc"] / c["act"]
        out[b] = {"act": str(c["act"]), "disc": str(c["disc"]),
                  "rate": "%s%%" % round(rate * 100, 1), "color": _band(rate)}
    return out


def summary_png(offices: Sequence[OfficeChurn], today: dt.date, out_dir: Path = OUT_DIR) -> Path:
    from automations.b2b_metrics.rep_boards import render_table_png
    columns = [b for b, _lo, _hi in BUCKETS]
    rows = [(o.label, "", False, cells(o.total, o.covered)) for o in offices]
    d2d = [o.label.split()[0] for o in offices if o.source != "NDS"]
    sub = ("ICD totals — %s (disconnected/activated lines by activation date: 0-30 Day = "
           "activated 0-30 days ago, 30 Day = 31-60, 60 Day = 61-90, 90 Day = 91-120; phones incl. "
           "BYODs + Internet Air; no upgrades, tablets, watches or fiber Internet; off Tableau's "
           "NDS-SN order log%s)"
           % (today.strftime("%B %d, %Y"),
              ("; %s's off the D2D order log (his own AT&T codes)" % " & ".join(d2d)) if d2d else ""))
    return render_table_png("WIRELESS CHURN — OWNERS (AIRS + BYODS INCLUDED)", sub,
                            columns, rows, out_dir / "owner_churn_summary.png")


def log_office(o: OfficeChurn, log=print) -> None:
    def fmt(d):
        return "  ".join("%s %d/%d" % (b, (d.get(b) or {}).get("disc", 0),
                                       (d.get(b) or {}).get("act", 0))
                         for b, _lo, _hi in BUCKETS)
    log("[owner-churn] %s (%s, %d line(s), %d days of orders): TOTAL %s"
        % (o.label, o.source, o.lines, o.covered, fmt(o.total)))
    for cls in CLASSES:
        log("[owner-churn]    %-8s %s" % (cls, fmt(o.per_cls.get(cls) or {})))


def tableau_check(offices: Sequence[OfficeChurn], today: dt.date, log=print) -> None:
    """Log Smart Circle's own CHURNRATES office totals (ChurnALlExp, every NDS
    owner's reps; port phone lines, no Air) next to ours without Air -- the
    proof the buckets line up with what the Tableau churn reports show."""
    from automations.office_metrics import nds_churn as NC
    path = OUT_DIR / ("nds_churn_view_all_%s.csv" % today.isoformat())
    try:
        if not (path.exists() and path.stat().st_size > 200):
            path.parent.mkdir(parents=True, exist_ok=True)
            NC._fetch(path, verbose=False)
    except Exception as e:  # noqa: BLE001 -- a check, never the board
        log("[owner-churn] tableau check: view unavailable (%s: %s)" % (type(e).__name__, str(e)[:120]))
        return
    periods = dict(zip((b for b, _lo, _hi in BUCKETS), ("0-30", "30", "60", "90")))
    for o in offices:
        if o.source != "NDS":
            continue
        NC._SLICE_OWNER = o.label
        try:
            tot = NC._parse(path)["office_total"]
        except Exception as e:  # noqa: BLE001
            log("[owner-churn] tableau check %s: %s" % (o.label, e))
            continue
        theirs = "  ".join("%s %d/%d" % (b, int((tot.get(pk) or {}).get("num") or 0),
                                         int((tot.get(pk) or {}).get("denom") or 0))
                           for b, pk in periods.items())
        ours = "  ".join("%s %d/%d" % (b, sum(((o.per_cls.get(c) or {}).get(b) or {}).get("disc", 0)
                                              for c in ("wireless", "byod")),
                                       sum(((o.per_cls.get(c) or {}).get(b) or {}).get("act", 0)
                                           for c in ("wireless", "byod")))
                         for b in periods)
        log("[owner-churn] tableau check %s: TABLEAU (ports) %s | OURS (phones, no Air) %s"
            % (o.label, theirs or "no rows on the view", ours))


def run(queries: Sequence[str], dm: Optional[str] = None, log=print,
        today: Optional[dt.date] = None, check: bool = False) -> int:
    import os
    today = today or dt.date.today()
    offices, missing = read_offices(queries, today, log=log)
    if not offices:
        log("[owner-churn] nobody found -- nothing built")
        return 1
    for o in offices:
        log_office(o, log=log)
    if check:
        tableau_check(offices, today, log=log)
    path = summary_png(offices, today)
    log("[owner-churn] built %s" % path)
    if not dm:
        log("[owner-churn] no --dm: built only, nothing sent")
        return 0
    from automations.shared import slack_metrics_post as smp
    as_bot = bool(os.environ.get("SLACK_BOT_TOKEN")) or smp.BOT_TOKEN_PATH.exists()
    if not as_bot:
        log("[owner-churn] no Lucy bot token on this machine -- DM from the metrics token")
    comment = ("\U0001F43A *Wireless Churn — %s* — %s\nSource: Tableau"
               % (", ".join(o.label.split()[0] for o in offices), today.strftime("%B %d, %Y")))
    if missing:
        comment += "\n(not found on Tableau: %s)" % ", ".join(missing)
    for user in [u.strip() for u in str(dm).split(",") if u.strip()]:
        smp.dm_user_with_file(path, user=user, file_name=path.name, comment=comment,
                              as_bot=as_bot)
        log("[owner-churn] DM'd the churn summary to %s" % user)
    return 0


def entry(args: Sequence[str]) -> int:
    """probe.py's --owner-churn "A;B;C" [--dm U...]."""
    args = list(args)
    i = args.index("--owner-churn")
    words = []
    for a in args[i + 1:]:
        if a.startswith("--"):
            break
        words.append(a.strip("'\""))
    queries = [q.strip() for q in re.split(r"[;,]", " ".join(words)) if q.strip()]
    if not queries:
        print("[owner-churn] usage: --owner-churn \"Carlos Hidalgo;Khalil Mansour\" [--dm U...]")
        return 2
    dm = None
    if "--dm" in args:
        j = args.index("--dm")
        dm = args[j + 1] if j + 1 < len(args) else None
    return run(queries, dm=dm, log=lambda m: print(m, flush=True),
               check="--tableau-check" in args)
