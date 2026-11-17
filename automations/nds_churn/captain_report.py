"""NDS churn report for ONE owner in Khalil's captainship (Carlos
2026-11-17: "i want a nds churn report for each of khalils people in his
captainship. But we don't need to see the BYOD and air activations and
disconnects. we also need to see the 90 day churn").

The NDS CHURN tab remade as a picture per owner, NON-BYOD PORT PHONE LINES
ONLY (no BYOD, no Air, no Internet, no tablets / watches / upgrades --
compute.line_kind == 'port' and not compute.is_byod), with the 90 Day
churn bucket beside the 0-30 one -- the two numbers Smart Circle's
Captain's Bonus reads (Sean Balderrama, "NDS Captain's Bonus DD WE 11/15",
2026-11-17: quality bonus +$0.50/piece at 0-30 <= 3.00% / 90 Day <= 8.00%;
DNQ -- the whole captain bonus is $0 -- at 0-30 >= 5.00% / 90 Day >= 13.00%).

Buckets are Tableau's, by activation-date age (office_metrics.nds_orderlog
CHURN_BUCKETS): 0-30 Day = 0..30 days since posted, 30 Day = 31..60,
60 Day = 61..90, 90 Day = 91..120. A disconnected line stays in the bucket
its age puts it in, like Smart Circle's Churn Rates view. The export is the
same NDS-SN ORDERLOG nds_metrics pulls, but over a 140-day Order-Date window
(the daily pull's 60 days cannot see the 90 Day bucket), cached beside the
daily file so the 06:00 job is untouched.

Reconcile: Smart Circle's all-owners Churn Rates view (ChurnALlExp) sliced
to the owner counts ALL port phone lines (BYOD included), so the gate
compares our all-port 0-30 numbers against it -- disconnects exact, base
within nds_churn.run.BASE_TOLERANCE -- and prints the 90 Day comparison
beside it. A 0-30 mismatch sends nothing (--skip-reconcile overrides).

  python -m automations.nds_churn.run --captain zaid --dry-run     # compute, diag tab + picture to the control sheet
  python -m automations.nds_churn.run --captain zaid --dm U...,U... # picture DM'd (Lucy) to those users
  python -m automations.nds_churn.run --captain zaid --from-file export.csv --dry-run

Nothing here writes a Google Sheet tab of the Vantura board; the picture
is the report.
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import html
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.nds_churn import comp
from automations.nds_churn import compute as C

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "nds_churn"
LOOKBACK_DAYS = 140          # Order-Date window: the 90 Day bucket is posted 91-120 days ago

# Khalil's captainship (Sean Balderrama, "Captain Report - Khalil",
# 2026-11-16): key -> display name (the view's spelling), the upper-cased
# tokens the export's Owner & Office cell must carry ("ZAID ARABYAT [aces
# acquisitions, inc.]"), and the owner's Slack id (resources/owner-slack-ids.md).
OWNERS = {
    "atef":    {"name": "Atef Choudhury",  "tokens": ("ATEF", "CHOUDHURY"), "slack": ""},
    "carlos":  {"name": "Carlos Hidalgo",  "tokens": ("CARLOS", "HIDALGO"),  "slack": "U046G04P5LG"},
    "isaiah":  {"name": "Isaiah Revelle",  "tokens": ("ISAIAH", "REVELLE"),  "slack": ""},
    "juan":    {"name": "Juan Lucio",      "tokens": ("JUAN", "LUCIO"),      "slack": ""},
    "khalil":  {"name": "Khalil Mansour",  "tokens": ("KHALIL", "MANSOUR"),  "slack": "U045F9JCPJT"},
    "maxamad": {"name": "Maxamad Aden",    "tokens": ("MAX", "ADEN"),        "slack": ""},
    "zaid":    {"name": "Zaid Arabyat",    "tokens": ("ZAID", "ARAB"),       "slack": "U084AMNNA3D"},
}
CAPTAIN_SLACK = "U045F9JCPJT"            # Khalil
CARLOS_SLACK = "U046G04P5LG"

# Tableau's churn buckets by activation-date age (inclusive day ranges).
BUCKETS = (("0-30", 0, 30), ("30", 31, 60), ("60", 61, 90), ("90", 91, 120))
BUCKET_LABEL = {"0-30": "0-30 Day", "30": "30 Day", "60": "60 Day", "90": "90 Day"}
SHOWN = ("0-30", "90")                   # the two the report shows (Carlos 11/17)
BUCKET_SPAN = {k: (lo, hi) for k, lo, hi in BUCKETS}

# Captain's Bonus quality lines (Sean Balderrama 2026-11-17, "NDS Captain's
# Bonus DD WE 11/15"): (bonus at or under, DNQ at or over), in %.
CAPTAIN_LINES = {"0-30": (3.00, 5.00), "90": (8.00, 13.00)}
CAPTAIN_SOURCE = "NDS Captain's Bonus DD WE 11/15 (Smart Circle, 11/17/2026)"
SOW_BANDS = {"0-30": comp.NONBYOD_0_30, "90": comp.NONBYOD_90}

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "NDS Captain Diag"
SHOT_TAB = "NDS Captain Shot"            # base64 PNG, 45000-char cells, read from the mini
SHOT_CHUNK = 45000


# ------------------------------------------------------------------ pull ----

def _looks_like_csv(b: bytes) -> bool:
    """nds_metrics.run.pull's rule: no HTML, a comma header on line 1."""
    head = b[:4000].decode("utf-8-sig", errors="replace")
    low = head.lower()
    first = head.splitlines()[0] if head else ""
    return ("<html" not in low and "<!doctype" not in low
            and first.count(",") >= 5)


