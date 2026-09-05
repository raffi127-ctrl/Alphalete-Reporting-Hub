"""By-rep Activation + Churn boards for the B2B Metrics thread (Carlos
2026-09-05).

THE ASK, in Carlos's words: the Activation-by-Rep screenshot gains the 31-60
day rate next to 0-30, both with a TOTAL row for the office; and a NEW churn
screenshot in the same style — one column per churn bucket (0-30 / 30 / 60 /
90 / 120 day), rows = ACTIVE reps only, with the office total row being the
TRUE office total (every rep, gone ones included), never just the sum of the
active rows shown.

DATA (probed live on Lucy 2, 2026-09-05 — geometry in the 'B2B Diag' tab):
  * churn:      the CHURNRATES rep view's '1 Rep Churn' crosstab — one row
                per rep x colour band x measure (Activated SPE/SP /
                Disconnect count (SPE/SP) / Churn Rate), buckets as columns;
                a reading lives in exactly ONE colour band. Its 'Grand Total'
                rep rows ARE the true office totals.
  * activation: the ACTIVATION RATES csv the vantura_churn pipeline already
                parses — activation_rates.parse_rep_rates (per-rep 0-30 /
                31-60) + parse_rates (true office totals).
  * ACTIVE reps: the office's Vantura Sales Board rep rows — the board IS the
                working roster (the audit maintains it); Name Aliases bridges
                spelling differences.

RENDER: self-contained HTML -> PNG (headless Chrome), same pattern and
saturated bands as activation_board.py. Churn cells carry Tableau's OWN
colour; activation cells are neutral until Carlos names banding rules.

  lucy rerun b2b_rep_boards -- --probe     # geometry probe (read-only)
  lucy rerun b2b_rep_boards -- --build     # build both PNGs -> B2B Shot tabs
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_metrics_preview"

# Carlos's EXPANDED churn view — the one whose 'Churn Rates Owner (+/-) Rep'
# table the thread screenshots; its crosstab carries the Rep dimension.
CHURN_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/7419b960-0fb1-41d5-a11e-76f0e81c0547/"
    "CarlosLocalOfficeEXPANDEDCHURN")
CHURN_REP_SHEET = "1 Rep Churn"
BUCKETS = ["0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]

M_ACT = "Activated SPE/SP"
M_DISC = "Disconnect count (SPE/SP)"
M_RATE = "Churn Rate"

DIAG_TAB = "B2B Diag"
SHOT_TAB_CHURN = "B2B Shot"
SHOT_TAB_ACT = "B2B Shot AR"

SALES_BOARD_SHEET = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\r", " ")).strip().lower()


# --------------------------------------------------------------- churn parse
def parse_rep_churn(grid: list, owner_prefix: str = "CARLOS HIDALGO") -> dict:
    """{rep: {bucket: {'act','disc','rate','color'}}} + a '__TOTAL__' entry
    from the export's own Grand Total rows (the TRUE office totals).

    A reading lives in exactly ONE colour band per rep/bucket (probed
    2026-09-05); a blank never overwrites a real value."""
    hdr = [str(h or "").strip() for h in grid[0]]
    need = ["Rep", "0-30 Day"]
    if any(c not in hdr for c in need):
        raise RuntimeError(f"'{CHURN_REP_SHEET}': header {hdr} missing {need}")
    i_rep = hdr.index("Rep")
    i_owner = hdr.index("OWNER & OFFICE") if "OWNER & OFFICE" in hdr else None
    i_color = next((i for i, h in enumerate(hdr) if "color" in h.lower()), None)
    i_measure = hdr.index("0-30 Day") - 1
    bucket_ix = {b: hdr.index(b) for b in BUCKETS if b in hdr}
    if len(bucket_ix) != len(BUCKETS):
        raise RuntimeError(
            f"'{CHURN_REP_SHEET}': buckets found {sorted(bucket_ix)}")

    out: dict = {}
    for r in grid[1:]:
        if len(r) <= max(bucket_ix.values()):
            continue
        rep = str(r[i_rep] or "").replace("\r", " ").strip()
        full = str(r[0] or "").strip()
        if not rep and "grand total" in full.lower():
            rep = "__TOTAL__"
        if "grand total" in rep.lower():
            rep = "__TOTAL__"
        if not rep:
            continue
        if rep != "__TOTAL__" and i_owner is not None:
            own = str(r[i_owner] or "").replace("\r", " ").upper()
            if own and not own.startswith(owner_prefix.upper()):
                continue
        measure = str(r[i_measure] or "").strip()
        if measure not in (M_ACT, M_DISC, M_RATE):
            continue
        color = str(r[i_color] or "").strip() if i_color is not None else ""
        slot = out.setdefault(rep, {b: {} for b in BUCKETS})
        for b, ci in bucket_ix.items():
            v = str(r[ci] or "").strip()
            if not v:
                continue
            cell = slot[b]
            if measure == M_ACT:
                cell["act"] = v
            elif measure == M_DISC:
                cell["disc"] = v
            else:
                cell["rate"] = v
            if color and not cell.get("color"):
                cell["color"] = color
    # Grand Total rows are absent from this worksheet's export (proven
    # 2026-09-05 — the dashboard's Grand Total lives in another sheet); the
    # caller supplies the office totals from 'ICD Churn' instead.
    return out


def parse_office_churn(grid: list,
                       owner_prefix: str = "CARLOS HIDALGO") -> dict:
    """{bucket: cell} — the TRUE office totals, from the view's 'ICD Churn'
    sheet (per owner x product x bucket; every rep's orders, gone reps
    included). A 'Total' product row is used verbatim when the export carries
    one; otherwise act/disc are summed across the product rows — numerator
    and denominator separately, never the published rates."""
    hdr = [str(h or "").strip() for h in grid[0]]
    if "0-30 Day" not in hdr:
        raise RuntimeError(f"'ICD Churn': header {hdr}")
    i_owner = 0
    i_prod = next((i for i, h in enumerate(hdr) if "product" in h.lower()), 1)
    i_measure = hdr.index("0-30 Day") - 1
    bucket_ix = {b: hdr.index(b) for b in BUCKETS if b in hdr}
    acc = {b: {"act": 0.0, "disc": 0.0} for b in BUCKETS}
    total_rows = {b: {} for b in BUCKETS}
    saw_total = False
    for r in grid[1:]:
        if len(r) <= max(bucket_ix.values()):
            continue
        own = str(r[i_owner] or "").replace("\r", " ").upper()
        if not own.startswith(owner_prefix.upper()):
            continue
        prod = str(r[i_prod] or "").strip()
        measure = str(r[i_measure] or "").strip()
        if measure not in (M_ACT, M_DISC):
            continue
        for b, ci in bucket_ix.items():
            v = str(r[ci] or "").replace(",", "").strip()
            if not v:
                continue
            try:
                f = float(v)
            except ValueError:
                continue
            if prod.lower() == "total":
                saw_total = True
                total_rows[b]["act" if measure == M_ACT else "disc"] = f
            else:
                acc[b]["act" if measure == M_ACT else "disc"] += f
    src = total_rows if saw_total else acc
    out = {}
    for b in BUCKETS:
        a, d = src[b].get("act", 0.0), src[b].get("disc", 0.0)
        if not a:
            out[b] = {}
            continue
        out[b] = {"act": str(int(a)), "disc": str(int(d)),
                  "rate": "{:.1f}%".format(100.0 * d / a)}
    return out


# ------------------------------------------------------------- active roster
def active_reps(log=print) -> set:
    """Normalised names with a Vantura Sales Board rep row — the working
    roster — expanded through the Name Aliases tab."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SALES_BOARD_SHEET)
    board = sh.worksheet("Sales Board").get_all_values()
    names = set()
    for r in board[4:]:
        nm = str(r[1]).strip() if len(r) > 1 else ""
        # rep rows carry a week tag (col N) or a campaign (col L); the SUMIFS
        # total rows don't have a personal name in col B anyway.
        if nm and len(r) > 13 and (str(r[13]).strip() or str(r[11]).strip()):
            names.add(_norm(nm))
    try:
        for r in sh.worksheet("Name Aliases").get_all_values():
            vals = [_norm(c) for c in r if str(c).strip()]
            if len(vals) > 1 and names & set(vals):
                names.update(vals)
    except Exception as e:  # noqa: BLE001
        log(f"  (aliases unavailable: {type(e).__name__})")
    log(f"  active roster: {len(names)} name(s) off the Sales Board")
    return names


