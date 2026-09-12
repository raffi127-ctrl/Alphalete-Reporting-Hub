"""Per-LINE wireless data from SaraPlus + the activation-date tracker.

SaraPlus never publishes WHEN a line activated — only each line's status
right now (hunted exhaustively 2026-09-12: grid CSV is order-level, the
customer card and the Wireless panel are per-line but carry only ship/
delivered dates). So this module manufactures the date: the report runs
daily, and the day a line FIRST shows "Active" is recorded as its
activation date in a state file. That is the same basis the DD pays on
(each line, its own activation date), one day granular, visible the next
morning instead of Friday.

Sources, in trust order, for a line already Active when tracking starts:
  1. live flip observed by this tracker            (src "live", exact day)
  2. Tableau ORDERLOG per-line posted date by TN   (src "tableau" — exact,
     Tableau is accurate for settled history; its sin is only the live edge)
  3. the SOH order-level active date               (src "order" — the first
     line's date, approximate for later lines)

The Wireless panel export ("Wireless Resolution Report.xls") is nested HTML
tables: each order a header row (13 cells, SaraPlus order id at [4]) with
line rows (11 cells, line index at [0]) under a Line/Line Type/... header.
The nested rendering makes naive table-regexes double-count, so rows are
walked in document order and deduped per order.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
STATE_PATH = CONFIG_DIR / "sp_line_activations.json"
KEEP_DAYS = 120

# Wireless panel controls (probed live 2026-09-12).
PANEL_INDEX = "2"
FIELD_START = "ctl00_MainContent_rdpWirelessStartDate"
FIELD_END = "ctl00_MainContent_rdpWirelessEndDate"
BTN_SUBMIT = "#MainContent_btnSubmitWirelessDateRange"
BTN_EXPORT = "#MainContent_btnExportWirelessExcel"

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_ORDER_ID = re.compile(r"^DSI\d+$")


def _cells(tr_html: str) -> List[str]:
    return [_html.unescape(_TAG.sub("", c)).replace("\xa0", " ").strip()
            for c in _TD.findall(tr_html)]


def norm_tn(v: str) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else ""


def parse_wireless_xls(data: bytes) -> List[Dict[str, str]]:
    """-> one dict per LINE:
    {order_id, customer, order_date, salesperson, order_status,
     line_idx, tn, line_type, device_type, device, plan, line_status}."""
    raw = data.decode("utf-8", errors="replace")
    out: List[Dict[str, str]] = []
    cur: Dict[str, str] = {}
    seen = set()
    for tr in _TR.findall(raw):
        c = _cells(tr)
        if len(c) >= 13 and _ORDER_ID.match(c[4] or ""):
            cur = {"order_id": c[4], "customer": c[2], "order_date": c[5],
                   "salesperson": c[9], "order_status": c[12]}
            continue
        if (cur and len(c) >= 7 and (c[0] or "").isdigit()
                and not _ORDER_ID.match(c[3] or "")):
            key = (cur["order_id"],) + tuple(c[:7])
            if key in seen:            # nested tables render each line twice
                continue
            seen.add(key)
            out.append({
                "order_id": cur["order_id"], "customer": cur["customer"],
                "order_date": cur["order_date"],
                "salesperson": cur["salesperson"],
                "order_status": cur["order_status"],
                "line_idx": c[0], "line_type": c[1], "device_type": c[2],
                "tn": norm_tn(c[3]), "device": c[4], "plan": c[5],
                "line_status": c[6],
            })
    return out


def product_of(line: Dict[str, str]) -> str:
    """Tableau's product buckets, so the workbook reads like the current one."""
    hay = ("%s %s" % (line.get("device_type", ""), line.get("device", ""))).lower()
    if "aia" in hay or "gateway" in hay or "inseego" in hay or "wavemaker" in hay:
        return "AIR/AWB"
    if "ipad" in hay or "tablet" in hay or " tab " in (" %s " % hay):
        return "TABLET"
    return "WIRELESS"


def line_key(line: Dict[str, str]) -> str:
    return line["tn"] or "%s#L%s" % (line["order_id"], line["line_idx"])


# --- the state file -----------------------------------------------------------

def load_state() -> Dict[str, dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except (ValueError, OSError):
        return {}


def save_state(state: Dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=0, sort_keys=True))
    tmp.replace(STATE_PATH)


def prune_state(state: Dict[str, dict], today: dt.date) -> Dict[str, dict]:
    cutoff = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    return {k: v for k, v in state.items()
            if str(v.get("last_seen", "")) >= cutoff}


