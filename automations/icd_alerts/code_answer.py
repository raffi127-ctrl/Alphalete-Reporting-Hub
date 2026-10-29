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

COST. Nothing at all while no Mac is asking -- one read of a tab the poster
already reads. While one is asking, one IMAP search a minute, for at most
REQUEST_MAX_MIN minutes.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

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
        if address:
            try:
                tell("*%s* set up the SaraPlus code forward during setup "
                     "(codes go to %s). Please confirm Gmail's forwarding "
                     "email in the reporting inbox, then they add the filter."
                     % (office, address))
            except Exception as e:  # noqa: BLE001 -- the row is what matters
                log("code forwards: could not tell Megan + Eve: %s" % type(e).__name__)
        done.append({"office": office, "status": "recorded" if address else "no address"})
    return done
