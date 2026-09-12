"""SaraPlus-sourced recreations of two B2B Metrics deliverables (PREVIEW).

Carlos (2026-09-12): "recreate the AT&T order log — the Excel file — and the
activation report overview screenshot, but instead of using the info from the
[Tableau] order log, use it from SaraPlus." Tableau lags days behind;
SaraPlus is near-live (proved 2026-09-10: orders sold 9/7 already showed 9/8-
9/9 activation dates that Tableau had not surfaced).

HOW IT LINES UP (Carlos: "look at how the order log that gets posted on the
B2B metrics is made, and it should line up with that"): the two existing
deliverables are both built from "lines" — the un-pivoted Tableau ORDERLOG
rows — by att_order_log.xlsx.build and att_order_log.payout +
box_order_log.png. This module changes ONLY the source: it downloads the
SaraPlus Sales Order History CSV (native export button, Customer Type Both,
date range) and reshapes each order into that same line dict, then calls the
SAME builders. Rendering code is untouched; the live Tableau report is
untouched.

COUNTING (Carlos 2026-09-12: "count each individual product sold, each unit
sold, each application sold as one activation or one post"): a wireless
order fans out into ONE LINE PER UNIT, matching Tableau's per-line counting.
The grid's line count sizes the fan-out; a uniform order stamps every line
with the order's status; a "Partial - …" order's exact active/pending split
is read off its View Customer card ("Line Status:" per line — probed
2026-09-12), visited for Partial orders only. If a card can't be trusted
(multi-order customer merging tracking blocks), the Partial counts ONE line
active and holds the rest open — it never over-counts.

STATUS MAPPING (verified against Tableau on all 9 orders of 2026-09-03):
  SaraPlus "Active" (+ Active/Install Date)      -> "Posted" (green; activated)
  "Partial - Active/…" (some lines active)       -> "Posted - Partial" (green)
  "Cancelled"                                    -> kept (red; cancelled)
  Shipped/Scheduled/Pending/Porting/…            -> kept (yellow; still open)
Extra SaraPlus spellings are registered into att_order_log.colors at RUNTIME
(this process only) so the workbook colours them instead of flagging them.

    python -m automations.sp_order_log.run --from-file export.csv   # offline
    python -m automations.sp_order_log.run                          # pull+build
    python -m automations.sp_order_log.run --push    # + base64 the artifacts
        # into the control sheet's 'SP XLSX' / 'SP AR Shot' tabs for the mini
    lucy rerun sp_order_log        # (base_args carry --push)

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.att_order_log import colors

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "sp_order_log"

WINDOW_DAYS = 31          # same window as the Tableau order log (Carlos
                          # 2026-07-22: "just show the last 31 days of sales")

XLSX_TAB = "SP XLSX"      # base64 relay tabs on the control sheet
SHOT_TAB = "SP AR Shot"

POSTED_COL = "spe.dtr Posted Date (copy)"

# SaraPlus statuses the shared colour map doesn't know yet, coloured by
# Carlos's own logic (posted -> green, in-flight -> yellow). Registered at
# runtime so THIS process's workbook colours them; colors.py itself — and the
# Tableau report that imports it — is untouched.
_EXTRA_COLORS = {
    "posted - partial":              colors.GREEN,   # some lines active
    "shipped - delivered":           colors.YELLOW,
    "shipped - intransit":           colors.YELLOW,
    "shipped - in transit":          colors.YELLOW,
    "partial - shipped/cancelled":   colors.YELLOW,  # rest still in flight
    "resolution required - porting": colors.YELLOW,  # ≈ Tableau Porting Issue
    "pending confirmation":          colors.YELLOW,
    "processing":                    colors.YELLOW,
    # per-LINE words off the customer card + the no-card-data partial filler
    "partial - pending":             colors.YELLOW,
    "intransit":                     colors.YELLOW,
    "in transit":                    colors.YELLOW,
}


def _register_colors() -> None:
    for k, v in _EXTRA_COLORS.items():
        colors.STATUS_COLORS.setdefault(k, v)


# --- SaraPlus CSV -> Tableau-shaped lines ------------------------------------

def _parse_us_date(v: str) -> Optional[dt.date]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        m, d, y = s.split("/")
        return dt.date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _get(row: Dict[str, str], key: str) -> str:
    return " ".join(str(row.get(key, "") or "").split())


def _wireless_package(row: Dict[str, str]) -> str:
    """The order's line split, so the per-order counting hides nothing."""
    total = _get(row, "Wireless Line Count") or "?"
    bits = []
    for label, col in (("new", "New Line Count"), ("port", "Port Line Count"),
                       ("upgrade", "Upgrade Line Count"),
                       ("BYOD", "BYOD Line Count"),
                       ("hotspot", "Hotspot Count")):
        v = _get(row, col)
        if v and v not in ("0", "0.0"):
            bits.append("%s %s" % (v, label))
    return "%s line%s%s" % (total, "" if total == "1" else "s",
                            (" (%s)" % ", ".join(bits)) if bits else "")


