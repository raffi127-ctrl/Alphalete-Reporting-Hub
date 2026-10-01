"""`/recruiting-audit` on Jiraiya — an office fills a form once, gets its audit.

Megan 2026-10-01 asked for the command to read "/Recruiting Audit". Slack
slash commands cannot contain a space, so it is `/recruiting-audit`, with
`/aca` kept as a short alias for anyone already using it.

Megan 2026-10-01: "they send //ACA and Jiriyah pops open a short form for
them to fill out (should only need to do it once per office and you log it)
then he gets the info and brings it back in a document they can download and
review. He should also send an email copy of it. if the office is asked a
2nd time then we should just ask 'is all of this info still correct' showing
them the info we have and they can confirm."

So it is two modals, not one:
  FIRST TIME   the form — office id, address, phone, Zoom link, meeting id,
               and the email to send it to. Saved to the Recruiting Audit
               Offices tab against their Slack id.
  AFTER THAT   what we hold, read back, with Confirm or Change. Nobody
               retypes an address they already gave us, and a wrong one
               gets caught by a human reading it rather than by the audit
               quietly checking against stale info.

WHY ASK AT ALL. The audit can only say an address is wrong if someone told
it the right one. Every check here is skipped and SAID when its field is
blank, never passed silently.

A branch in Jiraiya's _handler, per that module's rule: one listener, one
app, one token, no second process to keep alive.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import json
import traceback
from pathlib import Path

from automations.sms_audit import offices as O

# Slack has no spaces in a command, so "/Recruiting Audit" is this. Aliases
# are cheap and a wrong guess at the name is a dead end for whoever typed it.
COMMANDS = ("recruiting-audit", "recruitingaudit", "recruiting_audit", "aca")
FORM = "aca_form"
CONFIRM = "aca_confirm"
OUTPUT = Path(__file__).resolve().parents[2] / "output"


def _text(block_id, label, initial="", hint="", optional=False,
          placeholder=""):
    el = {"type": "plain_text_input", "action_id": "v"}
    if initial:
        el["initial_value"] = initial
    if placeholder:
        el["placeholder"] = {"type": "plain_text", "text": placeholder[:150]}
    b = {"type": "input", "block_id": block_id, "element": el,
         "label": {"type": "plain_text", "text": label}}
    if hint:
        b["hint"] = {"type": "plain_text", "text": hint}
    if optional:
        b["optional"] = True
    return b


MODES = ["In person", "Zoom"]
# Megan 2026-10-01: Raf's 11280 is D2D, and the approved "what is the job"
# answer names the locations available. Naming the wrong one is how an
# applicant turns up expecting a desk.
CAMPAIGNS = ["D2D", "B2B", "In store", "In office", "Mixed"]


def _select(block_id, label, initial="", options=None):
    """A picker that REDRAWS the form when it changes — dispatch_action is
    what makes Slack tell us, and without it the Zoom fields could only
    appear after a submit."""
    opts = [{"text": {"type": "plain_text", "text": m}, "value": m}
            for m in (options or MODES)]
    el = {"type": "static_select", "action_id": "v", "options": opts}
    for o in opts:
        if o["value"].lower() == (initial or "").strip().lower():
            el["initial_option"] = o
    return {"type": "input", "block_id": block_id, "element": el,
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": label}}


def form_modal(prefill=None):
    """The form. Zoom link fields appear only for a round actually run over
    Zoom — asking an in-person office for a link makes a correct setup look
    incomplete, and a blank one would then read as a missing check."""
    p = prefill or {}
    r1 = (p.get("r1_mode") or "").strip()
    r2 = (p.get("r2_mode") or "").strip()
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "*One time per office.* We check what your templates and your "
         "recruiters actually send against what you tell us here, so an "
         "answer left blank means that check does not run."}},
        _text("office", "ApplicantStream office ID", p.get("office", ""),
              "The number in the top bar, e.g. 11280"),
        _text("label", "ICD name \u2014 exactly as OwnerVille spells it",
              p.get("icd_name", ""),
              "Must match OV: it is what joins this to every other report. "
              "A real variant goes in the ICD alias sheet."),
        _text("address", "Address where interviews are conducted",
              p.get("address", ""),
              "Including the suite \u2014 a wrong suite is the most common "
              "thing we find"),
        _text("phone", "Recruiting phone number", p.get("phone", ""),
              optional=True),
        _select("campaign", "What does this office run?",
                p.get("campaign", ""), options=CAMPAIGNS),
        _select("r1_mode", "1st rounds \u2014 in person or Zoom?", r1),
    ]
    if r1.lower().startswith("zoom"):
        blocks += [
            _text("zoom", "1st round Zoom link", p.get("zoom", ""),
                  "Paste it, don't retype it \u2014 a look-alike character "
                  "in a pasted link is invisible and the link is dead",
                  placeholder="https://us02web.zoom.us/j/..."),
            _text("zoom_id", "1st round meeting ID", p.get("zoom_id", ""),
                  optional=True),
        ]
    blocks.append(_select("r2_mode", "2nd rounds \u2014 in person or Zoom?", r2))
    if r2.lower().startswith("zoom"):
        blocks += [
            _text("zoom2", "2nd round Zoom link", p.get("zoom2", ""),
                  placeholder="https://us02web.zoom.us/j/..."),
            _text("zoom2_id", "2nd round meeting ID", p.get("zoom2_id", ""),
                  optional=True),
        ]
    blocks.append(_text("email", "Email the report to", p.get("email", ""),
                        "We send a copy as well as posting it here"))
    return {
        "type": "modal", "callback_id": FORM,
        "title": {"type": "plain_text", "text": "Recruiting Audit"},
        "submit": {"type": "plain_text", "text": "Run it"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def confirm_modal(office):
    """Second time round: read back what we hold."""
    def row(k, label):
        v = (office.get(k) or "").strip()
        return "*{}*\n{}".format(label, v if v else "_not given — that check "
                                 "is not running_")
    lines = [row("icd_name", "ICD name"),
             row("address", "Interviews conducted at"),
             row("phone", "Recruiting phone"),
             row("r1_mode", "1st rounds"), row("r2_mode", "2nd rounds")]
    for key, lbl in (("zoom", "1st round Zoom"), ("zoom2", "2nd round Zoom")):
        if (office.get(key) or "").strip():
            lines.append(row(key, lbl))
    lines.append(row("email", "Email it to"))
    return {
        "type": "modal", "callback_id": CONFIRM,
        "private_metadata": office.get("office", ""),
        "title": {"type": "plain_text", "text": "Recruiting Audit"},
        "submit": {"type": "plain_text", "text": "Yes, still correct"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text":
             "Is all of this still correct for office *{}*?".format(
                 office.get("office", ""))}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": t} for t in lines[:10]]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text":
             "Last confirmed {}. If anything changed, hit *Change it* and "
             "the form opens with these filled in.".format(
                 office.get("updated") or "—")}]},
            {"type": "actions", "block_id": "aca_change", "elements": [
                {"type": "button", "action_id": "aca_change_btn",
                 "text": {"type": "plain_text", "text": "Change it"},
                 "value": office.get("office", "")}]},
        ],
    }


def values_of(view):
    """Form values, flattened — text inputs AND the mode selects."""
    out = {}
    for bid, block in (view.get("state", {}).get("values") or {}).items():
        for _aid, el in block.items():
            if el.get("type") == "static_select":
                out[bid] = ((el.get("selected_option") or {})
                            .get("value") or "").strip()
            else:
                out[bid] = (el.get("value") or "").strip()
    return out


def on_command(client, req, user_id):
    """`/aca` — confirm what we hold, or ask for it the first time."""
    known = None
    try:
        known = O.find(slack_user=user_id)
    except Exception:  # noqa: BLE001 — never block the form on a sheet read
        known = None
    view = confirm_modal(known) if known else form_modal()
    client.web_client.views_open(trigger_id=req.payload["trigger_id"],
                                 view=view)


def save_and_run(user_id, vals, web=None):
    """Store the row, run the audit, return (office, report path)."""
    from automations.sms_audit import icd_audit as IA
    row = dict(vals)
    if "label" in row:                     # the form's block id
        row["icd_name"] = row.pop("label")
    row["slack_user"] = user_id
    row.setdefault("active", "yes")
    office, _created = O.save(row)
    path = IA.report_path(office["office"])
    IA.main(["--office", office["office"]])
    return office, path


def deliver(web, user_id, office, path):
    """DM the document, then email a copy. Each is reported separately —
    'sent' has to mean the thing actually went, per the house rule."""
    sent = []
    try:
        web.files_upload_v2(
            channel=user_id, file=str(path),
            filename=path.name, title="Recruiting Audit — {}".format(
                office.get("icd_name") or office.get("office")),
            initial_comment="Here is the audit for *{}*. It opens with any "
                            "check we could NOT run and why.".format(
                                office.get("icd_name") or office.get("office")))
        sent.append("Slack")
    except Exception as e:  # noqa: BLE001
        sent.append("Slack FAILED ({})".format(type(e).__name__))
    to = (office.get("email") or "").strip()
    if to:
        try:
            from automations.shared import report_email as RE
            msg = RE.build_message(
                subject="Recruiting Audit — {}".format(
                    office.get("icd_name") or office.get("office")),
                to=[to], title="Recruiting Audit",
                blocks=[], attach=True, files=[(path.name, path)],
                intro_html="<p>The audit for <b>{}</b> is attached. It opens "
                           "with any check we could not run, and why.</p>"
                           .format(office.get("icd_name") or office.get("office")))
            RE.send_message(msg)
            sent.append("email to {}".format(to))
        except Exception as e:  # noqa: BLE001
            sent.append("email FAILED ({})".format(type(e).__name__))
    else:
        sent.append("no email on file, so none sent")
    return sent


def wants(req):
    """Is this request ours? Asked BEFORE acking, so Jiraiya only swallows
    the envelopes that belong to /aca and /dd keeps working."""
    p = req.payload or {}
    if req.type == "slash_commands":
        return p.get("command", "").lstrip("/").lower() in COMMANDS
    if req.type == "interactive":
        if p.get("type") == "block_actions":
            if p.get("view", {}).get("callback_id") == FORM:
                return True
            return any(a.get("action_id") == "aca_change_btn"
                       for a in p.get("actions", []))
        if p.get("type") == "view_submission":
            return p.get("view", {}).get("callback_id") in (FORM, CONFIRM)
    return False


def handle(client, req):
    """Return True when this request was ours."""
    p = req.payload or {}
    if req.type == "slash_commands" and p.get("command", "").lstrip("/").lower() \
            in COMMANDS:
        on_command(client, req, p.get("user_id", ""))
        return True
    # a mode select changed — redraw with or without that round's Zoom
    # fields, carrying everything already typed so nothing is lost
    if req.type == "interactive" and p.get("type") == "block_actions" \
            and (p.get("view", {}).get("callback_id") == FORM):
        vals = values_of(p["view"])
        if "label" in vals:
            vals["icd_name"] = vals.pop("label")
        client.web_client.views_update(view_id=p["view"]["id"],
                                       view=form_modal(vals))
        return True
    if req.type == "interactive" and p.get("type") == "block_actions" \
            and any(a.get("action_id") == "aca_change_btn"
                    for a in p.get("actions", [])):
        oid = p["actions"][0].get("value", "")
        client.web_client.views_update(
            view_id=p["view"]["id"], view=form_modal(O.find(office_id=oid)))
        return True
    if req.type == "interactive" and p.get("type") == "view_submission" \
            and p.get("view", {}).get("callback_id") in (FORM, CONFIRM):
        user_id = p.get("user", {}).get("id", "")
        view = p["view"]
        if view["callback_id"] == CONFIRM:
            vals = O.find(office_id=view.get("private_metadata", "")) or {}
        else:
            vals = values_of(view)
        import threading
        threading.Thread(target=_background, args=(client, user_id, vals),
                         daemon=True).start()
        return True
    return False


def _background(client, user_id, vals):
    web = client.web_client
    try:
        office, path = save_and_run(user_id, vals, web)
        sent = deliver(web, user_id, office, path)
        gaps = O.missing_fields(office)
        note = ""
        if gaps:
            note = "\n\n*Not checked* (nothing on file to check against): " \
                   + "; ".join(g.split(" — ")[0] for g in gaps)
        web.chat_postMessage(
            channel=user_id,
            text="Audit for *{}* — {}.{}".format(
                office.get("icd_name") or office.get("office"),
                ", ".join(sent), note))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        try:
            web.chat_postMessage(
                channel=user_id,
                text="The audit did not finish: {}. Nothing was sent.".format(
                    type(e).__name__))
        except Exception:  # noqa: BLE001
            pass
