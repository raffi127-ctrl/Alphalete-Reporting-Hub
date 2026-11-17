"""The feedback log — a dedicated Google Sheet with two tabs:

  Outreach  : one row per customer we texted (the once-per-customer ledger).
  Responses : one row per reply, with the feedback text + an opt-out flag.

Every function no-ops gracefully when LOG_SHEET_ID is unset (so a dry-run needs
no sheet): reads return empty, writes are skipped with a note.
"""
from __future__ import annotations

from typing import Dict, List, Set

from automations.cancel_feedback import config as C


def configured() -> bool:
    return bool(C.LOG_SHEET_ID)


def _ws(tab: str, headers: List[str]):
    """Open (creating + header-seeding if missing) one tab of the log sheet."""
    from automations.recruiting_report import fill as rfill
    sh = rfill._client().open_by_key(C.LOG_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
    except Exception:                                      # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=1000, cols=max(12, len(headers)))
        ws.update("A1", [headers])
        return ws
    if not (ws.row_values(1) or []):
        ws.update("A1", [headers])
    return ws


def _col(ws, header_name: str) -> int:
    hdr = ws.row_values(1)
    return hdr.index(header_name) if header_name in hdr else -1


def already_texted_phones(log=print) -> Set[str]:
    """Every phone we've ever recorded in Outreach whose send didn't fail —
    the guard that stops a customer being texted twice."""
    if not configured():
        return set()
    try:
        ws = _ws(C.OUTREACH_TAB, C.OUTREACH_HEADERS)
        rows = ws.get_all_records()
        out = set()
        for r in rows:
            if str(r.get("Status", "")).lower() != "failed":
                p = str(r.get("Phone", "")).strip()
                if p:
                    out.add(p)
        return out
    except Exception as e:                                 # noqa: BLE001
        log("  (couldn't read Outreach: %s: %s)" % (type(e).__name__, str(e)[:120]))
        return set()


def opted_out_phones(log=print) -> Set[str]:
    if not configured():
        return set()
    try:
        ws = _ws(C.RESPONSES_TAB, C.RESPONSES_HEADERS)
        out = set()
        for r in ws.get_all_records():
            if str(r.get("Opted Out", "")).strip().lower() in ("yes", "true", "1"):
                p = str(r.get("Phone", "")).strip()
                if p:
                    out.add(p)
        return out
    except Exception as e:                                 # noqa: BLE001
        log("  (couldn't read opt-outs: %s: %s)" % (type(e).__name__, str(e)[:120]))
        return set()


def outreach_map(log=print) -> Dict[str, str]:
    """phone -> customer name for everyone we've texted (to match replies)."""
    if not configured():
        return {}
    try:
        ws = _ws(C.OUTREACH_TAB, C.OUTREACH_HEADERS)
        out: Dict[str, str] = {}
        for r in ws.get_all_records():
            p = str(r.get("Phone", "")).strip()
            if p:
                out[p] = str(r.get("Customer", "")).strip()
        return out
    except Exception as e:                                 # noqa: BLE001
        log("  (couldn't read outreach map: %s: %s)" % (type(e).__name__, str(e)[:120]))
        return {}


def logged_reply_ids(log=print) -> Set[str]:
    """Message IDs already written to Responses, so re-runs don't double-log."""
    if not configured():
        return set()
    try:
        ws = _ws(C.RESPONSES_TAB, C.RESPONSES_HEADERS)
        return {str(r.get("Message ID", "")).strip()
                for r in ws.get_all_records() if str(r.get("Message ID", "")).strip()}
    except Exception as e:                                 # noqa: BLE001
        log("  (couldn't read reply ids: %s: %s)" % (type(e).__name__, str(e)[:120]))
        return set()


def record_outreach(entries: List[Dict], log=print) -> int:
    if not entries:
        return 0
    if not configured():
        log("  (log sheet not wired — %d outreach row(s) NOT persisted)" % len(entries))
        return 0
    ws = _ws(C.OUTREACH_TAB, C.OUTREACH_HEADERS)
    rows = [[e.get("texted_at", ""), e.get("customer", ""), e.get("phone", ""),
             e.get("kind", ""), e.get("reason", ""), e.get("rep", ""),
             e.get("owner", ""), e.get("status", ""), e.get("message_id", "")]
            for e in entries]
    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


def record_responses(entries: List[Dict], log=print) -> int:
    if not entries:
        return 0
    if not configured():
        log("  (log sheet not wired — %d response row(s) NOT persisted)" % len(entries))
        return 0
    ws = _ws(C.RESPONSES_TAB, C.RESPONSES_HEADERS)
    rows = [[e.get("received_at", ""), e.get("phone", ""), e.get("customer", ""),
             e.get("feedback", ""), "yes" if e.get("opted_out") else "",
             e.get("message_id", "")] for e in entries]
    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)