def _map_status(raw: str, active_date: str, cancel_date: str):
    """SaraPlus product status -> (display status, posted date, status date).

    "Posted" is kept as the activated word because that is Carlos's own rule
    for the Tableau log ("keep the label Posted — everything else calls it
    posted"); an in-flight or cancelled status keeps SaraPlus's wording."""
    s = " ".join((raw or "").split())
    low = s.lower()
    if not s:
        return None
    if low == "active":
        return ("Posted", active_date, active_date)
    if low.startswith("partial - active"):
        return ("Posted - Partial", active_date, active_date)
    # Activated-then-churned orders ("Active/Cancelled", "Active/Disconnected")
    # get the plain terminal word — exactly what Tableau's log shows for them,
    # and the only spelling payout's cancelled bucket matches. The date is the
    # cancel date so the loss lands in the week it happened.
    if low in ("cancelled", "canceled", "active/cancelled", "active/canceled"):
        d = cancel_date or active_date
        return ("Cancelled", d, d)
    if low in ("disconnected", "active/disconnected"):
        d = cancel_date or active_date
        return ("Disconnected", d, d)
    return (s, "", "")


def _map_line_status(raw_line_status: str, active_date: str, cancel_date: str):
    """A SINGLE wireless line's status word (from the customer card:
    'Active' / 'Delivered' / 'Shipped' / 'InTransit' / 'Cancelled' / ...)
    -> (display status, posted date, status date). Active = the activated
    unit (green 'Posted'); everything else keeps its word and stays open."""
    s = " ".join((raw_line_status or "").split())
    low = s.lower()
    if low == "active":
        return ("Posted", active_date, active_date)
    if low in ("cancelled", "canceled"):
        d = cancel_date or active_date
        return ("Cancelled", d, d)
    if low == "disconnected":
        d = cancel_date or active_date
        return ("Disconnected", d, d)
    return (s or "Pending", "", "")


