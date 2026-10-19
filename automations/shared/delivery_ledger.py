"""What a report actually DELIVERED today — recorded at the moment of sending.

WHY (Raf 2026-10-19: "if they got resolved then they should have marked green").
delivery_check only closes a corrections ticket on evidence of delivery
(feedback: green means DELIVERED, never exit 0). For a report with no `verify`
wired and no run-manifest there was no evidence at all, so every clean run
answered UNKNOWN and the ticket sat open until it rolled over "superseded".
Measured over 2026-09-28..10-19: 20 of 137 stranded tickets were exactly that —
"ran clean, but nothing can confirm it DELIVERED" — on reports that HAD
delivered (vantura_orderlog_sales six times, recruiting_chain three).

The evidence already passes through two shared choke points: Lucy's Slack client
(slack_metrics_post._client / _bot_client) and the shared email senders. This
module is the note those choke points leave: "report X put something in front of
its audience at T". delivery_check reads it LAST, only when nothing better
(phase count, verify, manifest, post-watch) has an opinion, and only a delivery
made SINCE the report last failed counts.

WHAT IS NOT DELIVERY, and is never recorded:
  * the corrections channel itself (alerts about the report);
  * #revision-emails (a draft posted for approval has reached nobody);
  * DMs (a report that fails often DMs a person to say so);
  * anything sent from a unit test.
Sheet writes are deliberately NOT recorded: a half-finished run still writes
cells (Applicant Tracker, 2026-08-19, office 9 of 16 then exit 0) — that is the
false green this whole system exists to stop.

Per machine, like run-manifests: the record lives where the send happened, and
delivery_check runs on the machine that ran the report. Best-effort throughout —
recording must never break a send.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO_ROOT / "output" / "state" / "deliveries"

CORRECTIONS_CHANNEL = "C0BK5PRG259"     # #claudecorrections-and-requests
REVIEW_CHANNEL = "C0BLLU9M0A2"          # #revision-emails
NOT_DELIVERY = frozenset({CORRECTIONS_CHANNEL, REVIEW_CHANNEL})

# Slack methods that put something in a channel.
SLACK_SEND_METHODS = frozenset({
    "chat.postMessage", "files.completeUploadExternal", "files.upload",
})


def current_report_id() -> str:
    """The report doing the sending: HUB_REPORT_ID (set by the orchestrator
    around every run and by `lucy rerun`), else the module python was started with
    (`python -m automations.box_order_log.run` -> box_order_log)."""
    for var in ("HUB_REPORT_ID", "ALPHALETE_REPORT_ID"):
        rid = (os.environ.get(var) or "").strip()
        if rid:
            return rid
    for a in sys.argv:
        m = re.match(r"automations\.([a-z0-9_]+)", a or "")
        if m:
            return m.group(1)
    try:
        name = getattr(sys.modules.get("__main__"), "__package__", "") or ""
        if name.startswith("automations."):
            return name.split(".")[1]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _path(day: dt.date) -> Path:
    return LEDGER_DIR / f"{day.isoformat()}.jsonl"


NOT_DELIVERY_NAMES = frozenset({"#claudecorrections-and-requests",
                                "#revision-emails"})


def counts_as_delivery(kind: str, dest: str) -> bool:
    dest = (dest or "").strip()
    if not dest:
        return False
    if kind == "slack":
        if (dest in NOT_DELIVERY or dest.lower() in NOT_DELIVERY_NAMES
                or dest.startswith("D") or dest.startswith("@")):
            return False
    return True


def record(kind: str, dest: str, *, report_id: Optional[str] = None,
           detail: str = "", now: Optional[dt.datetime] = None) -> bool:
    """Note one delivery. True if a line was written."""
    try:
        from automations.shared import live_effects
        if live_effects.driven_by_a_test() and now is None:
            return False
    except Exception:  # noqa: BLE001
        pass
    try:
        if not counts_as_delivery(kind, dest):
            return False
        rid = (report_id or current_report_id()).strip()
        if not rid:
            return False
        now = now or dt.datetime.now()
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"report_id": rid, "at": now.isoformat(timespec="seconds"),
                           "kind": kind, "dest": dest, "detail": detail[:120]})
        with open(_path(now.date()), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except Exception:  # noqa: BLE001 — never break a send
        return False


def _norm(rid: str) -> str:
    return (rid or "").strip().lower().replace("-", "_")


def deliveries(report_ids: Iterable[str], day: dt.date) -> List[dict]:
    """Today's delivery lines for any spelling of the report."""
    want = {_norm(r) for r in report_ids if r}
    out = []
    try:
        with open(_path(day), encoding="utf-8") as fh:
            for ln in fh:
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                if _norm(rec.get("report_id")) in want:
                    out.append(rec)
    except OSError:
        return []
    return out


def delivered_since(report_ids: Iterable[str], since: dt.datetime) -> Optional[dict]:
    """The newest delivery at or after `since` (same day), or None."""
    best = None
    for rec in deliveries(report_ids, since.date()):
        try:
            at = dt.datetime.fromisoformat(rec["at"])
        except (KeyError, ValueError):
            continue
        if at >= since and (best is None or at > dt.datetime.fromisoformat(best["at"])):
            best = rec
    return best


def record_slack_response(method: str, kwargs: dict, resp) -> None:
    """Hook for Lucy's Slack client: note a successful send to a real channel."""
    try:
        if method not in SLACK_SEND_METHODS:
            return
        if not (resp is not None and resp.get("ok")):
            return
        # The response's channel is the resolved ID even when the caller
        # passed a "#name" — prefer it, so a post to "#claudecorrections-…"
        # is still recognised as not-delivery.
        ch = resp.get("channel") if hasattr(resp, "get") else ""
        if not isinstance(ch, str) or not ch:
            ch = (kwargs.get("channel") or kwargs.get("channel_id")
                  or kwargs.get("channels") or "")
        if isinstance(ch, (list, tuple)):
            ch = ch[0] if ch else ""
        record("slack", str(ch).split(",")[0].strip(), detail=method)
    except Exception:  # noqa: BLE001
        pass