# ------------------------------------------------------------------- render
_CSS = """
<style>
 body{margin:0;font-family:'Helvetica Neue',Arial,sans-serif}
 .board{display:inline-block;padding:14px;background:#fff}
 .title{background:#1f3b64;color:#fff;text-align:center;font-weight:700;
        font-size:22px;padding:10px 18px}
 .sub{color:#555;text-align:center;font-weight:700;font-size:16px;
      padding:8px 0}
 table{border-collapse:collapse;margin:0 auto}
 th,td{border:1px solid #999;padding:6px 12px;font-size:13px;text-align:center}
 th.wh{background:#efefef;font-weight:700}
 td.lbl{text-align:left;font-weight:400;min-width:200px}
 td.grand{font-weight:700}
 .pct{font-weight:700;font-size:14px}
 .frac{font-size:11px}
 td.blank{background:#fff}
</style>"""

_BAND = {"Green": {"bg": "#1e8e3e", "fg": "#ffffff"},
         "Yellow": {"bg": "#ffe14d", "fg": "#000000"},
         "Red": {"bg": "#e04141", "fg": "#ffffff"}}


def _cell(cell: dict) -> str:
    if not cell or ("rate" not in cell and "disc" not in cell):
        return '<td class="blank"></td>'
    band = _BAND.get(cell.get("color", ""), {"bg": "#f4f4f4", "fg": "#000"})
    frac = ""
    if cell.get("disc") is not None and cell.get("act"):
        frac = f'<div class="frac">({cell.get("disc", "?")}/{cell["act"]})</div>'
    rate = f'<div class="pct">{cell.get("rate", "")}</div>'
    return (f'<td style="background:{band["bg"]};color:{band["fg"]}">'
            f"{frac}{rate}</td>")


