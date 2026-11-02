"""Hand an office Mac the SaraPlus code it is waiting for. Runs on Lucy 1.

WHY (Eve/Megan, 2026-10-29). Four SaraPlus accounts -- Eveliz, Luke, Rashad,
Tre -- are asked for an emailed code on EVERY fresh login, and SaraPlus ends
the session every 2-4 days whatever the keep-alive does. Each time the office
went dark until a person found the email and typed the code, and everybody got
a DM in the meantime. The code is the only thing missing, and it is sitting in
an inbox.

HOW, in three hops, none of them new:

  1. The office Mac hits the code screen, presses Get Code, and files a
     `probe-code-request` row on ICD Faults (the one road home it already
     has; probes are never posted). The summary carries the instant it asked.
  2. HERE, once a minute inside the poster: for each open request, ONE look
     in the reporting inbox for a SaraPlus code mailed to that office's own
     address after that instant. The owner forwards those mails to us -- the
     same forward Carlos has had since 2026-09-03 (rc_contact_sync). Found ->
     written to 'Code Answers'. Not yet -> left for the next tick. Never a
     wait inside the poster.
  3. The Mac asks the relay for its answer (relay `code_poll`, keyed like
     every other call) and types it in.

WHICH CODE IS WHOSE. One inbox, several offices, so a code is matched on the
address SaraPlus sent it TO (the forward keeps the original headers) and on
time. That address is a row on 'SaraPlus Code Mail', filled in by us when the
owner sets the forward up -- NOT in the repo, which is public. An office with
no row is answered "none" at once, so its Mac stops waiting and falls back to
the DM it always got.

THE GMAIL CONFIRMATION IS OURS TO CLICK, AND WE CLICK IT (Eve 2026-11-02).
Gmail will not forward until the receiving inbox accepts, and that step waited
on Megan or Eve. confirm_forwards accepts it, only for an address an office
filed on MAIL_TAB. check_forward_scope tells us if an address starts sending
more than SaraPlus's codes: the owner's filter is supposed to be the only
forward, and alphaletegp's whole-inbox forward shows how that one goes.

COST. Nothing at all while no Mac is asking -- one read of a tab the poster
already reads. While one is asking, one IMAP search a minute, for at most
REQUEST_MAX_MIN minutes.
"""
from __future__ import annotations

import datetime as dt
import email
import html
import http.cookiejar
import imaplib
import re
import urllib.parse
import urllib.request
from email.header import decode_header, make_header
from typing import Dict, Iterable, List, Optional, Tuple

REQUEST_STAGE = "probe-code-request"
SUMMARY_PREFIX = "SaraPlus code request "

CODES_TAB = "Code Answers"
CODES_HEADER = ["Office", "Requested At", "Code", "Written At", "Taken At", "Status"]
MAIL_TAB = "SaraPlus Code Mail"
MAIL_HEADER = ["Office", "Forwards From", "Added", "Note"]

# How long a request is worth answering. The Mac waits CODE_WAIT_MIN (9) for
# its answer; a code found after that is typed into nothing.
REQUEST_MAX_MIN = 12

STATUS_READY = "ready"
STATUS_NONE = "none"

# Setup's half (code_forward): the address SaraPlus mails this office's codes
# to, typed by the owner on the Zoom. Moved from ICD Faults onto MAIL_TAB here.
FORWARD_STAGE = "probe-code-forward"
FORWARD_PREFIX = "SaraPlus codes go to "


def summary_for(since: dt.datetime) -> str:
    """The fault summary a request is filed under. The instant rides in it
    because the relay folds same-summary rows into one -- two requests must
    never share a row."""
    return SUMMARY_PREFIX + since.isoformat(timespec="seconds")


def since_of(summary: str) -> Optional[dt.datetime]:
    """The instant a request was made, back out of its summary."""
    s = (summary or "").strip()
    if not s.startswith(SUMMARY_PREFIX):
        return None
    word = s[len(SUMMARY_PREFIX):].split()[0] if s[len(SUMMARY_PREFIX):].strip() else ""
    try:
        when = dt.datetime.fromisoformat(word)
    except ValueError:
        return None
    return when if when.tzinfo else when.astimezone()


def forward_summary(address: str) -> str:
    return FORWARD_PREFIX + address.strip()


def address_of(summary: str) -> str:
    s = (summary or "").strip()
    if not s.startswith(FORWARD_PREFIX):
        return ""
    word = s[len(FORWARD_PREFIX):].strip().split()
    return word[0] if word and "@" in word[0] else ""


