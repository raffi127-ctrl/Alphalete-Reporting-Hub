"""Reddit / Indeed / Glassdoor mentions, read from Lucy's inbox -> the office.

Lucy can't read Indeed or Glassdoor herself (robot checks -- and we don't get
around those), and Reddit search through Google lags by days. What CAN reach
us within minutes is email:

  * Reddit:   a free keyword-alert service (e.g. F5Bot) watching each
              office's business name, sending to alphaletereporting@gmail.com
  * Indeed / Glassdoor: the employer account's own "new review" emails,
              forwarded by the office (or sent there directly)

Every 10-minute pass reads NEW mail in that inbox. A message that links to
reddit.com / indeed.com / glassdoor.com AND names an office's business name
(or Alphalete's) becomes an alert -- short header, the subject + snippet +
link in the thread -- in that office's room, the alerts channel, and a DM to
the owner. Format-agnostic on purpose: we match links and names, not one
service's template, so a forwarded email works the same as a direct one.

INDEED IS NOTIFY-ONLY (Megan's standing rule): the alert says so; Lucy never
replies there.

FIRST LOOK SEEDS: the first pass records the newest message as the starting
point and alerts nothing. Each message alerts once (by its IMAP UID).
"""
from __future__ import annotations

import email
import imaplib
import json
import re
from email.header import decode_header
from pathlib import Path
from typing import Dict, List, Optional

ADDRESS = "alphaletereporting@gmail.com"
PASSWORD_FILE = Path.home() / ".config" / "recruiting-report" / "gmail-app-password"
STATE = Path.home() / ".config" / "brand-audit" / "email_alerts.json"
SITES = (("Reddit", r"reddit\.com"), ("Indeed", r"indeed\.com"),
         ("Glassdoor", r"glassdoor\.[a-z.]+"))


def _decode(h: str) -> str:
    return "".join(t.decode(c or "utf-8", "replace") if isinstance(t, bytes) else t
                   for t, c in decode_header(h or ""))


def text_of(msg) -> str:
    """Plain text of an email (HTML stripped when there's no text part)."""
    parts = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_payload(decode=True).decode(
                part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if ctype == "text/html":
            body = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", body)
            body = re.sub(r"(?s)<a [^>]*href=[\"']([^\"']+)[\"'][^>]*>", r" \1 ", body)
            body = re.sub(r"(?s)<[^>]+>", " ", body)
        parts.append(body)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


# ONLY mail that comes FROM one of these services (directly, or forwarded
# with its original "From:" line in the body). Lucy's inbox also gets report
# emails that can name an office next to an Indeed link -- those are not
# reviews and must never alert.
SENDERS = r"(f5bot\.com|indeed\.com|indeedemail\.com|glassdoor\.com)"


def from_a_watcher(sender: str, body: str) -> bool:
    if re.search(SENDERS, sender or "", re.I):
        return True
    return bool(re.search(r"From:[^\n]{0,120}?@[\w.-]*" + SENDERS, body or "", re.I))


def classify(subject: str, body: str, offices: List) -> List[Dict]:
    """[{office, site, link}] for each office this message is about."""
    blob = f"{subject} {body}"
    out = []
    for site, pat in SITES:
        links = re.findall(r"https?://[^\s\"'<>)]*" + pat + r"[^\s\"'<>)]*", blob, re.I)
        if not links and not re.search(pat, blob, re.I):
            continue
        for P in offices:
            if P.business_name and re.search(r"\b" + re.escape(P.business_name) + r"\b",
                                             blob, re.I):
                out.append({"office": P, "site": site, "link": (links or [""])[0]})
    return out


def messages(site: str, P, subject: str, body: str, link: str) -> tuple:
    verb = {"Reddit": "post mentioning", "Indeed": "Indeed review for",
            "Glassdoor": "Glassdoor review for"}[site]
    head = f":rotating_light: *New {verb} {P.business_name}*"
    snippet = body[:500] + ("…" if len(body) > 500 else "")
    detail = f"*{subject}*\n> {snippet}"
    if link:
        detail += f"\n{link}"
    if site == "Indeed":
        detail += "\n_Notify only: Lucy never replies on Indeed._"
    return head, detail


def _load() -> Dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d: Dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=2))


def _inbox():
    pw = PASSWORD_FILE.read_text().replace(" ", "").strip()
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(ADDRESS, pw)
    M.select("INBOX", readonly=True)
    return M


def check(offices: List, cl, *, live: bool, mailbox=None) -> List[Dict]:
    """New mail -> alerts. `offices` = the live offices + Alphalete."""
    from automations.brand_audit.config import ALERT_SLACK_CHANNEL_ID
    M = mailbox or _inbox()
    st = _load()
    try:
        uids = [int(u) for u in (M.uid("search", None, "ALL")[1][0] or b"").split()]
        if not uids:
            return []
        last = st.get("last_uid")
        if last is None:
            if live:
                _save({"last_uid": max(uids)})
            return [{"action": "seeded", "note": f"starting after message {max(uids)}"}]
        acts = []
        for uid in [u for u in uids if u > last][:200]:
            raw = M.uid("fetch", str(uid), "(BODY.PEEK[])")[1][0][1]
            msg = email.message_from_bytes(raw)
            subject, body = _decode(msg.get("Subject")), text_of(msg)
            if not from_a_watcher(_decode(msg.get("From")), body):
                continue
            for hit in classify(subject, body, offices):
                P = hit["office"]
                head, detail = messages(hit["site"], P, subject, body, hit["link"])
                acts.append({"action": "mention_alert" if live else "would_alert",
                             "note": f"{hit['site']} · {P.business_name}"})
                if not live:
                    continue
                rooms = [P.reviews_channel]
                if P.key != "alphalete" and ALERT_SLACK_CHANNEL_ID not in rooms:
                    rooms.append(ALERT_SLACK_CHANNEL_ID)
                for ch in rooms:
                    r = cl.chat_postMessage(channel=ch, text=head)
                    cl.chat_postMessage(channel=ch, thread_ts=r.get("ts"), text=detail)
                if P.owner_slack_id:
                    cl.chat_postMessage(channel=P.owner_slack_id, text=f"{head}\n{detail}")
        if live:
            _save({"last_uid": max(uids)})
        return acts
    finally:
        if mailbox is None:
            try:
                M.logout()
            except Exception:
                pass