def pull_long(today: dt.date, log=print, days: int = LOOKBACK_DAYS) -> Path:
    """The NDS-SN ORDERLOG over `days` of Order Date, cached per day beside
    the daily 60-day file (its own name, so nds_metrics never reuses it)."""
    from automations.office_metrics import nds_orderlog as NO
    from automations.shared.tableau_patchright import tableau_session
    out = OUT_DIR / f"nds_orderlog_{days}d_{today.isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 500 and _looks_like_csv(out.read_bytes()):
        log(f"[captain] reusing today's {days}-day pull ({out.stat().st_size:,} bytes)")
        return out
    if out.exists():
        out.unlink()
    url = NO._orderlog_url(today - dt.timedelta(days=days), today)
    last = ""
    for attempt in (1, 2, 3):
        with tableau_session(verbose=False) as page:
            r = page.context.request.get(url, timeout=300_000)
            body = r.body() or b""
            ok = r.status == 200 and len(body) >= 500 and _looks_like_csv(body)
            log(f"[captain] OL csv ({days}d) status={r.status} bytes={len(body):,} "
                f"valid={ok} (try {attempt}/3)")
            if ok:
                out.write_bytes(body)
                return out
            last = f"status={r.status} bytes={len(body)}"
    raise RuntimeError(f"NDS ORDERLOG {days}-day export failed after 3 tries: {last}")


def export_owners(path: Path, ix: dict, log=print) -> List[Tuple[str, int]]:
    """Distinct Owner & Office cells in the export with their row counts
    (first line of the cell, upper-cased), most rows first -- to see whose
    data the Tableau login actually returns (2026-11-17: Zaid's dry run found
    0 lines; was it the spelling or the identity?)."""
    i_owner = ix.get("owner")
    if i_owner is None:
        return []
    cnt: collections.Counter = collections.Counter()
    for r in C.read_rows(path)[1:]:
        if len(r) > i_owner:
            cnt[str(r[i_owner]).strip().upper().splitlines()[0] if str(r[i_owner]).strip() else "(blank)"] += 1
    return cnt.most_common(60)


# --------------------------------------------------------------- compute ----

def is_nonbyod_port(ln: dict) -> bool:
    """The report's universe: a ported voice line on a financed / new phone."""
    return (ln.get("prod") == "Wireless" and C.line_kind(ln) == C.PORT
            and not ln.get("byod"))


def is_port(ln: dict) -> bool:
    """Every port phone line (BYOD too) -- what Smart Circle's view counts."""
    return ln.get("prod") == "Wireless" and C.line_kind(ln) == C.PORT


def bucket_of(posted: Optional[dt.date], today: dt.date) -> Optional[str]:
    if not posted or posted > today:
        return None
    age = (today - posted).days
    for key, lo, hi in BUCKETS:
        if lo <= age <= hi:
            return key
    return None


def bucket_units(lines: List[dict], today: dt.date, keep=is_nonbyod_port
                 ) -> Dict[str, List[dict]]:
    """Distinct activated lines per bucket (Posted or Disconnected, by
    posted-date age), `keep` deciding the universe."""
    seen = set()
    out: Dict[str, List[dict]] = {k: [] for k, _, _ in BUCKETS}
    for ln in lines:
        if not keep(ln) or ln["status"].lower() not in C.ACTIVATED:
            continue
        b = bucket_of(ln["posted"], today)
        if b is None:
            continue
        key = C._line_key(ln)
        if key in seen:
            continue
        seen.add(key)
        out[b].append(ln)
    return out


def _is_dead(ln: dict) -> bool:
    return ln["status"].lower() in C.DISCONNECTED


