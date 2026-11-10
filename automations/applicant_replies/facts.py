"""Everything Lucy is allowed to tell an applicant, per office.

Same rule as new_start_followup.lucy_replies: the facts are built HERE, in
code, and the model only picks and phrases them. A question the facts can't
answer goes to a person — never a guess. A confident wrong answer to an
applicant (wrong suite, wrong pay) is how we got "Is it suite 232 or 207".

Two kinds of fact:
  * per office — address, Zoom link, how each round is run, pay. From the
    'Recruiting Audit Offices' tab (sms_audit.offices), read from its cached
    copy so a shadow run never touches Sheets. An office that hasn't told us
    a fact simply doesn't get that line, and Lucy hands the question off
    (standing rule: a missing fact is never a pass).
  * company-wide — the approved answers in sms_audit.rebuttals, which carry
    Megan's rulings (megan-overrides.md). Address/pay/Zoom rows there are
    Raf's and are deliberately NOT reused here; this file uses the office's own.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from automations.sms_audit import offices as OFF
from automations.sms_audit import rebuttals as R

# Raf's ruling (via Megan 2026-09-27) is the pay line for Raf's own accounts.
# Any other office needs its own pay_low/pay_high on the offices tab.
RAF = "rafael hidalgo"
RAF_PAY = ("We offer weekly pay ranging from $1,000-$1,500 plus bonuses or "
           "commission.")
# The company applicants are texting. Raf's AppStream Office Name is
# "Alphalete Marketing, INC." — written here in sentence case (ruling 5).
# Any other office needs a `company` column on the offices tab; until then
# "what company is this?" is a gap and goes to a person, never a guess.
RAF_COMPANY = "Alphalete Marketing, Inc."

# Company-wide approved answers, by rebuttals topic. Wording is the approved
# text minus the bracketed notes meant for us, not the applicant.
COMPANY_ANSWERS = {
    "Schedule / hours": "Our shifts range from 8am - 8pm, Monday - Saturday.",
    "Door-to-door / is it sales": (
        "We have different locations available for this role either in "
        "office, in store or Business 2 Business, depending on which client "
        "you work with. We do not knock on random doors; we work with leads."),
    "No experience": ("All of our roles are entry level, and we provide "
                      "complete paid training."),
    "Advancement": ("We fully promote from within and provide cross training "
                    "in all departments if you are interested in growth."),
    "Clients we work with": (
        "Our main client right now is AT&T, and we also work with clients in "
        "other industries such as Verizon, T-Mobile, Apple, Google and Samsung."),
    "Spam / scam likely": (
        "Apologize: our office number probably isn't saved as a contact in "
        "their phone. Then remind them which role they applied for."),
    "Group interview": ("Yes, the first interview is a small group interview. "
                        "Lead with yes and reassure them (ruling 3)."),
    "What is the role / company": (
        "Name the role they applied to (it is in our first text to them). In "
        "this position they handle customer service, escalations, new sales "
        "and upgrades with our AT&T client."),
}


def _row(office_id):
    """The office's row from the cached tab, else the seed. Never Sheets."""
    rows = []
    if OFF.CACHE.exists():
        try:
            rows = json.loads(OFF.CACHE.read_text(encoding="utf-8"))
        except ValueError:
            rows = []
    for r in list(rows) + list(OFF.SEED):
        if str(r.get("office", "")).strip() == str(office_id):
            return {k: (v or "").strip() if isinstance(v, str) else v
                    for k, v in r.items()}
    return None


def _date(s):
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except (TypeError, ValueError):
            pass
    return None


def office(office_id):
    """The row, with its address history and Zoom ids loaded into rebuttals
    so the guard checks the SAME facts the prompt was given."""
    row = _row(office_id)
    if row is None:
        return None
    R.set_address_history(str(office_id), row.get("address"),
                          row.get("address_prev"),
                          _date(row.get("address_changed")))
    R.set_zoom(str(office_id), [row.get("zoom_id"), row.get("zoom2_id"),
                                _zoom_digits(row.get("zoom")),
                                _zoom_digits(row.get("zoom2"))])
    R.set_pay(str(office_id), row.get("pay_low"), row.get("pay_high"))
    return row


def _zoom_digits(link):
    m = re.search(r"/j/(\d{9,11})", link or "")
    return m.group(1) if m else ""


def company(row):
    if (row.get("company") or "").strip():
        return row["company"].strip()
    if (row.get("owner") or "").strip().lower() == RAF:
        return RAF_COMPANY
    return None


def pay_line(row):
    lo, hi = (row.get("pay_low") or "").strip(), (row.get("pay_high") or "").strip()
    if lo and hi:
        return ("We offer weekly pay ranging from ${}-${} plus bonuses or "
                "commission.".format(lo.lstrip("$"), hi.lstrip("$")))
    if (row.get("owner") or "").strip().lower() == RAF:
        return RAF_PAY
    return None


def block(office_id, when=None):
    """(facts_text, gaps). gaps = what this office hasn't told us, so the
    report can say which questions Lucy would have handed off and why."""
    row = office(office_id)
    if row is None:
        return None, ["office {} is not on the Recruiting Audit Offices tab"
                      .format(office_id)]
    gaps = []
    lines = ["Office account {} ({}).".format(office_id, row.get("icd_name") or
                                              row.get("owner") or "unknown")]
    name = company(row)
    if name:
        lines.append("Company: " + name + " (write it exactly like this).")
    else:
        gaps.append("company name")
    addr = R.address_on(str(office_id), when)
    if addr:
        lines.append("Interview address, every round: " + addr + ".")
    else:
        gaps.append("address")
    for label, mode, link, _lid in OFF.rounds(row):
        if not mode:
            # The seed row predates r1_mode; a Zoom link on file for round 1
            # is how 11280 has always run it.
            if label == "1st round" and link:
                mode = "Zoom"
            else:
                gaps.append("{} format".format(label))
                continue
        if mode.lower().startswith("zoom"):
            if link:
                lines.append("{}: over Zoom, link {}.".format(label, link))
            else:
                gaps.append("{} Zoom link".format(label))
        else:
            lines.append("{}: {} at the address above.".format(label, mode))
    pay = pay_line(row)
    if pay:
        lines.append("Pay: " + pay + " Never call any of it a \"base\".")
    else:
        gaps.append("pay range")
    lines.append("")
    lines.append("Company-wide approved answers:")
    for topic, answer in COMPANY_ANSWERS.items():
        lines.append("- {}: {}".format(topic, answer))
    return "\n".join(lines), gaps
