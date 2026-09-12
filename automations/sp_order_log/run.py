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
    # per-LINE words off the customer card / Wireless panel
    "partial - pending":             colors.YELLOW,
    "intransit":                     colors.YELLOW,
    "in transit":                    colors.YELLOW,
    "pending activation":            colors.YELLOW,
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
    """A SINGLE wireless line's status word ('Active' / 'Delivered' /
    'Shipped' / 'Porting Issue' / ...) -> (display status, posted date,
    status date). Active = the activated unit (green 'Posted'); everything
    else keeps its word and stays open."""
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


def _iso_to_us(iso: str) -> str:
    """Tracked dates are ISO; the line dicts carry M/D/YYYY like Tableau."""
    try:
        d = dt.date.fromisoformat(iso)
        return "%d/%02d/%d" % (d.month, d.day, d.year)
    except (ValueError, TypeError):
        return ""


def shape_lines(csv_bytes: bytes, log=print,
                wl_lines: Optional[list] = None,
                act_dates: Optional[Dict[str, str]] = None
                ) -> List[Dict[str, str]]:
    """Tableau-shaped lines from the SaraPlus export — ONE LINE PER UNIT.

    Wireless orders are built from the Wireless panel's PER-LINE rows
    (`wl_lines`, wireless_lines.parse_wireless_xls) with each Active line
    dated by the tracker (`act_dates`, {line key: ISO date}) — the same
    per-line activation basis the DD pays on. An order missing from the
    wireless report falls back to the order-level fan-out (every line gets
    the order's status and first-activation date)."""
    from automations.sp_order_log import wireless_lines as WL

    text = csv_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    from automations.shared.name_case import titlecase_name

    wl_by_order: Dict[str, list] = {}
    for wl in (wl_lines or []):
        wl_by_order.setdefault(wl["order_id"], []).append(wl)
    act_dates = act_dates or {}

    lines: List[Dict[str, str]] = []
    skipped = 0
    from_panel = 0
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
        # one activation or one post"). The Wireless panel's per-line rows
        # carry each unit's own status; the tracker dates each Active line
        # by the day it FIRST showed Active (the DD's own pay basis).
        if _get(row, "Wireless Status"):
            panel = wl_by_order.get(order_id)
            if panel:
                for wl in panel:
                    key = WL.line_key(wl)
                    a_us = (_iso_to_us(act_dates.get(key, ""))
                            or _get(row, "Wireless Active Date"))
                    li_status, li_posted, li_sdate = _map_line_status(
                        wl["line_status"], a_us,
                        _get(row, "Wireless Cancel Date"))
                    ln = dict(base)
                    ln.update({
                        "Product Type (Broken Out)": WL.product_of(wl),
                        "DTR Status (enriched)": li_status,
                        "DTR Status Date": li_sdate,
                        POSTED_COL: li_posted,
                        "spe.TN": wl["tn"],
                        "spe.TN Type": wl["line_type"],
                        "spe.Account BAN": _get(row, "Wireless Acct #"),
                        "Package": wl["device"] or wl["plan"],
                    })
                    lines.append(ln)
                    from_panel += 1
                made_one = True
            else:
                # Not in the wireless report (window edge / non-mobility):
                # order-level fan-out, every line on the order's status and
                # first-activation date.
                mapped = _map_status(_get(row, "Wireless Status"),
                                     _get(row, "Wireless Active Date"),
                                     _get(row, "Wireless Cancel Date"))
                if mapped:
                    status, posted, sdate = mapped
                    if status == "Posted - Partial":
                        status = "Posted"
                    try:
                        n = max(1, int(float(_get(row, "Wireless Line Count") or 1)))
                    except ValueError:
                        n = 1
                    for i in range(n):
                        ln = dict(base)
                        ln.update({
                            "Product Type (Broken Out)": "WIRELESS",
                            "DTR Status (enriched)": status,
                            "DTR Status Date": sdate,
                            POSTED_COL: posted,
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

    log("shaped %d line(s) from %d SaraPlus order row(s) (%d per-line from "
        "the wireless panel)%s"
        % (len(lines), len(rows), from_panel,
           ("; %d had no product status" % skipped) if skipped else ""))
    unknown = colors.unmapped(
        ln.get("DTR Status (enriched)", "") for ln in lines)
    if unknown:
        log("  !! statuses with NO colour rule (render white): %s"
            % "; ".join(unknown))
    return lines


# --- the two deliverables -----------------------------------------------------

def build_xlsx(lines, today: dt.date, log=print,
               out_path: Optional[Path] = None) -> Path:
    from automations.att_order_log import xlsx
    out = out_path or (OUT_DIR / "SP ATT Order Log {}.xlsx".format(
        today.strftime("%m-%d-%Y")))
    xlsx.build(lines, out, today=today)
    log("order log workbook -> %s (%s bytes)"
        % (out.name, "{:,}".format(out.stat().st_size)))
    return out


def build_overview_png(lines, today: dt.date, log=print,
                       out_path: Optional[Path] = None) -> Path:
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
    out = out_path or (OUT_DIR / "sp_activation_overview.png")
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


def _sp_parse_date(s: str):
    """M/D/YYYY (or MM/DD/YYYY) -> date, else None."""
    try:
        m, d, y = (int(x) for x in s.strip().split("/"))
        return dt.date(y if y > 99 else 2000 + y, m, d)
    except Exception:  # noqa: BLE001
        return None


def _load_sow_periods(log=print) -> list:
    """[{effective: date, nonbyod_tier, byod_tier, air_tier}] sorted by
    effective date, from sow_tiers.json — the SOW Change Notice periods."""
    import json as _json
    p = Path(__file__).resolve().parent / "sow_tiers.json"
    try:
        raw = _json.loads(p.read_text())["periods"]
        out = sorted(
            ({**r, "effective": dt.date.fromisoformat(r["effective"])}
             for r in raw), key=lambda r: r["effective"])
        log("SOW periods: %d, newest effective %s (NB T%s / BYOD T%s / AIR T%s)"
            % (len(out), out[-1]["effective"].isoformat(),
               out[-1]["nonbyod_tier"], out[-1]["byod_tier"],
               out[-1]["air_tier"]))
        return out
    except Exception as e:  # noqa: BLE001
        log("SOW periods unavailable (%s) — legacy base rates stand"
            % type(e).__name__)
        return []


def _orderlog_attrs(log=print) -> dict:
    """{10-digit TN: {pricing fields}} from the newest Tableau order-log
    export on this box — the cross-reference Carlos named ('just look up the
    sale in the order log'). Sources, best first:
      1. output/captainship_boards/orderlog_*.csv — the 47-col export the
         Vantura revenue board prices (carries Auto Bill Pay).
      2. output/b2b_metrics/_shared/orderlog_*.csv — the 17-col crosstab
         (no ABP, but CRU/IRU / BYOD / OOF / Package).
    Best-effort: no file -> {} and the conservative defaults stand."""
    import csv as _csv
    from automations.sp_order_log.wireless_lines import norm_tn
    repo = Path(__file__).resolve().parents[2]
    fields = ("CRU/IRU", "Auto Bill Pay", "IF/OOF",
              "Wireless Installment Plan", "Package")
    # MERGE both sources — never stop at the first. The captainship export
    # only spans the CURRENT week (the revenue board pulls Mon->yesterday),
    # so on its own it matched 68/613 lines (2026-09-14); the 31-day shared
    # crosstab backfills everything older, captainship still wins per-TN for
    # its ABP field.
    out: dict = {}
    for sub in ("captainship_boards", "b2b_metrics/_shared"):
        cands = sorted((repo / "output" / sub).glob("orderlog_*.csv"))
        if not cands:
            continue
        src = cands[-1]
        added = 0
        try:
            with open(src, newline="", encoding="utf-8-sig",
                      errors="replace") as fh:
                for r in _csv.DictReader(fh):
                    tn = norm_tn(str(r.get("spe.TN") or ""))
                    if not tn or tn in out:
                        continue
                    out[tn] = {f: str(r.get(f) or "").strip()
                               for f in fields}
                    added += 1
        except Exception as e:  # noqa: BLE001
            log("orderlog attrs: %s unreadable (%s)" % (src.name,
                                                        type(e).__name__))
            continue
        log("orderlog attrs: +%d TN(s) from %s (total %d)"
            % (added, src.name, len(out)))
    return out


def build_revenue_png(lines, today: dt.date, log=print,
                      out_path: Optional[Path] = None) -> Path:
    """The Activation Overview's REVENUE TWIN (Carlos 2026-09-14: copy what
    the Box thread just got — 'Box now has a version where it shows the
    revenue that got activated' — for AT&T B2B off the SaraPlus
    activations). Same two week tables, same renderer, money=True: every
    unit priced on the office comp (vantura_payout_estimate.price — the
    pricer the Vantura revenue board uses) and the weekly Tiered Volume
    bonus rolled into each rep's activated $.

    Deliberately a LOCAL money variant rather than a money_fn bolted onto
    att_order_log.payout.build_week_tables — that builder feeds every
    office's Tableau path (see README playbook: change one layer, watch
    another break).

    PRICING ASSUMPTIONS (SaraPlus doesn't carry these fields; stated in the
    image subtitle so the number reads as what it is): CRU/IRU unknown ->
    priced as CRU and every eligible unit counts toward the tier bonus; no
    ABP/OOF flags -> those bumps aren't added (conservative); BYOD read
    from the device string; TABLET units unpriced ($0)."""
    from automations.att_order_log import payout as ap
    from automations.box_order_log import png as bpng
    from automations.vantura_payout_estimate.run import price
    from automations.vantura_revenue_board.run import tier_for
    from automations.sp_order_log.wireless_lines import norm_tn

    # Cross-reference the ORDER LOG for the fields SaraPlus doesn't carry
    # (Carlos 2026-09-14: "you still have access to the order log ... it's
    # still the same sale" — the log lags on STATUS, not on the sale's own
    # attributes). Joined by line number (TN); the 47-col captainship export
    # (the DD-reconciled pricing source) is preferred because it carries
    # Auto Bill Pay; the 17-col shared crosstab backfills CRU/IRU, BYOD,
    # OOF and Package when that's all we have.
    ENRICH_FIELDS = ("CRU/IRU", "Auto Bill Pay", "IF/OOF",
                     "Wireless Installment Plan", "Package")
    attrs = _orderlog_attrs(log=log)
    matched = [0]

    # SOW-declared tier pricing by SALE DATE (Carlos 2026-09-14: the
    # 'ATT-B2B-SBS SOW Revised Change and Churn Notice' email declares the
    # office's Port/AIR commission tiers per period — 'any sales from that
    # date forward are in whatever tier the email says', a near-identical
    # notice lands before each month). sow_tiers.json holds the periods; the
    # rate tables below are Schedule A's own (Effective 09/07/2026). For a
    # sale on/after a period's effective date, the port/AIR BASE price is
    # swapped from the legacy comp-sheet base to the SOW rate at the declared
    # tier — price()'s add-ons (ABP, Next Up, premium, internet/AIR ABP)
    # stay on top, untouched.
    NONBYOD_SOW = {1: (150, 135, 230, 135), 2: (160, 145, 240, 145),
                   3: (170, 155, 250, 155), 4: (180, 165, 260, 165),
                   5: (190, 175, 270, 175), 6: (210, 195, 290, 195)}
    BYOD_SOW = {1: (60, 75, 145, 75), 2: (85, 95, 170, 95),
                3: (110, 115, 195, 115), 4: (135, 125, 220, 125),
                5: (160, 135, 245, 135), 6: (185, 155, 270, 155)}
    AIR_SOW = {1: (208, 70), 2: (228, 80), 3: (288, 110),
               4: (308, 120), 5: (328, 130)}
    periods = _load_sow_periods(log=log)

    def _sow_adjust(row, sale_date) -> float:
        """SOW base minus the legacy base price() already charged, or 0."""
        per = None
        for pd_ in periods:
            if sale_date is not None and sale_date >= pd_["effective"]:
                per = pd_
        if per is None:
            return 0.0
        prod = str(row.get("Product Type (Broken Out)") or "").upper()
        cru = str(row.get("CRU/IRU") or "").strip().upper() or "CRU"
        tn = str(row.get("spe.TN Type") or "").lower()
        oof = str(row.get("IF/OOF") or "").strip().upper() == "OOF"
        byod = str(row.get("Wireless Installment Plan") or "").upper() == "BYOD"
        if prod == "WIRELESS" and tn == "port":
            table = BYOD_SOW if byod else NONBYOD_SOW
            tier = per["byod_tier"] if byod else per["nonbyod_tier"]
            r = table.get(tier)
            if not r:
                return 0.0
            sow = (r[2] if cru == "CRU" else r[3]) if oof else \
                  (r[0] if cru == "CRU" else r[1])
            if cru == "CRU":
                legacy = (255 if byod else 295) if oof else (170 if byod else 215)
            else:
                legacy = 25 if byod else 165
            return float(sow - legacy)
        if prod == "AIR/AWB":
            r = AIR_SOW.get(per["air_tier"])
            if not r:
                return 0.0
            sow = r[0] if cru == "CRU" else r[1]
            legacy = (268 + 20) if cru == "CRU" else (100 + 10)
            return float(sow - legacy)
        return 0.0

    def _amount(ln) -> float:
        row = dict(ln)
        hit = attrs.get(norm_tn(str(row.get("spe.TN") or "")))
        if hit:
            matched[0] += 1
            for f in ENRICH_FIELDS:
                if hit.get(f) and not str(row.get(f) or "").strip():
                    row[f] = hit[f]
        pkg = str(row.get("Package") or "")
        if not str(row.get("Wireless Installment Plan") or "").strip() \
                and "BYOD" in pkg.upper():
            row["Wireless Installment Plan"] = "BYOD"
        # keep the enriched CRU/IRU on the line for the payable rule below
        ln["_cru"] = str(row.get("CRU/IRU") or "").strip().upper() or "CRU"
        amt, _label, _notes = price(row)
        sale_date = _sp_parse_date(str(row.get("sp.Order Date (copy)") or ""))
        return float(amt or 0) + _sow_adjust(row, sale_date)

    def _eligible(ln) -> bool:
        prod = str(ln.get("Product Type (Broken Out)") or "").upper()
        tn = str(ln.get("spe.TN Type") or "").lower()
        if prod in ("VOICE", "VIDEO") or tn == "upgrade":
            return False
        # vantura rule: IRU Air is not payable toward the tier bonus.
        return not (prod == "AIR/AWB" and ln.get("_cru") == "IRU")

    ls, le, ts, te = ap.week_bounds(today)
    reps: dict = {}
    for ln in lines:
        rep = str(ln.get("Rep", "") or "").strip()
        if not rep:
            continue
        a = reps.setdefault(rep, {"open": 0.0, "act_last": 0.0,
                                  "act_this": 0.0, "can_last": 0.0,
                                  "can_this": 0.0, "n_last": 0, "n_this": 0})
        posted = ap._parse_date(ln.get(ap.POSTED_DATE_COL))
        status = str(ln.get("DTR Status (enriched)", "")).strip().lower()
        amt = _amount(ln)
        if status in ap.CANCEL_STATUSES:
            if ap._in_week(posted, ls, le):
                a["can_last"] += amt
            elif ap._in_week(posted, ts, te):
                a["can_this"] += amt
        elif posted is None:
            a["open"] += amt
        else:
            if ap._in_week(posted, ls, le):
                a["act_last"] += amt
                a["n_last"] += 1 if _eligible(ln) else 0
            elif ap._in_week(posted, ts, te):
                a["act_this"] += amt
                a["n_this"] += 1 if _eligible(ln) else 0

    def _table(start, end, act_key, can_key, n_key):
        rows = []
        for rep, a in reps.items():
            _t, rate = tier_for(a[n_key])
            rows.append({"rep": rep,
                         "posted": round(a[act_key] + rate * a[n_key]),
                         "pending": round(a["open"]),
                         "canceled": round(a[can_key])})
        rows.sort(key=lambda r: (-r["posted"], -r["pending"],
                                 r["rep"].lower()))
        totals = {k: sum(r[k] for r in rows)
                  for k in ("posted", "pending", "canceled")}
        return {"label": ap.label(start, end), "rows": rows,
                "totals": totals}

    tables = {"last": _table(ls, le, "act_last", "can_last", "n_last"),
              "this": _table(ts, te, "act_this", "can_this", "n_this")}
    out = out_path or (OUT_DIR / "activation_revenue.png")
    saved_cols = list(bpng.COLS)
    bpng.COLS[:] = [
        ("Rep Name", "rep", "left"),
        ("Posted $", "posted", "center"),
        ("Cancelled $", "canceled", "center"),
        ("Still Open $", "pending", "center"),
    ]
    n_lines = sum(1 for ln in lines if str(ln.get("Rep") or "").strip())
    if periods:
        pp = periods[-1]
        sow_note = ("SOW tiers NB T{} / BYOD T{} / AIR T{} (eff {}) by sale "
                    "date. ").format(pp["nonbyod_tier"], pp["byod_tier"],
                                     pp["air_tier"],
                                     pp["effective"].strftime("%-m/%-d"))
    else:
        sow_note = ""
    try:
        bpng.render(
            tables, out, money=True,
            subtitle="Activated $ by activation week, weekly volume bonus "
                     "included. " + sow_note +
                     "CRU/IRU, ABP, OOF, BYOD cross-referenced from the "
                     "order log by line ({}/{} matched); unmatched priced "
                     "as CRU, no ABP/OOF. Tablets unpriced.".format(
                         matched[0], n_lines))
    finally:
        bpng.COLS[:] = saved_cols
    log("activation revenue -> %s (%s bytes, %d/%d lines enriched)"
        % (out.name, "{:,}".format(out.stat().st_size), matched[0], n_lines))
    return out


# --- SaraPlus pull (Lucy 2) ---------------------------------------------------

def pull_csv(start: dt.date, end: dt.date, *, headless: bool = True,
             log=print):
    """-> (soh csv bytes, wireless report bytes or None). One browser
    session, two downloads: the Sales Order History export and the Wireless
    panel's per-LINE report."""
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
            # Same session, one more download: the Wireless panel's per-LINE
            # report — every order's individual lines with their own status.
            from automations.sp_order_log import wireless_lines as WL
            wl_bytes = WL.pull_wireless(page, start, end, log=log)
            return data, wl_bytes
        finally:
            ctx.close()


def _push(path: Path, tab: str, log=print) -> None:
    from automations.rc_contact_sync.status_probe import _upload_bytes
    _upload_bytes(path.read_bytes(), tab, log=log)


def track_lines(data: bytes, wl_bytes, today: dt.date, log=print):
    """The activation-date tracker: fold today's per-line statuses into the
    state file; a line's date is the day WE first saw it Active (seeded from
    Tableau's per-line posted history / the order date on adoption).
    -> (parsed wireless lines, {line key: activation date ISO})."""
    from automations.sp_order_log import wireless_lines as WL

    wl_parsed: list = []
    act_dates: Dict[str, str] = {}
    if wl_bytes:
        wl_parsed = WL.parse_wireless_xls(wl_bytes)
        log("wireless report: %d line(s) across %d order(s)"
            % (len(wl_parsed), len({w["order_id"] for w in wl_parsed})))
        state = WL.load_state()
        needs_seed = any(
            w["line_status"].strip().lower() == "active"
            and "first_active" not in state.get(WL.line_key(w), {})
            for w in wl_parsed)
        seed = WL.build_tableau_seed(log=log) if needs_seed else {}
        soh_active: Dict[str, str] = {}
        for row in csv.DictReader(io.StringIO(
                data.decode("utf-8-sig", errors="replace"))):
            oid, ad = _get(row, "Order ID"), _get(row, "Wireless Active Date")
            d = _parse_us_date(ad)
            if oid and d:
                soh_active[oid] = d.isoformat()
        act_dates = WL.update_state(state, wl_parsed, today, seed, soh_active,
                                    log=log)
        WL.save_state(WL.prune_state(state, today))
    else:
        log("NO wireless per-line report — wireless orders fall back to "
            "order-level dating")
    return wl_parsed, act_dates


def build_artifacts(out_dir: Optional[Path] = None,
                    today: Optional[dt.date] = None, log=print) -> Dict[str, Path]:
    """One-call build for the B2B Metrics runner (Carlos 2026-09-14: 'have
    this replace the one that was being made through Tableau'): pull
    SaraPlus, update the line tracker, and write BOTH artifacts under the
    runner's own filenames. Returns {"xlsx": Path, "png": Path}; raises on
    any failure so the caller (b2b_metrics.capture) can fall back to the
    Tableau path and the thread never goes without its sections."""
    today = today or dt.date.today()
    _register_colors()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = today - dt.timedelta(days=WINDOW_DAYS)
    log("SaraPlus pull %s..%s (Customer Type Both)" % (start, today))
    data, wl_bytes = pull_csv(start, today)
    (OUT_DIR / "sp_export_{}.csv".format(today.isoformat())).write_bytes(data)
    wl_parsed, act_dates = track_lines(data, wl_bytes, today, log=log)
    lines = shape_lines(data, log=log, wl_lines=wl_parsed, act_dates=act_dates)
    if not lines:
        raise RuntimeError("no lines shaped from the SaraPlus export")
    dest = Path(out_dir) if out_dir else OUT_DIR
    dest.mkdir(parents=True, exist_ok=True)
    xlsx_path = build_xlsx(
        lines, today, log=log,
        out_path=dest / "ATT Order Log {}.xlsx".format(today.strftime("%m-%d-%Y")))
    png_path = build_overview_png(
        lines, today, log=log, out_path=dest / "activation_overview.png")
    revenue_path = build_revenue_png(
        lines, today, log=log, out_path=dest / "activation_revenue.png")
    return {"xlsx": xlsx_path, "png": png_path, "revenue": revenue_path}


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
    ap_.add_argument("--wireless-file", default=None, metavar="XLS",
                     help="with --from-file: this Wireless Resolution Report "
                          "export (offline testing)")
    ap_.add_argument("--push", action="store_true",
                     help="base64 the two artifacts into the control sheet "
                          "('%s' / '%s') for the mini" % (XLSX_TAB, SHOT_TAB))
    ap_.add_argument("--headed", action="store_true")
    args = ap_.parse_args(argv)

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _register_colors()

    from automations.sp_order_log import wireless_lines as WL

    wl_bytes = None
    if args.from_file:
        data = Path(args.from_file).read_bytes()
        print("using %s (%s bytes)" % (args.from_file, "{:,}".format(len(data))))
        if args.wireless_file:
            wl_bytes = Path(args.wireless_file).read_bytes()
    else:
        start = (dt.date.fromisoformat(args.start) if args.start
                 else today - dt.timedelta(days=WINDOW_DAYS))
        end = dt.date.fromisoformat(args.end) if args.end else today
        print("SaraPlus pull %s..%s (Customer Type Both)" % (start, end))
        data, wl_bytes = pull_csv(start, end, headless=not args.headed)
        raw = OUT_DIR / "sp_export_{}.csv".format(today.isoformat())
        raw.write_bytes(data)
        print("export saved: %s (%s bytes)" % (raw.name, "{:,}".format(len(data))))

    wl_parsed, act_dates = track_lines(data, wl_bytes, today, log=print)
    lines = shape_lines(data, wl_lines=wl_parsed, act_dates=act_dates)
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