def counts(units: Dict[str, List[dict]]) -> Dict[str, dict]:
    """{bucket: {'act', 'disc', 'pct'}} (pct 0-100, None without activations)."""
    out = {}
    for b, us in units.items():
        act = len(us)
        disc = sum(1 for u in us if _is_dead(u))
        out[b] = {"act": act, "disc": disc, "pct": (100.0 * disc / act) if act else None}
    return out


def rep_counts(units: Dict[str, List[dict]]) -> Dict[str, Dict[str, dict]]:
    """{rep: {bucket: {'act', 'disc', 'pct'}}}."""
    per: Dict[str, Dict[str, List[dict]]] = collections.defaultdict(
        lambda: {k: [] for k, _, _ in BUCKETS})
    for b, us in units.items():
        for u in us:
            per[u["rep"] or "(no rep)"][b].append(u)
    return {rep: counts(d) for rep, d in per.items()}


def activation_rate(lines: List[dict], today: dt.date) -> Tuple[dict, Dict[str, dict]]:
    """Non-BYOD phone lines sold by Order-Date bucket (0-30 / 31-60):
    activated (Posted or Disconnected) / sold, office + per rep -- the
    NDS CHURN tab's rate on the All Wireless box row."""
    def _blank():
        return {b: {"activated": 0, "sold": 0, "rate": None} for b in C.BUCKETS}
    office = _blank()
    reps: Dict[str, dict] = {}
    seen = set()
    for ln in lines:
        if C.box_class(ln) != "wireless":
            continue
        od = ln["order_date"]
        if not od:
            continue
        age = (today - od).days
        bucket = "0-30" if 0 <= age <= 30 else "31-60" if 31 <= age <= 60 else None
        if bucket is None:
            continue
        key = C._line_key(ln)
        if key in seen:
            continue
        seen.add(key)
        act = ln["status"].lower() in C.ACTIVATED
        for slot in (office[bucket],
                     reps.setdefault(ln["rep"] or "(no rep)", _blank())[bucket]):
            slot["sold"] += 1
            if act:
                slot["activated"] += 1
    for d in [office] + list(reps.values()):
        for b in C.BUCKETS:
            s = d[b]
            s["rate"] = (s["activated"] / s["sold"]) if s["sold"] else None
    return office, reps


def pending(lines: List[dict], today: dt.date) -> int:
    """Non-BYOD phone lines sold in the last 30 days, not activated, not
    canceled (the box's All Wireless Pending)."""
    seen, n = set(), 0
    for ln in lines:
        if C.box_class(ln) != "wireless":
            continue
        od = ln["order_date"]
        if not od or not (0 <= (today - od).days <= C.WINDOW_DAYS):
            continue
        st = ln["status"].lower()
        if st in C.ACTIVATED or st in C.CANCELED:
            continue
        key = C._line_key(ln)
        if key in seen:
            continue
        seen.add(key)
        n += 1
    return n


def _groups(units: List[dict], today: dt.date, leave_days: int) -> List[dict]:
    """Disconnected lines of a bucket grouped per account (BAN, else
    customer), soonest to leave the bucket first. leave_days = the bucket's
    upper bound + 1 (a 0-30 line falls off the report at day 31; a 90 Day
    line leaves that bucket at day 121)."""
    groups: Dict[tuple, List[dict]] = collections.defaultdict(list)
    for u in units:
        if _is_dead(u):
            groups[(u["customer"], u["ban"])].append(u)

    def _posted(grp):
        return min(u["posted"] for u in grp)

    out = []
    for (customer, ban), grp in sorted(groups.items(),
                                       key=lambda kv: (_posted(kv[1]), kv[0][0])):
        posted = _posted(grp)
        leaves = posted + dt.timedelta(days=leave_days)
        out.append({
            "customer": customer, "ban": ban, "posted": posted,
            "leaves": leaves, "days_left": (leaves - today).days, "lines": len(grp),
            "rep": C._join_uniq(g["rep"] for g in grp),
            "order_date": min((g["order_date"] for g in grp if g["order_date"]), default=None),
            "disc_date": min((g["status_date_d"] for g in grp if g["status_date_d"]), default=None),
            "kind": C._join_uniq(f"{C.line_kind(g)} · {g['if_oof']}".strip(" ·") for g in grp),
            "device": C._join_uniq(g["device"] or g["package"] for g in grp),
            "ported_from": C._join_uniq(g.get("ported_from") or "" for g in grp),
        })
    return out


def pct_after(groups: List[dict], leaves: dt.date, base: int) -> Optional[float]:
    """What the bucket's churn reads once the groups leaving on `leaves` have
    gone: lines of groups leaving LATER / base (0-100)."""
    if not base:
        return None
    later = sum(g["lines"] for g in groups if g["leaves"] > leaves)
    return 100.0 * later / base