def query_for(address: str) -> str:
    """Gmail search for SaraPlus codes mailed to ONE office's address."""
    return "from:security.info@saraplus.com to:%s newer_than:1d" % address.strip()


def _tab(book, title: str, header: List[str]):
    try:
        return book.worksheet(title)
    except Exception:  # noqa: BLE001 -- first use: make it, headed
        sh = book.add_worksheet(title=title, rows=200, cols=len(header))
        sh.update("A1", [header])
        return sh


def forwarding_addresses(book) -> Dict[str, str]:
    """office -> the address its SaraPlus codes are mailed to."""
    try:
        rows = book.worksheet(MAIL_TAB).get_all_values()
    except Exception:  # noqa: BLE001 -- no tab yet: nobody is set up
        return {}
    out = {}
    for r in rows[1:]:
        if len(r) >= 2 and r[0].strip() and "@" in r[1]:
            out[r[0].strip().lower()] = r[1].strip()
    return out


def _newest_code(since: dt.datetime, query: str):
    """One look in the reporting inbox. Imported late: only Lucy 1 has it."""
    from automations.rc_contact_sync import verify_code as VC
    return VC._newest_code(since, query)


def answer_requests(book=None, *, send: bool = False,
                    now: Optional[dt.datetime] = None, newest_code=None,
                    log=print) -> List[Dict]:
    """Answer every open code request that can be answered. Never raises.

    Returns what was decided, one dict per request looked at.
    """
    from automations.icd_alerts import post as P

    newest_code = newest_code or _newest_code
    now = now or dt.datetime.now().astimezone()
    try:
        if book is None:
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        faults = [f for f in P.open_faults(now.date(), book=book)
                  if f["stage"] == REQUEST_STAGE]
    except Exception as e:  # noqa: BLE001 -- never cost the poster its tick
        log("code requests: could not read faults: %s" % type(e).__name__)
        return []
    if not faults:
        return []

    addresses = forwarding_addresses(book)
    done = []
    try:
        codes = _tab(book, CODES_TAB, CODES_HEADER) if send else None
        faults_tab = book.worksheet(P.FAULTS_TAB) if send else None
    except Exception as e:  # noqa: BLE001
        log("code requests: could not open the tabs: %s" % type(e).__name__)
        return []
    stamp = now.isoformat(timespec="seconds")

    def _close(f, why):
        if send:
            try:
                faults_tab.update_cell(f["rownum"], P.F_POSTED + 1, "%s %s" % (stamp, why))
            except Exception as e:  # noqa: BLE001
                log("code requests: could not mark row %d: %s" % (f["rownum"], type(e).__name__))

    def _answer(office, since, code, status):
        if send:
            codes.append_row([office, since.isoformat(timespec="seconds"), code,
                              stamp, "", status], value_input_option="RAW")

    for f in faults:
        office = f["office"]
        since = since_of(f["summary"])
        if since is None:
            _close(f, "unreadable request")
            done.append({"office": office, "status": "unreadable"})
            continue
        if now - since > dt.timedelta(minutes=REQUEST_MAX_MIN):
            log("CODE   %-10s request from %s expired unanswered"
                % (office, since.strftime("%H:%M")))
            _close(f, "expired")
            done.append({"office": office, "status": "expired"})
            continue
        address = addresses.get(office)
        if not address:
            log("CODE   %-10s asked for a code; no forward set up -> none" % office)
            try:
                _answer(office, since, "", STATUS_NONE)
            except Exception as e:  # noqa: BLE001
                log("code requests: could not answer %s: %s" % (office, type(e).__name__))
                continue
            _close(f, "no forward")
            done.append({"office": office, "status": STATUS_NONE})
            continue
        try:
            hit = newest_code(since, query_for(address))
        except Exception as e:  # noqa: BLE001 -- inbox down: try again next tick
            log("CODE   %-10s inbox not readable: %s" % (office, type(e).__name__))
            done.append({"office": office, "status": "inbox-error"})
            continue
        if not hit:
            log("CODE   %-10s waiting for the code mail (asked %s)"
                % (office, since.strftime("%H:%M:%S")))
            done.append({"office": office, "status": "waiting"})
            continue
        code, when = hit
        log("CODE   %-10s code mailed %s handed over" % (office, when.strftime("%H:%M:%S")))
        try:
            _answer(office, since, code, STATUS_READY)
        except Exception as e:  # noqa: BLE001
            log("code requests: could not write %s's code: %s" % (office, type(e).__name__))
            continue
        _close(f, "answered")
        done.append({"office": office, "status": STATUS_READY})
    return done