def shape_lines(csv_bytes: bytes, log=print,
                per_line_splits: Optional[Dict[str, list]] = None
                ) -> List[Dict[str, str]]:
    """Tableau-shaped lines from the SaraPlus export — ONE LINE PER UNIT.

    A wireless order fans out to its line count (Carlos 2026-09-12: count each
    unit as one activation). `per_line_splits` maps an order id to the list of
    that order's per-line status words read off its customer card — supplied
    for Partial orders so the active/pending split is exact; absent, a Partial
    counts one line active and holds the rest open."""
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    from automations.shared.name_case import titlecase_name

    lines: List[Dict[str, str]] = []
    skipped = 0
    for row in rows:
        order_id = _get(row, "Order ID")
        if not order_id:
            continue
        rep = titlecase_name(_get(row, "User Name"))
        order_date = _get(row, "Order Date")
        base = {
            "Rep": rep,
            "sp.Order Date (copy)": order_date,
            "Customer Name": titlecase_name(_get(row, "Customer Name")),
            "CRU/IRU": "",
            "spe.TN": "",
            "spe.TN Type": "",
            "sp.SPM Number": order_id,
            "spe.Phone": _get(row, "Phone"),
            "Wireless Installment Plan": "",
            "IF/OOF": "",
            "spe.Install Date": "",
            "Order date to Install Date Days": "",
        }

        made_one = False
        # -- wireless: ONE LINE PER UNIT (Carlos 2026-09-12: "count each
        # individual product sold, each unit sold, each application sold as
        # one activation or one post"). N comes from the grid's line count;
        # a uniform order stamps every line with the order's status, and a
        # Partial order's exact active/pending split is resolved from the
        # customer card (per_line_splits) when we have it.
        if _get(row, "Wireless Status"):
            raw_status = _get(row, "Wireless Status")
            mapped = _map_status(raw_status,
                                 _get(row, "Wireless Active Date"),
                                 _get(row, "Wireless Cancel Date"))
            if mapped:
                status, posted, sdate = mapped
                try:
                    n = max(1, int(float(_get(row, "Wireless Line Count") or 1)))
                except ValueError:
                    n = 1
                split = (per_line_splits or {}).get(order_id)
                for i in range(n):
                    li_status, li_posted, li_sdate = status, posted, sdate
                    if split:
                        li_raw = split[i] if i < len(split) else split[-1]
                        m = _map_line_status(
                            li_raw, _get(row, "Wireless Active Date"),
                            _get(row, "Wireless Cancel Date"))
                        li_status, li_posted, li_sdate = m
                    elif status == "Posted - Partial":
                        # No card data for this partial: count ONE line
                        # activated (a Partial guarantees at least one) and
                        # hold the rest open — never over-counts.
                        if i == 0:
                            li_status = "Posted"
                        else:
                            li_status, li_posted, li_sdate = \
                                "Partial - pending", "", ""
                    ln = dict(base)
                    ln.update({
                        "Product Type (Broken Out)": "WIRELESS",
                        "DTR Status (enriched)": li_status,
                        "DTR Status Date": li_sdate,
                        POSTED_COL: li_posted,
                        "spe.TN": "line %d of %d" % (i + 1, n),
                        "spe.Account BAN": _get(row, "Wireless Acct #"),
                        "Package": _wireless_package(row),
                    })
                    lines.append(ln)
                made_one = True
        # -- internet ------------------------------------------------------
        if _get(row, "Internet Status"):
            mapped = _map_status(_get(row, "Internet Status"),
                                 _get(row, "Internet Install Date"),
                                 _get(row, "Internet Cancel Date"))
            if mapped:
                status, posted, sdate = mapped
                install = _get(row, "Internet Install Date")
                od, idd = _parse_us_date(order_date), _parse_us_date(install)
                ln = dict(base)
                ln.update({
                    "Product Type (Broken Out)": "NEW INTERNET",
                    "DTR Status (enriched)": status,
                    "DTR Status Date": sdate,
                    POSTED_COL: posted,
                    "spe.Account BAN": _get(row, "Internet Acct #"),
                    "Package": _get(row, "Internet Package"),
                    "spe.Install Date": install,
                    "Order date to Install Date Days":
                        str((idd - od).days) if (od and idd) else "",
                })
                lines.append(ln)
                made_one = True
        # -- voice / video (rare on this board; kept so nothing vanishes) --
        for prod, label in (("Voice", "VOICE"), ("Video", "VIDEO")):
            if not _get(row, "%s Status" % prod):
                continue
            mapped = _map_status(
                _get(row, "%s Status" % prod),
                _get(row, "%s Active Date" % prod)
                or _get(row, "%s Install Date" % prod),
                _get(row, "%s Cancel Date" % prod))
            if mapped:
                status, posted, sdate = mapped
                ln = dict(base)
                ln.update({
                    "Product Type (Broken Out)": label,
                    "DTR Status (enriched)": status,
                    "DTR Status Date": sdate,
                    POSTED_COL: posted,
                    "spe.Account BAN": _get(row, "%s Acct #" % prod),
                    "Package": _get(row, "%s Package" % prod),
                })
                lines.append(ln)
                made_one = True
        if not made_one:
            skipped += 1
            log("  (no product status on order %s — %s; skipped)"
                % (order_id, _get(row, "Customer Name") or "?"))

    log("shaped %d line(s) from %d SaraPlus order row(s)%s"
        % (len(lines), len(rows),
           ("; %d had no product status" % skipped) if skipped else ""))
    unknown = colors.unmapped(
        ln.get("DTR Status (enriched)", "") for ln in lines)
    if unknown:
        log("  !! statuses with NO colour rule (render white): %s"
            % "; ".join(unknown))
    return lines


# --- the two deliverables -----------------------------------------------------

def build_xlsx(lines, today: dt.date, log=print) -> Path:
    from automations.att_order_log import xlsx
    out = OUT_DIR / "SP ATT Order Log {}.xlsx".format(today.strftime("%m-%d-%Y"))
    xlsx.build(lines, out, today=today)
    log("order log workbook -> %s (%s bytes)"
        % (out.name, "{:,}".format(out.stat().st_size)))
    return out