def build(lines: List[dict], today: dt.date) -> dict:
    """Everything the picture shows, non-BYOD port phones only, plus the
    all-port numbers the reconcile needs."""
    units = bucket_units(lines, today)
    box = counts(units)
    reps = rep_counts(units)
    office_rate, rep_rate = activation_rate(lines, today)
    tables = {}
    for b in SHOWN:
        lo, hi = BUCKET_SPAN[b]
        grps = _groups(units[b], today, hi + 1)
        rows = []
        for g in grps:
            rows.append({**g, "pct_after": pct_after(grps, g["leaves"], box[b]["act"])})
        tables[b] = rows
    all_port = counts(bucket_units(lines, today, keep=is_port))
    all_port_reps = rep_counts(bucket_units(lines, today, keep=is_port))
    return {"box": box, "reps": reps, "office_rate": office_rate, "rep_rate": rep_rate,
            "pending": pending(lines, today), "tables": tables,
            "all_port": all_port, "all_port_reps": all_port_reps}


def rep_order(reps: Dict[str, Dict[str, dict]]) -> List[str]:
    """Worst 0-30 churn first (ties: more disconnects, then the 90 Day rate),
    reps with nothing activated in 0-30 at the bottom (Carlos 11/14)."""
    def _k(name):
        r = reps[name]
        p30, p90 = r["0-30"]["pct"], r["90"]["pct"]
        return (0 if p30 is not None else 1, -(p30 or 0), -r["0-30"]["disc"],
                -(p90 or 0), name)
    return sorted(reps, key=_k)


# ------------------------------------------------------------- reconcile ----

def view_counts(owner_name: str, today: dt.date, log=print, fresh: bool = False
                ) -> Optional[dict]:
    """Smart Circle's Churn Rates view (ChurnALlExp, every NDS owner) sliced
    to this owner: per bucket {'disc', 'base'} summed over the reps, plus the
    per-rep detail. Same cached file as the daily job (the slice happens at
    parse time, so the file is shared)."""
    from automations.office_metrics import nds_churn as NC
    NC._SLICE_OWNER = owner_name
    out = OUT_DIR / f"nds_churn_view_{today.isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if fresh or not (out.exists() and out.stat().st_size > 200):
        NC._fetch(out, verbose=False)
    parsed = NC._parse(out)
    reps = parsed.get("reps") or {}
    if not reps:
        return None
    res: dict = {"reps": len(reps), "detail": {}}
    for b in ("0-30", "30", "60", "90"):
        num = denom = 0.0
        got = False
        for rep_name, slots in reps.items():
            s = slots.get(b) or {}
            if s.get("denom") is not None:
                denom += s["denom"]; got = True
            if s.get("num") is not None:
                num += s["num"]
            res["detail"].setdefault(rep_name, {})[b] = (s.get("num"), s.get("denom"), s.get("pct"))
        res[b] = {"disc": int(round(num)), "base": int(round(denom))} if got else None
    return res


def reconcile(owner_name: str, rep: dict, today: dt.date, log=print
              ) -> Tuple[Optional[bool], str, Optional[dict]]:
    """Gate on 0-30, all port lines (the view's universe): disconnects
    exact, base within BASE_TOLERANCE; a mismatch against the cached view
    re-pulls once (nds_churn.run's rule). The 90 Day comparison rides along
    in the text. -> (ok | None when unverifiable, detail, view)."""
    from automations.nds_churn.run import BASE_TOLERANCE
    view = None
    for fresh in (False, True):
        try:
            view = view_counts(owner_name, today, log, fresh=fresh)
        except Exception as e:  # noqa: BLE001
            return None, f"view pull failed ({type(e).__name__}: {str(e)[:120]})", None
        if not view or not view.get("0-30"):
            return None, f"the Churn Rates view has no 0-30 rows for {owner_name}", view
        v = view["0-30"]
        ours = rep["all_port"]["0-30"]
        ok = (v["disc"] == ours["disc"] and abs(v["base"] - ours["base"]) <= BASE_TOLERANCE)
        if ok or fresh:
            break
        log(f"RECONCILE: 0-30 mismatch on the cached view -- re-pulling once")
    v90 = view.get("90")
    o90 = rep["all_port"]["90"]
    txt90 = (f"90 Day view {v90['disc']}/{v90['base']} vs ours {o90['disc']}/{o90['base']}"
             f"{' ✓' if v90['disc'] == o90['disc'] and abs(v90['base'] - o90['base']) <= BASE_TOLERANCE else ' ✗'}"
             if v90 else f"90 Day: view has no rows; ours {o90['disc']}/{o90['base']}")
    detail = (f"0-30 (all port lines) view {v['disc']}/{v['base']} vs ours "
              f"{ours['disc']}/{ours['base']} {'✓' if ok else '✗'}; {txt90}")
    return ok, detail, view


