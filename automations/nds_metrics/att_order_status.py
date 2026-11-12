"""AT&T's own order status (and FedEx's) for every NDS line still in
"Shipped" -> the NDS Order Log tab's Shipping Notes column.

Carlos 2026-11-11 pm: "we need a shipping notes column right next to the ship
date for all of these sales that say shipped ... whenever something is
shipped, you're always checking the status updates once a day and updating
it on here." So: every line in Shipped with no Delivered date, every morning,
whatever its age; the cell is REPLACED with today's reading.

Carlos 2026-11-11: "If it's been shipped for more than 3 days and it's still
in shipped status, go ahead and look up the order on AT&T's site and put in
the notes what you see." The SaraPlus feed shows nothing past the ship date
(Rajeshkanna Chandrakasan's order read "Shipped - InTransit" from 10/21 to
11/11), so the answer has to come from AT&T: att.com/orders/checkmyorder
takes the order number and ZIP, then asks for the e-mail address on the
order (both on the tab since 11/11: Zip off the Tableau export, Email off
the SaraPlus customer card) and shows the order's status and tracking.

Per order with at least one line Shipped for STALE_DAYS or more and no
Delivered date: look it up, keep the status / tracking / delivery lines of
what AT&T shows, and write "MM/DD AT&T: ..." in front of Notes on each of
those lines. A status AT&T already gave yesterday (same words) is not
written again; a lookup that fails writes nothing and says why in the log
(a screenshot lands in output/nds_metrics/att_<order>.png).

    python -m automations.nds_metrics.att_order_status            # plan + what AT&T shows, tab untouched
    python -m automations.nds_metrics.att_order_status --live     # writes the notes
    python -m automations.nds_metrics.att_order_status --limit 2 --order 99-717053512695236

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Sequence

from automations.nds_metrics.run import OUT_DIR, REPO_ROOT

CHECK_URL = "https://www.att.com/orders/checkmyorder"
# The details page itself takes the three values in its address (seen 11/11
# after a lookup by hand): no form, no e-mail dialog, no overlays to fight.
DETAILS_URL = "https://www.att.com/acctmgmt/order/details?emailAddress={email}&orderId={order}&zipCode={zip}"
# FedEx's public tracking page: AT&T's page names the carrier and number, and
# FedEx says what AT&T's "Shipped" hides (11/11, Rajeshkanna: "couldn't be
# delivered and is returning to the shipper", three weeks in)
FEDEX_URL = "https://www.fedex.com/fedextrack/?trknbr={n}"
FEDEX_KEEP_RE = re.compile(r"deliver|on the way|return|currently in|exception|held|pick ?up|delay|"
                           r"label created|scheduled|new tracking|signature required", re.I)
FEDEX_NOISE_RE = re.compile(r"delivery manager|register or log in|view more details|get status updates|"
                            r"^#|^label created$|^on the way$|^delivered$|^delivery updated$|^returning to shipper$|"
                            r"we'll need someone|if you're not home", re.I)
PROFILE_DIR = REPO_ROOT / "automations" / "uploaded" / ".att_profile"
STALE_DAYS = 0                   # every Shipped line, every day (was 3 until 11/11 pm)
NOTE_TAG = "AT&T:"
COL_OUT = "Shipping Notes"       # the column written (Notes until 11/11 pm)
NAV_TIMEOUT_MS = 60_000
KEEP_RE = re.compile(r"shipp|deliver|transit|track|arriv|estimat|carrier|\bups\b|fedex|usps|"
                     r"status|on its way|out for|label|cancel|ordered on", re.I)
NOISE_RE = re.compile(r"cookie|privacy|feedback|sign in|skip navigation|chat|cart|search or|"
                      r"look up another order|shipping address|device protection|shop again|back up your device|"
                      r"^order status\s*\|?|number of items|^ordered$|^shipped$|^delivered$|"
                      r"check my status|confirm the status for orders|search as a guest|"
                      r"find an order or claim|view all my orders|order or claim$|zip code$|"
                      r"start search|let.s verify your info|please enter the email|email address$",
                      re.I)
# still on the lookup form (or back on it): nothing was looked up
LANDING_RE = re.compile(r"search as a guest|find an order or claim|let.s verify your info", re.I)
SHOT_TAB = "ATT Shot"            # the last lookup's page, base64-chunked on the control sheet
FAIL_RE = re.compile(r"couldn.t find|can.t find|unable to|doesn.t match|does not match|"
                     r"no (?:matching )?order|try again|something went wrong|not found", re.I)
TRACK_RE = re.compile(r"\b(1Z[0-9A-Z]{16}|\d{12,22})\b")
EMAIL_PROMPT_RE = re.compile(r"let.s verify your info|email address", re.I)


def _parse_date(v) -> Optional[dt.date]:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


# --- what to look up ----------------------------------------------------------------

def _hdr(header: Sequence[str]) -> Dict[str, int]:
    return {_norm(h).lower(): i for i, h in enumerate(header)}


def _cell(row: Sequence[str], cols: Dict[str, int], name: str) -> str:
    i = cols.get(name.lower())
    return _norm(row[i]) if i is not None and i < len(row) else ""


def stale_orders(header: Sequence[str], rows: Sequence[Sequence[str]], *, today: dt.date,
                 days: int = STALE_DAYS) -> List[Dict]:
    """One entry per order with a line Shipped `days`+ days ago and no
    Delivered date: {order, zip, email, customer, rep, lines: [{row, line,
    ship_date, notes}]}. Orders without a ZIP or an e-mail are listed too,
    with 'why' set, so the log says what blocks them."""
    cols = _hdr(header)
    for need in ("Line Status", "Ship Date", "Delivered", "Wireless Order #",
                 "Zip", "Email", COL_OUT, "Customer", "Line"):
        if need.lower() not in cols:
            raise RuntimeError("NDS Order Log tab has no %r column -- header: %r"
                               % (need, list(header)))
    cutoff = today - dt.timedelta(days=days)
    by_order: Dict[str, Dict] = {}
    for n, r in enumerate(rows, start=2):           # sheet row numbers, header is 1
        if _cell(r, cols, "Line Status").lower() != "shipped":
            continue
        if _parse_date(_cell(r, cols, "Delivered")):
            continue
        sd = _parse_date(_cell(r, cols, "Ship Date"))
        # a Shipped line with no ship date at all is looked up too (11/11:
        # six of them a week old); with days > 0 only dated, old ones are
        if days > 0 and (sd is None or sd > cutoff):
            continue
        order = _cell(r, cols, "Wireless Order #")
        if not order:
            continue
        o = by_order.setdefault(order, {
            "order": order, "zip": _cell(r, cols, "Zip").lstrip("'"),
            "email": _cell(r, cols, "Email"), "customer": _cell(r, cols, "Customer"),
            "rep": _cell(r, cols, "Rep"), "lines": [], "why": ""})
        o["lines"].append({"row": n, "line": _cell(r, cols, "Line"), "ship_date": _fmt(sd),
                           "notes": _cell(r, cols, COL_OUT)})
    out = []
    for o in by_order.values():
        missing = [k for k in ("zip", "email") if not o[k]]
        o["why"] = ("no %s on the tab" % " / ".join(missing)) if missing else ""
        out.append(o)
    out.sort(key=lambda o: (o["why"] != "", o["customer"]))
    return out


def _fmt(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


# --- AT&T ------------------------------------------------------------------------------

def summarize(text: str) -> Dict[str, object]:
    """What AT&T's status page says, boiled down: the status/shipping lines
    (at most 6, each trimmed) and any tracking number."""
    lines = []
    seen = set()
    for raw in (text or "").splitlines():
        ln = _norm(raw)
        if not ln or len(ln) > 160 or NOISE_RE.search(ln) or not KEEP_RE.search(ln):
            continue
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(ln[:110])
        if len(lines) >= 6:
            break
    tracking = ""
    trackings: List[str] = []
    for m in TRACK_RE.finditer(text or ""):
        at = text.rfind("\n", 0, m.start())
        ctx = text[max(0, at - 80): m.end() + 40].lower()
        if ("track" in ctx or m.group(1).startswith("1Z")) and m.group(1) not in trackings:
            trackings.append(m.group(1))
    tracking = trackings[0] if trackings else ""
    landing = bool(LANDING_RE.search(text or ""))
    failed = (bool(FAIL_RE.search(text or "")) and not lines) or landing
    if landing:
        lines = []
    return {"lines": lines, "tracking": tracking, "trackings": trackings, "failed": failed,
            "landing": landing}


SHIP_ON_RE = re.compile(r"^(shipped|delivered|ordered) on:\s*(.*)$", re.I)
CARRIER_RE = re.compile(r"^(fedex|ups|usps)\s+tracking:\s*([0-9A-Z]+)$", re.I)


def _short_date(s: str) -> str:
    """'Wed, Oct 21, 2026' -> 'Oct 21'."""
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", s or "")
    return "%s %s" % (m.group(1), m.group(2)) if m else _norm(s)


def shipments(text: str) -> List[Dict[str, str]]:
    """AT&T's details page as shipment blocks: each 'Shipped on:' /
    'Delivered on:' (or a lone 'Ordered on:') opens a block that gathers its
    status line and its carrier tracking numbers."""
    out: List[Dict[str, object]] = []
    cur: Optional[Dict[str, object]] = None
    lines = [_norm(l) for l in (text or "").splitlines()]
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = SHIP_ON_RE.match(ln)
        if m:
            kind, when = m.group(1).lower(), m.group(2).strip()
            if not when and i + 1 < len(lines) and re.match(r"^[A-Z][a-z]{2}, ", lines[i + 1]):
                when = lines[i + 1]
                i += 1
            cur = {"kind": kind, "date": _short_date(when), "status": "", "tracking": []}
            out.append(cur)
        elif cur is not None:
            c = CARRIER_RE.match(ln)
            if c:
                cur["tracking"].append("%s %s" % (c.group(1).upper() if c.group(1).lower() != "fedex" else "FedEx", c.group(2)))
            elif not cur["status"] and re.search(r"on the way|arrived|delivered|cancel|return|delay|held|pick", ln, re.I) \
                    and not NOISE_RE.search(ln) and len(ln) < 120:
                cur["status"] = ln
        i += 1
    # 'Ordered on:' heads every page; it only counts as a block of its own
    # when nothing has shipped yet (its tracking numbers then belong to it)
    if any(b["kind"] != "ordered" for b in out):
        out = [b for b in out if b["kind"] != "ordered"]
    return out


def _status_word(s: str) -> str:
    low = (s or "").lower()
    if "return" in low:
        return "returning to shipper"
    if "arrived" in low or "was delivered" in low or low.startswith("delivered"):
        return "delivered"
    if "delay" in low or "new delivery date" in low:
        return "delayed"
    if "on the way" in low or "on its way" in low:
        return "on the way"
    if "cancel" in low:
        return "cancelled"
    if "held" in low or "pick" in low:
        return "held for pickup"
    return _norm(s)[:40]


def short_text(text: str, today: dt.date, carrier: Sequence[str] = ()) -> str:
    """The cell: one short clause per shipment, today's date in front.
    'Shipped Nov 9, on the way (UPS …4036) | Delivered Nov 10 (UPS …2114)';
    a FedEx reading replaces AT&T's word for that package."""
    fx = {}
    for c in carrier or ():
        m = re.match(r"FedEx (\d+): (.*)", c or "")
        if m:
            fx[m.group(1)] = _status_word(m.group(2).split(" / ")[0])
    parts = []
    for sh in shipments(text):
        word = _status_word(str(sh["status"]))
        for t in sh["tracking"]:
            n = t.split()[-1]
            if n in fx and fx[n]:
                word = "FedEx: " + fx[n]
        tr = ", ".join("%s …%s" % (t.split()[0], t.split()[-1][-4:]) for t in sh["tracking"])
        if sh["kind"] == "delivered":
            head = "Delivered %s" % sh["date"]
        elif sh["kind"] == "shipped":
            head = "Shipped %s%s" % (sh["date"], (", " + word) if word and word != "delivered" else (", delivered" if word == "delivered" else ""))
        else:
            head = "Ordered %s, not shipped yet" % sh["date"]
        parts.append(head + ((" (%s)" % tr) if tr else ""))
    if not parts:
        return ""
    return "%s: %s" % (today.strftime("%m/%d"), " | ".join(parts))