def build_overview_png(lines, today: dt.date, log=print) -> Path:
    """The Activation Report Overview, exactly as capture.payout_image builds
    it — same tables, same renderer, same column headers — from these lines."""
    from automations.att_order_log import payout as ap
    from automations.box_order_log import png as bpng

    tables = ap.build_week_tables(lines, today)
    for wk in ("last", "this"):
        for r in tables[wk]["rows"]:
            r["posted"] = r.pop("activated")
            r["pending"] = r.pop("open")
        # The renderer's TOTAL strip now reads the table's own totals dict
        # (box png 31ddeb9d), so its keys need the same remap as the rows.
        t = tables[wk].get("totals")
        if t and "activated" in t:
            t["posted"] = t.pop("activated")
            t["pending"] = t.pop("open")
    out = OUT_DIR / "sp_activation_overview.png"
    saved_cols = list(bpng.COLS)
    bpng.COLS[:] = [
        ("Rep Name", "rep", "left"),
        ("Posted", "posted", "center"),
        ("Cancelled", "canceled", "center"),
        ("Still Open", "pending", "center"),
    ]
    try:
        bpng.render(tables, out,
                    subtitle="SOURCE: SaraPlus (near-live) — every line/unit "
                             "counts as one. Posted & Cancelled are for that "
                             "week — pay follows. Still Open = not yet "
                             "posted, any week.")
    finally:
        bpng.COLS[:] = saved_cols
    log("activation overview -> %s (%s bytes)"
        % (out.name, "{:,}".format(out.stat().st_size)))
    return out


# --- SaraPlus pull (Lucy 2) ---------------------------------------------------

def _partial_orders(csv_bytes: bytes) -> Dict[str, int]:
    """{order id: wireless line count} for orders whose wireless status is
    'Partial - …' — the ones whose active/pending split only the customer
    card can settle."""
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    out: Dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(text)):
        oid = _get(row, "Order ID")
        if not oid:
            continue
        if _get(row, "Wireless Status").lower().startswith("partial"):
            try:
                out[oid] = max(1, int(float(_get(row, "Wireless Line Count") or 1)))
            except ValueError:
                out[oid] = 1
    return out


def _read_partial_splits(page, partials: Dict[str, int], log=print
                         ) -> Dict[str, list]:
    """Open each Partial order's View Customer card off the loaded grid and
    read its per-line statuses ('Line Status: Active / Delivered / …').

    The RadWindow reuses one iframe and can briefly show the PREVIOUS
    customer (seen on the 2026-09-12 probe), so the card is only trusted
    once a frame carries THIS order's id. A split is kept only when the card
    yields exactly the order's line count — a customer with two wireless
    orders merges their tracking blocks, and a miscounted split would
    misattribute lines."""
    from automations.rc_contact_sync import config as C

    splits: Dict[str, list] = {}
    for oid, n in partials.items():
        res = page.evaluate(
            """(cfg) => {
                 const data = document.getElementById(cfg.gid);
                 if (!data) return 'no grid';
                 const row = [...data.querySelectorAll('tbody > tr')]
                   .find(r => (r.innerText || '').includes(cfg.oid));
                 if (!row) return 'row not found';
                 const e = [...row.querySelectorAll('a')]
                   .find(x => /view/i.test(x.innerText || ''));
                 if (!e) return 'no View link';
                 e.click();
                 return 'clicked';
               }""", {"gid": C.GRID_DATA, "oid": oid})
        if res != "clicked":
            log("  card %s: %s" % (oid, res))
            continue
        txt = ""
        for _ in range(10):                       # up to ~15s for the RIGHT card
            page.wait_for_timeout(1500)
            for fr in page.frames:
                if fr == page.main_frame:
                    continue
                try:
                    t = fr.evaluate("() => (document.body.innerText || '')") or ""
                except Exception:  # noqa: BLE001
                    continue
                if oid in t:
                    txt = t
                    break
            if txt:
                break
        if txt:
            sts = [s.strip() for s in
                   re.findall(r"Line Status:\s*\n\s*([^\n]+)", txt)]
            if len(sts) == n:
                splits[oid] = sts
                log("  card %s: %s" % (oid, ", ".join(sts)))
            else:
                log("  card %s: %d Line Status block(s) for %d line(s) — "
                    "NOT trusted (multi-order customer?)" % (oid, len(sts), n))
        else:
            log("  card %s: never showed this order — skipped" % oid)
        page.evaluate(
            """() => {
                 const els = [...document.querySelectorAll('a')];
                 const b = els.find(e => /rwCloseButton|CloseButton/i.test(e.className || ''))
                        || els.find(e => /^close$/i.test((e.textContent || '').trim()));
                 if (b) b.click();
               }""")
        page.wait_for_timeout(1200)
    return splits


