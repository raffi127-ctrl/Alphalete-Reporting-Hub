"""Alert Megan when an ICD self-submits a tracker request.

The ICD fills the public form; the request lands on the 'Tracker Onboarding'
tab as status=pending. This posts a heads-up to the corrections channel — the
standing place for requests — with a confirm deep-link. NOTHING is wired until
Megan opens that link, checks Lucy is in the channel, and clicks Confirm.

Mirrors office_onboarding.request_notify: best-effort by design — no Slack
creds / a post failure never blocks the ICD's submission (it's saved anyway).
Corrections-channel format (standing): one emoji-free line, detail in thread.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from automations.tracker_onboarding.schema import TrackerRecord, tracker_catalog

# The deployed form. The ping deep-links to ?confirm=<key>, which opens the
# access-code-gated confirm view. MUST match the deployed subdomain.
FORM_URL = "https://alphaletetrackerintake.streamlit.app"


def _lines(rec: TrackerRecord,
           lucy: "Optional[List[dict]]") -> Tuple[str, List[str]]:
    who = rec.owner or rec.key
    ch_names = " + ".join(n or "?" for _, n in rec.channel_pairs())
    title = "New tracker request — {} wants {} daily tracker board(s) in {}".format(
        who, len(rec.trackers), ch_names)
    link = "{}/?confirm={}".format(FORM_URL, rec.key or "")
    titles = {t["id"]: t["title"] for t in tracker_catalog()}
    thread = ["Requested by: {}".format(rec.requested_by or who),
              "Boards: " + ", ".join(titles.get(t, t) for t in rec.trackers)]
    if lucy:
        from automations.tracker_onboarding.slack_check import human_line
        for r in lucy:
            thread.append(human_line(r))
    thread.append("👉 <{}|Review + confirm {}'s trackers →>".format(link, who))
    return title, thread


def notify(rec: TrackerRecord, lucy: "Optional[List[dict]]" = None, *,
           dry_run: bool = False) -> Tuple[bool, str]:
    """Post the request heads-up (title line + detail as a thread reply).
    `lucy` = one slack_check result per channel (primary first).
    Returns (ok, note). Never raises — alerting must not break the submit."""
    title, thread = _lines(rec, lucy)
    if dry_run:
        print(title + "\n  " + "\n  ".join(thread))
        return True, "dry-run"

    channel = None
    try:
        from automations.day_orchestrator import registry, notify as _n
        cfg = registry.load_config()
        channel = _n._corrections_channel(cfg)
    except Exception as e:  # noqa: BLE001
        print("[tracker request_notify] config load failed: {}: {}".format(
            type(e).__name__, e))
    if not channel:
        return False, "no corrections channel configured (config unreadable?)"

    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
    except Exception as e:  # noqa: BLE001
        return False, "no Slack token — add a `slack_user_token` (xoxp-…) secret ({})".format(e)
    try:
        top = client.chat_postMessage(channel=channel, text=title,
                                      unfurl_links=False, unfurl_media=False)
        client.chat_postMessage(channel=channel, thread_ts=top["ts"],
                                text="\n".join(thread),
                                unfurl_links=False, unfurl_media=False)
        print("[tracker request_notify] posted request ping to {}".format(channel))
        return True, "posted to {}".format(channel)
    except Exception as e:  # noqa: BLE001
        print("[tracker request_notify] post FAILED to {}: {}".format(channel, e))
        return False, "{}: {}".format(type(e).__name__, str(e)[:200])