def _tell_us(text: str) -> None:
    """Megan + Eve, as Lucy: the one step left is ours."""
    from automations.icd_alerts import offices as O
    from automations.icd_alerts import post as P
    P._group_dm(list(O.APPROVERS), text)


def record_forwards(book=None, *, send: bool = False,
                    now: Optional[dt.datetime] = None, tell=None,
                    log=print) -> List[Dict]:
    """Put each address setup sent home onto MAIL_TAB. Never raises.

    ONE ROW PER OFFICE: a second setup run replaces the address rather than
    adding a row the matcher would have to choose between. Then Megan + Eve
    hear about it, because Gmail will not forward a thing until somebody
    clicks its confirmation mail in the reporting inbox.
    """
    from automations.icd_alerts import post as P

    tell = tell or _tell_us
    now = now or dt.datetime.now().astimezone()
    try:
        if book is None:
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        faults = [f for f in P.open_faults(now.date(), book=book)
                  if f["stage"] == FORWARD_STAGE]
    except Exception as e:  # noqa: BLE001
        log("code forwards: could not read faults: %s" % type(e).__name__)
        return []
    if not faults:
        return []
    done = []
    try:
        mail = _tab(book, MAIL_TAB, MAIL_HEADER) if send else None
        faults_tab = book.worksheet(P.FAULTS_TAB) if send else None
        rows = mail.get_all_values() if send else []
    except Exception as e:  # noqa: BLE001
        log("code forwards: could not open the tabs: %s" % type(e).__name__)
        return []
    stamp = now.isoformat(timespec="seconds")
    for f in faults:
        office, address = f["office"], address_of(f["summary"])
        log("FWD    %-10s SaraPlus code forward from setup" % office)
        if not send:
            done.append({"office": office, "status": "dry-run"})
            continue
        try:
            if address:
                at = next((i for i, r in enumerate(rows[1:], start=2)
                           if r and r[0].strip().lower() == office), None)
                row = [office, address, stamp, "from setup"]
                if at:
                    mail.update("A%d:D%d" % (at, at), [row])
                else:
                    mail.append_row(row, value_input_option="RAW")
                    rows.append(row)
            faults_tab.update_cell(f["rownum"], P.F_POSTED + 1,
                                   "%s %s" % (stamp, "recorded" if address else "no address"))
        except Exception as e:  # noqa: BLE001
            log("code forwards: could not record %s: %s" % (office, type(e).__name__))
            continue
        done.append({"office": office, "status": "recorded" if address else "no address"})
    return done


# --- accepting Gmail's confirmation -----------------------------------------
CONFIRM_QUERY = "from:forwarding-noreply@google.com subject:forwarding newer_than:2d"
NOTE_CONFIRMED = "gmail confirmed"
NOTE_NO_MAIL = "no gmail mail yet"
NOTE_FAILED = "gmail confirm failed"
# An owner adds the address, then sends it home: the mail is normally there
# already. Past this they most likely stopped before Add a forwarding address.
CONFIRM_PATIENCE_MIN = 20
# After this a row is left alone, so a forward nobody finished costs nothing.
CONFIRM_WINDOW_DAYS = 2

# THE FIRST LINK, BY ITS WORDING. The same mail's second link CANCELS.
_CONFIRM_LINK = re.compile(
    r"confirm the request:\s*(https://mail-settings\.google\.com/mail/\S+)", re.I)
_REQUESTER = re.compile(r"Receive Mail from\s+([\w.+-]+@[\w.-]+\w)", re.I)
_ASKS_CONFIRM = "please confirm forwarding"


def confirmation_link(body: str) -> str:
    m = _CONFIRM_LINK.search(body or "")
    return m.group(1) if m else ""


def requester_of(subject: str) -> str:
    m = _REQUESTER.search(subject or "")
    return m.group(1).lower() if m else ""


def _imap():
    from automations.shared import email_ingest as I
    M = imaplib.IMAP4_SSL(I.IMAP_HOST)
    M.login(I.ACCOUNT, I._app_password())
    M.select('"[Gmail]/All Mail"', readonly=True)
    return M


def _search(M, query: str) -> List[bytes]:
    typ, data = M.search(None, "X-GM-RAW", '"%s"' % query)
    return (data[0] or b"").split() if typ == "OK" else []