def render_table_png(title: str, subtitle: str, columns: list, rows: list,
                     out_path: Path) -> Path:
    """rows = [(label, is_total, {col: cell-dict})]; cell-dict keys
    act/disc/rate/color (rate pre-formatted, e.g. '11.1%')."""
    ths = "".join(f'<th class="wh">{c}</th>' for c in columns)
    trs = []
    for label, is_total, cells in rows:
        cls = ' class="grand"' if is_total else ""
        tds = "".join(_cell(cells.get(c)) for c in columns)
        trs.append(f'<tr><td class="lbl{" grand" if is_total else ""}">'
                   f"{label}</td>{tds}</tr>")
    html = (f"<html><head><meta charset='utf-8'>{_CSS}</head><body>"
            f'<div class="board"><div class="title">{title}</div>'
            f'<div class="sub">{subtitle}</div>'
            f'<table><tr><th class="wh"></th>{ths}</tr>'
            + "".join(trs) + "</table></div></body></html>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".html")
    tmp.write_text(html, encoding="utf-8")
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = None
        for kw in ({"channel": "chrome"}, {}):
            try:
                browser = p.chromium.launch(headless=True, **kw)
                break
            except Exception:  # noqa: BLE001
                continue
        if browser is None:
            raise RuntimeError("no headless Chrome/Chromium to render")
        try:
            page = browser.new_page(device_scale_factor=2,
                                    viewport={"width": 1400, "height": 900})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.query_selector(".board").screenshot(path=str(out_path))
        finally:
            browser.close()
    return out_path


# -------------------------------------------------------------------- build
def build(log=print) -> int:
    """Pull both exports on Lucy 2, render both boards, b64 them into the
    B2B Shot tabs for the mini to decode (preview flow; thread wiring comes
    after Carlos signs off on the pictures)."""
    import csv as _csv
    import datetime as dt

    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright)
    from automations.vantura_churn import cdp_pull
    from automations.vantura_churn import activation_rates as ar
    from automations.vantura_churn import compute

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    churn_csv = OUT_DIR / "rep_churn.csv"
    act_rows = None

    with cdp_pull._cdp_lock(label="b2b rep_boards build", log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        try:
            with sync_playwright() as p:
                browser = None
                for attempt in range(10):
                    time.sleep(5)
                    try:
                        browser = p.chromium.connect_over_cdp(
                            "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                        break
                    except Exception:  # noqa: BLE001
                        if attempt == 9:
                            raise
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                download_crosstab_patchright(CHURN_VIEW, CHURN_REP_SHEET,
                                             churn_csv, page=page,
                                             verbose=False)
                icd_csv = OUT_DIR / "office_churn.csv"
                download_crosstab_patchright(CHURN_VIEW, "ICD Churn",
                                             icd_csv, page=page,
                                             verbose=False)
                # per-rep activation lives on the 'Activation Office'
                # worksheet of CARLOSLOCALEXPANDED (see activation_rates.py)
                act_rep_csv = OUT_DIR / "rep_activation.csv"
                download_crosstab_patchright(ar.VIEW_URL, ar.REP_SHEET,
                                             act_rep_csv, page=page,
                                             verbose=False)
                # office-level activation totals: the plain csv export
                import io
                for label, url in ar.csv_urls():
                    r = page.context.request.get(url, timeout=300_000)
                    body = r.body() or b""
                    log(f"  [act {label}] status={r.status} "
                        f"bytes={len(body):,}")
                    if r.status == 200 and len(body) > 200:
                        act_rows = list(_csv.reader(io.StringIO(
                            body.decode("utf-8-sig", "replace"))))
                        break
        finally:
            cdp_pull._kill_ours()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    today = dt.date.today().strftime("%B %d, %Y")
    roster = active_reps(log=log)

    # ---- churn board
    grid = compute._load_grid(churn_csv)
    churn = parse_rep_churn(grid)
    churn.pop("__TOTAL__", None)
    total = parse_office_churn(compute._load_grid(OUT_DIR / "office_churn.csv"))
    kept, dropped = [], 0
    for rep, cells in sorted(churn.items()):
        if _norm(rep) in roster:
            kept.append((rep, False, cells))
        else:
            dropped += 1
    log(f"  churn: {len(kept)} active rep row(s), {dropped} inactive "
        "dropped (their numbers still count in the office total)")
    rows = [("Office Total (all reps)", True, total)] + kept
    churn_png = render_table_png(
        "CHURN RATES BY REP", f"Carlos's B2B Office — {today} "
        "(active reps; total = whole office)", BUCKETS, rows,
        OUT_DIR / "churn_by_rep.png")
    cdp_pull._upload_png(churn_png.read_bytes(), tab=SHOT_TAB_CHURN)
    log(f"  churn board -> {SHOT_TAB_CHURN!r} "
        f"({churn_png.stat().st_size:,} bytes)")

    # ---- activation board
    if not act_rows:
        log("  activation csv unavailable — activation board skipped")
        return 1
    office = ar.parse_rates(act_rows)
    try:
        reps = ar.parse_rep_rates(
            compute._load_grid(OUT_DIR / "rep_activation.csv"))
    except Exception as e:  # noqa: BLE001
        log(f"  per-rep activation grid unusable ({e}) — office totals "
            "only this pass")
        reps = {}

    def _acell(d):
        if not d or d.get("rate") is None:
            return {}
        return {"act": str(d["sold"]), "disc": str(d["activated"]),
                "rate": f"{round(d['rate'] * 100, 1)}%"}

    cols = ["0-30 Day", "31-60 Day"]
    a_rows = [("Office Total (all reps)", True,
               {"0-30 Day": _acell(office.get("0-30")),
                "31-60 Day": _acell(office.get("31-60"))})]
    a_dropped = 0
    for rep, d in sorted(reps.items()):
        if _norm(rep) not in roster:
            a_dropped += 1
            continue
        a_rows.append((rep, False, {"0-30 Day": _acell(d.get("0-30")),
                                    "31-60 Day": _acell(d.get("31-60"))}))
    log(f"  activation: {len(a_rows) - 1} active rep row(s), "
        f"{a_dropped} inactive dropped")
    act_png = render_table_png(
        "ACTIVATION RATES BY REP", f"Carlos's B2B Office — {today} "
        "(activated/sold; total = whole office)", cols, a_rows,
        OUT_DIR / "activation_by_rep.png")
    cdp_pull._upload_png(act_png.read_bytes(), tab=SHOT_TAB_ACT)
    log(f"  activation board -> {SHOT_TAB_ACT!r} "
        f"({act_png.stat().st_size:,} bytes)")
    return 0


def _upload_diag(lines) -> None:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(
        "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
    try:
        t = sh.worksheet(DIAG_TAB)
    except Exception:  # noqa: BLE001
        t = sh.add_worksheet(title=DIAG_TAB, rows=400, cols=1)
    t.clear()
    t.update([[ln[:4900]] for ln in lines][:400], "A1")


def probe(argv_url: str = "") -> int:
    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull
    from automations.vantura_churn import activation_rates as ar

    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(str(msg))

    url = argv_url or CHURN_VIEW
    with cdp_pull._cdp_lock(label="b2b rep_boards probe", log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        try:
            with sync_playwright() as p:
                browser = None
                for attempt in range(10):
                    time.sleep(5)
                    try:
                        browser = p.chromium.connect_over_cdp(
                            "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                        break
                    except Exception:  # noqa: BLE001
                        if attempt == 9:
                            raise
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                ar.probe_view(page, url, log=log)
        finally:
            cdp_pull._kill_ours()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
    _upload_diag(lines)
    print("probe output -> sheet tab {!r} ({} line(s))".format(
        DIAG_TAB, len(lines)), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_metrics.rep_boards")
    ap.add_argument("--probe", action="store_true",
                    help="enumerate + download the churn view's worksheets; "
                         "geometry to the B2B Diag tab (read-only)")
    ap.add_argument("--build", action="store_true",
                    help="pull both exports, render both boards, b64 them "
                         "into the B2B Shot tabs (preview flow)")
    ap.add_argument("--url", default="", help="probe a different view URL")
    args = ap.parse_args(argv)
    if args.probe:
        return probe(args.url)
    if args.build:
        return build()
    ap.error("pass --probe or --build")
    return 2


if __name__ == "__main__":
    sys.exit(main())