# ---------------------------------------------------------------- render ----

_CSS = """
<style>
 body{margin:0;font-family:'Helvetica Neue',Arial,sans-serif}
 .board{display:inline-block;padding:16px 18px;background:#fff;min-width:1300px}
 .title{background:#1f3b64;color:#fff;text-align:center;font-weight:700;font-size:24px;padding:10px 18px}
 .sub{color:#555;text-align:center;font-weight:700;font-size:15px;padding:8px 0 2px}
 .src{color:#777;text-align:center;font-size:12px;padding:0 0 10px}
 h3{margin:16px 0 6px;font-size:16px;color:#1f3b64}
 .band{margin:14px 0 4px;padding:6px 10px;background:#1f3b64;color:#fff;font-weight:700;font-size:15px}
 table{border-collapse:collapse;margin:0}
 th,td{border:1px solid #999;padding:5px 10px;font-size:13px;text-align:center;white-space:nowrap}
 th.wh{background:#efefef;font-weight:700}
 td.lbl{text-align:left;min-width:150px}
 td.l{text-align:left}
 tr.total td{font-weight:700;background:#f4f4f4}
 .pct{font-weight:700;font-size:15px}
 .frac{font-size:11px;color:#333}
 .small{font-size:12px;color:#444}
 .note{font-size:11.5px;color:#555;margin-top:12px;max-width:1300px;white-space:normal;line-height:1.35}
 .two{display:flex;gap:24px;align-items:flex-start}
 .rose td{background:#fde2e4}
 .empty{font-style:italic;color:#666;padding:6px 2px;font-size:13px}
</style>"""

GREEN = ("#1e8e3e", "#fff")
YELLOW = ("#ffe14d", "#000")
RED = ("#e04141", "#fff")
GREY = ("#f4f4f4", "#000")


def _band(bucket: str, pct: Optional[float]) -> Tuple[str, str]:
    """Colour by the Captain's Bonus lines: green at/under the bonus line,
    red at/over the DNQ line, yellow between, grey with no rate."""
    if pct is None:
        return GREY
    bonus, dnq = CAPTAIN_LINES[bucket]
    if pct <= bonus + 1e-9:
        return GREEN
    if pct >= dnq - 1e-9:
        return RED
    return YELLOW


def _pct_cell(bucket: str, c: dict) -> str:
    bg, fg = _band(bucket, c["pct"])
    frac = f'<div class="frac">({c["disc"]}/{c["act"]})</div>' if c["act"] else ""
    rate = f'{c["pct"]:.1f}%' if c["pct"] is not None else "—"
    return f'<td style="background:{bg};color:{fg}">{frac}<div class="pct">{rate}</div></td>'


def _rate_cell(s: dict) -> str:
    if not s or not s["sold"]:
        return "<td>—</td>"
    return (f'<td><div class="frac">({s["activated"]}/{s["sold"]})</div>'
            f'<div class="pct">{100 * s["rate"]:.0f}%</div></td>')


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _fmt_pct(p: Optional[float]) -> str:
    return "—" if p is None else f"{p:.1f}%"


def _tier_text(bucket: str, pct: Optional[float]) -> str:
    t = comp.tier_for(pct, SOW_BANDS[bucket])
    return "—" if t is None else f"Tier {t} band"


def _captain_text(bucket: str, pct: Optional[float]) -> str:
    if pct is None:
        return "—"
    bonus, dnq = CAPTAIN_LINES[bucket]
    if pct <= bonus + 1e-9:
        return f"✓ bonus line (≤ {bonus:.2f}%)"
    if pct >= dnq - 1e-9:
        return f"✗ DNQ line (≥ {dnq:.2f}%)"
    return f"between {bonus:.2f}% and {dnq:.2f}%"


def _box_html(rep: dict) -> str:
    box, orate = rep["box"], rep["office_rate"]
    rows = []
    for b in SHOWN:
        c = box[b]
        lo, hi = BUCKET_SPAN[b]
        rows.append(
            f'<tr><td class="lbl"><b>{BUCKET_LABEL[b]} churn</b>'
            f'<div class="small">activated {lo}–{hi} days ago</div></td>'
            f"<td>{c['act']}</td><td>{c['disc']}</td>{_pct_cell(b, c)}"
            f"<td>{_e(_tier_text(b, c['pct']))}</td><td>{_e(_captain_text(b, c['pct']))}</td></tr>")
    box_t = ('<table><tr><th class="wh"></th><th class="wh">Activated</th>'
             '<th class="wh">Disconnected</th><th class="wh">Churn %</th>'
             '<th class="wh">SOW Non-BYOD chart</th><th class="wh">Captain\'s Bonus line</th></tr>'
             + "".join(rows) + "</table>")
    rate_t = ('<table><tr><th class="wh"></th><th class="wh">0-30</th><th class="wh">31-60</th></tr>'
              f'<tr><td class="lbl"><b>Activation rate</b><div class="small">activated ÷ sold, by sale date</div></td>'
              f'{_rate_cell(orate["0-30"])}{_rate_cell(orate["31-60"])}</tr>'
              f'<tr><td class="lbl"><b>Pending orders</b><div class="small">sold last 30 days, not activated, not canceled</div></td>'
              f'<td>{rep["pending"]}</td><td></td></tr></table>')
    return f'<div class="two">{box_t}{rate_t}</div>'


