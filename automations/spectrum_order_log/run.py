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
    python -m automations.spectrum_order_log.run --sample     # DM the .xlsx to Eve only
    python -m automations.spectrum_order_log.run --post       # reply in today's Metrics thread

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


def pull() -> "tuple[list[str], list[list]]":
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
        page.goto(probe.ORDERLOG_URL, wait_until="domcontentloaded")
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
        vals = []
        for h in headers:
            v = rec[h]
            if h in ("Sale Date", "Sale Week"):
                try:
                    v = dt.datetime.strptime(str(v), "%m/%d/%Y").date()
                except ValueError:
                    pass
            elif h in ("Gig+",):
                v = "Yes" if str(v).lower() == "true" else ("No" if str(v).lower() == "false" else v)
            elif h == "PIA $":
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    pass
            else:
                v = "" if v is None else str(v)   # account #s stay text
            vals.append(v)
        ws.append(vals)
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

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", action="store_true",
                   help="DM the .xlsx to Eve only (preview)")
    g.add_argument("--post", action="store_true",
                   help="reply in today's Metrics thread (#alphalete-sales)")
    args = ap.parse_args(argv)

    today = dt.date.today()
    fields, rows = pull()
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

    if args.sample:
        from automations.shared.slack_metrics_post import dm_user_with_file
        # as_bot=False: the Lucys sign with the 'Lucy Reporting' USER token;
        # the bot-app token only exists on Lucy 2 (failed on Lucy 4 11/25).
        res = dm_user_with_file(
            path, user=EVE_SLACK_ID, file_name=name, as_bot=False,
            comment=(f"SAMPLE — {comment} ({len(recs)} lines). This is what "
                     f"will post in the Metrics thread once you say go."))
        print(f"  ✓ sample DM'd to Eve: {res}")
        return 0 if res.get("ok") else 1
    if args.post:
        from automations.shared.slack_metrics_post import (
            SlackPostError, post_reply_text_only, post_reply_with_file)
        try:
            if not recs:
                post_reply_text_only(
                    f"{comment} — {today:%b} {today.day} — No data available",
                    react_emoji="satellite_antenna")
            else:
                post_reply_with_file(path, comment=comment, file_name=name,
                                     react_emoji="satellite_antenna")
        except SlackPostError as e:
            print(f"  ⚠ Slack post failed: {e}")
            return 1
        print("  ✓ posted in today's Metrics thread")
        return 0
    print("  dry run — posted nothing (--sample = DM Eve, --post = Metrics thread)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
