"""Phase 2 — Slack alerts for negative brand-health findings.

Posts NEW negative findings (bad reviews, bad Reddit threads, negative search
results) to #alphaletemarketingbrandhealth. Reuses the shared Slack user token.

Dedup: every finding gets a stable key (company + level + URL, or + message when
there's no URL). Keys we've already alerted are stored in
~/.config/brand-audit/alerted.json, so the same r/Devilcorp thread isn't
re-pinged every run — you only hear about something the first time it appears.

--dry-run prints what it WOULD post and never touches Slack or the state file.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from automations.brand_audit.config import ALERT_SLACK_CHANNEL_ID

_STATE_PATH = Path.home() / ".config" / "brand-audit" / "alerted.json"


def _finding_key(company_name: str, flag: dict) -> str:
    anchor = flag.get("url") or flag.get("message", "")
    return f"{company_name}|{flag.get('level')}|{anchor}"


def _load_state() -> dict:
    try:
        return json.loads(_STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2))


def _new_negatives(company_name: str, flags: list[dict], state: dict):
    """Return (new_flags, keys) — negatives whose key we haven't alerted yet.
    Dedupes within this run too (same URL surfaced by two collectors -> once)."""
    seen_now = set()
    new = []
    keys = []
    for f in flags:
        if f.get("level") != "negative":
            continue
        k = _finding_key(company_name, f)
        if k in state or k in seen_now:
            continue
        seen_now.add(k)
        new.append(f)
        keys.append(k)
    return new, keys


def _format_message(company_name: str, overall_grade: str,
                    new_flags: list[dict], total_negatives: int) -> str:
    lines = [
        f":rotating_light: *Brand Health alert — {company_name}*",
        f"Overall grade *{overall_grade}* · "
        f"{len(new_flags)} new negative finding(s) "
        f"({total_negatives} total this run)",
        "",
    ]
    for f in new_flags:
        msg = f.get("message", "")
        detail = (f.get("detail") or "").strip()
        url = f.get("url")
        if url:
            label = detail or "open thread"
            lines.append(f"• {msg} — <{url}|{label}>")
        else:
            lines.append(f"• {msg}" + (f" — {detail}" if detail else ""))
    return "\n".join(lines)


def send_alerts(company_name: str, scorecard: dict, *, dry_run: bool = False,
                channel_id: str = ALERT_SLACK_CHANNEL_ID) -> dict:
    flags = scorecard.get("flags", [])
    total_neg = sum(1 for f in flags if f.get("level") == "negative")
    state = _load_state()
    new_flags, new_keys = _new_negatives(company_name, flags, state)

    if not new_flags:
        return {"posted": False, "reason": "no new negatives",
                "total_negatives": total_neg}

    message = _format_message(company_name, scorecard.get("overall_grade", "?"),
                              new_flags, total_neg)

    if dry_run:
        return {"dry_run": True, "would_post": len(new_flags),
                "channel": channel_id, "message": message}

    # Reuse the shared Slack client (same xoxp- token the metrics posts use).
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    resp = client.chat_postMessage(channel=channel_id, text=message)

    # Only record keys once the post actually succeeded.
    now = datetime.now(timezone.utc).isoformat()
    for k in new_keys:
        state[k] = now
    _save_state(state)

    return {"posted": bool(resp.get("ok")), "count": len(new_flags),
            "channel": channel_id, "ts": resp.get("ts")}