def _confirmation_mails() -> Dict[str, str]:
    """requester address -> confirm link, newest mail winning. Read-only."""
    M = _imap()
    try:
        out: Dict[str, str] = {}
        for uid in _search(M, CONFIRM_QUERY):      # oldest first: newest overwrites
            typ, data = M.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK" or not data or not data[0]:
                continue
            msg = email.message_from_bytes(data[0][1])
            who = requester_of(str(make_header(decode_header(msg.get("Subject", "")))))
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = (part.get_payload(decode=True) or b"").decode(
                        part.get_content_charset() or "utf-8", "replace")
                    link = confirmation_link(body)
                    if who and link:
                        out[who] = link
                    break
        return out
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def _page_text(raw: bytes) -> str:
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", raw.decode("utf-8", "replace"))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _browser_fetch():
    """One visit to Gmail's page, the way a browser makes it.

    The page sets a cookie when it opens and the Confirm button posts back to
    the same address. Luke's forward, 2026-11-02: Lucy's bare post came back
    still asking (ValueError), and the same link took a person's click in a
    browser. The missing cookie is the likely difference, not a proven one; the
    next owner's forward is the proof. So the read and the press share a cookie
    jar, and the press says where it came from.
    """
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def fetch(url: str, data: Optional[bytes] = None) -> str:
        headers = {"User-Agent": "Mozilla/5.0"}
        if data is not None:
            parts = urllib.parse.urlsplit(url)
            headers["Referer"] = url
            headers["Origin"] = "%s://%s" % (parts.scheme, parts.netloc)
        req = urllib.request.Request(url, data=data, headers=headers)
        with opener.open(req, timeout=30) as r:
            return _page_text(r.read())
    return fetch


def accept_confirmation(link: str, requester: str, fetch=None) -> None:
    """Press Confirm on Gmail's page. Raises unless it clearly took.

    The link alone confirms nothing: it opens a page with one Confirm button
    (read off the real page 2026-11-02). That page names who is forwarding, so
    it is checked against the address we expected before anything is pressed.
    """
    fetch = fetch or _browser_fetch()
    if not link.startswith("https://mail-settings.google.com/"):
        raise ValueError("not Gmail's confirmation page")
    page = fetch(link).lower()
    if _ASKS_CONFIRM not in page or requester.lower() not in page:
        raise ValueError("unexpected confirmation page: %s" % page[:120])
    after = fetch(link, b"").lower()
    if _ASKS_CONFIRM in after:
        raise ValueError("still asking after Confirm: %s" % after[:120])


def _added_at(text: str) -> Optional[dt.datetime]:
    try:
        when = dt.datetime.fromisoformat((text or "").strip())
    except ValueError:
        return None
    return when if when.tzinfo else when.astimezone()


def confirm_forwards(book=None, *, send: bool = False,
                     now: Optional[dt.datetime] = None, mails=None, accept=None,
                     tell=None, log=print) -> List[Dict]:
    """Accept Gmail's forwarding mail for offices on MAIL_TAB. Never raises.

    ONLY FOR AN ADDRESS ON THE TAB: any other request to forward into this
    inbox stays exactly as it was. One read of the tab per tick; the inbox is
    only opened while a row is waiting.
    """
    from automations.icd_alerts import post as P

    mails = mails or _confirmation_mails
    accept = accept or accept_confirmation
    tell = tell or _tell_us
    now = now or dt.datetime.now().astimezone()
    try:
        if book is None:
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        sheet = book.worksheet(MAIL_TAB)
        rows = sheet.get_all_values()
    except Exception as e:  # noqa: BLE001 -- includes no tab yet
        log("code forwards: could not read the mail tab: %s" % type(e).__name__)
        return []
    waiting = []
    for at, r in enumerate(rows[1:], start=2):
        r = list(r) + [""] * (len(MAIL_HEADER) - len(r))
        added = _added_at(r[2])
        if not (r[0].strip() and "@" in r[1] and added):
            continue
        if now - added > dt.timedelta(days=CONFIRM_WINDOW_DAYS):
            continue
        if NOTE_CONFIRMED in r[3] or NOTE_FAILED in r[3]:
            continue
        waiting.append((at, r[0].strip(), r[1].strip().lower(), added, r[3]))
    if not waiting:
        return []
    try:
        found = mails()
    except Exception as e:  # noqa: BLE001 -- inbox down: next tick
        log("code forwards: inbox not readable: %s" % type(e).__name__)
        return []
    done = []

    def _note(at, old, word):
        if send:
            sheet.update_cell(at, 4, ("%s; %s" % (old, word)).strip("; "))

    def _say(text):
        if send:
            try:
                tell(text)
            except Exception as e:  # noqa: BLE001 -- the note is what matters
                log("code forwards: could not tell Megan + Eve: %s" % type(e).__name__)

    for at, office, address, added, note in waiting:
        link = found.get(address)
        try:
            if not link:
                late = now - added > dt.timedelta(minutes=CONFIRM_PATIENCE_MIN)
                if late and NOTE_NO_MAIL not in note:
                    log("FWD    %-10s no Gmail confirmation mail" % office)
                    _note(at, note, NOTE_NO_MAIL)
                    _say("*%s* started the SaraPlus code forward, but Gmail's "
                         "confirmation never reached the reporting inbox. They "
                         "may have stopped before adding the address." % office)
                done.append({"office": office, "status": "no mail"})
                continue
            if not send:
                log("FWD    %-10s would confirm Gmail's forward" % office)
                done.append({"office": office, "status": "dry-run"})
                continue
            try:
                accept(link, address)
            except Exception as e:  # noqa: BLE001 -- a person can still click it
                log("FWD    %-10s could not confirm: %s" % (office, e))
                _note(at, note, NOTE_FAILED)
                _say("*%s*: Lucy could not confirm Gmail's SaraPlus forward "
                     "(%s: %s). Please click the confirmation email in the "
                     "reporting inbox." % (office, type(e).__name__, str(e)[:120]))
                done.append({"office": office, "status": "failed"})
                continue
            log("FWD    %-10s Gmail forward confirmed" % office)
            _note(at, note, NOTE_CONFIRMED)
            _say("*%s*: Gmail's SaraPlus code forward is confirmed. It starts "
                 "working once they save the filter." % office)
            done.append({"office": office, "status": "confirmed"})
        except Exception as e:  # noqa: BLE001 -- one row never costs the rest
            log("code forwards: row %d: %s" % (at, type(e).__name__))
    return done