def _reps_html(rep: dict) -> str:
    reps, rates = rep["reps"], rep["rep_rate"]
    names = rep_order(reps)
    for n in rates:                        # a rep who sold but has nothing activated yet
        if n not in reps:
            names.append(n)
    tot = rep["box"]
    head = ('<tr><th class="wh">Sales Rep</th><th class="wh">0-30 Day churn</th>'
            '<th class="wh">90 Day churn</th><th class="wh">Activation rate 0-30</th>'
            '<th class="wh">Activation rate 31-60</th></tr>')
    blank = {"act": 0, "disc": 0, "pct": None}
    trs = [f'<tr class="total"><td class="lbl">OFFICE TOTAL</td>{_pct_cell("0-30", tot["0-30"])}'
           f'{_pct_cell("90", tot["90"])}{_rate_cell(rep["office_rate"]["0-30"])}'
           f'{_rate_cell(rep["office_rate"]["31-60"])}</tr>']
    for n in names:
        r = reps.get(n, {})
        rr = rates.get(n, {})
        trs.append(f'<tr><td class="lbl">{_e(n)}</td>{_pct_cell("0-30", r.get("0-30", blank))}'
                   f'{_pct_cell("90", r.get("90", blank))}{_rate_cell(rr.get("0-30"))}'
                   f'{_rate_cell(rr.get("31-60"))}</tr>')
    return f"<table>{head}{''.join(trs)}</table>"


def _table_html(bucket: str, rows: List[dict], box: dict, today: dt.date) -> str:
    c = box[bucket]
    lo, hi = BUCKET_SPAN[bucket]
    band = (f"{BUCKET_LABEL[bucket].upper()} DISCONNECTS — {c['disc']} of {c['act']} "
            f"non-BYOD lines activated {lo}–{hi} days ago = {_fmt_pct(c['pct'])}")
    leave = "Falls off report" if bucket == "0-30" else "Leaves 90 Day bucket"
    head = (f'<tr><th class="wh">Days left</th><th class="wh">{leave}</th><th class="wh">Lines</th>'
            f'<th class="wh">{BUCKET_LABEL[bucket]} % after rolloff</th><th class="wh">Customer</th>'
            '<th class="wh">Sales Rep</th><th class="wh">Order Date</th><th class="wh">Activation Date</th>'
            '<th class="wh">Disconnect Date</th><th class="wh">Line · IF/OOF</th>'
            '<th class="wh">Ported From</th><th class="wh">Phone</th></tr>')
    if not rows:
        return f'<div class="band">{_e(band)}</div><div class="empty">no disconnects in this bucket</div>'
    trs = []
    recent = today - dt.timedelta(days=7)
    for g in rows:
        rose = ' class="rose"' if g["disc_date"] and g["disc_date"] >= recent else ""
        trs.append(f"<tr{rose}><td>{g['days_left']}d</td><td>{C.fmt_date(g['leaves'])}</td>"
                   f"<td>{g['lines']}</td><td>{_fmt_pct(g['pct_after'])}</td>"
                   f"<td class=\"l\">{_e(g['customer'])}</td><td class=\"l\">{_e(g['rep'])}</td>"
                   f"<td>{C.fmt_date(g['order_date'])}</td><td>{C.fmt_date(g['posted'])}</td>"
                   f"<td>{C.fmt_date(g['disc_date'])}</td><td>{_e(g['kind'])}</td>"
                   f"<td>{_e(g['ported_from'])}</td><td class=\"l\">{_e(g['device'])}</td></tr>")
    return f'<div class="band">{_e(band)}</div><table>{head}{"".join(trs)}</table>'


