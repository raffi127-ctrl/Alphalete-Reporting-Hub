"""NDS week-over-week board: every rep, every stat, last week next to the week
before, with the change (Carlos 2026-11-02: "something that shows a week over
week comparison for each person / each stat").

Reads the two weekly_knock_dispositions boards' row dumps (the .json next to
each PNG; rendered dry if missing) and draws one table: a cell reads
"prev → last (Δ)". Green = better, red = worse. "Better" is higher for every
column except gaps and first knock (lower is better there).

    python -m automations.nds_oof.run --compare 2026-10-31 --week-thread 'NDS Metrics' --send
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOWER_IS_BETTER = ("gap", "first knock")
GREEN = (74, 222, 128)
RED = (252, 165, 165)
NEUTRAL = None


def _log(msg: str) -> None:
    print("[nds-wow] %s" % msg, flush=True)


# --- parsing ------------------------------------------------------------------
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", re.I)
_DUR = re.compile(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?$", re.I)
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse(v) -> Tuple[Optional[str], Optional[float]]:
    """(kind, number) for a board cell: num / pct / dur (minutes) / clock
    (minutes since midnight) / (None, None) when it is not a number."""
    s = str(v or "").strip().replace(",", "")
    if not s or s in ("—", "-", "–", "n/a", "N/A"):
        return None, None
    if s.endswith("%") and _NUM.match(s[:-1].strip()):
        return "pct", float(s[:-1])
    if _NUM.match(s):
        return "num", float(s)
    m = _CLOCK.match(s)
    if m:
        h, mi, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3).upper()
        return "clock", float(h * 60 + mi + (720 if ap == "PM" else 0))
    m = _DUR.match(s)
    if m and (m.group(1) or m.group(2)):
        return "dur", float(int(m.group(1) or 0) * 60 + int(m.group(2) or 0))
    return None, None


def _fmt_num(x: float) -> str:
    return ("%d" % round(x)) if abs(x - round(x)) < 0.05 else ("%.1f" % x)


def fmt_delta(kind: str, d: float) -> str:
    sign = "+" if d > 0 else ("-" if d < 0 else "")
    a = abs(d)
    if kind == "pct":
        return "%s%s pts" % (sign, _fmt_num(a))
    if kind in ("dur", "clock"):
        h, m = divmod(int(round(a)), 60)
        return "%s%s" % (sign, ("%dh %02dm" % (h, m)) if h else ("%dm" % m))
    return "%s%s" % (sign, _fmt_num(a))


def better(header: str, d: float) -> Optional[bool]:
    """True = improved, False = worse, None = unchanged."""
    if abs(d) < 1e-9:
        return None
    low = any(k in header.lower() for k in LOWER_IS_BETTER)
    return (d < 0) if low else (d > 0)


# --- table ----------------------------------------------------------------------
def build(prev: Dict, last: Dict) -> Tuple[List[str], List[List[str]], Dict[Tuple[int, int], tuple], int]:
    """(header, rows, cell_bgs, n_totals_rows). Rows: totals first, then reps in
    last week's order, then reps who were on the board the week before but not
    last week."""
    hdr_l, hdr_p = list(last["headers"]), list(prev["headers"])
    rows_l, rows_p = last["rows"], prev["rows"]
    name_i = 1 if len(hdr_l) > 1 else 0
    stats = [(i, h) for i, h in enumerate(hdr_l) if i != name_i and i != 0 and h in hdr_p]

    def _blank(v) -> bool:
        return str(v or "").strip() in ("", "—", "-", "–", "n/a", "N/A")
    # A column that is empty for everyone in BOTH weeks (Apps on an NDS board)
    # is noise on a 20-column picture: dropped.
    stats = [(i, h) for i, h in stats
             if any(not _blank(r[i]) for r in rows_l if i < len(r))
             or any(not _blank(r[hdr_p.index(h)]) for r in rows_p if hdr_p.index(h) < len(r))]
    pidx = {h: hdr_p.index(h) for _, h in stats}

    def key(r):
        return re.sub(r"\s+", " ", str(r[name_i] if len(r) > name_i else "")).strip().lower()
    prev_by = {key(r): r for r in rows_p if len(r) > name_i}
    header = ["Rep"] + [h for _, h in stats]
    out: List[List[str]] = []
    bgs: Dict[Tuple[int, int], tuple] = {}
    totals_label = "office totals"
    ordered = sorted(rows_l, key=lambda r: 0 if key(r) == totals_label else 1)
    seen = set()
    for r in ordered:
        k = key(r)
        if not k:
            continue
        seen.add(k)
        pr = prev_by.get(k)
        line = [str(r[name_i])]
        for ci, (li, h) in enumerate(stats, start=1):
            lv = str(r[li]).strip() if li < len(r) else ""
            pv = str(pr[pidx[h]]).strip() if pr is not None and pidx[h] < len(pr) else ""
            kl, nl = parse(lv)
            kp, np_ = parse(pv)
            if pr is None:
                line.append("new → %s" % (lv or "—"))
                continue
            if kl and kp and kl == kp:
                d = nl - np_
                cell = "%s → %s  (%s)" % (pv, lv, fmt_delta(kl, d))
                b = better(h, d)
                if b is True:
                    bgs[(len(out), ci)] = GREEN
                elif b is False:
                    bgs[(len(out), ci)] = RED
            else:
                cell = "%s → %s" % (pv or "—", lv or "—")
            line.append(cell)
        out.append(line)
    for r in rows_p:
        k = key(r)
        if k and k not in seen:
            line = [str(r[name_i])]
            for li, h in stats:
                pv = str(r[pidx[h]]).strip() if pidx[h] < len(r) else ""
                line.append("%s → off board" % (pv or "—"))
            out.append(line)
    n_tot = 1 if out and re.sub(r"\s+", " ", out[0][0]).strip().lower() == totals_label else 0
    return header, out, bgs, n_tot


# --- data + render ------------------------------------------------------------
def _json_path(saturday: dt.date) -> Path:
    from automations.nds_oof import config as C
    from automations.weekly_knock_dispositions import run as W
    return (Path(W.OUT_DIR) / W._slug(C.WEEK_ROW_KEY)
            / ("weekly_knock_dispositions_%s.json" % saturday.isoformat()))


def ensure_rows(saturday: dt.date) -> Dict:
    """The week's row dump; renders the board dry (Ownerville pull) when the
    json is missing or predates the row dump."""
    from automations.nds_oof import config as C
    from automations.weekly_knock_dispositions import run as W
    p = _json_path(saturday)
    data = json.loads(p.read_text()) if p.exists() else {}
    if not data.get("rows"):
        _log("rendering %s dry to get its rows" % saturday.isoformat())
        rc = W.main(["--office", C.WEEK_ROW_KEY, saturday.isoformat(), "--dry-run"])
        if rc:
            raise RuntimeError("weekly_knock_dispositions returned %s for %s" % (rc, saturday))
        data = json.loads(p.read_text())
        if not data.get("rows"):
            raise RuntimeError("no rows in %s" % p)
    return data


def title_for(prev_sat: dt.date, last_sat: dt.date) -> str:
    from automations.nds_oof import config as C
    pm, lm = prev_sat - dt.timedelta(days=5), last_sat - dt.timedelta(days=5)
    return "%s Week over Week — %s–%s vs %s–%s" % (
        C.TEAM, pm.strftime("%-m/%-d"), prev_sat.strftime("%-m/%-d"),
        lm.strftime("%-m/%-d"), last_sat.strftime("%-m/%-d"))


def render(last_sat: dt.date, out_dir: Optional[Path] = None) -> Tuple[Path, str]:
    from automations.total_knocks import render as KR
    from automations.weekly_knock_dispositions import board as B
    prev_sat = last_sat - dt.timedelta(days=7)
    prev, last = ensure_rows(prev_sat), ensure_rows(last_sat)
    header, rows, bgs, n_tot = build(prev, last)
    title = title_for(prev_sat, last_sat)
    out_dir = out_dir or _json_path(last_sat).parent
    out = out_dir / ("nds_week_over_week_%s.png" % last_sat.isoformat())
    KR._draw(header, rows, title, B.THEME_PLUM, out, name_col=0,
             wrap_headers=True, highlight_first_row=n_tot,
             top_row_colors=[B.THEME_PLUM["header_bg"]] * n_tot,
             cell_bgs=bgs)
    _log("rendered %s" % out)
    return out, title


def post(last_sat: dt.date, *, thread_prefix: str, send: bool) -> int:
    from automations.nds_oof import config as C
    from automations.shared import slack_metrics_post as smp
    png, title = render(last_sat)
    client = smp._client()
    today = dt.date.today()
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    hist = client.conversations_history(channel=C.SLACK_CHANNEL, oldest=str(oldest), limit=300)
    ts = next((m.get("thread_ts") or m.get("ts") for m in hist.get("messages", [])
               if (m.get("text") or "").replace("*", "").startswith(thread_prefix)), None)
    if not ts:
        _log("no thread today starting with %r" % thread_prefix)
        return 1
    try:
        reps = client.conversations_replies(channel=C.SLACK_CHANNEL, ts=ts, limit=200)
        if any((m.get("text") or "").replace("*", "").startswith(title)
               for m in reps.get("messages", [])[1:]):
            _log("%s already in today's %r thread -- not posting again" % (title, thread_prefix))
            return 0
    except Exception as e:  # noqa: BLE001
        _log("reply check failed (%s) -- posting anyway" % type(e).__name__)
    if not send:
        _log("DRY RUN -- would post %s into thread %s (%r)" % (png, ts, thread_prefix))
        return 0
    client.files_upload_v2(channel=C.SLACK_CHANNEL, file=str(png), filename=png.name,
                           initial_comment="*%s*" % title, thread_ts=ts)
    _log("posted %s into today's %r thread" % (title, thread_prefix))
    return 0