# --- nothing but SaraPlus's codes -------------------------------------------
SCOPE_STAMP_NAME = "code-forward-scope.txt"
SCOPE_EVERY_MIN = 60


def scope_query(address: str) -> str:
    return "deliveredto:%s -from:security.info@saraplus.com newer_than:1d" % address


def _foreign_counts(addresses: Iterable[str]) -> Dict[str, int]:
    """address -> mails it forwarded us that are not SaraPlus's. COUNTS ONLY:
    nobody's mail is opened to find this out."""
    M = _imap()
    try:
        return {a: len(_search(M, scope_query(a))) for a in addresses}
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def _scope_due(stamp_path, now: dt.datetime) -> bool:
    try:
        last = dt.datetime.fromisoformat(stamp_path.read_text().strip())
    except (OSError, ValueError):
        return True
    return now - last >= dt.timedelta(minutes=SCOPE_EVERY_MIN)


def check_forward_scope(book=None, *, send: bool = False,
                        now: Optional[dt.datetime] = None, counts=None,
                        stamp_path=None, tell=None, log=print) -> List[Tuple[str, int]]:
    """Tell Megan + Eve if an office forwards more than SaraPlus's code mails.

    Once an hour, once per office per day. Never raises.
    """
    from automations.icd_alerts import config as C
    from automations.icd_alerts import post as P

    now = now or dt.datetime.now().astimezone()
    stamp_path = stamp_path or (C.APP_DIR / SCOPE_STAMP_NAME)
    if not _scope_due(stamp_path, now):
        return []
    counts = counts or _foreign_counts
    tell = tell or _tell_us
    wide = []
    try:
        if book is None:
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        sheet = book.worksheet(MAIL_TAB)
        rows = sheet.get_all_values()
        where = {}
        for at, r in enumerate(rows[1:], start=2):
            r = list(r) + [""] * (len(MAIL_HEADER) - len(r))
            if r[0].strip() and "@" in r[1]:
                where[r[1].strip().lower()] = (at, r[0].strip(), r[3])
        got = counts(list(where)) if where else {}
        word = "wide forward %s" % now.date().isoformat()
        for address, n in got.items():
            if not n:
                continue
            at, office, note = where[address]
            wide.append((office, n))
            log("FWD    %-10s forwarded %d mails that are not SaraPlus's" % (office, n))
            if send and word not in note:
                sheet.update_cell(at, 4, ("%s; %s" % (note, word)).strip("; "))
                tell("*%s* is forwarding more than SaraPlus's codes to the "
                     "reporting inbox (%d other mails in the last day). They "
                     "should pick \"Disable forwarding\" in Gmail and keep only "
                     "the filter." % (office, n))
        if send:
            stamp_path.parent.mkdir(parents=True, exist_ok=True)
            stamp_path.write_text(now.isoformat(timespec="seconds"))
    except Exception as e:  # noqa: BLE001 -- never cost the poster its tick
        log("code forwards: scope check: %s" % type(e).__name__)
    return wide