def render_html(owner: dict, rep: dict, today: dt.date, recon_text: str) -> str:
    title = f"🐺 NDS Customer Churn — {owner['name']}"
    sub = (f"Non-BYOD port phone lines only · as of {today.month}/{today.day}/{today.year}"
           " · 0-30 Day and 90 Day buckets by activation date")
    src = ("Source: Tableau NDS-SN Order Log (140-day window), counted the way Smart Circle's "
           f"Churn Rates view counts · {_e(recon_text)}")
    note = (
        "What's counted: ported voice lines on a financed or new phone — no BYOD, no Air, no Internet, "
        "no tablets / watches / upgrades / new-number lines. Buckets are Tableau's, by days since the line "
        "activated: 0-30 Day = 0–30, 90 Day = 91–120; a disconnected line stays in the bucket its age puts "
        "it in. Churn % = disconnected ÷ activated in the bucket. Colours follow the Captain's Bonus quality "
        f"lines ({_e(CAPTAIN_SOURCE)}): green = at or under the bonus line (0-30 ≤ 3.00%, 90 Day ≤ 8.00%), "
        "red = at or over the DNQ line (0-30 ≥ 5.00%, 90 Day ≥ 13.00%) — the captain's bonus is judged on the "
        "whole team's port lines, so one office can sit red while the team does not. 'SOW Non-BYOD chart' = "
        "where the rate lands on Schedule A's Non-BYOD churn tiers (4 best … 1 worst). Rose rows = disconnected "
        "in the last 7 days. '% after rolloff' = that bucket's churn once the row's lines have aged out of it.")
    body = (f'<div class="board"><div class="title">{_e(title)}</div><div class="sub">{_e(sub)}</div>'
            f'<div class="src">{src}</div>'
            + _box_html(rep)
            + "<h3>By rep — worst 0-30 Day churn first</h3>" + _reps_html(rep)
            + _table_html("0-30", rep["tables"]["0-30"], rep["box"], today)
            + _table_html("90", rep["tables"]["90"], rep["box"], today)
            + f'<div class="note">{note}</div></div>')
    return f"<html><head><meta charset='utf-8'>{_CSS}</head><body>{body}</body></html>"


def render_png(owner: dict, rep: dict, today: dt.date, recon_text: str, out: Path) -> Path:
    from automations.b2b_metrics.rep_boards import _capture_board
    return _capture_board(render_html(owner, rep, today, recon_text), out, width=1500)


# ------------------------------------------------------------------ diag ----

def diag_lines(owner: dict, rep: dict, today: dt.date, recon: str, view: Optional[dict],
               n_lines: int, owner_cells=None) -> List[str]:
    out = [f"CAPTAIN REPORT {owner['name']} {today.isoformat()} -- {n_lines} line(s) on the owner",
           "EXPORT OWNER CELLS: " + ("; ".join(f"{k} x{v}" for k, v in (owner_cells or [])) or "(none)"),
           "BOX (non-BYOD port phones): " + "; ".join(
               f"{BUCKET_LABEL[b]} {c['disc']}/{c['act']} = {_fmt_pct(c['pct'])}"
               for b, c in rep["box"].items()),
           "ALL PORT (BYOD too, the view's universe): " + "; ".join(
               f"{BUCKET_LABEL[b]} {c['disc']}/{c['act']} = {_fmt_pct(c['pct'])}"
               for b, c in rep["all_port"].items()),
           f"PENDING non-BYOD 0-30: {rep['pending']}",
           "RATES: " + "   ".join(
               f"{b} {s['activated']}/{s['sold']} = {('%.1f%%' % (100 * s['rate'])) if s['rate'] is not None else 'n/a'}"
               for b, s in rep["office_rate"].items()),
           "RECONCILE: " + recon,
           "REPS (non-BYOD 0-30 disc/act | 90 disc/act | rate 0-30):"]
    for n in rep_order(rep["reps"]):
        r = rep["reps"][n]
        rr = rep["rep_rate"].get(n, {}).get("0-30") or {}
        out.append(f"  {n}: {r['0-30']['disc']}/{r['0-30']['act']} | {r['90']['disc']}/{r['90']['act']}"
                   f" | {rr.get('activated', 0)}/{rr.get('sold', 0)}")
    out.append("ALL-PORT REPS (0-30 disc/act | 90 disc/act) vs VIEW (0-30 | 90):")
    vd = (view or {}).get("detail", {})
    for n in sorted(set(rep["all_port_reps"]) | set(vd)):
        r = rep["all_port_reps"].get(n)
        v = vd.get(n, {})
        ours = (f"{r['0-30']['disc']}/{r['0-30']['act']} | {r['90']['disc']}/{r['90']['act']}"
                if r else "—")
        vv = " | ".join(f"{int(v[b][0] or 0)}/{int(v[b][1] or 0)}" if v.get(b) and v[b][1] is not None
                        else "—" for b in ("0-30", "90"))
        out.append(f"  {n}: ours {ours}   view {vv}")
    for b in SHOWN:
        out.append(f"TABLE {BUCKET_LABEL[b]}: {len(rep['tables'][b])} group(s)")
        for g in rep["tables"][b]:
            out.append(f"  {g['days_left']}d | {C.fmt_date(g['leaves'])} | {g['lines']} | "
                       f"{_fmt_pct(g['pct_after'])} | {g['customer']} | {g['rep']} | "
                       f"{C.fmt_date(g['order_date'])} | {C.fmt_date(g['posted'])} | "
                       f"{C.fmt_date(g['disc_date'])} | {g['kind']} | {g['ported_from']} | {g['device']}")
    return out


