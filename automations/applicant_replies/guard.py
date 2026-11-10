"""The checks every Lucy draft has to pass before it could ever be sent.

These are the SAME checks the weekly SMS audit scores recruiters and the AI
on — imported, not copied, so Lucy can't be held to a looser standard than
the people she covers for, and a ruling changed in rebuttals.py changes
here too. A draft that fails any of them is HELD, with the reason, and in a
live run a held draft would go to a person instead.

Curly quotes / dashes are not a failure: they are swapped for plain ones
first (sms_text.clean), because that is a mechanical fix, not a judgement.
"""
from __future__ import annotations

import re

from automations.applicant_replies import config as C
from automations.sms_audit import escalations as E
from automations.sms_audit import rebuttals as R
from automations.sms_audit import sms_text as S

# Recruiting copy compliance (standing rule 2026-07-09): never an age,
# gender or "who we hire" preference.
PROTECTED = re.compile(
    r"\b(young|younger|old(er)?|age[ds]?|years? old|\d{2}\s?-?\s?somethings?|"
    r"guys|girls|men|women|male|female|ladies|gentlemen|pregnan\w*|"
    r"religio\w*|nationality|citizen\w*|race|disabilit\w*)\b", re.I)

# Template plumbing that leaked through.
PLACEHOLDER = re.compile(r"\[[^\]]{1,40}\]|\{[^}]{1,40}\}|applicantFirstName|"
                         r"adPostingTitle|officeAddress\w*|\bxxxx\b|\bNAME\b")

LINK = re.compile(r"https?://\S+", re.I)


def shouts(body):
    """Stricter than rebuttals.shouts. The audit excuses a capitalised job
    title or company name because AppStream pastes the ad's own title into
    templates — the recruiter never typed it. Lucy writes every word
    herself, so ruling 5 applies to all of it; only links, emails and
    genuine initialisms (R.SHOUTING's own exclusions) are let through."""
    skip = R._addressy_spans(body)
    for m in R.SHOUTING.finditer(body):
        if any(a < m.end() and m.start() < b for a, b in skip):
            continue
        got = m.group(0).strip(" ,.&-")
        if got:
            return got
    return None


def check(office_id, text, when=None, reason=None):
    """(clean_text, [problems]). Empty problems = would be sendable."""
    body = S.clean(" ".join((text or "").split()))
    probs = []
    if reason == "opt_out":
        if body:
            probs.append("replied to someone who said stop")
        return body, probs
    if not body:
        return body, probs
    if R.REFUSES.search(body) or R.DEFERS.search(body):
        probs.append("deflects instead of answering (ruling 4)")
    if E.ESC_CALL_PROMISE.search(body):
        probs.append("puts a time on a call (ruling 8)")
    if R.says_base_pay(body):
        probs.append("says there is a \"base\" pay (ruling 1)")
    if E.PAY_TOPIC.search(body) and E.PAY_BAD.search(body):
        probs.append("pay figure under $1,000 a week (ruling 1)")
    over = R.pay_outside_range(str(office_id), body, when)
    if over:
        probs.append("pay outside this office's range: " + over)
    shout = shouts(body)
    if shout:
        probs.append("block capitals: " + shout + " (ruling 5)")
    addr = R.wrong_address(str(office_id), body, when)
    if addr:
        probs.append("not this office's address: " + addr)
    zoom = R.wrong_zoom(str(office_id), body, when)
    if zoom:
        probs.append("not this office's Zoom: " + zoom)
    for link in LINK.findall(body):
        if "zoom.us" not in link.lower():
            probs.append("a link we didn't supply: " + link)
    m = PROTECTED.search(body)
    if m:
        probs.append("protected-class wording: " + m.group(0))
    m = PLACEHOLDER.search(body)
    if m:
        probs.append("unfilled placeholder: " + m.group(0))
    seg = S.measure(body)["segments"]
    if seg > C.MAX_SEGMENTS:
        probs.append("{} SMS segments (target {})".format(seg, C.MAX_SEGMENTS))
    return body, probs
