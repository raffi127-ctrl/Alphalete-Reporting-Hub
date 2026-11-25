"""Spectrum Order Log (Raf) -> .xlsx in today's Metrics thread.

Maud 2026-11-24: "would you be able to create an order log for Spectrum
please? There is a Charter workbook on Tableau now!" Eve 2026-11-25: works
like the AT&T Order Log — same channel (#alphalete-sales), inside the day's
"Metrics for:" thread — but a SAMPLE goes to Eve first.

WHERE THE DATA COMES FROM
  Tableau (sci) -> Charter D2D Sales Metrics -> Order Log dashboard ->
  worksheet "Order Log Raw" (one row per line). Downloads are OFF on that
  dashboard (csv/crosstab give only 'Last Update', View Data is blocked,
  EXPORT OPTIONS does nothing) and Tableau is SCI's, so nobody here can turn
  them on. The table is drawn by the browser, though, so its rows arrive in
  the page's own bootstrapSession reply: probe._tables_from_bootstrap reads
  them from there — full values, every row.

    python -m automations.spectrum_order_log.run              # dry run: build, post nothing
    python -m automations.spectrum_order_log.run --sample     # DM the same thread to Eve only
    python -m automations.spectrum_order_log.run --post       # #alphalete-sales post: name index + one reply per rep

Runs on a Lucy with Raf's Tableau (rhidalgo): Lucy 1, 3 or 4.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — py3.9 / non-tty
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "spectrum_order_log"

SHEET = "Order Log Raw"
EVE_SLACK_ID = "U088E2KJEV8"   # resources/owner-slack-ids.md
METRICS_CHANNEL = "C068PH3RFSM"   # #alphalete-sales (same as the AT&T log)
NON_REP_TABS = {"Order Log", "By Rep"}

# (Tableau field, header in the .xlsx) — order mirrors the AT&T Order Log:
# who, when, customer, what, status, then the pay drivers.
COLUMNS = [
    ("Rep Name", "Rep"),
    ("Sale Date", "Sale Date"),
    ("Customer Name", "Customer Name"),
    ("CustomerCityName", "City"),
    ("Customer Zip Code", "Zip"),
    ("Account Num", "Account Number"),
    ("App ID", "Order #"),
    ("Sup Category Code", "Product Type"),
    ("Product Name", "Package"),
    ("Sup Status Code", "Status"),
    ("PIA $", "PIA $"),
    ("Gig+ Ind", "Gig+"),
    ("Auto Bill Pay", "Auto Bill Pay"),
    ("Usage Ind", "Usage"),
    ("Sale Week", "Sale Week"),
]

# Same colors as the AT&T log (uploaded.order_log.STATUS_COLORS).
STATUS_FILL = {"installed": "57BB8A", "pending": "FFD666", "canceled": "E67C73",
               "cancelled": "E67C73"}
STATUS_TEXT = {"canceled": "CC0000", "cancelled": "CC0000"}
STATUS_ORDER = {"pending": 0, "installed": 1, "canceled": 2, "cancelled": 2}


# ------------------------------------------------------------------ pull
def _print_filters(obj, depth: int = 0) -> None:
    """'FILTER: <field> = <selected values>' for every quick filter the
    bootstrap carries, so a filter left on (e.g. only Internet) shows up in
    the log instead of silently cutting rows."""
    if depth > 40:
        return
    if isinstance(obj, dict):
        dom = obj.get("domainTables")
        if isinstance(dom, list) and dom:
            name = obj.get("fn") or obj.get("fieldCaption") or obj.get("caption") or "?"
            sel = [str(d.get("label")) for d in dom
                   if isinstance(d, dict) and d.get("isSelected")]
            print(f"FILTER: {name} = {sel[:12]} ({len(sel)}/{len(dom)} selected)",
                  flush=True)
        for v in obj.values():
            _print_filters(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _print_filters(v, depth + 1)


# Last 30 days, like the AT&T log (Eve 2026-11-25). The dashboard opens on
# the current Sale Week only; a URL filter widens it. Sale Week = the Saturday
# that closes a Sun-Sat week, and ONLY yyyy-mm-dd works in the URL (probe
# --weeks: m/d/yyyy and mm/dd/yyyy came back with this week only).
DAYS_BACK = 30


def sale_weeks(today: dt.date) -> "list[dt.date]":
    """Every Sale Week (Saturday) with a day inside the last DAYS_BACK days."""
    sat = today + dt.timedelta(days=(5 - today.weekday()) % 7)
    first = today - dt.timedelta(days=DAYS_BACK)
    out = []
    while sat >= first:
        out.append(sat)
        sat -= dt.timedelta(weeks=1)
    return out


def orderlog_url(today: dt.date) -> str:
    from automations.spectrum_order_log import probe
    weeks = ",".join(f"{d:%Y-%m-%d}" for d in sale_weeks(today))
    return f"{probe.ORDERLOG_URL}?Sale%20Week={weeks}"


def pull(today: "dt.date | None" = None) -> "tuple[list[str], list[list]]":
    from automations.shared.tableau_patchright import tableau_session
    from automations.spectrum_order_log import probe

    bodies: list = []

    def _grab(resp):
        if "bootstrapSession" in resp.url:
            try:
                bodies.append(resp.text())
            except Exception as e:  # noqa: BLE001
                print(f"  bootstrap body unreadable: {type(e).__name__}: {e}")

    with tableau_session(verbose=True) as page:
        page.context.on("response", _grab)
        url = orderlog_url(today or dt.date.today())
        print(f"  opening {url}", flush=True)
        page.goto(url, wait_until="domcontentloaded")
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]'
                    ).wait_for(state="visible", timeout=120_000)
        page.wait_for_timeout(15_000)
    for b in bodies:
        for part in probe._split_bootstrap(b):
            info = part.get("secondaryInfo")
            if not info:
                continue
            _print_filters(part)
            tables = probe._tables_from_bootstrap(info)
            if SHEET in tables:
                return tables[SHEET]
    raise RuntimeError(f"no '{SHEET}' worksheet in the Order Log page "
                       f"({len(bodies)} bootstrap repl(ies)) — dashboard changed?")


# ------------------------------------------------------------------ shape
def shape(fields: list, rows: list) -> "list[dict]":
    missing = [f for f, _ in COLUMNS if f not in fields]
    if missing:
        raise RuntimeError(f"Order Log Raw lost column(s) {missing}; has {fields}")
    at = {f: i for i, f in enumerate(fields)}
    out = []
    for r in rows:
        rec = {h: r[at[f]] for f, h in COLUMNS}
        if not str(rec["Rep"]).strip() and not str(rec["Order #"]).strip():
            continue
        out.append(rec)

    def _key(rec):
        try:
            d = dt.datetime.strptime(str(rec["Sale Date"]), "%m/%d/%Y").date()
        except ValueError:
            d = dt.date.min
        return (STATUS_ORDER.get(str(rec["Status"]).lower(), 9),
                str(rec["Rep"]).lower(), d)
    return sorted(out, key=_key)


# ------------------------------------------------------------------ xlsx
# Columns on each rep's own tab (Raf 2026-11-25: "Can we do a tab per rep?").
# Rep is in the tab name and Sale Week is in each section banner, so both drop.
REP_TAB_COLUMNS = [
    "Sale Date", "Customer Name", "Package", "Product Type", "Status",
    "Account Number", "Order #", "City", "Zip", "PIA $", "Gig+",
    "Auto Bill Pay", "Usage",
]
_BAD_SHEET_CHARS = str.maketrans({c: " " for c in r":\/?*[]"})


def _parse_date(v):
    try:
        return dt.datetime.strptime(str(v), "%m/%d/%Y").date()
    except ValueError:
        return None


def _cell_value(h: str, v):
    """Tableau text -> what the cell holds: real dates, PIA as a number,
    Gig+ as Yes/No, everything else text (account #s keep leading zeros)."""
    if h in ("Sale Date", "Sale Week"):
        return _parse_date(v) or v
    if h == "Gig+":
        s = str(v).lower()
        return "Yes" if s == "true" else ("No" if s == "false" else v)
    if h == "PIA $":
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return "" if v is None else str(v)


def _sheet_title(name: str, used: set) -> str:
    """Excel tab name: no :\\/?*[] , max 31 chars, unique in the workbook."""
    base = " ".join(str(name).translate(_BAD_SHEET_CHARS).split())[:31] or "Rep"
    title, n = base, 2
    while title.lower() in {u.lower() for u in used}:
        sfx = f" ({n})"
        title, n = base[:31 - len(sfx)] + sfx, n + 1
    used.add(title)
    return title


def _add_rep_tabs(wb, recs: "list[dict]", border, head_font) -> int:
    """One tab per rep, laid out like the AT&T log's rep tabs: a section per
    Sale Week with the INSTALLED lines (earliest week first), then one
    'Pending / Canceled' section. Returns how many tabs were added."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    week_fill = PatternFill("solid", fgColor="2563EB")
    open_fill = PatternFill("solid", fgColor="C55A11")
    head_fill = PatternFill("solid", fgColor="434343")
    ncol = len(REP_TAB_COLUMNS)
    used = {ws.title for ws in wb.worksheets}

    per_rep: dict = {}
    for rec in recs:
        rep = str(rec["Rep"] or "").strip()
        if not rep:
            continue
        b = per_rep.setdefault(rep, {"weeks": {}, "open": []})
        if str(rec["Status"]).lower() == "installed":
            b["weeks"].setdefault(_parse_date(rec["Sale Week"]) or dt.date.min,
                                  []).append(rec)
        else:
            b["open"].append(rec)

    def banner(sh, r, text, fill):
        c = sh.cell(row=r, column=1, value=text)
        c.fill, c.font, c.alignment, c.border = fill, head_font, center, border
        sh.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncol)

    def header(sh, r):
        for i, h in enumerate(REP_TAB_COLUMNS, 1):
            c = sh.cell(row=r, column=i, value=h)
            c.fill, c.font, c.alignment, c.border = head_fill, head_font, center, border

    def line(sh, r, rec):
        st = str(rec["Status"]).lower()
        for i, h in enumerate(REP_TAB_COLUMNS, 1):
            c = sh.cell(row=r, column=i, value=_cell_value(h, rec[h]))
            c.border, c.alignment = border, center
            if isinstance(c.value, dt.date):
                c.number_format = "m/d/yyyy"
            elif h == "PIA $" and isinstance(c.value, float):
                c.number_format = "$#,##0.00"
            if h == "Status":
                if st in STATUS_FILL:
                    c.fill = PatternFill("solid", fgColor=STATUS_FILL[st])
                if st in STATUS_TEXT:
                    c.font = Font(bold=True, color=STATUS_TEXT[st])

    def by_date(rec):
        return _parse_date(rec["Sale Date"]) or dt.date.min

    for rep in sorted(per_rep, key=str.lower):
        b = per_rep[rep]
        sh = wb.create_sheet(_sheet_title(rep, used))
        r = 1
        for wk in sorted(b["weeks"]):
            rows = sorted(b["weeks"][wk], key=by_date)
            start = wk - dt.timedelta(days=6) if wk != dt.date.min else None
            label = (f"Week {start:%m/%d} to {wk:%m/%d}" if start
                     else "Week ?")
            banner(sh, r, f"{label}  •  {len(rows)} installed", week_fill)
            header(sh, r + 1)
            r += 2
            for rec in rows:
                line(sh, r, rec)
                r += 1
            r += 1
        if b["open"]:
            rows = sorted(b["open"], key=lambda x: (
                STATUS_ORDER.get(str(x["Status"]).lower(), 9), by_date(x)))
            banner(sh, r, f"Pending / Canceled  •  {len(rows)} line(s)", open_fill)
            header(sh, r + 1)
            r += 2
            for rec in rows:
                line(sh, r, rec)
                r += 1
        for i, h in enumerate(REP_TAB_COLUMNS, 1):
            col = get_column_letter(i)
            data = [len(str(rec[h] or "")) for bk in
                    (list(b["weeks"].values()) + [b["open"]]) for rec in bk]
            sh.column_dimensions[col].width = min(
                max([len(h)] + data) + 3, 40)
        # Big black name band on top, same as the AT&T rep tabs: Slack's
        # phone preview never shows the tab name.
        from automations.uploaded.order_log_split import _name_banner
        _name_banner(sh, rep)
    return len(per_rep)


def to_xlsx(recs: "list[dict]", path: Path, today: dt.date) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center", vertical="center")
    headers = [h for _, h in COLUMNS]

    wb = Workbook()
    ws = wb.active
    ws.title = "Order Log"
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font, c.alignment, c.border = head_fill, head_font, center, border
    status_col = headers.index("Status") + 1
    for rec in recs:
        ws.append([_cell_value(h, rec[h]) for h in headers])
        r = ws.max_row
        st = str(rec["Status"]).lower()
        for c in ws[r]:
            c.border, c.alignment = border, center
            if isinstance(c.value, dt.date):
                c.number_format = "m/d/yyyy"
            if c.column == headers.index("PIA $") + 1 and isinstance(c.value, float):
                c.number_format = "$#,##0.00"
        sc = ws.cell(row=r, column=status_col)
        if st in STATUS_FILL:
            sc.fill = PatternFill("solid", fgColor=STATUS_FILL[st])
        if st in STATUS_TEXT:
            sc.font = Font(bold=True, color=STATUS_TEXT[st])
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    for i, h in enumerate(headers, 1):
        width = max([len(h)] + [len(str(ws.cell(row=r, column=i).value or ""))
                                for r in range(2, ws.max_row + 1)])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width + 3, 40)

    # By Rep: sales, installed, pending, canceled — the at-a-glance tab.
    by = wb.create_sheet("By Rep")
    by.append(["Rep", "Sales", "Installed", "Pending", "Canceled"])
    for c in by[1]:
        c.fill, c.font, c.alignment, c.border = head_fill, head_font, center, border
    reps: dict = {}
    for rec in recs:
        t = reps.setdefault(rec["Rep"], [0, 0, 0, 0])
        t[0] += 1
        st = str(rec["Status"]).lower()
        if st == "installed":
            t[1] += 1
        elif st == "pending":
            t[2] += 1
        elif st in ("canceled", "cancelled"):
            t[3] += 1
    for rep, t in sorted(reps.items(), key=lambda kv: (-kv[1][0], kv[0])):
        by.append([rep] + t)
    by.append(["TOTAL"] + [sum(t[i] for t in reps.values()) for i in range(4)])
    for row in by.iter_rows(min_row=2):
        for c in row:
            c.border, c.alignment = border, center
    for c in by[by.max_row]:
        c.font = Font(bold=True)
    by.column_dimensions["A"].width = max([22] + [len(str(k)) + 3 for k in reps])
    for col in "BCDE":
        by.column_dimensions[col].width = 12

    _add_rep_tabs(wb, recs, border, head_font)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", action="store_true",
                   help="DM the same thread to Eve only (preview)")
    g.add_argument("--post", action="store_true",
                   help="#alphalete-sales: one thread, name index + a file per rep")
    args = ap.parse_args(argv)

    today = dt.date.today()
    fields, rows = pull(today)
    recs = shape(fields, rows)
    counts: dict = {}
    for r in recs:
        counts[r["Status"]] = counts.get(r["Status"], 0) + 1
    weeks = sorted({str(r["Sale Week"]) for r in recs})
    print(f"Spectrum Order Log: {len(recs)} line(s), weeks {weeks}, {counts}")
    for r in recs[:50]:
        print("  " + " | ".join(str(r[h]) for _, h in COLUMNS))

    name = f"Spectrum Order Log {today:%m-%d-%Y}.xlsx"
    path = to_xlsx(recs, OUT_DIR / name, today)
    print(f"  saved {path}")
    comment = "📡 Spectrum Order Log"

    # Same shape as Raf's AT&T log (Eve 2026-11-25): a channel post whose
    # thread opens with a "Tap your name" index, then one reply per rep with
    # their one-tab file — a rep finds their part from the phone without
    # scrolling. Few Spectrum reps, so ONE thread (no A-F / G-M / N-Z split).
    from automations.uploaded import order_log_split as ols
    stamp = f"{today:%m-%d-%Y}"
    split_dir = OUT_DIR / "threads" / stamp

    def _thread(client, channel):
        return ols.post_threads(client, channel, [(ols.WHOLE, path)], split_dir,
                                stamp, title_text="Spectrum Order Log",
                                emoji="📡", skip=NON_REP_TABS)

    if args.sample:
        from automations.shared.slack_metrics_post import _client
        # Lucy USER token: the bot-app token only exists on Lucy 2 (failed on
        # Lucy 4 11/25). DM Lucy <-> Eve, nobody else.
        client = _client()
        ch = client.conversations_open(users=EVE_SLACK_ID)["channel"]["id"]
        client.chat_postMessage(
            channel=ch, text=(f"SAMPLE — {comment} ({len(recs)} lines). The "
                              f"post below is what goes in #alphalete-sales "
                              f"once you say go 👇"))
        _thread(client, ch)
        print(f"  ✓ sample thread DM'd to Eve ({ch})")
        return 0
    if args.post:
        from automations.shared.slack_metrics_post import (
            SlackPostError, _client, mirror_channels, post_reply_text_only)
        if not recs:
            try:
                post_reply_text_only(
                    f"{comment} — {today:%b} {today.day} — No data available",
                    react_emoji="satellite_antenna")
            except SlackPostError as e:
                print(f"  ⚠ Slack post failed: {e}")
                return 1
            return 0
        failed = False
        try:   # a line in the Metrics thread points at the channel post
            post_reply_text_only(f"{comment} — posted in the channel 👇 "
                                 f"(open it and tap your name)",
                                 react_emoji="satellite_antenna")
        except SlackPostError as e:
            print(f"  ⚠ Metrics-thread pointer failed: {e}")
            failed = True
        client = _client()
        for ch in [METRICS_CHANNEL] + mirror_channels(METRICS_CHANNEL):
            try:
                _thread(client, ch)
                print(f"  ✓ Spectrum Order Log thread posted in {ch}")
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ Spectrum Order Log thread failed in {ch}: {e}")
                failed = True
        return 1 if failed else 0
    print("  dry run — posted nothing (--sample = DM Eve, --post = #alphalete-sales)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