def shot_to_tab(png: Path, log=print, tab: str = SHOT_TAB) -> None:
    """The picture, base64 in SHOT_CHUNK-char cells down column A of a
    control-sheet tab -- the way to look at a Lucy-2 PNG from the mini."""
    from automations.nds_churn.run import write_diag
    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    chunks = [b64[i:i + SHOT_CHUNK] for i in range(0, len(b64), SHOT_CHUNK)]
    write_diag([f"PNG {png.name} {png.stat().st_size} bytes, {len(chunks)} chunk(s)"] + chunks,
               log=log, tab=tab)


# ------------------------------------------------------------------- run ----

def run(owner_key: str, today: dt.date, *, dry_run: bool = False,
        from_file: Optional[str] = None, dm: Optional[str] = None,
        skip_reconcile: bool = False, log=print) -> int:
    from automations.nds_churn.run import write_diag
    key = (owner_key or "").strip().lower()
    if key not in OWNERS:
        log(f"unknown captainship owner {owner_key!r}; one of {', '.join(OWNERS)}")
        return 2
    owner = OWNERS[key]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(from_file) if from_file else pull_long(today, log)
    header, ix, lines = C.load_owner_lines(path, log=log, owner_tokens=owner["tokens"])
    log(f"[captain] {owner['name']}: {len(lines)} line(s) on the owner")
    owner_cells = export_owners(path, ix, log)
    if not lines:
        log("[captain] NO lines on the owner -- the export's Owner & Office cells: "
            + "; ".join(f"{k} x{v}" for k, v in owner_cells))
    rep = build(lines, today)
    if skip_reconcile:
        ok, recon, view = None, "not checked (--skip-reconcile)", None
    else:
        ok, recon, view = reconcile(owner["name"], rep, today, log)
    log("RECONCILE: " + ("OK" if ok else "UNVERIFIED" if ok is None else "MISMATCH") + " -- " + recon)
    recon_short = ("✓ reconciled to Smart Circle's Churn Rates view (all port lines, 0-30)"
                   if ok else "⚠ not reconciled to Smart Circle's Churn Rates view: " + recon)
    for ln in diag_lines(owner, rep, today, recon, view, len(lines), owner_cells):
        log("  " + ln)
    png = render_png(owner, rep, today, recon_short,
                     OUT_DIR / f"nds_captain_{key}_{today.isoformat()}.png")
    log(f"[captain] picture {png} ({png.stat().st_size:,} bytes)")
    if dry_run:
        write_diag(diag_lines(owner, rep, today, recon, view, len(lines), owner_cells), log=log, tab=DIAG_TAB)
        try:
            shot_to_tab(png, log=log)
        except Exception as e:  # noqa: BLE001 -- the picture tab never fails a dry run
            log(f"[captain] shot tab failed: {type(e).__name__}: {e}")
        log("[dry-run] nothing sent.")
        print("=== done ===", flush=True)
        return 0
    if ok is False:
        log("✗ 0-30 does not match the Churn Rates view -- nothing sent (--skip-reconcile overrides)")
        write_diag(diag_lines(owner, rep, today, recon, view, len(lines), owner_cells), log=log, tab=DIAG_TAB)
        return 1
    if dm:
        from automations.shared import slack_metrics_post as smp
        users = [u.strip() for u in dm.replace(";", ",").split(",") if u.strip()]
        b30, b90 = rep["box"]["0-30"], rep["box"]["90"]
        comment = (f"🐺 *NDS Customer Churn — {owner['name']}* (non-BYOD port phone lines) · "
                   f"0-30 Day {b30['disc']}/{b30['act']} = {_fmt_pct(b30['pct'])} · "
                   f"90 Day {b90['disc']}/{b90['act']} = {_fmt_pct(b90['pct'])} · "
                   f"as of {today.month}/{today.day}. Source: Tableau NDS-SN Order Log.")
        res = smp.dm_users_with_file(png, users=users, comment=comment, file_name=png.name)
        log(f"[captain] sent ({res.get('mode')}) to {users}: ok={res.get('ok')}")
    print("=== done ===", flush=True)
    return 0