def detail_text(summary: Dict[str, object], today: dt.date, carrier: Sequence[str] = ()) -> str:
    """The hover note: everything AT&T and FedEx said, one item per line."""
    parts = ["Checked %s" % dt.datetime.now().strftime("%m/%d/%Y %H:%M"), ""]
    parts.extend("AT&T: " + l for l in (summary.get("lines") or []))
    parts.extend(str(c) for c in (carrier or ()) if c)
    return "\n".join(parts)


def note_text(summary: Dict[str, object], today: dt.date, carrier: Sequence[str] = ()) -> str:
    parts = [l for l in (summary.get("lines") or []) if not l.lower().startswith("fedex tracking")]
    for n in (summary.get("trackings") or ([summary["tracking"]] if summary.get("tracking") else [])):
        parts.append("tracking %s" % n)
    parts.extend(c for c in carrier if c)
    return "%s %s %s" % (today.strftime("%m/%d"), NOTE_TAG, "; ".join(parts))


def already_noted(notes: str, body: str) -> bool:
    """The same AT&T words are already in the line's Notes (any day)."""
    want = body.split(NOTE_TAG, 1)[-1].strip().lower()
    for chunk in (notes or "").split(NOTE_TAG)[1:]:
        have = chunk.split("|")[0].strip().lower()
        if have == want:
            return True
    return False


