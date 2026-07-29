"""Alert Megan when an office OWNER submits a metrics request.

The owner fills the simple request form (program + which metrics + who/where);
this posts a heads-up to the corrections channel — the standing place for
requests — so Megan can create the office's Google Sheet and finalize the wiring
in the Office Onboarding form (where the request is now pre-filled).

Best-effort by design: no Slack creds / a post failure never blocks the owner's
submission. The request is already saved to the 'Metric Requests' tab regardless.
"""
from __future__ import annotations

from typing import List, Tuple

from automations.office_onboarding.schema import OnboardingRecord, REPORTS_BY_KEY

# The onboarding (finalize) form. The ping deep-links to it with ?request=<key>
# so it opens pre-selected on this request. MUST match the deployed subdomain.
ONBOARDING_URL = "https://alphaletemetricsintake.streamlit.app"


def _lines(rec: OnboardingRecord) -> Tuple[str, List[str]]:
    fam = "D2D" if rec.family == "d2d" else "B2B"
    who = rec.owner or rec.business_name or rec.key
    title = (":sparkles: *New metrics request — {}*  ({} · {})".format(
        who, rec.business_name or "—", fam))
    plans = rec.channel_plans or []
    body: List[str] = []
    if plans:
        body.append("*Wants these posted:*")
        for p in plans:
            labels = ", ".join(REPORTS_BY_KEY[k].label for k in p.report_keys
                               if k in REPORTS_BY_KEY) or "_(no metrics)_"
            body.append("• *{}* → {}".format(p.channel_name, labels))
    else:
        body.append("*Wants these metrics in* {}:".format(
            rec.channel_name or "_(channel not given)_"))
        for er in rec.ordered_reports():
            rk = REPORTS_BY_KEY.get(er.key)
            body.append("• {}".format(rk.label if rk else er.key))
    body.append("")
    contact = []
    if rec.owner_email:
        contact.append("email {}".format(rec.owner_email))
    if rec.website:
        contact.append(rec.website)
    if rec.ov_account:
        contact.append("OV #{}".format(rec.ov_account))
    if contact:
        body.append("_Owner gave:_ " + " · ".join(contact))
    link = "{}/?request={}".format(ONBOARDING_URL, rec.key or "")
    body.append("👉 <{}|Finalize {}'s onboarding here> — it opens pre-filled with "
                "this request; create their Google Sheet, then submit.".format(
                    link, who))
    return title, body


def notify(rec: OnboardingRecord, *, dry_run: bool = False) -> Tuple[bool, str]:
    """Post the request heads-up to the corrections channel. Returns (ok, note).
    Never raises — alerting must not break the owner's submit.

    Posts DIRECTLY (rather than via day_orchestrator._post_corrections, which
    swallows Slack errors) so `note` carries the real failure reason — no token,
    invalid_auth, not_in_channel, missing_scope — surfaced to Megan on-screen.
    """
    title, body = _lines(rec)
    text = "\n".join([title] + body)
    if dry_run:
        print(text)
        return True, "dry-run"

    # 1) resolve the corrections channel from config (falls back to the known id).
    channel = None
    try:
        from automations.day_orchestrator import registry, notify as _n
        cfg = registry.load_config()
        channel = _n._corrections_channel(cfg)
    except Exception as e:  # noqa: BLE001
        print("[request_notify] config load failed: {}: {}".format(
            type(e).__name__, e))
    if not channel:
        return False, "no corrections channel configured (config unreadable?)"

    # 2) get a Slack client (reads SLACK_USER_TOKEN — set from the app's
    #    slack_user_token secret) and post, surfacing the real Slack error.
    try:
        from automations.shared.slack_metrics_post import _client
    except Exception as e:  # noqa: BLE001
        return False, "slack client import failed: {}".format(e)
    try:
        client = _client()
    except Exception as e:  # noqa: BLE001 — SlackPostError = no token resolves
        return False, "no Slack token — add a `slack_user_token` (xoxp-…) secret ({})".format(e)
    try:
        client.chat_postMessage(channel=channel, text=text,
                                unfurl_links=False, unfurl_media=False)
        print("[request_notify] posted metric-request ping to {}".format(channel))
        return True, "posted to {}".format(channel)
    except Exception as e:  # noqa: BLE001
        print("[request_notify] post FAILED to {}: {}".format(channel, e))
        return False, "{}: {}".format(type(e).__name__, str(e)[:200])
