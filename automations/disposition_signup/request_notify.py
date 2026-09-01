"""Alert Megan when an owner self-submits a disposition sign-up.

The owner fills the public link; the request lands on the 'Disposition Signup'
tab as status=pending. This posts a heads-up to the corrections channel — the
standing place for requests — with a confirm deep-link. NOTHING is wired until
Megan opens that link, sets the campaign + Office Access, and clicks Confirm.

Mirrors tracker_onboarding.request_notify: best-effort by design — no Slack
creds / a post failure never blocks the owner's submission (it is saved
anyway). Corrections-channel format (standing): one emoji-free line, detail in
the thread.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from automations.disposition_signup.schema import DispositionRecord

# The deployed form. The ping deep-links to ?confirm=<key>, which opens the
# access-code-gated confirm view. MUST match the deployed subdomain.
FORM_URL = "https://alphaletedispositions.streamlit.app"


def _lines(rec: DispositionRecord, lucy: "Optional[dict]" = None
           ) -> Tuple[str, List[str]]:
    who = rec.owner or rec.key
    title = ("New disposition sign-up — {} wants the knocks and dispositions "
             "board {}".format(who, rec.cadence_label().lower()))
    link = "{}/?confirm={}".format(FORM_URL, rec.key or "")
    thread = ["- Requested by: {}".format(rec.requested_by or who),
              "- ICD (OwnerVille): {}".format(rec.owner or "?"),
              "- Owner/applicant ID: {}".format(rec.ov_account or "not given"),
              "- Campaign: {}".format(
                  (rec.campaign() or {}).get("name", "?")),
              "- How often: {}".format(rec.cadence_label())]
    thread += ["- {}".format(r) for r in rec.routes()]
    if rec.notes.strip():
        thread.append("- Notes: {}".format(rec.notes.strip()[:300]))
    if lucy:
        try:
            from automations.tracker_onboarding.slack_check import human_line
            thread.append("- " + human_line(lucy))
        except Exception:                            # noqa: BLE001
            pass
    thread.append("- Wired OFF until Office Access is granted for {} — "
                  "impersonation fails every tick without it.".format(who))
    thread.append("<{}|Review + confirm {}'s dispositions>".format(link, who))
    return title, thread


def notify(rec: DispositionRecord, lucy: "Optional[dict]" = None, *,
           dry_run: bool = False) -> Tuple[bool, str]:
    """Post the request heads-up (title line + detail as a thread reply).
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
    except Exception as e:                           # noqa: BLE001
        print("[disposition request_notify] config load failed: {}: {}".format(
            type(e).__name__, e))
    if not channel:
        return False, "no corrections channel configured (config unreadable?)"

    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
    except Exception as e:                           # noqa: BLE001
        return False, ("no Slack token — add a `slack_user_token` (xoxp-...) "
                       "secret ({})".format(e))
    try:
        top = client.chat_postMessage(channel=channel, text=title,
                                      unfurl_links=False, unfurl_media=False)
        client.chat_postMessage(channel=channel, thread_ts=top["ts"],
                                text="\n".join(thread),
                                unfurl_links=False, unfurl_media=False)
        print("[disposition request_notify] posted request ping to {}".format(
            channel))
        return True, "posted to {}".format(channel)
    except Exception as e:                           # noqa: BLE001
        print("[disposition request_notify] post FAILED to {}: {}".format(
            channel, e))
        return False, "{}: {}".format(type(e).__name__, str(e)[:200])