def pull_csv(start: dt.date, end: dt.date, *, headless: bool = True,
             log=print):
    """-> (csv bytes, {partial order id: per-line status list}). One browser
    session does both: export the grid, then open only the Partial orders'
    customer cards to settle their line splits."""
    from patchright.sync_api import sync_playwright

    from automations.rc_contact_sync import config as C
    from automations.rc_contact_sync import sara
    from automations.rc_contact_sync.status_probe import _export_csv

    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = sara.login(page, cr["email"], cr["password"], log=log)
            log("logged in as %s" % cr["email"])
            page.goto(base + C.HUB_PATH, wait_until="networkidle",
                      timeout=C.NAV_TIMEOUT_MS)
            sara.open_order_history_panel(page, log=log)
            sara._set_telerik_date(page, C.FIELD_START, start)
            sara._set_telerik_date(page, C.FIELD_END, end)
            sara._set_customer_type(page, C.CUSTOMER_TYPE_BOTH, log=log)
            # Customer Type autoposts back and can reset the dates.
            sara._set_telerik_date(page, C.FIELD_START, start)
            sara._set_telerik_date(page, C.FIELD_END, end)
            sara._submit(page, log=log)
            data = _export_csv(page, log)
            if data is None:
                raise sara.SaraError("the CSV export produced no download")
            partials = _partial_orders(data)
            log("%d Partial order(s) need their customer card" % len(partials))
            splits = _read_partial_splits(page, partials, log=log) \
                if partials else {}
            return data, splits
        finally:
            ctx.close()


def _push(path: Path, tab: str, log=print) -> None:
    from automations.rc_contact_sync.status_probe import _upload_bytes
    _upload_bytes(path.read_bytes(), tab, log=log)


# --- main ---------------------------------------------------------------------

def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(
        prog="sp_order_log",
        description="AT&T order log workbook + activation overview PNG, "
                    "built from SaraPlus instead of Tableau (preview).")
    ap_.add_argument("--start", default=None, metavar="YYYY-MM-DD",
                     help="pull range start (default: today - %d)" % WINDOW_DAYS)
    ap_.add_argument("--end", default=None, metavar="YYYY-MM-DD",
                     help="pull range end (default: today)")
    ap_.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                     help="'today' for the week tables (default: real today)")
    ap_.add_argument("--from-file", default=None, metavar="CSV",
                     help="parse this SaraPlus export instead of pulling")
    ap_.add_argument("--push", action="store_true",
                     help="base64 the two artifacts into the control sheet "
                          "('%s' / '%s') for the mini" % (XLSX_TAB, SHOT_TAB))
    ap_.add_argument("--headed", action="store_true")
    args = ap_.parse_args(argv)

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _register_colors()

    splits: Dict[str, list] = {}
    if args.from_file:
        data = Path(args.from_file).read_bytes()
        print("using %s (%s bytes; no card visits — Partial orders count "
              "one line active)" % (args.from_file, "{:,}".format(len(data))))
    else:
        start = (dt.date.fromisoformat(args.start) if args.start
                 else today - dt.timedelta(days=WINDOW_DAYS))
        end = dt.date.fromisoformat(args.end) if args.end else today
        print("SaraPlus pull %s..%s (Customer Type Both)" % (start, end))
        data, splits = pull_csv(start, end, headless=not args.headed)
        raw = OUT_DIR / "sp_export_{}.csv".format(today.isoformat())
        raw.write_bytes(data)
        print("export saved: %s (%s bytes)" % (raw.name, "{:,}".format(len(data))))

    lines = shape_lines(data, per_line_splits=splits)
    if not lines:
        print("no lines shaped — nothing to build")
        print("=== done ===", flush=True)
        return 1

    xlsx_path = build_xlsx(lines, today)
    png_path = build_overview_png(lines, today)
    if args.push:
        _push(xlsx_path, XLSX_TAB)
        _push(png_path, SHOT_TAB)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
