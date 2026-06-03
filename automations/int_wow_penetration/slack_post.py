"""Post a one-line 'report updated' note to the Penetration Reports thread.

Channel #level10-alphalete, thread 'Penetration Reports 2026' (a persistent
thread reused every week). Posts as the same Slack user the other reports use
(reuses slack_metrics_post's token + client). Best-effort: a Slack failure is
logged but NEVER fails the run — the sheet fill is what matters (Eve 2026-06-02).
"""
from __future__ import annotations

from automations.shared import slack_metrics_post as _smp

CHANNEL_ID = "C075PCEL92M"          # #level10-alphalete (private)
THREAD_TS = "1770832092.278019"     # 'Penetration Reports 2026' parent message


def post_update(label: str, dry_run: bool = False) -> dict:
    """Reply in the Penetration Reports thread that this week is done.
    `label` is the column header, e.g. 'WE 5.31'. Returns a result dict and
    never raises."""
    text = f"📶 Penetration % — {label} ready ✅"
    if dry_run:
        print(f"  [dry-run] would post to #level10-alphalete thread: {text!r}")
        return {"dry_run": True, "text": text}
    try:
        client = _smp._client()
        resp = client.chat_postMessage(channel=CHANNEL_ID, thread_ts=THREAD_TS,
                                       text=text)
        return {"ok": resp.get("ok"), "ts": resp.get("ts"), "text": text}
    except Exception as e:                      # noqa: BLE001 — best-effort
        return {"ok": False, "error": str(e), "text": text}