def _dismiss_overlays(page, log=print) -> None:
    """The cookie banner and the "Andi" assistant panel sit over the page
    (seen in the 11/11 page shot); their close / opt-out controls are
    clicked when present so nothing covers the form."""
    import re as _re
    for name in (_re.compile(r"^close$", _re.I), _re.compile(r"opt out|reject|decline", _re.I)):
        try:
            btns = page.get_by_role("button", name=name)
            n = btns.count()
            for i in range(min(n, 3)):
                b = btns.nth(i)
                if b.is_visible():
                    b.click(timeout=3_000)
                    page.wait_for_timeout(600)
        except Exception:  # noqa: BLE001
            continue


def fedex_status(page, number: str, log=print) -> str:
    """What FedEx's tracking page says about one package, in a line or two."""
    try:
        page.goto(FEDEX_URL.format(n=number), wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            # the page is script-built: wait for its status words, not for the network
            page.wait_for_function(
                """() => /currently in|on the way|delivered|returning|label created|signature|exception/i
                         .test(document.body ? document.body.innerText : '')""",
                timeout=20_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
        text = page.evaluate("() => (document.body.innerText || '')")
    except Exception as e:  # noqa: BLE001
        log("    (FedEx %s: page failed: %s)" % (number, type(e).__name__))
        return ""
    kept, seen = [], set()
    for raw in (text or "").splitlines():
        ln = _norm(raw)
        if not ln or len(ln) > 170 or FEDEX_NOISE_RE.search(ln) or not FEDEX_KEEP_RE.search(ln):
            continue
        if ln.lower() in seen:
            continue
        seen.add(ln.lower())
        kept.append(ln[:120])
        if len(kept) >= 3:
            break
    if not kept:
        log("    (FedEx %s: no status read -- %d chars)" % (number, len(text or "")))
        return ""
    return "FedEx %s: %s" % (number, " / ".join(kept))


def lookup(page, order: str, zip_code: str, email: str, log=print) -> Dict[str, object]:
    """One guest lookup on AT&T's page; returns summarize()'s dict plus
    'text' (the page) and 'error' (why it could not be read). The details
    address is opened straight away; the form is the fallback when that
    lands back on the lookup page."""
    import re as _re
    from urllib.parse import quote
    try:
        page.goto(DETAILS_URL.format(email=quote(email), order=quote(order), zip=quote(zip_code)),
                  wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(2500)
        text = page.evaluate("() => (document.querySelector('main') || document.body).innerText || ''")
        s = summarize(text)
        if s["lines"] and not s["failed"] and shipments(text):
            s["text"] = text
            s["error"] = ""
            return s
        log("    (details address did not show a status -- trying the form)")
    except Exception as e:  # noqa: BLE001
        log("    (details address failed: %s -- trying the form)" % type(e).__name__)
    page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)
    _dismiss_overlays(page, log)
    try:
        page.get_by_role("textbox", name=_re.compile(r"order", _re.I)).first.fill(order, timeout=15_000)
        zipbox = page.get_by_role("textbox", name=_re.compile(r"zip", _re.I)).first
        zipbox.fill(zip_code, timeout=15_000)
        page.get_by_role("button", name=_re.compile(r"start search|search", _re.I)).first.click(timeout=15_000)
    except Exception as e:  # noqa: BLE001
        return {"lines": [], "tracking": "", "failed": True, "text": "",
                "error": "lookup form not usable: %s: %s" % (type(e).__name__, str(e)[:140])}
    page.wait_for_timeout(2500)
    # the e-mail step ("Let's verify your info"). 11/11 on Lucy 2 (headless):
    # the form stayed put after the click -- the screenshot showed the order
    # and ZIP filled and nothing else -- so Enter in the ZIP box is tried too.
    box = page.get_by_role("textbox", name=_re.compile(r"e-?mail", _re.I)).first
    prompted = False
    for attempt in ("click", "enter"):
        try:
            box.wait_for(timeout=12_000)
            prompted = True
            break
        except Exception:  # noqa: BLE001
            if attempt == "click":
                log("    (no e-mail prompt after the click -- pressing Enter in the ZIP box)")
                try:
                    zipbox.press("Enter", timeout=5_000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(2500)
    if prompted:
        try:
            box.fill(email, timeout=10_000)
            page.get_by_role("button", name=_re.compile(r"see details|continue|submit", _re.I)).first.click(timeout=10_000)
        except Exception as e:  # noqa: BLE001
            log("    (e-mail prompt could not be answered: %s)" % type(e).__name__)
    else:
        log("    (no e-mail prompt: the search never returned)")
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(4000)
    try:
        text = page.evaluate("() => (document.querySelector('main') || document.body).innerText || ''")
    except Exception as e:  # noqa: BLE001
        text = ""
        log("    (page text unreadable: %s)" % type(e).__name__)
    s = summarize(text)
    s["text"] = text
    s["error"] = ""
    if not s["failed"] and s["lines"] and not shipments(text):
        s["failed"] = True                  # words like "Check status" with no order on the page
    if s["failed"] or not s["lines"]:
        m = FAIL_RE.search(text or "")
        if s.get("landing"):
            s["error"] = "still on the lookup form -- the search never returned a status (%s)" % (
                "e-mail prompt seen" if EMAIL_PROMPT_RE.search(text or "") else "no e-mail prompt")
        elif m:
            s["error"] = "AT&T: %s" % _norm(text[max(0, m.start() - 40): m.end() + 80])
        else:
            s["error"] = "no status lines on the page (%d chars)" % len(text or "")
        log("    page said: %s" % " / ".join(
            _norm(l) for l in (text or "").splitlines() if _norm(l) and not NOISE_RE.search(l))[:600])
    return s


def run(today: Optional[dt.date] = None, *, live: bool = False, limit: Optional[int] = None,
        only: Sequence[str] = (), days: int = STALE_DAYS, headless: bool = True,
        log=print) -> int:
    from patchright.sync_api import sync_playwright
    from automations.nds_metrics import order_log_tab as T
    from automations.recruiting_report.fill import open_by_key, _retry

    today = today or dt.date.today()
    sh = open_by_key(T.VANTURA_SHEET_ID)
    ws = sh.worksheet(T.TAB)
    rows = _retry(lambda: ws.get_all_values())
    if not rows:
        log("[att] the NDS Order Log tab is empty")
        return 0
    header = rows[0]
    orders = stale_orders(header, rows[1:], today=today, days=days)
    if only:
        keep = {_norm(x) for x in only}
        orders = [o for o in orders if o["order"] in keep]
    log("[att] %d order(s) with a line in Shipped and no Delivered date%s"
        % (len(orders), (" (shipped %d+ days ago)" % days) if days else ""))
    blocked = [o for o in orders if o["why"]]
    for o in blocked:
        log("  – %-26s %s  %s" % (o["customer"][:26], o["order"], o["why"]))
    todo = [o for o in orders if not o["why"]]
    if limit:
        todo = todo[:limit]
    if not todo:
        log("[att] nothing to look up")
        return 0
    cols = _hdr(header)
    i_notes = cols[COL_OUT.lower()]
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    import gspread
    cells = []
    pending = []
    fedex_seen: Dict[str, str] = {}
    written = 0
    read = failed = unchanged = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, args=["--disable-sync"],
            viewport={"width": 1400, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for o in todo:
                log("• %s  %s  zip %s  %s" % (o["customer"], o["order"], o["zip"], o["email"]))
                s = lookup(page, o["order"], o["zip"], o["email"], log=log)
                if s["error"]:
                    try:
                        from automations.rc_contact_sync.status_probe import _upload_shot
                        _upload_shot(page.screenshot(full_page=True), SHOT_TAB, log=log)
                    except Exception as e:  # noqa: BLE001
                        log("    (page shot not uploaded: %s)" % type(e).__name__)
                    failed += 1
                    log("    ✗ %s" % s["error"])
                    try:
                        png = OUT_DIR / ("att_%s.png" % re.sub(r"\W", "", o["order"]))
                        page.screenshot(path=str(png), full_page=True)
                        log("    screenshot -> %s" % png.name)
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                read += 1
                carrier = []
                for n in (s.get("trackings") or [])[:3]:
                    if n.startswith("1Z"):
                        log("    (UPS %s: not looked up)" % n)
                        continue
                    if n not in fedex_seen:
                        fedex_seen[n] = fedex_status(page, n, log=log)
                    if fedex_seen[n]:
                        carrier.append(fedex_seen[n])
                body = short_text(s.get("text", ""), today, carrier) or note_text(s, today, carrier)
                detail = detail_text(s, today, carrier)
                log("    %s" % body)
                batch = []
                note_reqs = []
                for ln in o["lines"]:
                    # the hover note carries the full detail and is rewritten
                    # every day (Carlos 11/11: "put them inside of a note where
                    # we hover over it and we can read everything")
                    note_reqs.append({"updateCells": {
                        "start": {"sheetId": ws.id, "rowIndex": ln["row"] - 1, "columnIndex": i_notes},
                        "rows": [{"values": [{"note": detail}]}], "fields": "note"}})
                    if ln["notes"].strip() == body:
                        unchanged += 1
                        continue
                    # today's reading replaces yesterday's: the column is a
                    # status, not a history (Notes keeps the history)
                    batch.append(gspread.cell.Cell(ln["row"], i_notes + 1, body))
                cells.extend(batch)
                if live and note_reqs:
                    try:
                        _retry(lambda: sh.batch_update({"requests": note_reqs}))
                    except Exception as e:  # noqa: BLE001
                        log("    (hover notes not written: %s)" % type(e).__name__)
                # written as it goes: ~40 orders x (AT&T + FedEx pages) runs
                # long, and a run cut off by its timeout must keep what it read
                if live and batch:
                    try:
                        _retry(lambda: ws.update_cells(batch, value_input_option="RAW"))
                        written += len(batch)
                    except Exception as e:  # noqa: BLE001
                        log("    (write failed, kept for the end: %s)" % type(e).__name__)
                        pending.extend(batch)
        finally:
            ctx.close()
    log("[att] %d order(s) read, %d failed, %d line note(s) to write (%d already said this)"
        % (read, failed, len(cells), unchanged))
    if not live:
        log("[att] dry run -- nothing written (pass --live)")
        return 0
    if pending:
        _retry(lambda: ws.update_cells(pending, value_input_option="RAW"))
        written += len(pending)
    log("[att] %s written on %d line(s)" % (COL_OUT, written))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_att_order_status",
                                 description="AT&T order status for stale Shipped lines -> NDS Order Log Notes")
    ap.add_argument("--live", action="store_true", help="write the notes (default: dry run)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--order", action="append", default=[], help="only this Wireless Order # (repeatable)")
    ap.add_argument("--days", type=int, default=STALE_DAYS,
                    help="only lines shipped at least this many days ago (default 0: every Shipped line)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today)")
    a = ap.parse_args(argv)
    today = dt.datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else dt.date.today()
    rc = run(today, live=a.live, limit=a.limit, only=a.order, days=a.days, headless=not a.headed)
    print("=== done ===", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