def update_state(state: Dict[str, dict], lines: List[Dict[str, str]],
                 today: dt.date, seed: Dict[str, str],
                 soh_active: Dict[str, str], log=print) -> Dict[str, str]:
    """Fold today's per-line statuses in; return {line key: activation date
    ISO} for every line that has one. A line's first_active never changes
    once stamped — the whole point is that WE saw (or seeded) the flip."""
    stamped = {"live": 0, "tableau": 0, "order": 0}
    for ln in lines:
        key = line_key(ln)
        active = ln["line_status"].strip().lower() == "active"
        rec = state.get(key)
        if rec is None:
            rec = {"order_id": ln["order_id"]}
            if active:
                d = seed.get(ln["tn"]) or soh_active.get(ln["order_id"])
                src = ("tableau" if seed.get(ln["tn"])
                       else ("order" if soh_active.get(ln["order_id"])
                             else "live"))
                rec["first_active"] = d or today.isoformat()
                rec["src"] = src
                stamped[src] += 1
            state[key] = rec
        else:
            if active and "first_active" not in rec:
                # THE FLIP — this line turned Active since the last run.
                rec["first_active"] = today.isoformat()
                rec["src"] = "live"
                stamped["live"] += 1
        rec["status"] = ln["line_status"]
        rec["last_seen"] = today.isoformat()
    log("line tracker: %d live flip(s), %d tableau-seeded, %d order-dated"
        % (stamped["live"], stamped["tableau"], stamped["order"]))
    return {k: v["first_active"] for k, v in state.items()
            if v.get("first_active")}


# --- the Tableau history seed -------------------------------------------------

def build_tableau_seed(log=print) -> Dict[str, str]:
    """{10-digit TN: posted date ISO} from the newest shared ORDERLOG export
    on this box (the b2b_metrics morning pull). Best-effort: no file, no
    seed — the tracker still works, first-seen actives just fall back to
    the order date."""
    from automations.att_order_log.sheet import _parse_date
    repo = Path(__file__).resolve().parents[2]
    cands = sorted((repo / "output" / "b2b_metrics" / "_shared").glob("orderlog_*.csv"))
    if not cands:
        log("seed: no shared ORDERLOG export on this box — skipping")
        return {}
    src = cands[-1]
    try:
        from automations.att_order_log import clean
        rows = clean.load_rows(str(src), owner_prefix="CARLOS HIDALGO")
    except Exception as e:  # noqa: BLE001
        log("seed: could not parse %s (%s: %s)" % (src.name, type(e).__name__,
                                                   str(e)[:120]))
        return {}
    out: Dict[str, str] = {}
    for r in rows:
        if str(r.get("DTR Status (enriched)", "")).strip() != "Posted":
            continue
        tn = norm_tn(r.get("spe.TN", ""))
        d = _parse_date(r.get("spe.dtr Posted Date (copy)"))
        if tn and d and tn not in out:
            out[tn] = d.isoformat()
    log("seed: %d posted TN(s) from %s" % (len(out), src.name))
    return out


# --- the pull (inside sp_order_log's logged-in session) -----------------------

def pull_wireless(page, start: dt.date, end: dt.date, log=print) -> Optional[bytes]:
    """Open the Wireless panel, run the range, capture its Excel export."""
    from automations.rc_contact_sync import config as C
    from automations.rc_contact_sync import sara

    posted = page.evaluate(
        """(cfg) => {
             const t = document.getElementsByName('__EVENTTARGET')[0];
             const a = document.getElementsByName('__EVENTARGUMENT')[0];
             if (!t || !a) return 'no postback fields';
             t.value = cfg.target;
             a.value = JSON.stringify({type: 0, index: cfg.index});
             const f = document.getElementById(cfg.form) || document.forms[0];
             if (!f) return 'no form';
             f.submit();
             return 'posted';
           }""",
        {"target": C.TAB_POSTBACK_TARGET, "index": PANEL_INDEX,
         "form": C.FORM_ID})
    if posted != "posted":
        log("wireless panel: %s" % posted)
        return None
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2000)
    sara._set_telerik_date(page, FIELD_START, start)
    sara._set_telerik_date(page, FIELD_END, end)
    page.click(BTN_SUBMIT, timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=C.GRID_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)
    try:
        with page.expect_download(timeout=60_000) as dl:
            page.click(BTN_EXPORT, timeout=15_000, no_wait_after=True)
        data = Path(dl.value.path()).read_bytes()
        log("wireless lines export: %s bytes" % "{:,}".format(len(data)))
        return data
    except Exception as e:  # noqa: BLE001
        log("wireless lines export FAILED (%s: %s) — wireless orders will "
            "fall back to order-level fan-out" % (type(e).__name__,
                                                  str(e)[:150]))
        return None
