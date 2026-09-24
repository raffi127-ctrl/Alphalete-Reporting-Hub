#!/usr/bin/env python3
"""OAT Processing — automate the "One App at a time" leftovers queue.

Runs on Lucy 2, in Carlos's OFFICE (11580) — reached by switching offices inside
the shared 'Raf – Captain' AppStream login, not by logging in as Carlos (his
CarlosNLR account was retired 2026-08-21). Rides the SAME holder-warmed
patchright session resume_pushing uses (`appstream_direct_session` — seeded from
the exported ownerville session, so NO service-account key and NO Cloudflare
login form), switches to office 11580 via `fetch_office._switch_office`, then
walks the classic OAT queue under Applicants -> Process Emails -> One App at a
time, classifying each applicant (see classify.py) and carrying out the action.

(The classic `applicant_tracker` driver was the first cut, but its
service-account-reads-creds-from-a-Sheet path is a Lucy-1 thing — that key is
deliberately absent on Lucy 2. The AppStream session is already warm here.)

SAFETY MODEL
------------
This report SENDS REAL TEXTS/EMAILS to applicants and REMOVES records — both
are outward, effectively irreversible actions. So, unlike most reports:

  * DRY-RUN IS THE DEFAULT. Without --live the run reads the queue, classifies
    every applicant, and prints exactly what it WOULD do — it never clicks a
    send/remove/override control.
  * --live is required to actually act, and only after Megan/Carlos confirm the
    dry-run output looks right.

FLAGS
  (default)   Dry-run: read + classify + print planned actions. No clicks.
  --live      Actually perform the send/remove/override clicks.
  --limit N   Process at most N applicants this run (default config.MAX_PER_RUN).
  --debug     Land on the OAT page, print a health check (which controls/labels
              are visible), then STOP. Run this FIRST on Lucy 2 to capture the
              selectors the stubbed helpers below still need.
  --headed    Force a visible browser (overrides HEADLESS).

STATUS: the page-READING (read_current_applicant, advance_to_next) and page-
ACTING (do_*) helpers below are marked `# >>> VERIFY on Lucy 2` where the
classic OAT DOM hasn't been confirmed yet. The decision core (classify.py) and
the no-phone flagging are complete and tested. Run `--debug` on Lucy 2 to fill
the remaining selectors.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import csv
import datetime as dt
import re
import os
import sys
import time

from automations.shared.tableau_patchright import (
    appstream_direct_session, AppStreamBusy)
from automations.recruiting_report import fetch_office

from . import config
from .classify import (Applicant, Action, Decision, classify,
                       interview_verdict,
                       verdict_for_history as classify_history)


def _norm_name(s: str) -> str:
    """Fold a name for allowlist matching: lowercase, strip accents/punctuation,
    collapse whitespace. AppStream renders 'Willy Jean - Felix' and the removed
    table 'Willy Jean-Felix' for the same person."""
    import unicodedata
    t = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return " ".join(t.split())


def _load_only_names():
    """Set of folded names from $OAT_ONLY_NAMES, or None when unset."""
    path = os.environ.get("OAT_ONLY_NAMES", "").strip()
    if not path:
        return None
    with open(path) as fh:
        names = {_norm_name(l) for l in fh if l.strip()}
    names.discard("")
    return names


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Navigation to the classic OAT screen
# --------------------------------------------------------------------------- #
def open_oat(page) -> bool:
    """Applicants -> Process Emails -> "One App at a time" (classic surface).

    Text/label-based (no hardcoded p= page number): open the "Applicants" top-nav
    (its Process Emails submenu holds the link), then click "One App at a time".
    Returns True if we landed on it.
    # >>> VERIFY on Lucy 2: confirm the nav labels + that this is the right page.
    """
    # 1) reveal the Applicants menu (hover, then click as fallback).
    for how in ("hover", "click"):
        try:
            loc = page.locator(
                "xpath=//a[normalize-space(.)='Applicants'] "
                "| //*[self::button or @role='button'][normalize-space(.)='Applicants']"
            ).first
            if loc.count() == 0:
                break
            getattr(loc, how)(timeout=5000)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass
    # 2) click the OAT link (a/link/menu item), tolerating minor label variants.
    #    The AppStream nav is laggy on the mini — a single 8s click often times
    #    out, dropping the walk onto a page with no pager (every later applicant
    #    then reads as not_found). Retry the menu-click a few times with longer
    #    timeouts + re-reveal the menu each round before falling back.
    oat_xp = ("xpath=//a[contains(normalize-space(.),'One App at a time')] "
              "| //*[@role='menuitem'][contains(normalize-space(.),'One App at a time')] "
              "| //a[contains(normalize-space(.),'One App at a Time')]")
    for attempt in range(3):
        try:
            page.locator(oat_xp).first.click(timeout=12000)
            page.wait_for_timeout(2000)
            if "p=604" in (page.url or ""):
                return True
        except Exception as e:  # noqa: BLE001
            _log(f"[oat] menu click miss {attempt + 1}/3 ({type(e).__name__})")
        # re-reveal the Applicants menu before the next attempt
        try:
            page.locator(
                "xpath=//a[normalize-space(.)='Applicants'] "
                "| //*[self::button or @role='button'][normalize-space(.)='Applicants']"
            ).first.hover(timeout=4000)
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001
            pass

    # Fallback: the OAT page is index.cfm?p=604 (confirmed 2026-07-27). Navigate
    # straight there, reusing the session's rqst token from the current URL.
    import re
    m = re.search(r"rqst=([A-F0-9-]+)", page.url or "", re.I)
    if not m:
        _log("[oat] no rqst token in URL — cannot direct-nav to p=604")
        return False
    for _ in range(2):
        try:
            page.goto(
                f"https://applicantstream.com/index.cfm?p=604&rqst={m.group(1)}",
                wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if "p=604" in (page.url or ""):
                return True
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(1500)
    return "p=604" in (page.url or "")


def _open_oat_ready(page, tries: int = 3) -> bool:
    """open_oat + confirm we actually landed on a walkable queue (a Next pager or
    a readable applicant). Retries the whole open when the laggy nav drops us on a
    pager-less page. Used by the no-phone fill walk so a slow load doesn't turn
    every remaining applicant into a false not_found."""
    for _ in range(tries):
        if open_oat(page):
            page.wait_for_timeout(800)
            has_pager = page.locator(
                "xpath=//img[contains(translate(@alt,'NEXT','next'),'next')]"
            ).count() > 0
            a = read_current_applicant(page)
            if has_pager or (a.first_name or a.last_name):
                return True
        page.wait_for_timeout(1500)
    return False


# --------------------------------------------------------------------------- #
# Reading one applicant off the OAT screen  # >>> VERIFY on Lucy 2
# --------------------------------------------------------------------------- #
# One text-based extraction of every signal off the OAT panel (p=604). Text-based
# (find the dup table by its "Status"/"Duplicate Type" header; search body text for
# the red-message patterns) because the model was built from the Loom's pixels, not
# the DOM — so it's robust to exact ids. See FINDINGS.md for the state model.
_EXTRACT_JS = r"""() => {
  const val = n => { const e=document.querySelector(`[name='${n}']`);
    if(!e) return '';
    // for a <select>, return the visible option text, not the numeric value
    if(e.tagName==='SELECT') return (e.options[e.selectedIndex]?.text||'').trim();
    return (e.value||'').trim(); };
  const body = (document.body.innerText||'');
  // --- the duplicate table: header row has both "Status" and "Duplicate Type" ---
  let dupRows = [];
  for (const t of document.querySelectorAll('table')) {
    const head = (t.querySelector('tr')?.innerText||'').toLowerCase();
    if (head.includes('status') && head.includes('duplicate type')) {
      const trs=[...t.querySelectorAll('tr')];
      const cols=[...trs[0].children].map(c=>c.innerText.trim().toLowerCase());
      const ci=name=>cols.findIndex(c=>c.includes(name));
      const iStatus=ci('status'), iType=ci('duplicate type'),
            iDate=ci('date entered'), iApp=ci('applicant');
      for (let i=1;i<trs.length;i++){ const td=[...trs[i].children];
        if(!td.length) continue;
        dupRows.push({
          applicant: iApp>=0 ? (td[iApp]?.innerText||'').trim() : '',
          dateEntered: iDate>=0 ? (td[iDate]?.innerText||'').trim() : '',
          status: iStatus>=0 ? (td[iStatus]?.innerText||'').trim() : '',
          dupType: iType>=0 ? (td[iType]?.innerText||'').trim() : '',
        });
      }
      break;
    }
  }
  // --- red inline messages ---
  const cannotOverride = /cannot override this applicant/i.test(body);
  const corrM = body.match(/last correspondence was on\s+([0-9]{1,2}\/[0-9]{1,2}\/[0-9]{2,4})/i);
  // --- overwrite+send button present? ---
  const btnText = [...document.querySelectorAll('button,input[type=button],input[type=submit],a')]
    .map(e=>(e.innerText||e.value||'')).join(' | ').toLowerCase();
  // BOTH wordings ship in AppStream and they mean the same control: some
  // records render "Overwrite Old Applicants (Send to AI)", others "Override and
  // Send to AI" (Carlos read the second off a live screen 2026-08-27, and one
  // walk saw both labels within a few applicants of each other). Matching only
  // 'overwrite' made every 'Override…' record read as override_button=false, so
  // classify() routed a sendable applicant to re-text/remove instead. Never
  // match one spelling.
  const overrideBtn = /overri|overwri/.test(btnText) && btnText.includes('send to ai');
  // --- pager: "<page> of <N> Emails" ---
  const pm = body.match(/of\s+([0-9]+)\s+emails/i);
  // --- account: the "To:" address of the source application email (bottom of the
  //     page), e.g. "To: team@peaksalesstrategiestx.com" — the account this
  //     applicant came in under. Skip the Indeed relay address; take the last real
  //     To: (the source-email footer sits at the bottom).
  let account = '';
  const toAll = body.match(/To:\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})/gi) || [];
  for (let i = toAll.length - 1; i >= 0; i--) {
    const em = toAll[i].replace(/^To:\s*/i, '').trim();
    if (!/indeedemail\.com|indeed\.com/i.test(em)) { account = em; break; }
  }
  if (!account && toAll.length) account = toAll[toAll.length-1].replace(/^To:\s*/i,'').trim();
  // --- applied/entered date: the source email footer "Sent: <date>" (bottom of the
  //     page), e.g. "Sent: Thursday, August 6, 2026 02:30 PM" — how long they've been
  //     sitting. Take the last "Sent:" (the footer). Grab the date-looking remainder.
  let entered = '';
  const sentAll = body.match(/Sent:\s*([A-Za-z0-9,:\/ ]+\d{4}[A-Za-z0-9,: ]*)/gi) || [];
  if (sentAll.length) entered = sentAll[sentAll.length-1].replace(/^Sent:\s*/i,'').trim();
  return {
    fname: val('fname'), lname: val('lname'), phone: val('phone'),
    cellPhone: val('cellPhone'), email: val('email'), jBoard: val('jBoard'),
    subject: val('emailApplicantSubject'), account, entered,
    dupRows, cannotOverride, lastCorrespondence: corrM ? corrM[1] : '',
    overrideBtn, total: pm ? parseInt(pm[1],10) : null,
  };
}"""


def _parse_us_date(s: str):
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except Exception:  # noqa: BLE001
            continue
    # "Thursday, July 23, 2026 02:23 PM" style (dup-table Date Entered)
    for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s.split(" 0")[0].strip().rstrip(","), fmt).date()
        except Exception:  # noqa: BLE001
            continue
    try:
        return dt.datetime.strptime(s.strip().split(",")[1].strip() + s.strip().split(",")[2].split()[0],
                                    "%B %d %Y").date()
    except Exception:  # noqa: BLE001
        return None


def read_current_name(page) -> str:
    """Just the current applicant's name off the p=604 panel — cheap enough to
    poll while waiting for a send to settle."""
    try:
        d = page.evaluate(_EXTRACT_JS) or {}
        return f"{d.get('fname') or ''} {d.get('lname') or ''}".strip()
    except Exception:  # noqa: BLE001
        return ""


def read_current_applicant(page, today: dt.date = None) -> Applicant:
    """Read the applicant panel (p=604) + duplicate table + red messages into an
    Applicant, deriving the state signals classify() needs. See FINDINGS.md."""
    today = today or dt.date.today()
    try:
        d = page.evaluate(_EXTRACT_JS)
    except Exception as e:  # noqa: BLE001
        _log(f"[oat] extract failed: {type(e).__name__}: {e}")
        d = {}

    dup_rows = d.get("dupRows") or []
    statuses = " || ".join(r.get("status", "") for r in dup_rows)

    # interview signals from the dup-table Status column
    interview_future = False
    interview_past_noshow = False
    for r in dup_rows:
        st = (r.get("status") or "").lower()
        if "interview assigned" in st or "interview" in st:
            # "Unmarked Show" means the interview day has NOT ARRIVED yet — every
            # past day gets marked on the calendar, so an unmarked one is still
            # in the future. That is an active booking: remove as a duplicate,
            # do not treat it as a no-show. (Carlos, 8/29, on Alexandra.)
            if "unmarked show" in st:
                interview_future = True
            elif "no show" in st or "no-show" in st:
                interview_past_noshow = True
            else:
                # a future/scheduled interview shows a date; treat any non-no-show
                # "interview assigned" as an active (future) booking.
                interview_future = True

    # sent-to-call-list-today: a dup row "Sent to Call List" dated today
    sent_today = False
    for r in dup_rows:
        if "sent to call list" in (r.get("status") or "").lower():
            de = _parse_us_date(r.get("dateEntered") or "")
            if de == today:
                sent_today = True

    last_corr = _parse_us_date(d.get("lastCorrespondence") or "") if d.get("lastCorrespondence") else None
    applied = _parse_us_date(d.get("entered") or "") if d.get("entered") else None

    a = Applicant(
        first_name=d.get("fname", ""), last_name=d.get("lname", ""),
        phone=d.get("phone", ""), cell_phone=d.get("cellPhone", ""),
        email=d.get("email", ""), job_board=d.get("jBoard", ""),
        position=(d.get("subject", "") or "").strip(),
        account=(d.get("account", "") or "").strip(),
        applied_date=applied,
        override_button=bool(d.get("overrideBtn")),
        correspondence_blocked=bool(d.get("cannotOverride")),
        last_correspondence=last_corr,
        interview_future=interview_future,
        interview_past_noshow=interview_past_noshow,
        sent_to_call_list_today=sent_today,
        raw_status=statuses[:300],
    )
    a._total = d.get("total")  # type: ignore[attr-defined]  # queue size, for advance
    return a


# --- pager settle ----------------------------------------------------------- #
# BACKED OUT 2026-09-13, same day it shipped. The idea was sound — the flat
# 1800ms after every Next click is paid ~4,000 times a day and the pager is
# usually back in ~300ms — but the early-return condition was wrong.
#
# It returned as soon as the PANEL signature changed: pager position plus the
# name/email fields. Those are in the top document and settle first. The applicant's
# RESUME renders in a nested frame that loads later, and the walk's very next move
# is to look for the "View resume" link in that frame. Returning early meant
# looking before it existed, and a missing link is not retried — it is read as
# "no resume attached at all", which is a verdict about the APPLICANT.
#
# Cost, measured in Carlos's office the afternoon it shipped: 219 applicants
# marked "no resume on file" in one afternoon, against 1 per walk on 9/10 under
# the old wait. Megan spotted it from the outside — "62 is SUPER high" — and a
# screenshot of one flagged record showed the View resume link plainly present.
#
# The flat wait is restored. If this is retried, the condition has to be the
# thing the walk actually needs next — the resume link being reachable — not the
# first sign of any change at all. A faster walk that mislabels people is not
# faster, it is wrong.
_ADVANCE_SETTLE_CAP_MS = 1800


def jump_to_last(page) -> bool:
    """Click the pager's LAST control (⏮/⏭ jump-to-end) so the walk starts at
    the newest applicant and works backward. Carlos, 2026-09-20: the front of
    the queue is a wall of Cloudflare-blocked no-phone people that eats every
    tick; the newest applicants (who have numbers) never get reached. Returns
    True if it clicked something."""
    try:
        return bool(page.evaluate(
            """() => {
               const imgs=[...document.querySelectorAll('img')];
               const t=e=>((e.alt||'')+' '+(e.title||'')).toLowerCase();
               let el=imgs.find(e=>/last|end|\u23ed|\u25ba\u25ba/.test(t(e)));
               if(!el){ const as=[...document.querySelectorAll('a')];
                 el=as.find(a=>/\u23ed|>>|last/i.test(a.innerText||'')); }
               if(!el) return false;
               el.scrollIntoView({block:'center'}); el.click(); return true; }"""))
    except Exception:  # noqa: BLE001
        return False


def advance_to_next(page) -> bool:
    """Advance the OAT pager ("<page> of <N> Emails", top-right of the dup area)
    to the next applicant. Returns False when there's no next control (end of
    queue). # >>> VERIFY on Lucy 2: confirm the next-arrow locator."""
    # The pager Next control is an <img alt="Next"> (confirmed 2026-07-27). Click
    # the image itself (its click handler is jQuery-bound, no inline onclick).
    # WALK_FROM_END reverses direction — "next" becomes the PREV arrow.
    if os.environ.get("OAT_WALK_FROM_END") == "1":
        candidates = [
            "xpath=//img[translate(@alt,'PREV','prev')='prev']",
            "xpath=//img[contains(translate(@alt,'PREVIOUS','previous'),'previous')]",
            "xpath=//a[normalize-space(.)='\u25c4' or normalize-space(.)='<']",
        ]
    else:
        candidates = [
        "xpath=//img[translate(@alt,'NEXT','next')='next']",
        "xpath=//img[contains(translate(@alt,'NEXT','next'),'next')]",
        "xpath=//img[contains(translate(@alt,'NEXT','next'),'next')]/ancestor::a[1]",
        "xpath=//a[normalize-space(.)='►' or normalize-space(.)='>']",
    ]
    # POLL, don't glance. Every applicant we send / remove / re-text re-renders
    # this page, and a single count()==0 the instant before the pager comes back
    # was being read as "the queue has ended". It ended walks with most of the
    # queue untouched — 8/27: Atef 11 of 21, 15 of 22, 15 of 23; Carlos 2 of 13
    # and 3 of 13 — and since those walks then called themselves complete, the
    # to-do post published a short list as the whole backlog (Megan: "you have
    # follow up need for 6 on atef but his inbox is 23"). 52 walks ended this way
    # in one day.
    #
    # A real end of queue costs this wait ONCE per walk, which is nothing against
    # a walk that runs minutes; a missed pager costs applicants sitting unseen for
    # hours. Same lesson as the FOR LUCY template race fixed earlier today: on
    # this machine, a fixed-instant look at an async re-render is a coin flip, and
    # it got worse when Atef's office doubled Lucy 2's load.
    import time as _t
    _deadline = _t.monotonic() + 6.0
    _polls = 0
    while True:
        for xp in candidates:
            try:
                loc = page.locator(xp).first
                if loc.count() == 0:
                    continue
                loc.click(timeout=5000, no_wait_after=True)
                # FLAT WAIT, DELIBERATELY. See _settle_after_advance below: the
                # adaptive version returned as soon as the NAME fields changed,
                # which is earlier than the resume frame finishes loading.
                page.wait_for_timeout(_ADVANCE_SETTLE_CAP_MS)
                if _polls:
                    _log(f"[oat] next-pager appeared after {_polls} extra poll(s) "
                         f"— a single look would have ended this walk early")
                return True
            except Exception:  # noqa: BLE001
                continue
        if _t.monotonic() >= _deadline:
            break
        _polls += 1
        page.wait_for_timeout(500)
    _log("[oat] no next-pager control found — treating as end of queue")
    return False


# --------------------------------------------------------------------------- #
# Actions  (all clicks are # >>> VERIFY on Lucy 2 and gated behind --live)
# --------------------------------------------------------------------------- #
def _would(live: bool, what: str) -> None:
    _log(f"    {'[LIVE] ' if live else '[dry-run] would '}{what}")


# Confirmed OAT controls (Lucy 2 --debug, 2026-07-27), for when these get armed:
#   "Send to AI" button · removApp checkbox + rmvReason <select> (pick the option
#   whose text contains "duplicate") + "Save Applicant" (submitSaveApplicant) ·
#   "Email Applicant" button + emailApplicantSubject / emailApplicantMessage
#   (textarea) + qNotes Quick-Note <select>. What's NOT yet observed: the
#   overwrite/duplicate confirm DIALOG that appears when you Send to AI on a dup,
#   the "Interview Assigned" status line, and how the page ADVANCES to the next
#   applicant. So the clicks stay gated until those states are seen live.
def _click_first(page, labels, timeout: int = 6000) -> bool:
    """Click the first visible button/link/submit whose text (or value) contains
    one of `labels`. Returns True if something was clicked."""
    for label in labels:
        loc = page.locator(
            f"xpath=//button[contains(normalize-space(.),'{label}')]"
            f" | //a[contains(normalize-space(.),'{label}')]"
            f" | //input[@type='submit' or @type='button'][contains(@value,'{label}')]"
            f" | //*[@role='button'][contains(normalize-space(.),'{label}')]")
        try:
            if loc.count() > 0:
                loc.first.click(timeout=timeout, no_wait_after=True)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


_DUP_STATUS_JS = """() => { const out=[]; const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  for (const t of document.querySelectorAll('table')) {
    const h=[...(t.rows[0]||{cells:[]}).cells].map(c=>norm(c.innerText).toLowerCase());
    const si=h.findIndex(x=>x.indexOf('status')>=0); if (si<0) continue;
    for (const r of [...t.rows].slice(1)) {
      const v=norm((r.cells[si]||{}).innerText); if (v) out.push(v); } }
  return out; }"""


def read_dup_statuses(page):
    """Status cells from the 'Following Applicants found with the same email
    address or phone number' box — the interview history a recruiter reads before
    deciding whether to re-text or remove. Header matched by SUBSTRING; an exact
    'status' match missed the table entirely."""
    try:
        return page.evaluate(_DUP_STATUS_JS) or []
    except Exception:  # noqa: BLE001
        return []


def _has_dup_signal(x: Applicant) -> bool:
    return bool(x.override_button or x.correspondence_blocked or x.interview_future
                or x.interview_past_noshow or x.sent_to_call_list_today)


def _body(page) -> str:
    """ALL-frames body text, lowercased. Top-document-only reading is how the
    walk missed an overwrite button that rendered inside a frame and removed
    Moises Santamaria while the control sat on Carlos's screen (2026-08-29,
    the third wrong removal of the day — every one traced to a read that saw
    less of the page than the human watching it)."""
    texts = []
    try:
        texts.append(page.inner_text("body") or "")
    except Exception:  # noqa: BLE001
        pass
    try:
        for fr in (getattr(page, "frames", None) or []):
            try:
                t = fr.evaluate("() => (document.body.innerText || '')")
            except Exception:  # noqa: BLE001
                continue
            if t and t not in texts:
                texts.append(t)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(texts).lower()


def _red_messages(page):
    """The red inline error lines on the refusal screen, verbatim — so the log
    shows WHAT refused a send, not just that one did."""
    out = []
    body = _body(page)
    for ln in body.splitlines():
        ln = ln.strip()
        if ln and ("cannot send to ai" in ln or "cannot override" in ln
                   or "last correspondence" in ln):
            out.append(ln[:160])
    return out[:4]


def _parse_last_corr(body: str):
    m = re.search(r"last correspondence was on\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
                  body)
    return _parse_us_date(m.group(1)) if m else None


DUP_REASON = r"duplicate"
# Carlos 2026-08-27: an applicant with NO reachable phone number must not be
# filed as a duplicate — the removal reason is the only record of WHY they were
# dropped, and "duplicate" on someone who simply had no number makes the ad look
# like it produced a repeat applicant instead of an unusable one. Matches the
# "Incorrect / Insufficient Contact Info" option the office already uses by hand.
NO_CONTACT_REASON = r"incorrect|insufficient|contact info"


def _perform_remove(page, reason_pattern: str = DUP_REASON) -> bool:
    """Remove the current applicant: check 'Remove Applicant?' (removApp), set the
    Remove Reason to the first option matching ``reason_pattern``, and click
    'Remove Applicant'. Done in ONE in-page step so it isn't tripped up by the
    post-block panel's actionability quirks. Fails safe (returns False, logs why)
    if the reason or the button isn't found.

    ``reason_pattern`` defaults to duplicate so every existing caller behaves
    exactly as before; pass NO_CONTACT_REASON for the no-phone case."""
    if not _guard_office_now(page, "remove"):
        return False
    try:
        # 1) CHECK "Remove Applicant?" — a real check so the ATS reveals the Remove
        #    Reason dropdown + the "Remove Applicant" button (Megan 7/27).
        cb = page.locator("[name='removApp']").first
        if cb.count() == 0:
            _log("    [remove] FAIL: no 'Remove Applicant?' checkbox")
            return False
        try:
            cb.check(timeout=4000)
        except Exception:  # noqa: BLE001
            cb.click(force=True, timeout=4000)
        page.wait_for_timeout(700)
        # 2) pick the remove reason matching the caller's pattern.
        picked = page.evaluate(
            """(pat) => {
                const s = document.querySelector("select[name='rmvReason']");
                if (!s) return '';
                const re = new RegExp(pat, 'i');
                const o = [...s.options].find(o => re.test(o.text));
                if (!o) return '';
                s.value = o.value; s.dispatchEvent(new Event('change',{bubbles:true}));
                return o.text;
            }""", reason_pattern)
        if not picked:
            _log(f"    [remove] FAIL: no reason matching /{reason_pattern}/ on the page")
            return False
        # 3) Click the "REMOVE APPLICANT" button — NOT "Save Applicant" (that one is
        #    BLOCKED for dupes: "Cannot Save this Applicant"). Real click + nav wait
        #    so the form actually POSTs; the dialog handler accepts any confirm.
        btn = page.locator(
            "[name='submitRemoveApplicant'], input[value='Remove Applicant']").first
        if btn.count() == 0:
            btn = page.locator(
                "xpath=//input[@type='submit'][contains(@value,'Remove Applicant')]"
                " | //button[contains(normalize-space(.),'Remove Applicant')]").first
        if btn.count() == 0:
            _log("    [remove] FAIL: no 'Remove Applicant' button")
            return False
        try:
            with page.expect_navigation(timeout=8000):
                btn.click(timeout=6000)
        except Exception:  # noqa: BLE001
            try:
                btn.click(timeout=6000, force=True, no_wait_after=True)
            except Exception as e2:  # noqa: BLE001
                _log(f"    [remove] FAIL: Remove click ({type(e2).__name__})")
                return False
        page.wait_for_timeout(2500)
        _log(f"    [remove] REMOVED (reason: {picked})")
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"    remove error: {type(e).__name__}: {e}")
        return False


def _wait_send_outcome(page, a, timeout_ms: int = 15000) -> str:
    """After a Send-to-AI click, wait for a DEFINITE outcome instead of taking
    one snapshot. The refusal panel and its override button render via separate
    requests, so a single 2.5s peek can see neither — which on 2026-08-29 made
    the walk remove Rossana Martheins while her overwrite button was still
    loading, and call refused sends 'clean'. Returns:
      'refused'  — the cannot-send panel rendered
      'sent'     — the applicant left the current slot (a new name is loaded)
      'unknown'  — neither, even after the full wait. NEVER remove on unknown.
    """
    deadline = time.time() + timeout_ms / 1000.0
    target = f"{a.first_name} {a.last_name}".strip().lower()
    while time.time() < deadline:
        body = _body(page)
        if "cannot send to ai" in body:
            return "refused"
        try:
            cur = read_current_name(page).strip().lower()
        except Exception:  # noqa: BLE001
            cur = ""
        if cur and target and cur != target:
            return "sent"
        page.wait_for_timeout(800)
    return "unknown"


def _try_overwrite_send(page) -> bool:
    """Push to AI via the override control when the ATS allows it (control
    present, no 'Cannot override'). The ATS still blocks a recent contact, so
    this only sends when legitimately allowed. Send-maximizer.

    MATCH THE CONTROL BY PATTERN, NEVER BY AN EXACT LABEL. AppStream renders this
    button as "Overwrite Old Applicants (Send to AI)", "Override and Send to AI",
    or a bare "Overwrite old Applicants" with no AI suffix at all (Paula Ruiz,
    2026-08-28) — which is why the fallback matcher drops the /\bai\b/ clause — both appear in the same office, sometimes a few applicants
    apart. The old exact-label list only carried the first, so on an "Override…"
    record the click silently found nothing, do_send_ai concluded the applicant
    could not be sent, and routed them to re-text or remove. Measured on Atef's
    office 2026-08-27: of 26 restored applicants with a clear verdict, 21 were
    sendable and 16 of those needed exactly this button — i.e. this one mismatch
    was the difference between a person reaching the call list and being written
    off. Pattern-match /overri|overwri/, prefer the one that also says AI."""
    # WAIT for the control by scanning ELEMENTS, never body text. The control is
    # a <button> in some offices but an <input> in others (Haytham's, found
    # 2026-08-29 via a full control dump) — and an input's label lives in its
    # value attribute, which body text does NOT contain. The text gate said "no
    # override" on a page whose 'Override and Send to AI' input was plainly
    # visible, and Moises Santamaria was removed for it — twice. Same matcher as
    # the click below: innerText OR value, across every frame.
    _FIND_JS = """() => {
         const t = e => (e.innerText || e.value || '').trim();
         return [...document.querySelectorAll(
             'button, input[type=submit], input[type=button], a')]
           .some(e => e.offsetParent !== null && /overri|overwri/i.test(t(e)));
    }"""
    _found = False
    for _ in range(8):                       # up to ~8s for it to render
        for _fr in (getattr(page, "frames", None) or [page]):
            try:
                if _fr.evaluate(_FIND_JS):
                    _found = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if _found:
            break
        page.wait_for_timeout(1000)
    if not _found:
        return False
    # DO NOT bail just because the page says "Cannot override this applicant."
    # Carlos, 2026-08-28: "you even told me that you saw the option that said
    # overwrite old applicants, so you should have been able to." Those are two
    # different controls. The bare "Overwrite old Applicants" button does not send
    # — it clears the old duplicate records so this applicant CAN be saved — and
    # the send is a separate click afterwards. Refusing to click it (or checking
    # for the error immediately after) reports a dead end on an applicant who was
    # one more click from the call list.
    _CLICK_JS = """() => {
             const els = Array.from(document.querySelectorAll(
                 'button, input[type=submit], input[type=button], a'))
               .filter(e => e.offsetParent !== null);
             const t = e => (e.innerText || e.value || '').trim();
             const el = els.find(e => /overri|overwri/i.test(t(e))
                                   && /\bai\b/i.test(t(e)))
                     || els.find(e => /overri|overwri/i.test(t(e)));
             if (!el) return null;
             const label = t(el);
             el.scrollIntoView({block: 'center'});
             el.click();
             return label; }"""
    # EVERY frame, not just the top document — the control can render inside one
    # (Moises Santamaria, 2026-08-29: button on screen, top-document click found
    # nothing, applicant removed).
    if not _guard_office_now(page, "override/overwrite send"):
        return False
    clicked = None
    for _fr in (getattr(page, "frames", None) or [page]):
        try:
            clicked = _fr.evaluate(_CLICK_JS)
        except Exception:  # noqa: BLE001
            continue
        if clicked:
            break
    if not clicked:
        return False
    _log(f"    [override] clicked {clicked!r}")
    page.wait_for_timeout(2500)
    if "cannot send to ai" not in _body(page):
        return True
    # A bare "Overwrite…" (no AI suffix) only cleared the duplicates; the send is
    # the NEXT click. Try it before calling this blocked.
    if (_guard_office_now(page, "Send to AI (post-overwrite)")
            and _click_first(page, ["Send to AI", "Send To AI"], timeout=6000)):
        page.wait_for_timeout(2500)
        if "cannot send to ai" not in _body(page):
            _log("    [override] send succeeded after the overwrite cleared the dups")
            return True
    return False


_RETEXT_ROWS: list = []


def _flag_retext(a: Applicant, days) -> None:
    """Re-text (>1wk) sends a real message, so it's FLAGGED for review (not
    auto-sent yet) — written to output/oat-retext-queue.csv. Phone is recorded so
    a send (manual --retext-send-live or armed auto) can bind the thread exactly."""
    _RETEXT_ROWS.append([dt.date.today().isoformat(), a.first_name, a.last_name,
                         a.email, a.position, a.cell_phone or a.phone,
                         days if days is not None else ""])


def do_send_ai(page, a: Applicant, live: bool) -> str:
    """GOAL = get to AI. Attempt Send, then handle the ATS's post-click reveal:
    SEND > overwrite+SEND > (>1wk) flag re-text > auto-remove. Returns an outcome
    tag for the run summary."""
    _would(live, "click 'Send to AI'")
    if not live:
        return "dry"
    guard = read_current_applicant(page)
    if _has_dup_signal(guard):
        # a dup that WAS visible on load slipped in as SEND_AI — route it.
        return _handle_visible_dup(page, guard, live)
    if not _guard_office_now(page, "Send to AI"):
        return _office_guard_outcome()
    if not _click_first(page, ["Send to AI", "Send To AI"]):
        _log("    'Send to AI' button not found — skipped")
        return "no_button"
    page.wait_for_timeout(2500)
    if "cannot send to ai" not in _body(page):
        _log(f"    ✅ SENT to AI: {a.first_name} {a.last_name}")
        return "sent"
    # blocked by prior correspondence — first try to send anyway via overwrite.
    if _try_overwrite_send(page):
        _log(f"    ✅ SENT via overwrite: {a.first_name} {a.last_name}")
        return "sent_override"
    # The ATS refuses. Before the generic date-based fallbacks, read the INTERVIEW
    # HISTORY — Carlos 2026-08-28. "Delay disqualified" means we interviewed them
    # and chose not to advance them, so texting again is pointless; "no show /
    # rejected / not qualified" means they never really got interviewed, so they
    # deserve the await text rather than a silent removal. Getting these two
    # backwards either pesters someone we already passed on or throws away a live
    # candidate.
    # LOG THE RAW STATUS TEXT, always. The verdict alone hides which history we
    # actually saw, so an unrecognised status (e.g. "Second Round Showed Up",
    # Carlos 2026-08-29) silently falls through to the generic path and nobody
    # can tell afterwards which applicant it was or what it said.
    _statuses = read_dup_statuses(page)
    _verdict = classify_history(_statuses)
    for _st in (_statuses or []):
        _known = interview_verdict(_st)
        _log(f"    [history] {_st!r} -> {_known or 'UNRECOGNISED (no rule)'}")
    if _verdict == "remove_duplicate":
        if _perform_remove(page, DUP_REASON):
            _log(f"    🗑 removed — interviewed and disqualified (no re-text): "
                 f"{a.first_name} {a.last_name}")
            return "removed"
    elif _verdict == "override_send":
        # "Left Message" = we called and never reached them, and they are
        # applying again, so they are still looking. Override them straight onto
        # the call list (Carlos 2026-08-29, Kim Hamilton).
        if _try_overwrite_send(page):
            _log(f"    ✅ override-sent — prior contact only left a message: "
                 f"{a.first_name} {a.last_name}")
            return "sent_override"
        _log(f"    ⚑ left-message override refused: {a.first_name} {a.last_name}")
    elif _verdict == "retext":
        # A no-show / not-qualified was never actually interviewed, so if the ATS
        # will not let us override them onto the call list we TEXT them instead of
        # dropping them (Carlos 2026-08-28). Only fall back to flagging when the
        # send itself could not be completed — never silently.
        if not getattr(config, "ALLOW_RETEXT", False):
            # An office that does not text still SENDS whenever it can. We are on
            # the refused screen here (the verdict came off it), so the override
            # control is legitimate to wait for; _try_overwrite_send polls up to
            # ~8s for it. Only a refusal WITH no control after that wait earns a
            # removal — anything ambiguous is flagged, never removed.
            if _try_overwrite_send(page):
                _log(f"    ✅ override-sent instead of removing: "
                     f"{a.first_name} {a.last_name}")
                return "sent_override"
            if ("cannot send to ai" in _body(page)
                    and _perform_remove(page, DUP_REASON)):
                _log(f"    🗑 removed as duplicate (refused, no override after "
                     f"waiting, office does not text): "
                     f"{a.first_name} {a.last_name}")
                return "removed"
            _flag_retext(a, None)
            _log(f"    ⚑ FLAG (ambiguous — not removing): "
                 f"{a.first_name} {a.last_name}")
            return "flag_retext"
        ph_now = (a.cell_phone or a.phone or "").strip()
        if not ph_now:
            got_ph, _d = lookup_resume_phone(page)
            if got_ph:
                _fill_contact(page, got_ph)
                ph_now = got_ph
        if ph_now:
            role = _role_from_position(read_posting_title(page, a.position))
            st, det = retext_applicant(page, a.first_name, a.last_name, ph_now,
                                       role, do_send=True)
            if st == "sent":
                _log(f"    📲 re-texted (no-show / not qualified — never truly "
                     f"interviewed): {a.first_name} {a.last_name}")
                if _perform_remove(page, DUP_REASON):
                    return "retext_removed"
                return "retext_sent"
            _log(f"    ⚑ re-text could not send ({st}: {str(det)[:70]}) — flagging: "
                 f"{a.first_name} {a.last_name}")
        else:
            _log(f"    ⚑ no number for the re-text — flagging: "
                 f"{a.first_name} {a.last_name}")
        _flag_retext(a, None)
        return "flag_retext"

    # genuinely can't send → >1wk re-text (armed: text+remove, else flag) else
    # auto-remove (recent dup).
    lc = _parse_last_corr(_body(page))
    days = (dt.date.today() - lc).days if lc else None
    if days is not None and days > config.RETEXT_MIN_DAYS:
        return _armed_retext(page, a, days, live)
    if _perform_remove(page):
        _log(f"    🗑 auto-removed (dup, last contact "
             f"{days if days is not None else '?'}d): {a.first_name} {a.last_name}")
        return "removed"
    return "left"


def _handle_visible_dup(page, a: Applicant, live: bool) -> str:
    """Route a dup that classify() saw on page load, prioritizing a send."""
    if a.override_button:
        return do_override_send_ai(page, a, live)
    if a.interview_future or a.sent_to_call_list_today:
        return do_remove_duplicate(page, a, live)      # already booked / sent today
    if (a.last_correspondence
            and (dt.date.today() - a.last_correspondence).days > config.RETEXT_MIN_DAYS):
        _flag_retext(a, (dt.date.today() - a.last_correspondence).days)
        return "flag_retext"
    return do_remove_duplicate(page, a, live)


def do_override_send_ai(page, a: Applicant, live: bool) -> str:
    _would(live, "Overwrite Old Applicants (Send to AI)")
    if not live:
        return "dry"
    if _try_overwrite_send(page):
        _log(f"    ✅ SENT via overwrite: {a.first_name} {a.last_name}")
        return "sent_override"
    _log(f"    overwrite-send unavailable/blocked — left: {a.first_name} {a.last_name}")
    return "left"


def do_remove_duplicate(page, a: Applicant, live: bool) -> str:
    _would(live, "remove for duplicate")
    if not live:
        return "dry"
    if _perform_remove(page):
        _log(f"    🗑 auto-removed for duplicate: {a.first_name} {a.last_name}")
        return "removed"
    return "left"


_TEMPLATE_NAME = "FOR LUCY"

# The await/re-engagement copy, given verbatim by Carlos 2026-08-28. Kept HERE so
# the re-text no longer depends on a saved template: office 11580's Load Template
# modal holds only three templates (BG still needed / IN PERSON / ZOOM CODE) and
# has NO "FOR LUCY" at all, so every automated re-text failed with "FOR LUCY
# Select link not found" and the applicant was flagged instead of contacted.
AWAIT_TEXT = ("Hey {first}, this is Elena with Vantura! We received your "
              "application for the {role} role and would love to set up a quick "
              "20-minute Zoom interview. Are you available?")

# AppStream's own placeholders are applicantFirstName / adPostingTitle — NOT the
# NAME / xxxx this module used to substitute. A template loaded and left
# unsubstituted would have texted the applicant the literal word
# "applicantFirstName".
_PLACEHOLDERS_FIRST = (r"applicantFirstName", r"\bNAME\b")
_PLACEHOLDERS_ROLE = (r"adPostingTitle", r"xxxx")


def _fill_placeholders(text: str, first: str, role: str) -> str:
    out = text or ""
    for pat in _PLACEHOLDERS_FIRST:
        out = re.sub(pat, first, out)
    for pat in _PLACEHOLDERS_ROLE:
        out = re.sub(pat, role, out)
    return out


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


_SUBJECT_ROLE_RE = re.compile(
    r"new application for\s+(.+?)\s*(?:,\s*[A-Za-z .]+,\s*[A-Z]{2}\b|$)", re.I)


def read_posting_title(page, fallback: str = "") -> str:
    """The role the applicant applied to.

    `emailApplicantSubject` is blank on plenty of records (every one walked on
    2026-08-28), which made _role_from_position fall back to the word "open" —
    so a re-text would have read "we received your application for the open
    role". The title is still on the page: the source email's subject line says
    "[Action required] New application for <TITLE>, <City>, <ST>", and Indeed's
    own panel repeats it. Read those before giving up."""
    if (fallback or "").strip():
        return fallback
    for fr in list(page.frames):
        try:
            txt = fr.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except Exception:  # noqa: BLE001
            continue
        for line in txt.splitlines():
            m = _SUBJECT_ROLE_RE.search(" ".join(line.split()))
            if m and len(m.group(1)) > 3:
                return m.group(1).strip()
    return ""


def _role_from_position(position: str) -> str:
    """Short role for the template's 'xxxx' slot, e.g.
    'Event Marketing & Sales Assistant (Spanish Needed), 2 locations'
    -> 'Event Marketing & Sales Assistant'."""
    p = (position or "").strip()
    for cut in ("(", ",", " - ", " – "):
        i = p.find(cut)
        if i > 3:
            p = p[:i].strip()
    return p or "open"


def _close_sms_panel(page) -> None:
    for xp in ("xpath=(//*[normalize-space(.)='Close'])[1]",
               "xpath=//a[normalize-space(.)='×']",
               "xpath=//*[normalize-space(.)='×'][1]"):
        try:
            loc = page.locator(xp).first
            if loc.count() > 0:
                loc.click(timeout=2000, no_wait_after=True)
                page.wait_for_timeout(500)
                return
        except Exception:  # noqa: BLE001
            continue


def _sms_widget_frame(page, timeout_ms: int = 30000):
    """Find the frame that holds the Bandwidth SMS widget — identified by its Name
    filter. The widget injects SLOWLY (~15-20s after the SMS click), so poll
    patiently (detected via fr.evaluate, same as the probe). Returns
    (frame_or_None, diag)."""
    last_exc = ""
    for k in range(max(1, timeout_ms // 500)):
        for fr in page.frames:
            try:
                if fr.evaluate("() => !!document.querySelector("
                               "\"#sms_name_filter, [name='sms_name_filter']\")"):
                    _log(f"    [retext] widget appeared at ~{k * 0.5:.0f}s")
                    return fr, ""
            except Exception as e:  # noqa: BLE001
                last_exc = type(e).__name__
                continue
        page.wait_for_timeout(500)
    diag = [f"lastExc={last_exc}"] if last_exc else []
    for fr in page.frames:
        try:
            names = fr.evaluate(
                "() => [...document.querySelectorAll('input,select,textarea')]"
                ".map(e=>e.name||e.id||'').filter(n=>/sms/i.test(n)).slice(0,8)")
            diag.append(f"{(fr.url or '')[-24:]}|sms:{names}")
        except Exception as e:  # noqa: BLE001
            diag.append(f"err:{type(e).__name__}")
    return None, " ; ".join(diag)


def _xframe(page, selector):
    """First (frame, locator) across all frames where `selector` matches >=1."""
    for fr in page.frames:
        try:
            loc = fr.locator(selector).first
            if loc.count() > 0:
                return fr, loc
        except Exception:  # noqa: BLE001
            continue
    return None, None


def _xframe_wait(page, selector, timeout_s: float = 12.0, poll_ms: int = 400,
                 on_retry=None):
    """_xframe, but WAIT for the selector instead of judging it on a single look.

    The SMS template modal renders its list asynchronously, inside a frame. Looking
    once after a fixed sleep is a race, and it is the race that abandoned 46
    re-texts on 2026-08-27 ("FOR LUCY Select link not found") — every one of which
    had ALREADY found the applicant's thread and only needed the template picked.
    The skew gives it away: 39 of those were Atef's office and 7 Carlos's, and Atef
    was added to this machine the day before, so every fixed sleep on Lucy 2 became
    likelier to expire before the render finished.

    `on_retry(n)` runs before each re-poll — used here to re-type the template
    filter, since the search box itself can enter the DOM after our first look."""
    import time as _t
    deadline = _t.monotonic() + timeout_s
    tries = 0
    while True:
        fr, loc = _xframe(page, selector)
        if loc is not None:
            return fr, loc, tries
        if _t.monotonic() >= deadline:
            return None, None, tries
        tries += 1
        if on_retry is not None:
            try:
                on_retry(tries)
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(poll_ms)


# The 'Select' control on the FOR LUCY row. Kept broad on purpose: the ATS renders
# it as a link, but a button/input variant costs nothing to also accept and is one
# less way for this step to fail silently.
_SELECT_TEMPLATE_XPATH = (
    "xpath=//tr[.//*[normalize-space(.)='FOR LUCY']]//a[normalize-space(.)='Select']"
    " | //tr[contains(.,'FOR LUCY')]//a[normalize-space(.)='Select']"
    " | //tr[contains(.,'FOR LUCY')]//button[normalize-space(.)='Select']"
    " | //tr[contains(.,'FOR LUCY')]//input[@type='button'][contains(@value,'Select')]"
    " | //tr[contains(.,'FOR LUCY')]//input[@type='submit'][contains(@value,'Select')]"
)

_TEMPLATE_SEARCH_XPATH = ("xpath=//*[contains(normalize-space(.),'Loading SMS "
                          "Template')]/following::input[@type='text'][1]")


def retext_applicant(page, first, last, phone, role, *, do_send: bool):
    """Send the 'FOR LUCY' re-engagement text to ONE applicant through the Bandwidth
    SMS widget, then report (status, detail). Choreography confirmed with Megan
    2026-07-28 (screenshots): open SMS widget -> Date filter 'This Month' -> type
    applicant NAME in the widget Name box -> Search -> click the matching
    conversation (binds the recipient) -> Load Template -> Search 'FOR LUCY' ->
    Select -> replace NAME/xxxx in the compose box -> (Send).

    Fails SAFE: never sends unless do_send=True; if the recipient thread can't be
    uniquely matched (no thread that far back, or ambiguous), returns 'no_thread'
    WITHOUT sending so the caller flags it for a human instead of guessing."""
    name = f"{first} {last}".strip()
    want = _digits(phone)[-10:]
    if not _open_sms_panel(page):
        return "sms_panel_fail", "could not open SMS widget"
    # The Bandwidth widget injects its DOM asynchronously and may live in a child
    # iframe — resolve the actual frame that holds it before driving anything.
    w, diag = _sms_widget_frame(page, 30000)
    if w is None:
        _log(f"    [retext] widget frame not found — frames: {diag}")
        _close_sms_panel(page)
        return "sms_panel_fail", f"SMS widget did not load; frames=[{diag[:180]}]"
    _log(f"    [retext] widget frame ok (url …{(w.url or '')[-30:]})")
    page.wait_for_timeout(800)

    # Search across WIDENING date windows until the applicant's thread turns up.
    # Threads can be this-month, older ('Last Month'), or created later in the day —
    # so sweep instead of a single window (Megan 2026-07-29: "look at Last Month").
    _SET_JS = r"""(args) => {
        const nm=args[0], phone=args[1], win=args[2];
        const out={date:'', term:false, by:'', opts:[]};
        // Reset the TYPE filter first. It persists across uses of the widget, so a
        // filter left on (e.g. "Await Call") silently hides the applicant's thread
        // and the re-text dies as no_thread even though the conversation exists —
        // observed 2026-08-28 when a diagnostic left it set.
        const tf=document.querySelector("#sms_type_filter,[name='sms_type_filter']");
        if(tf){ const all=[...tf.options].find(o=>/^all$/i.test(o.text.trim()));
            if(all && tf.value!==all.value){ tf.value=all.value;
                tf.dispatchEvent(new Event('change',{bubbles:true})); } }
        const d=document.querySelector("#sms_date_filter, [name='sms_date_filter']");
        if(d){ out.opts=[...d.options].map(o=>o.text.trim());
            const o=[...d.options].find(o=>o.text.trim().toLowerCase()===win.toLowerCase())
                  ||[...d.options].find(o=>new RegExp(win,'i').test(o.text));
            if(o){ d.value=o.value; d.dispatchEvent(new Event('change',{bubbles:true})); out.date=o.text.trim(); } }
        const setF=(sel,val)=>{const e=document.querySelector(sel); if(!e)return false;
            e.value=val; e.dispatchEvent(new Event('input',{bubbles:true}));
            e.dispatchEvent(new Event('change',{bubbles:true})); return true;};
        setF("#sms_name_filter, [name='sms_name_filter']","");
        setF("#sms_phone_filter, [name='sms_phone_filter']","");
        if(phone && setF("#sms_phone_filter, [name='sms_phone_filter']",phone)){out.term=true;out.by='phone';}
        else if(setF("#sms_name_filter, [name='sms_name_filter']",nm)){out.term=true;out.by='name';}
        return out;
    }"""
    _PICK_JS = r"""(args) => {
        const want = args[0], name = (args[1]||'').toLowerCase();
        const norm = s => (s||'').replace(/\D/g,'');
        const all = [...document.querySelectorAll('div,li,a,tr')];
        const rows = all.filter(e => { const t=e.innerText||'';
            return t.length<200 && norm(t).length>=10 && /\+?1?\d{10}/.test(norm(t))
                   && e.querySelectorAll('*').length<25; });
        const cand = rows.filter(e => !rows.some(o => o!==e && e.contains(o)));
        window.__oat_rows = cand;
        const scored = cand.map((e,i)=>{ const t=e.innerText||'', d=norm(t);
            return {i, hasPhone:!!(want && d.includes(want)),
                    hasName:!!(name && t.toLowerCase().includes(name)),
                    text:t.replace(/\s+/g,' ').slice(0,60)}; });
        const byPhone = scored.find(s=>s.hasPhone);
        const named = scored.filter(s=>s.hasName);
        const choice = byPhone || (named.length===1 ? named[0] : (cand.length===1 ? scored[0] : null));
        return {count:cand.length, choice, sample:scored.slice(0,6)};
    }"""
    picked = None; used_win = None; opts = None
    for win in ("This Month", "Last Month", "This Week", "Today"):
        set_ok = w.evaluate(_SET_JS, [last or name, want, win])
        opts = set_ok.get("opts")
        if not set_ok.get("term"):
            _close_sms_panel(page)
            return "retext_err", "sms name/phone filter not found in widget frame"
        if not set_ok.get("date"):
            continue                      # this window isn't in the dropdown
        try:
            w.locator("#sms_filter_search").first.click(timeout=4000, no_wait_after=True)
        except Exception:  # noqa: BLE001
            w.evaluate("() => { const b=document.querySelector('#sms_filter_search');"
                       " if (b) b.click(); }")
        page.wait_for_timeout(2600)
        p = w.evaluate(_PICK_JS, [want, name])
        _log(f"    [retext] window={win!r} by={set_ok.get('by')} results={p.get('count')}")
        if p.get("choice"):
            picked = p; used_win = win; break
        picked = p
    _log(f"    [retext] date opts={opts} matched_in={used_win!r}")
    choice = picked.get("choice") if picked else None
    if not choice:
        _close_sms_panel(page)
        return "no_thread", f"no thread for {name} ({want or 'no-phone'}) across windows"
    try:
        w.evaluate("(i) => window.__oat_rows[i].click()", choice["i"])
        page.wait_for_timeout(1800)
    except Exception as e:  # noqa: BLE001
        _close_sms_panel(page)
        return "retext_err", f"thread click: {type(e).__name__}"
    _log(f"    [retext] bound thread: {choice.get('text')} "
         f"(byPhone={choice.get('hasPhone')})")

    # 4) Load Template -> modal -> filter to 'FOR LUCY' -> Select. The modal can
    #    render in the widget frame OR the main page, so locate across frames.
    _, lt = _xframe(page,
                    "xpath=//button[contains(normalize-space(.),'Load Template')]"
                    " | //a[contains(normalize-space(.),'Load Template')]"
                    " | //input[@type='button'][contains(@value,'Load Template')]")
    if lt is None:
        _close_sms_panel(page)
        return "retext_err", "Load Template button not found"
    lt.click(timeout=4000, no_wait_after=True)
    page.wait_for_timeout(1600)
    def _type_filter(_n=0):
        """Type the template name into the modal's search box. Re-run on every
        poll: the box can enter the DOM after our first look, and a filter typed
        into a box that wasn't there yet is why the list stayed unfiltered."""
        _, _ms = _xframe(page, _TEMPLATE_SEARCH_XPATH)
        if _ms is None:
            return
        try:
            if (_ms.input_value() or "").strip().upper() != _TEMPLATE_NAME:
                _ms.fill(_TEMPLATE_NAME, timeout=2500)
        except Exception:  # noqa: BLE001
            pass

    _type_filter()
    # WAIT for the row rather than looking once after a fixed sleep — see
    # _xframe_wait. 12s is far past a healthy render (well under a second) and
    # still cheap against a walk, and it only costs that long on a pick that was
    # going to be abandoned anyway.
    _, sel, _tries = _xframe_wait(page, _SELECT_TEMPLATE_XPATH, timeout_s=12.0,
                                  on_retry=_type_filter)
    if sel is None:
        # No saved template by that name in this office — compose the copy
        # ourselves rather than abandoning the applicant. This is the normal path
        # for office 11580, whose template modal has no await template at all.
        _log("    [retext] no saved template — composing the await copy directly")
        body = AWAIT_TEXT.format(first=first, role=role)
        cf0, _ = _xframe(page, "#ta_smsChat, textarea[name='ta_smsChat']")
        cf0 = cf0 or w
        wrote = cf0.evaluate(
            """(msg) => { const ta = document.querySelector(
                   "#ta_smsChat, textarea[name='ta_smsChat']")
                || [...document.querySelectorAll('textarea')]
                     .find(t => /Write message/i.test(t.placeholder || ''));
               if (!ta) return '';
               ta.value = msg;
               ta.dispatchEvent(new Event('input', { bubbles: true }));
               return ta.value; }""", body)
        if not wrote:
            _close_sms_panel(page)
            return "retext_err", "compose box not found (no template, direct write failed)"
        _log(f"    [retext] composed -> {wrote[:150]!r}")
        if not do_send:
            _close_sms_panel(page)
            return "retext_dry", wrote
        sfr2, sbtn2 = _xframe(page, "#btn-sms-send")
        try:
            (sbtn2 or w.locator("#btn-sms-send").first).click(timeout=5000,
                                                              no_wait_after=True)
            page.wait_for_timeout(2200)
        except Exception as e:  # noqa: BLE001
            _close_sms_panel(page)
            return "retext_err", f"send click: {type(e).__name__}"
        _close_sms_panel(page)
        return "sent", wrote
    if _tries:
        _log(f"    [retext] template row appeared after {_tries} extra poll(s) "
             f"— a single look would have abandoned this re-text")
    sel.click(timeout=4000, no_wait_after=True)
    page.wait_for_timeout(1300)

    # 5) Replace NAME + xxxx in the compose box (search frames for ta_smsChat).
    cf, _ = _xframe(page, "#ta_smsChat, textarea[name='ta_smsChat']")
    cf = cf or w
    filled = cf.evaluate(
        r"""(args) => {
            const first = args[0], role = args[1];
            const ta = document.querySelector("#ta_smsChat, textarea[name='ta_smsChat']")
                    || [...document.querySelectorAll('textarea')]
                         .find(t => /Write message/i.test(t.placeholder||''))
                    || [...document.querySelectorAll('textarea')]
                         .find(t => /NAME|Vantura/.test(t.value||''));
            if (!ta) return '';
            let v = (ta.value || '')
                .replace(/applicantFirstName/g, first)
                .replace(/\bNAME\b/g, first)
                .replace(/adPostingTitle/g, role)
                .replace(/xxxx/g, role);
            ta.value = v; ta.dispatchEvent(new Event('input', { bubbles: true }));
            return v;
        }""", [first, role])
    if not filled:
        _close_sms_panel(page)
        return "retext_err", "compose box not found after template load"
    _log(f"    [retext] composed -> {filled[:130]!r}")
    if any(t in filled for t in ("applicantFirstName", "adPostingTitle",
                                        "NAME", "xxxx")):
        _log("    [retext] WARN: placeholder still present after fill")

    if not do_send:
        _close_sms_panel(page)
        return "retext_dry", filled

    # 6) Send.
    sfr, sbtn = _xframe(page, "#btn-sms-send")
    try:
        (sbtn or w.locator("#btn-sms-send").first).click(timeout=5000,
                                                         no_wait_after=True)
        page.wait_for_timeout(2200)
    except Exception as e:  # noqa: BLE001
        _close_sms_panel(page)
        return "retext_err", f"send click: {type(e).__name__}"
    _close_sms_panel(page)
    return "retext_sent", filled


def _deaccent(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def _name_matches(a: Applicant, first: str, last: str) -> bool:
    # accent-insensitive: AS often stores "Rodriguez" where the resume/tab has
    # "Rodríguez"; without stripping, the walk never finds them (not_found).
    who = _deaccent(f"{a.first_name} {a.last_name}").strip().lower()
    first = _deaccent(first).lower()
    last = _deaccent(last).lower()
    tgt = f"{first} {last}".strip()
    return who == tgt or (bool(first) and bool(last)
                          and first in who and last in who)


def _walk_to_and_remove(page, first, last, max_hops: int = 80) -> str:
    """Walk the OAT queue to the applicant matching (first,last) and remove them
    (Duplicate reason). Used to finish a re-texted applicant when we're not already
    sitting on their record. Returns 'removed' / 'not_found' / 'left'."""
    seen: set = set()
    hops = 0
    for hops in range(max_hops):
        a = read_current_applicant(page)
        who = f"{a.first_name} {a.last_name}".strip().lower()
        _log(f"    [remove-one] hop {hops}: {a.first_name!r} {a.last_name!r}")
        if _name_matches(a, first, last):
            _log(f"    [remove-one] found {a.first_name} {a.last_name} — removing")
            return "removed" if _perform_remove(page) else "left"
        key = f"{a.email}|{who}"
        if key in seen:
            _log(f"    [remove-one] re-seen {who!r} — treating as end of queue")
            break
        seen.add(key)
        if not advance_to_next(page):
            _log("    [remove-one] no next control — end of queue")
            break
    _log(f"    [remove-one] not found after {hops + 1} hops")
    return "not_found"


# --- Route-through-your-browser no-phone flow (Megan 2026-08-02) --------------- #
# The bot can't pass Indeed's Cloudflare on resume pages, but Megan's real Chrome
# can. So: (1) emit_nophone_resumes walks the queue and writes each no-phone
# applicant + their 'View resume' URL to a Sheet tab; (2) a human/Claude-in-Chrome
# opens those URLs in a real browser and fills the phone column; (3)
# fill_nophone_from_tab reads the phones back, walks to each applicant, types the
# number and sends to AI.
_NOPHONE_TAB = "OAT_NoPhone_Resumes"
_NOPHONE_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"


def _nophone_ws(create=False):
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(_NOPHONE_SHEET)
    try:
        return sh.worksheet(_NOPHONE_TAB)
    except Exception:  # noqa: BLE001
        if create:
            return sh.add_worksheet(title=_NOPHONE_TAB, rows=300, cols=5)
        raise


def emit_nophone_resumes(page, max_hops: int = 80) -> int:
    """Walk the OAT queue and write every no-phone applicant + their 'View resume'
    URL to the OAT_NoPhone_Resumes tab (cols: name, resume_url, phone, status).
    A real browser then fills the phone column; fill_nophone_from_tab sends them."""
    out = [["name", "resume_url", "phone", "status"]]
    seen: set = set()
    for _ in range(max_hops):
        a = read_current_applicant(page)
        who = f"{a.first_name} {a.last_name}".strip()
        key = f"{a.email}|{who}".lower()
        if not who or key in seen:
            if not advance_to_next(page):
                break
            continue
        seen.add(key)
        if not (a.cell_phone or a.phone):        # no phone on file
            href = _view_resume_href(page)
            if href:
                out.append([who, href, "", ""])
                _log(f"    [emit-nophone] {who} -> resume url captured")
        if not advance_to_next(page):
            break
    ws = _nophone_ws(create=True)
    ws.clear()
    ws.update(out, "A1", value_input_option="RAW")
    _log(f"[oat] emit-nophone-resumes: wrote {len(out)-1} applicants to {_NOPHONE_TAB}")
    return 0


def _walk_to_and_fill_send(page, first, last, phone, max_hops: int = 300) -> str:
    """Walk OAT to the named applicant, TYPE the phone into Phone/Cell, and Send to
    AI. Returns the do_send_ai outcome / 'not_found' / 'fill_failed'."""
    seen: set = set()
    for _ in range(max_hops):
        a = read_current_applicant(page)
        who = f"{a.first_name} {a.last_name}".strip().lower()
        if _name_matches(a, first, last):
            if not _fill_phone_field(page, phone):
                return "fill_failed"
            page.wait_for_timeout(900)
            _log(f"    [fill-send] {a.first_name} {a.last_name} phone {phone} -> Send to AI")
            return do_send_ai(page, a, True)
        key = f"{a.email}|{who}"
        if key in seen:
            break
        seen.add(key)
        if not advance_to_next(page):
            break
    return "not_found"


def fill_nophone_from_tab(page) -> int:
    """Read OAT_NoPhone_Resumes: for each applicant whose phone column was filled
    (by the real-browser resume scrape) and not yet done, walk to them, type the
    number, and Send to AI. Marks status back on the tab."""
    ws = _nophone_ws(create=False)
    rows = ws.get_all_records()
    done = 0
    for i, r in enumerate(rows):
        phone = re.sub(r"\D", "", str(r.get("phone", "")))
        status = str(r.get("status", "")).strip().lower()
        if len(phone) < 10 or status in ("sent", "sent_override", "done"):
            continue
        nm = str(r.get("name", "")).split()
        first = nm[0] if nm else ""
        last = " ".join(nm[1:]) if len(nm) > 1 else ""
        if not _open_oat_ready(page):
            # queue page won't load (laggy/stale session) — don't burn this row as
            # a false not_found; leave status blank so a later pass retries it.
            _log(f"[oat] fill-nophone {r.get('name')} -> queue not ready, skipping")
            continue
        st = _walk_to_and_fill_send(page, first, last, phone)
        _log(f"[oat] fill-nophone {r.get('name')} -> {st}")
        try:
            ws.update_cell(i + 2, 4, st)          # col D = status
        except Exception:  # noqa: BLE001
            pass
        if st in ("sent", "sent_override"):
            done += 1
    _log(f"[oat] fill-nophone-from-tab: sent {done}")
    return 0


def _armed_retext(page, a: Applicant, days, live: bool) -> str:
    """Shared re-text handler for BOTH re-text paths (do_retext_then_remove AND
    do_send_ai's >1wk block). Armed (live + config.RETEXT_ARMED): text the quiet
    applicant via the SMS widget, then remove the current record
    ('re-texted & removed'). Not armed, or no reachable SMS thread: FLAG (no
    send/remove) — never guesses/spams."""
    # Texting is per-office. An office that has not opted in gets the applicant
    # FLAGGED for a human instead of messaged. (Carlos, 2026-08-29: only his
    # office and Atef's text people.)
    if not getattr(config, "ALLOW_RETEXT", False):
        # Send if we possibly can (override/overwrite, either label); otherwise
        # this office removes rather than leaving them flagged forever.
        #
        # CLICK SEND FIRST. The override/overwrite control only RENDERS on the
        # refused screen, and do_retext_then_remove reaches here without ever
        # having attempted a send — so looking for the control now would find
        # nothing and remove someone who was sendable all along. That is the very
        # mistake this audit exists to find. (Carlos, 2026-08-29, on Rossana
        # Martheins: "I'm pretty sure Rosanna had the option to overwrite.")
        outcome = "refused" if "cannot send to ai" in _body(page) else ""
        if not outcome:
            if not _guard_office_now(page, "Send to AI"):
                _flag_retext(a, days)
                return "flag_retext"
            _click_first(page, ["Send to AI", "Send To AI"], timeout=6000)
            # Wait for a DEFINITE outcome — refusal panel, or the applicant gone
            # from the slot. One 2.5s snapshot saw neither and produced both
            # failure modes of 2026-08-29: refused sends logged as clean, and
            # Rossana removed while her overwrite button was still rendering.
            outcome = _wait_send_outcome(page, a)
        if outcome == "sent":
            _log(f"    ✅ SENT to AI (confirmed left the slot): "
                 f"{a.first_name} {a.last_name}")
            return "sent"
        if outcome == "refused":
            for _ln in _red_messages(page):
                _log(f"    [refusal] {_ln}")
        if outcome == "refused" and _try_overwrite_send(page):
            _log(f"    ✅ override-sent instead of removing: "
                 f"{a.first_name} {a.last_name}")
            return "sent_override"
        if outcome == "refused":
            # Positive refusal AND the override wait came up empty — only now is
            # a removal earned.
            if _perform_remove(page, DUP_REASON):
                _log(f"    🗑 removed as duplicate (refused, no override after "
                     f"waiting, office does not text): "
                     f"{a.first_name} {a.last_name}")
                return "removed"
        # 'unknown', or the remove itself failed: NEVER remove on ambiguity.
        _flag_retext(a, days)
        _log(f"    ⚑ FLAG (outcome={outcome or 'unknown'} — not removing): "
             f"{a.first_name} {a.last_name} "
             f"[{a.cell_phone or a.phone or 'no-phone'}]")
        return "flag_retext"
    if not (live and getattr(config, "RETEXT_ARMED", False)):
        _flag_retext(a, days)
        tail = f" (last contact {days}d)" if days is not None else ""
        _log(f"    ⚑ FLAG re-text: {a.first_name} {a.last_name} "
             f"[{a.cell_phone or a.phone or 'no-phone'}]{tail}")
        return "flag_retext"
    # Already established today that no thread of theirs is reachable? Then the
    # whole widget dance below can only end the same way — flag them and move on,
    # which is what keeps a walk from spending its time re-deciding settled cases.
    _key = _nophone_key(a)
    if _key in _load_nothread():
        global _SETTLED_SKIPS
        _SETTLED_SKIPS += 1          # a page-turn, not a slot (see run_walk)
        _flag_retext(a, days)
        _log(f"    ⚑ no reachable thread (settled earlier today) — skipping the "
             f"re-text attempt: {a.first_name} {a.last_name}")
        return "flag_retext"
    role = _role_from_position(a.position)
    phone = a.cell_phone or a.phone
    status, detail = retext_applicant(page, a.first_name, a.last_name, phone, role,
                                      do_send=True)
    if status == "retext_sent":
        _log(f"    \U0001f4f2 re-texted: {a.first_name} {a.last_name} -> {detail[:80]}")
        if _perform_remove(page):
            _log(f"    \U0001f5d1 re-texted & removed: {a.first_name} {a.last_name}")
            return "retext_removed"
        return "retext_sent"
    # couldn't uniquely reach them — flag for a human, don't guess/spam.
    # Settle ONLY 'no_thread': structural (no fresh threads in AppStream, and the
    # widget cannot see one older than this month), so today's answer is fixed.
    # 'retext_err' is transient — a missed template or a lost race — and must be
    # retried, or we repeat the 2026-08-25 resume-read mistake where a blip wrote
    # 90 applicants off for the day.
    if status == "no_thread":
        _mark_nothread(_key)
    _flag_retext(a, days)
    _log(f"    ⚑ re-text fell back to FLAG ({status}: {detail}): "
         f"{a.first_name} {a.last_name}")
    return "flag_retext"


def do_retext_then_remove(page, a: Applicant, live: bool) -> str:
    """Re-text a quiet applicant (>1wk, past-interview path) then remove them."""
    _would(live, "re-text then remove")
    if not live:
        return "dry"
    return _armed_retext(page, a, None, live)


def probe_search(page, term: str) -> None:
    """Diagnostic: map the AS search (Megan uses Home→Search→first name), then run a
    search for `term` and dump the results structure so we can wire retext_by_name."""
    first = term.split()[0] if term else ""
    last = term.split()[-1] if term else ""
    # what search inputs / nav exist?
    info = page.evaluate(
        """() => ({
            url: location.href.slice(-46),
            nav: [...document.querySelectorAll('a')].map(e=>(e.innerText||'').trim())
                 .filter(t=>t && t.length<22).slice(0,34),
            searchInputs: [...document.querySelectorAll('input')]
                .filter(e=>/search|srch|name|fname|lname/i.test((e.name||'')+(e.placeholder||'')+(e.id||'')))
                .map(e=>`${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,18)}`).slice(0,16)
        })""")
    _log(f"[search] url={info.get('url')}")
    _log(f"[search] nav={info.get('nav')}")
    _log(f"[search] searchInputs={info.get('searchInputs')}")
    # Go to Advanced Search (Megan's Home→Search), dump its form, search by first
    # name, then dump the results + applicant links.
    try:
        for lbl in ("Advanced Search", "Search"):
            loc = page.locator(f"xpath=//a[normalize-space(.)='{lbl}']").first
            if loc.count() > 0:
                loc.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(3000)
                _log(f"[search] clicked nav '{lbl}'")
                break
        form = page.evaluate(
            """() => ({
                url: location.href.slice(-40),
                fields: [...document.querySelectorAll('input,select')]
                    .filter(e=>!/hidden/.test(e.type||''))
                    .map(e=>`${e.tagName}:${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,16)}`).slice(0,26),
                submits: [...document.querySelectorAll('input[type=submit],button,input[type=button]')]
                    .map(e=>(e.value||e.innerText||'').trim()).filter(Boolean).slice(0,10)
            })""")
        _log(f"[search] ADV url={form.get('url')}")
        for x in form.get("fields", []):
            _log(f"[search] ADV field {x}")
        _log(f"[search] ADV submits={form.get('submits')}")
        # fill a first-name-ish field, submit
        filled = page.evaluate(
            """(fn) => { const c=[...document.querySelectorAll('input')]
                .filter(e=>/first|fname/i.test((e.name||'')+(e.id||'')+(e.placeholder||'')));
                if(c[0]){c[0].value=fn; c[0].dispatchEvent(new Event('input',{bubbles:true}));
                    return c[0].name||c[0].id;} return null; }""", first)
        _log(f"[search] ADV filled first-name field: {filled}")
        for lbl in ("Search", "Go", "Submit", "Find"):
            b = page.locator(f"xpath=//input[@type='submit'][contains(@value,'{lbl}')]"
                             f" | //button[contains(normalize-space(.),'{lbl}')]").first
            if b.count() > 0:
                b.click(timeout=4000, no_wait_after=True); break
        page.wait_for_timeout(3500)
        res = page.evaluate(
            """(full) => ({
                url: location.href.slice(-40),
                rows: [...document.querySelectorAll('tr')]
                    .filter(e=>(e.innerText||'').toLowerCase().includes(full))
                    .map(e=>(e.innerText||'').replace(/\\s+/g,' ').slice(0,80)).slice(0,6),
                links: [...document.querySelectorAll('a')]
                    .filter(e=>(e.innerText||'').toLowerCase().includes(full.split(' ')[0])
                        || /p=604|openApp|viewApp|editApp/i.test(e.getAttribute('href')||''))
                    .map(e=>((e.innerText||'').trim().slice(0,24))+' -> '+(e.getAttribute('href')||'').slice(0,42)).slice(0,10)
            })""", f"{first} {last}".lower())
        _log(f"[search] RESULT url={res.get('url')}")
        for r in res.get("rows", []):
            _log(f"[search] RESULT row: {r}")
        for l in res.get("links", []):
            _log(f"[search] RESULT link: {l}")
    except Exception as e:  # noqa: BLE001
        _log(f"[search] probe err: {type(e).__name__}: {e}")


def retext_by_name(page, first, last, phone=""):
    """Re-text an applicant who has already LEFT the OAT queue: global-search AS by
    last name (Home→Search), open their record to read the role they applied for,
    then re-text via the SMS widget. Returns (status, detail)."""
    last = last or first
    try:
        page.fill("input[name='globalSrchFor']", last, timeout=6000)
        clicked = False
        for sel in ("#glblSrchSbmt", "input[name='glblSrchSbmt']",
                    "xpath=//input[@value='Go']", "xpath=//*[normalize-space(.)='Go']"):
            try:
                b = page.locator(sel).first
                if b.count() > 0:
                    b.click(timeout=4000, no_wait_after=True)
                    clicked = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            page.press("input[name='globalSrchFor']", "Enter")
        page.wait_for_timeout(3200)
    except Exception as e:  # noqa: BLE001
        return "search_err", f"{type(e).__name__}"
    # Open the matching applicant from the results.
    #
    # Match FIRST and LAST independently, order-free and accent-folded. Looking for
    # the literal "first last" substring failed on every applicant: the results
    # grid renders "Last, First", so the needle never appeared, and a name like
    # "Darisleidy Remedios González" also lost to the accent. Both came back
    # not_found and NO text was sent (2026-08-28) — the applicant was silently
    # skipped rather than re-engaged, which is the exact failure this flow exists
    # to prevent.
    f_norm, l_norm = _deaccent(first).lower(), _deaccent(last).lower()
    opened = page.evaluate(
        """(args) => {
            const [f, l] = args;
            const fold = s => (s || '')
                .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
            const links = [...document.querySelectorAll('a')];
            // prefer a link carrying BOTH names; fall back to the last name alone
            const both = links.find(e => {
                const t = fold(e.innerText);
                return t.includes(f) && t.includes(l); });
            const one = both || links.find(e => {
                const t = fold(e.innerText);
                return l.length > 2 && t.includes(l) && t.length < 60; });
            if (one) { one.click(); return (one.innerText || '').trim().slice(0, 40); }
            return null; }""", [f_norm, l_norm])
    if not opened:
        return "not_found", f"no search result for {first} {last}"
    page.wait_for_timeout(2500)
    a = read_current_applicant(page)
    role = _role_from_position(read_posting_title(page, a.position))
    ph = phone or a.cell_phone or a.phone
    _log(f"    [retext-name] opened {a.first_name} {a.last_name} role={role!r} "
         f"phone={ph!r}")
    if not ph:
        return "no_phone", f"{first} {last} has no phone on record"
    status, detail = retext_applicant(page, first, last, ph, role, do_send=True)
    _log(f"    [retext-name] {first} {last} -> {status} :: {detail[:70]}")
    return status, f"{detail} (role={role})"


_NO_PHONE_ROWS: list = []


# Email seen on the last resume read — set by lookup_resume_phone, consumed by
# _fill_contact right after the phone goes in. Carlos, 2026-08-29: "when we open
# up the resume, we want to grab the email for everyone if it's there. If it's
# not there, all good — we just leave the email that's generated on there."
_LAST_RESUME_EMAIL = ""


def _fill_email_field(page, email: str) -> bool:
    """Type the applicant's real email over the job-board-generated relay.
    Keystrokes for the same reason as the phone: JS-setting the value makes AS
    re-render and drop the Send-to-AI button."""
    if not email or "@" not in email:
        return False
    try:
        loc = page.locator("input[name='email']").first
        if loc.count() == 0:
            return False
        cur = (loc.input_value() or "").strip().lower()
        if cur == email.strip().lower():
            return True                      # already right — leave it alone
        loc.click(timeout=4000)
        loc.fill("")
        loc.press_sequentially(email.strip(), delay=25)
        page.keyboard.press("Tab")
        _log(f"    ✉ filled email from resume: {email.strip()}")
        return True
    except Exception:  # noqa: BLE001
        return False


def _fill_contact(page, phone: str) -> bool:
    """Phone + (when the resume carried one) email, in one move. The phone is
    what gates the send; the email is best-effort on top."""
    ok = _fill_phone_field(page, phone)
    if ok and _LAST_RESUME_EMAIL:
        _fill_email_field(page, _LAST_RESUME_EMAIL)
    return ok


def _fill_phone_field(page, phone: str) -> bool:
    """Fill the AS Phone + Cell Phone fields by REAL keystrokes — the way a human
    does it. (JS-setting the value + firing 'change' makes AS re-render and drop
    the 'Send to AI' button; typing keeps it — Megan 2026-07-28.)"""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        return False
    ok = False
    for sel in ("input[name='phone']", "input[name='cellPhone']"):
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.click(timeout=4000)
            loc.fill("")                       # clear any partial
            loc.press_sequentially(d, delay=35)  # type the 10 digits, human-like
            ok = True
        except Exception:  # noqa: BLE001
            continue
    try:
        page.keyboard.press("Tab")             # blur the last field
    except Exception:  # noqa: BLE001
        pass
    return ok


_NOTHREAD = None   # lazily-loaded set of applicants with no reachable SMS thread


def _nothread_path():
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    (root / "output").mkdir(parents=True, exist_ok=True)
    return (root / "output" /
            f"oat-nothread-{dt.date.today().isoformat()}{config.FILE_SUFFIX}.json")


def _load_nothread() -> set:
    """Applicants we ALREADY established today have no SMS thread the widget can
    see. Their re-text is not worth re-attempting this day.

    Why this exists (Megan 2026-08-27): "the walks should get shorter because
    there should be less to process especially if you're recognizing what apps you
    can now skip." The no-number cache only ever skipped the resume READ — a
    flagged applicant still had the ENTIRE re-text attempt re-run every walk: open
    the SMS widget, bind the thread, hunt the template, fail, flag. With ~11 of
    them in one office that was the bulk of a walk, repeated every ten minutes, to
    reach a conclusion we had already reached.

    ONLY 'no_thread' is cached. That one is structural — AppStream cannot start a
    fresh thread and the widget cannot see one older than this month, so the answer
    cannot change today. A 'retext_err' (a missed template, a click that lost a
    race) is TRANSIENT and must be retried, or we would repeat the mistake the
    resume-read cache made on 2026-08-25, when a Cloudflare blip wrote 90
    applicants off for the whole day."""
    global _NOTHREAD
    if _NOTHREAD is None:
        try:
            import json as _json
            _NOTHREAD = set(_json.loads(_nothread_path().read_text()))
            if _NOTHREAD:
                _log(f"[oat] no-thread cache: {len(_NOTHREAD)} applicant(s) already "
                     f"known unreachable today — their re-text is skipped")
        except Exception:  # noqa: BLE001
            _NOTHREAD = set()
    return _NOTHREAD


def _mark_nothread(key: str) -> None:
    import json as _json
    c = _load_nothread()
    c.add(key)
    try:
        _nothread_path().write_text(_json.dumps(sorted(c)))
    except Exception:  # noqa: BLE001
        pass


def _persist_phone(page, phone: str) -> bool:
    """Write a recovered number onto the applicant's record with 'Save Applicant'.

    WHY: when the ATS refuses the send ("correspondence with this phone number has
    already occurred"), the number we just read off the resume is never saved, so
    the record still shows a BLANK phone. Two costs. The next walk sees no phone,
    re-opens the same resume and repeats the whole thing every ~10 minutes — that
    is the loop Claudia Ceniceros sat in from 2026-08-21 to 08-27. And the human
    who has to text these people by hand opens the record to find no number, so
    they go pull it from Indeed themselves: exactly the work this bot exists to
    remove. A fresh SMS thread would avoid the manual text entirely, but AppStream
    cannot start one (Megan 2026-08-27, and she is asking the vendor for a 90-day
    filter), so the manual text is the real destination and the number must be
    sitting on the record when the human gets there.

    Only called AFTER the send has been attempted and did not happen, so the 163
    sends a day that do go straight through are untouched by this. Best-effort:
    every failure path returns False and is logged, never raised — a number we
    could not save is the status quo, while an exception here would cost the walk."""
    try:
        loc = page.locator("input[name='phone']").first
        if loc.count() == 0:
            return False        # not on the record any more — nothing to save onto
        want = re.sub(r"\D", "", phone or "")
        if len(want) == 11 and want.startswith("1"):
            want = want[1:]
        if len(want) != 10:
            return False
        if re.sub(r"\D", "", loc.input_value() or "") != want:
            # The field lost the value (the ATS re-renders on refusal), so retype
            # it — by keystroke, for the same reason _fill_phone_field does.
            if not _fill_phone_field(page, phone):
                return False
        if not _click_first(page, ["Save Applicant", "Save applicant"]):
            return False
        page.wait_for_timeout(1800)
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"    could not save the number to the record: {type(e).__name__}")
        return False


_NOPHONE_CHECKED = None   # lazily-loaded set of applicant keys already read today
_NOPHONE_SKIPS = 0        # count of resume re-reads SKIPPED this walk (cache hits)
# Applicants this walk PAGED PAST for free — already settled today (no number on
# the resume we read, or no reachable SMS thread), so the handler returns without
# doing anything. They cost a page-turn, not a slot: run_walk excludes them from
# the per-run cap so the walk can still reach the back of the queue.
_SETTLED_SKIPS = 0
_NOPHONE_BLOCKED = None   # lazily-loaded {key: {"n": attempts, "last": iso}} retry state

# A resume read that ended BLOCKED (page never rendered) is marked with this prefix
# in lookup_resume_phone's detail string, so flag_no_phone can tell it apart from a
# resume that genuinely carries no number. Blocked reads get retried later in the
# day; empty resumes are settled and never re-read (Megan's 2026-08-06 rule).
_BLOCKED_PREFIX = "blocked: "

# Cloudflare / sign-in-wall markers. If the resume tab still shows one of these when
# the poll runs out, we never saw the resume at all.
_BLOCK_SIGNS = (
    "just a moment", "verify you are human", "checking your browser",
    "attention required", "access denied", "enable javascript",
)
# Checked against the TITLE ONLY. Indeed answers a blocked client with a page
# titled "Blocked - Indeed.com" that carries a normal-length body, so it passed
# every existing gate: no Cloudflare phrase, no sign-in phrase, body over the
# 200-char floor. The read was therefore filed as "the resume opened and has no
# number" — the CONFIRMED-uncontactable verdict. That verdict caches the
# applicant for the rest of the day and, in an office with REMOVE_NO_PHONE on
# (Atef's 23467), REMOVES them for "Incorrect / Insufficient Contact Info".
# So a block on our side was costing applicants their record.
# Seen for real on 2026-08-27/28: a headless walker gets this on every resume.
# Title-only on purpose: a résumé body can legitimately contain the word
# "blocked" (a candidate who "blocked out schedules"), and matching that would
# turn every such resume into a permanent retry.
_BLOCK_TITLE_SIGNS = ("blocked", "forbidden", "403", "too many requests", "429")
_SIGNIN_SIGNS = (
    "sign in to your account", "employer sign in", "sign in with google",
    "create your account", "log in to indeed", "sign in to indeed",
)

# POSITIVE PROOF THAT THE RESUME ITSELF RENDERED — not just the viewer around it.
# WHY (Shanice Rankine, office 23467, 2026-09-03). Her number is in the header,
# "Lakewood, CO 80215 | +1 754 302 3395 | shanice…@indeedemail.com" — the same
# layout the reader pulled from Tamara Derryberry and Manuel Montana the same day.
# Her first read of the morning still came back empty, and _blocked_reason cleared
# her: no Cloudflare phrase, no sign-in phrase, and a body well over the 200-char
# floor — because the VIEWER CHROME alone ("Shanice Rankine's Resume", nav,
# footer) is over it. So a resume frame that had not rendered YET was recorded as
# "the resume opened and has no number", the CONFIRMED-uncontactable verdict, which
# caches for the day. She was then skipped 75 times without the resume being
# reopened once, and Megan sent her by hand at 6:24 PM.
#
# The 8/27 fix taught the reader to look INSIDE frames; this is the other half —
# noticing when there is no frame content to look at. A rendered Indeed resume
# always carries at least one of these; the chrome carries none of them. Absent
# every one, we did not see a resume, so the read is BLOCKED (retryable) rather
# than a confirmed-empty one. Keep the list GENEROUS and err toward "rendered":
# a marker we forgot costs one needless retry, bounded by the retry budget; a
# marker we lack settles a reachable applicant for the whole day. The bias is deliberate and matches Carlos's rule
# ("If that doesn't work, then just leave it there. Don't remove that applicant"):
# a needless retry costs ~12s, a wrong "confirmed empty" costs the applicant their
# whole day. The retry budget (_BLOCKED_MAX_ATTEMPTS) still bounds the cost.
_RENDERED_RESUME_SIGNS = (
    "experience", "education", "skills", "authorized to work", "employment",
    "certification", "objective", "summary", "references", "qualifications",
    "@",                       # every resume header carries a contact email
)

# Retry budget for a blocked read: try at most this many times per applicant per day,
# each at least _BLOCKED_RETRY_AFTER_MIN apart. The cool-off is the point — Megan's
# 8/6 complaint was the walk reopening the same resumes every 5 minutes, and a bare
# retry would bring that straight back. After the last attempt the applicant is
# promoted to the settled cache and left to the twice-daily manual to-do post.
_BLOCKED_MAX_ATTEMPTS = 3
_BLOCKED_RETRY_AFTER_MIN = 45


def _blocked_reason(title: str, body: str) -> str:
    """Why this resume tab never rendered — '' when it rendered fine (so an empty
    resume stays an empty resume). Takes the LAST title/body seen by the poll."""
    t = (title or "").lower()
    b = (body or "").lower()
    for sign in _BLOCK_SIGNS:
        if sign in t or sign in b:
            return "cloudflare challenge never cleared"
    for sign in _BLOCK_TITLE_SIGNS:
        if sign in t:
            return f"indeed blocked the read (title says {sign!r})"
    for sign in _SIGNIN_SIGNS:
        if sign in b:
            return "indeed sign-in wall"
    if len(b.strip()) < 200:
        # A real resume is never this short. An empty/near-empty body means the page
        # didn't render — usually the employer portal bouncing us.
        return "resume page never rendered (empty body)"
    if not any(sign in b for sign in _RENDERED_RESUME_SIGNS):
        # Long enough to pass the floor, but carrying none of the marks a real
        # resume has — i.e. the viewer shell with nothing in it yet. See
        # _RENDERED_RESUME_SIGNS: this is Shanice Rankine's case.
        return "viewer chrome only — resume body never rendered"
    return ""


def _is_blocked_detail(detail: str) -> bool:
    return str(detail or "").startswith(_BLOCKED_PREFIX)


def _write_walk_diag(start, end, cache_size, skips, counts) -> None:
    """Append a one-row proof of this walk to the 'OAT Walk Diag' Sheet tab so the
    walk's behaviour can be verified queue-independently (read the Sheet directly),
    since the mini-control poller can get jammed. Shows the queue delta, the
    no-number cache size + how many re-reads were SKIPPED (cache working), and the
    full outcome counts (incl. re-text sent/removed). Best-effort."""
    try:
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(
            "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            ws = sh.worksheet(config.WALK_DIAG_TAB)
        except Exception:  # noqa: BLE001
            ws = sh.add_worksheet(title=config.WALK_DIAG_TAB, rows=1000, cols=6)
            ws.append_row(["At", "Queue", "NoNumberCache", "ResumeReReadsSkipped",
                           "Outcomes"], value_input_option="RAW")
        cs = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        ws.append_row([dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       f"{start} -> {end}", str(cache_size), str(skips), cs],
                      value_input_option="RAW")
    except Exception as e:  # noqa: BLE001
        _log(f"[oat] walk diag write failed: {type(e).__name__}: {e}")


def _nophone_key(a: Applicant) -> str:
    # Key on the NAME only — it's always present and stable across walks. Email was
    # flakier (sometimes blank in the read), which would flip the key and defeat the
    # cache (Megan 2026-08-06: it kept re-reading the same resumes).
    return f"{a.first_name} {a.last_name}".strip().lower()


def _nophone_checked_path():
    # REPO-ROOT-anchored, NOT cwd-relative — so the write and every later walk's read
    # always hit the same file no matter what directory launchd starts the walk in.
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    (root / "output").mkdir(parents=True, exist_ok=True)
    return (root / "output" /
            f"oat-nophone-checked-{dt.date.today().isoformat()}{config.FILE_SUFFIX}.json")


def _nophone_settled_path():
    """The CROSS-DAY store of applicants whose resume we opened and confirmed
    carries no number. NOT date-keyed — that is the whole point."""
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    (root / "output").mkdir(parents=True, exist_ok=True)
    return (root / "output" / f"oat-nophone-settled{config.FILE_SUFFIX}.json")


def _load_nophone_settled() -> dict:
    """{key: 'YYYY-MM-DD'} — the day we last CONFIRMED this resume has no number.

    Entries past the re-check window are dropped on load, which is how the
    periodic re-read happens: forget the verdict and the next walk earns it again.
    """
    import json as _json
    try:
        with open(_nophone_settled_path()) as _fh:
            raw = _json.load(_fh)
        if not isinstance(raw, dict):
            return {}
    except Exception:  # noqa: BLE001
        return {}
    window = int(getattr(config, "SETTLED_RECHECK_DAYS", 7))
    cutoff = dt.date.today() - dt.timedelta(days=window)
    out = {}
    for k, v in raw.items():
        try:
            if dt.date.fromisoformat(str(v)) > cutoff:
                out[k] = str(v)
        except Exception:  # noqa: BLE001 — an unparseable date re-reads, which is safe
            continue
    return out


def _mark_nophone_settled(key: str) -> None:
    """Record a CONFIRMED-empty resume so later DAYS skip it too. Only ever called
    for a read that actually opened the resume — never for a blocked one."""
    if not key:
        return
    import json as _json
    state = _load_nophone_settled()          # already pruned to the window
    state[key] = dt.date.today().isoformat()
    try:
        with open(_nophone_settled_path(), "w") as _fh:
            _json.dump(state, _fh, indent=0, sort_keys=True)
    except Exception as _e:  # noqa: BLE001
        _log(f"[oat] WARN could not persist the settled no-number store: {_e}")


def _load_nophone_checked() -> set:
    """Applicants whose resume we already opened TODAY and found no number — so a
    later walk skips re-reading the same dead-end resume (Megan 2026-08-06: don't
    waste ~12s reopening resumes we've already confirmed have no phone). Per-day so
    it self-re-checks each morning (a resume could update, or Cloudflare ease)."""
    global _NOPHONE_CHECKED
    if _NOPHONE_CHECKED is None:
        import json as _json
        try:
            with open(_nophone_checked_path()) as _fh:
                _NOPHONE_CHECKED = set(_json.load(_fh))
        except Exception:  # noqa: BLE001
            _NOPHONE_CHECKED = set()
        # Carry forward the CONFIRMED-empty verdicts from earlier days. Without
        # this the whole flagged backlog gets its resume reopened every morning —
        # the same dead ends, daily, while new applicants wait behind them.
        _carried = set(_load_nophone_settled()) - _NOPHONE_CHECKED
        if _carried:
            _NOPHONE_CHECKED |= _carried
            _log(f"[oat] carried {len(_carried)} confirmed-empty resume(s) over "
                 f"from earlier days (re-checked every "
                 f"{getattr(config, 'SETTLED_RECHECK_DAYS', 7)} days) — not "
                 f"re-opening those today")
        _log(f"[oat] no-number cache loaded: {len(_NOPHONE_CHECKED)} app(s) already "
             f"checked today (these skip the resume re-read)")
    return _NOPHONE_CHECKED


def _mark_nophone_checked(key: str, *, confirmed: bool = False) -> None:
    """Stop re-reading this applicant's resume today.

    `confirmed=True` means we OPENED the resume and it carries no number — a
    verdict that keeps, so it also goes in the cross-day store. The default is
    for the blocked-read path, which gives up for TODAY having never seen the
    resume: that one must come back tomorrow.
    """
    if confirmed:
        _mark_nophone_settled(key)
    s = _load_nophone_checked()
    if key and key not in s:
        s.add(key)
        import json as _json
        try:
            with open(_nophone_checked_path(), "w") as _fh:
                _json.dump(sorted(s), _fh)
        except Exception as _e:  # noqa: BLE001
            _log(f"[oat] WARN could not persist no-number cache: {_e}")


# --- blocked-read retry state -------------------------------------------------
# Separate from the settled no-number cache ABOVE on purpose. That cache means "we
# read this resume and it has no number" — permanent for the day. This one means
# "we never got to see this resume", which is a temporary condition (Cloudflare, a
# sign-in wall) and deserves another look before we hand the applicant to a human.

def _nophone_blocked_path():
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    (root / "output").mkdir(parents=True, exist_ok=True)
    return (root / "output" /
            f"oat-nophone-blocked-{dt.date.today().isoformat()}{config.FILE_SUFFIX}.json")


def _load_nophone_blocked() -> dict:
    """{key: {"n": attempts_so_far, "last": iso-timestamp}} for today."""
    global _NOPHONE_BLOCKED
    if _NOPHONE_BLOCKED is None:
        import json as _json
        try:
            with open(_nophone_blocked_path()) as _fh:
                loaded = _json.load(_fh)
            _NOPHONE_BLOCKED = loaded if isinstance(loaded, dict) else {}
        except Exception:  # noqa: BLE001
            _NOPHONE_BLOCKED = {}
        if _NOPHONE_BLOCKED:
            _log(f"[oat] blocked-read retry state: {len(_NOPHONE_BLOCKED)} app(s) "
                 f"waiting on another try today")
    return _NOPHONE_BLOCKED


def _save_nophone_blocked() -> None:
    import json as _json
    try:
        with open(_nophone_blocked_path(), "w") as _fh:
            _json.dump(_load_nophone_blocked(), _fh, indent=0, sort_keys=True)
    except Exception as _e:  # noqa: BLE001
        _log(f"[oat] WARN could not persist blocked-read state: {_e}")


def _blocked_due(key: str) -> bool:
    """Is this blocked applicant ready for another try? True when we've never tried,
    when the cool-off has elapsed and attempts remain — False while it's cooling off
    (that's what keeps the walk from reopening the same resume every 5 minutes)."""
    rec = _load_nophone_blocked().get(key)
    if not rec:
        return True
    if int(rec.get("n", 0)) >= _BLOCKED_MAX_ATTEMPTS:
        return False
    try:
        last = dt.datetime.fromisoformat(str(rec.get("last")))
    except Exception:  # noqa: BLE001
        return True
    elapsed_min = (dt.datetime.now() - last).total_seconds() / 60.0
    return elapsed_min >= _BLOCKED_RETRY_AFTER_MIN


def _mark_nophone_blocked(key: str, reason: str) -> int:
    """Record one blocked attempt; returns the attempt count. On the last allowed
    attempt the applicant is promoted into the settled cache so later walks stop
    trying and the manual to-do post picks them up."""
    if not key:
        return 0
    state = _load_nophone_blocked()
    rec = state.get(key) or {"n": 0}
    rec["n"] = int(rec.get("n", 0)) + 1
    rec["last"] = dt.datetime.now().isoformat(timespec="seconds")
    rec["why"] = str(reason)[:80]
    state[key] = rec
    _save_nophone_blocked()
    if rec["n"] >= _BLOCKED_MAX_ATTEMPTS:
        _mark_nophone_checked(key)
    return rec["n"]


def _blocked_pending_count() -> int:
    """Applicants still owed a retry today (for the walk-diag proof row)."""
    return sum(1 for r in _load_nophone_blocked().values()
               if int((r or {}).get("n", 0)) < _BLOCKED_MAX_ATTEMPTS)


_ATTACHMENT_PROBE_JS = r"""
() => {
  const pick = (el) => ({
    tag: el.tagName,
    text: (el.innerText || el.value || '').trim().slice(0, 40),
    href: el.getAttribute('href') || '',
    src: el.getAttribute('src') || el.getAttribute('data') || '',
  });
  const out = { tabs: [], files: [], frames: [] };
  // Tab-like controls in the applicant panel: 'Resume', 'Attachment',
  // 'PDF Quick View' are what Megan's screenshot shows above the viewer.
  for (const el of document.querySelectorAll(
         'a,button,li,span,div[role=tab],input[type=button]')) {
    const t = (el.innerText || el.value || '').trim();
    if (/^(resume|attachment|attachments|pdf quick view|download)$/i.test(t)) {
      out.tabs.push(pick(el));
    }
  }
  // Anything that looks like the file itself.
  for (const el of document.querySelectorAll('a[href],embed[src],object[data],iframe[src]')) {
    const u = el.getAttribute('href') || el.getAttribute('src') || el.getAttribute('data') || '';
    if (/\.(pdf|docx?|rtf|txt)(\?|$)|attach|download|viewfile|getfile|resume/i.test(u)) {
      out.files.push(pick(el));
    }
  }
  for (const f of document.querySelectorAll('iframe,frame')) {
    out.frames.push((f.getAttribute('src') || '').slice(0, 140));
  }
  return out;
}
"""


# The walk's deadline, published so the EXPENSIVE work inside an applicant can
# see it too. run_walk checks between applicants, but one applicant can run for
# minutes — an attachment fetch, then Indeed with a Cloudflare wait, then a
# download — so a between-applicants check alone can overshoot the wrapper's
# SIGKILL by more than the headroom (2026-09-20, Raf's 11280: the 900s deadline
# passed at 18:30 and the walk was still mid-read at 18:34).
_WALK_DEADLINE = None            # monotonic seconds, or None when unbounded
# A resume read needs about this long in the bad case: attachment GET, Indeed
# tab, up to 40s of Cloudflare, a download and possibly OCR. With less than this
# left we do not START one — the applicant is simply flagged, unread and
# UNCACHED, so the next tick tries them properly.
RESUME_READ_RESERVE_S = int(os.environ.get("OAT_RESUME_READ_RESERVE_S", "150"))


def _walk_time_left():
    """Seconds left in this walk, or None when it has no deadline."""
    if _WALK_DEADLINE is None:
        return None
    return _WALK_DEADLINE - time.monotonic()


def _time_for_a_resume_read() -> bool:
    left = _walk_time_left()
    return left is None or left > RESUME_READ_RESERVE_S


# How long the FIRST resume read of a browser session waits for Indeed's
# Cloudflare check to clear itself, in ~1s polls. Every later read in the same
# session is not challenged at all (proven 2026-09-22, see lookup_resume_phone),
# so this is paid once per tick, not per applicant.
_CF_FIRST_READ_POLLS = int(os.environ.get("OAT_CF_FIRST_READ_POLLS", "150"))
# Set once anything has rendered in this browser session.
_CF_CLEARED = False
# Set when the session's first read never got past the check: the whole tick is
# walled, so the walk stops opening resumes instead of spending its budget (and
# each applicant's retries) on a gate that is closed for all of them.
_CF_WALLED = False
_CF_WALL_DETAIL = "cloudflare challenge never cleared"


def _cf_session_cleared() -> bool:
    return _CF_CLEARED


def _mark_cf_cleared() -> None:
    global _CF_CLEARED, _CF_WALLED
    _CF_CLEARED, _CF_WALLED = True, False


def _cf_walled() -> bool:
    return _CF_WALLED


def _mark_cf_walled(detail: str) -> None:
    """The session's opening challenge never cleared — every resume in this tick is
    behind the same gate, so say so ONCE, loudly enough for the Slack watcher to
    see it, and stop reading."""
    global _CF_WALLED, _CF_WALL_DETAIL
    if _CF_WALLED:
        return
    _CF_WALLED, _CF_WALL_DETAIL = True, detail
    _log(f"    [cf] CLOUDFLARE WALL — office {getattr(config, 'OFFICE_ID', '?')}: "
         f"Indeed's check never cleared for this browser session ({detail}); "
         f"skipping resume reads for the rest of this tick")


def reset_cf_session() -> None:
    """Forget the session's Cloudflare verdict. Called when a fresh browser session
    opens, so one tick's wall never silences the next tick's read."""
    global _CF_CLEARED, _CF_WALLED
    _CF_CLEARED, _CF_WALLED = False, False


def _rd_mod():
    """resume_download, imported lazily — it pulls in the PDF/OCR extractors and
    the walk must start even on a machine where those are missing."""
    from automations.oat_processing import resume_download as _rd
    return _rd


def _shot(pg, tag) -> None:
    """Diag screenshot (2026-09-23, Carlos: "get me a screenshot because you're
    screwing something up"). Only when OAT_SHOTS_DIR is set; never raises."""
    import os as _os
    d = _os.environ.get("OAT_SHOTS_DIR", "")
    if not d:
        return
    try:
        _os.makedirs(d, exist_ok=True)
        n = len([f for f in _os.listdir(d) if f.endswith(".png")]) + 1
        pg.screenshot(path=_os.path.join(d, "%02d-%s.png" % (n, tag)),
                      full_page=False)
        _log("    [shot] saved %02d-%s.png" % (n, tag))
    except Exception as e:  # noqa: BLE001
        _log("    [shot] failed (%s): %s" % (tag, type(e).__name__))


def _probe_attachment(page, a) -> None:
    """Log what resume surfaces THIS panel offers. Read-only; never raises.

    See config.ATTACHMENT_PROBE for why this exists. Runs across every frame,
    because the panel's viewer is itself framed and a top-document-only read is
    the mistake that has cost this walk twice already."""
    try:
        seen = {"tabs": [], "files": [], "frames": []}
        for fr in page.frames:
            try:
                d = fr.evaluate(_ATTACHMENT_PROBE_JS) or {}
            except Exception:  # noqa: BLE001
                continue
            for k in seen:
                for item in (d.get(k) or []):
                    if item and item not in seen[k]:
                        seen[k].append(item)
        _log("    [probe] %s %s — tabs=%s" % (a.first_name, a.last_name,
                                              seen["tabs"][:6]))
        _log("    [probe] files=%s" % (seen["files"][:6],))
        _log("    [probe] frames=%s" % (seen["frames"][:5],))
        # AND ACTUALLY READ IT. The real read is gated on `live`, which the
        # weekend quiet window blocks until Sunday 1PM — but the read itself is a
        # GET plus a parse, so the probe can prove end-to-end tonight that a real
        # number comes back, WITHOUT filling a field or sending anyone anywhere.
        try:
            _ph, _det = _rd_mod().phone_from_attachment(page)
            _log("    [probe] attachment read -> phone=%s (%s)" % (_ph, _det))
        except Exception as e:  # noqa: BLE001
            _log("    [probe] attachment read errored: %s: %s"
                 % (type(e).__name__, str(e)[:80]))
    except Exception as e:  # noqa: BLE001
        _log("    [probe] failed: %s: %s" % (type(e).__name__, str(e)[:80]))


def flag_no_phone(page, a: Applicant, live: bool) -> str:
    """No phone on file → first try to pull the real number off the applicant's
    Indeed resume (Megan's 'View resume' method, 2026-07-28). If found, fill it in
    and Send to AI (turns a dead-end into a real send). Only when the resume has no
    phone either do we flag as 'need to get number from Indeed'.

    Reads each applicant's resume AT MOST ONCE per day ONCE WE'VE ACTUALLY SEEN IT:
    a resume we read that carries no number is settled, and later walks skip it (just
    flag it fast) instead of reopening the same dead end.

    A read that was BLOCKED (Cloudflare never cleared, Indeed sign-in wall, the tab
    never opened) is NOT settled — we never saw the resume. Those get up to
    _BLOCKED_MAX_ATTEMPTS tries a day, _BLOCKED_RETRY_AFTER_MIN apart, then go to the
    manual to-do list. Before this split, a blocked read was filed as "no number" and
    the applicant was written off for the day: on 2026-08-25 that was 90 of 161
    flagged reads — the queue sat at 35 all day and only 9 applicants were sent."""
    if getattr(config, "ATTACHMENT_PROBE", False):
        _probe_attachment(page, a)
    key = _nophone_key(a)
    already_checked = key in _load_nophone_checked()
    cooling_off = (not already_checked) and (not _blocked_due(key))
    if already_checked or cooling_off:
        global _NOPHONE_SKIPS, _SETTLED_SKIPS
        _NOPHONE_SKIPS += 1
        _SETTLED_SKIPS += 1          # a page-turn, not a slot (see run_walk)
        _why = ("no resume number" if already_checked
                else f"blocked, retrying in <{_BLOCKED_RETRY_AFTER_MIN}min")
        _log(f"    already checked today ({_why}) — skip re-read: "
             f"{a.first_name} {a.last_name}")
    if (live and getattr(config, "AUTOMATE_PHONE_LOOKUP", False)
            and not already_checked and not cooling_off and _cf_walled()):
        # Indeed's check is closed for this whole browser session (the first read
        # proved it). Flag WITHOUT reading and WITHOUT caching or counting an
        # attempt: this applicant is not a confirmed no-number one, and the next
        # tick opens a fresh browser that usually gets straight in.
        _log(f"    [cf] session is walled — flagging unread (no attempt spent): "
             f"{a.first_name} {a.last_name}")
    elif (live and getattr(config, "AUTOMATE_PHONE_LOOKUP", False)
            and not already_checked and not cooling_off
            and not _time_for_a_resume_read()):
        # Out of tick. Flag WITHOUT reading and WITHOUT caching: an unread
        # applicant is not a confirmed no-number one, and the next tick must try
        # them properly rather than skip them as settled.
        _log(f"    no time left in this tick for a resume read — flagging "
             f"unread (next tick retries): {a.first_name} {a.last_name}")
    elif (live and getattr(config, "AUTOMATE_PHONE_LOOKUP", False)
            and not already_checked and not cooling_off):
        # THE ATTACHMENT ON THIS VERY PAGE COMES FIRST (2026-09-18). Megan, on an
        # applicant we had flagged as needing a number: "the number is right
        # there" — her screenshot showed the resume in AppStream's own Attachment
        # viewer carrying a cell number, while lookup_resume_phone was off
        # fighting Indeed, the one path that has been bot-blocked since August.
        # The panel carries a plain 'Download Attachment' href on the SAME origin
        # we are already signed in to, so this read needs no Indeed login, no
        # Cloudflare wait and no second tab. Indeed stays as the fallback for
        # applicants whose resume lives only there.
        phone, detail = None, ""
        try:
            phone, detail = _rd_mod().phone_from_attachment(page)
            if phone:
                _log(f"    \U0001f4ce attachment phone {phone} ({detail})")
            else:
                _log(f"    [attachment] {detail} — trying Indeed")
        except Exception as e:  # noqa: BLE001
            _log(f"    [attachment] errored ({type(e).__name__}) — trying Indeed")
            phone, detail = None, ""
        if not phone:
            try:
                phone, detail = lookup_resume_phone(page)
            except Exception as e:  # noqa: BLE001
                # Never saw the resume -> blocked (retryable), not a confirmed empty one.
                phone, detail = None, f"{_BLOCKED_PREFIX}read error: {type(e).__name__}"
        if phone and _fill_contact(page, phone):
            _log(f"    \U0001f4de resume phone {phone} → filled + sending: "
                 f"{a.first_name} {a.last_name} "
                 f"[panel email: {a.email or '(blank)'}]")
            try:
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(1500)   # let AS settle after the phone change
            # The holder-warmed session can leave the SMS widget open from a prior
            # re-text run, overlaying the panel so 'Send to AI' can't be clicked.
            # Close it before sending.
            _close_sms_panel(page)
            page.wait_for_timeout(600)
            try:
                diag = page.evaluate(
                    "() => ({ url: location.href.slice(-42),"
                    " smsOpen: !!document.querySelector('#sms_name_filter'),"
                    " hasSendToAI: /send to ai/i.test(document.body.innerText||''),"
                    " btns: [...document.querySelectorAll("
                    "'button,input[type=submit],input[type=button]')]"
                    ".map(e=>(e.innerText||e.value||'').trim()).filter(Boolean).slice(0,22) })")
                _log(f"    [phones] after-fill url=…{diag.get('url')} "
                     f"smsOpen={diag.get('smsOpen')} hasSendToAI={diag.get('hasSendToAI')} "
                     f"btns={diag.get('btns')}")
            except Exception as e:  # noqa: BLE001
                _log(f"    [phones] diag err: {type(e).__name__}")
            _outcome = do_send_ai(page, a, live)
            # A send that landed needs nothing more; a REMOVED record must not be
            # re-saved. Everything else leaves the applicant sitting in the queue
            # with a number we know and the record still showing blank — so put it
            # on the record, for the next walk and for the human who has to text
            # them. A navigating click here is nothing new: sends, removes and
            # re-texts all navigate, and the walk already carries on after them.
            if _outcome not in ("sent", "sent_override", "removed", "retext_removed"):
                if _persist_phone(page, phone):
                    _log(f"    \U0001f4be saved {phone} to the record "
                         f"(send was refused: {_outcome}) — no re-read next walk, "
                         f"and the number is there for the manual text: "
                         f"{a.first_name} {a.last_name}")
            return _outcome
        if _is_blocked_detail(detail):
            n = _mark_nophone_blocked(key, detail[len(_BLOCKED_PREFIX):])
            if n >= _BLOCKED_MAX_ATTEMPTS:
                # In the audit offices a resume page that will not open, even
                # after every retry, gets the applicant removed as INSUFFICIENT
                # CONTACT INFO — never "Duplicate", they are not one. (Carlos,
                # 2026-08-29, on Rashad's office: "if the page isn't opening for
                # those, can you choose a different removal reason?") Carlos's
                # and Atef's offices keep the leave-them rule.
                # BANNED 2026-09-13 (Carlos: "No one should be getting removed
                # for no contact info.") — the flag is ignored for EVERY office;
                # unreachable applicants stay in the queue and flag to a human.
                if False and getattr(config, "REMOVE_BLOCKED_READ", False):
                    if _perform_remove(page, NO_CONTACT_REASON):
                        _log(f"    \U0001f5d1 removed (resume page never opened "
                             f"after {n} tries — insufficient contact info): "
                             f"{a.first_name} {a.last_name}")
                        return "removed_no_contact"
                _log(f"    resume read BLOCKED ({detail}) — attempt "
                     f"{n}/{_BLOCKED_MAX_ATTEMPTS}, giving up for today → flag: "
                     f"{a.first_name} {a.last_name}")
            else:
                _log(f"    resume read BLOCKED ({detail}) — attempt "
                     f"{n}/{_BLOCKED_MAX_ATTEMPTS}, retrying in "
                     f"{_BLOCKED_RETRY_AFTER_MIN}min: "
                     f"{a.first_name} {a.last_name}")
        elif "no view-resume link" in str(detail):
            # No resume attached to the record at all — nothing to open, so there is
            # no number anywhere: panel blank AND no resume. Uncontactable.
            # BANNED 2026-09-13 (Carlos): no-contact-info removals are off for
            # every office, permanently — flag instead.
            if False and getattr(config, "REMOVE_NO_PHONE", False):
                if _perform_remove(page, NO_CONTACT_REASON):
                    _log(f"    \U0001f5d1 removed (no resume, no phone — "
                         f"insufficient contact info): {a.first_name} {a.last_name}")
                    return "removed_no_contact"
                _log(f"    remove-for-no-contact FAILED → flag: "
                     f"{a.first_name} {a.last_name}")
            else:
                _log(f"    no resume on file ({detail}) → flag + remember (won't "
                     f"re-check for "
                     f"{getattr(config, 'SETTLED_RECHECK_DAYS', 7)} days): "
                     f"{a.first_name} {a.last_name}")
                # SETTLE IT (2026-09-13). This branch was the only terminal path in
                # flag_no_phone that did NOT record a verdict, so an applicant with
                # no resume attached was re-decided on EVERY walk forever — and
                # each re-decision spends one of the run's MAX_PER_RUN work slots.
                #
                # In an office that leaves these people in the queue (11580 and
                # 11901, and 23467 since 9/12) they collect at the front, so once
                # there are 60 of them the walk burns its whole budget on the same
                # names every pass and never reaches anyone behind them. Measured
                # 2026-09-13: Carlos's queue 178 -> 185 across three walks with
                # flag_no_phone=60/60/62, ONE send and a no-number cache still
                # reading 0, while Atef — same code, same box, same hour — sent 28
                # and drained 113 -> 82. Megan: "it should be processing all apps."
                #
                # Settling it makes them page-turns instead of slots (see run_walk's
                # _SETTLED_SKIPS), which is exactly what the 2026-09-03 cap change
                # was built for — it just never fired here, because nothing ever
                # marked these applicants settled.
                #
                # Confirmed, not blocked: the code above already treats a missing
                # link as "panel blank AND no resume", distinct from a read we were
                # denied. It still re-checks on the SETTLED_RECHECK_DAYS cadence, so
                # a resume uploaded later, or a link we missed to a render race, is
                # picked up within the week rather than never.
                _mark_nophone_checked(key, confirmed=True)
        else:
            # The resume OPENED and genuinely carries no number. Confirmed
            # uncontactable — distinct from a blocked read, which is OUR failure and
            # must never cost an applicant their record (see _is_blocked_detail).
            # BANNED 2026-09-13 (Carlos): no-contact-info removals are off for
            # every office, permanently — flag instead.
            if False and getattr(config, "REMOVE_NO_PHONE", False):
                if _perform_remove(page, NO_CONTACT_REASON):
                    _log(f"    \U0001f5d1 removed (no phone on resume — "
                         f"insufficient contact info): {a.first_name} {a.last_name}")
                    return "removed_no_contact"
                _log(f"    remove-for-no-contact FAILED → flag: "
                     f"{a.first_name} {a.last_name}")
            else:
                _log(f"    no resume phone ({detail}) → flag + remember (won't "
                     f"re-read for "
                     f"{getattr(config, 'SETTLED_RECHECK_DAYS', 7)} days): "
                     f"{a.first_name} {a.last_name}")
            # CONFIRMED empty: the resume opened and carries no number. That
            # verdict holds across days — see config.SETTLED_RECHECK_DAYS.
            _mark_nophone_checked(key, confirmed=True)
    _NO_PHONE_ROWS.append([
        dt.date.today().isoformat(), a.first_name, a.last_name,
        a.email, a.job_board, a.position,
    ])
    _log(f"    flagged no-phone -> {config.NO_PHONE_FLAG_CSV}")
    return "flag_no_phone"


def _flush_csv(path, header, rows, label) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(header)
        w.writerows(rows)
    _log(f"[oat] wrote {len(rows)} {label} to {path}")


_ACTIVITY_ROWS: list = []


def _activity_csv(today: dt.date = None) -> str:
    today = today or dt.date.today()
    return f"output/oat-activity-{today.isoformat()}{config.FILE_SUFFIX}.csv"


def reset_activity() -> int:
    """Archive today's activity log + the flag queues so the scorecard restarts
    from a clean slate (e.g. after a day of manual testing polluted the log).
    Files are RENAMED to .bak (not deleted) so nothing is lost."""
    import shutil
    stamp = dt.datetime.now().strftime("%H%M%S")
    moved = []
    for path in (_activity_csv(), "output/oat-retext-queue.csv",
                 config.NO_PHONE_FLAG_CSV):
        if os.path.exists(path):
            bak = f"{path}.{stamp}.bak"
            try:
                shutil.move(path, bak)
                moved.append(os.path.basename(bak))
            except Exception as e:  # noqa: BLE001
                _log(f"[reset] could not archive {path}: {type(e).__name__}")
    _log(f"[reset] archived {len(moved)} file(s) -> {moved}; scorecard starts fresh")
    return 0


def reset_nophone_cache() -> int:
    """Archive TODAY's no-number caches for the active office so the next walk
    re-reads those resumes instead of skipping them.

    Needed whenever the reason a read failed gets fixed mid-day. The cache is
    deliberately sticky — it exists so we stop reopening the same dead-end resumes
    every five minutes — but that stickiness also pins in place any applicant who
    was written off for a reason that is no longer true. That is exactly what the
    2026-08-27 frame-blind read did: 24 of Atef's and 19 of Carlos's applicants
    were cached as "checked, no number" off a read that never opened the frame the
    number was in, and without this they would sit until the date-keyed cache
    rolled at midnight.

    Files are RENAMED to .bak, never deleted, and the in-process caches are
    dropped so a walk in this same process reloads from disk."""
    import shutil
    global _NOPHONE_CHECKED, _NOPHONE_BLOCKED, _NOTHREAD
    stamp = dt.datetime.now().strftime("%H%M%S")
    moved = []
    # The cross-day store is archived here too. This helper exists for the case
    # where the REASON a read failed has been fixed (the 2026-08-27 frame-blind
    # read wrote off 43 applicants between the two offices), and a stale verdict
    # that now outlives the day would otherwise pin those people for a week.
    for path in (_nophone_checked_path(), _nophone_blocked_path(),
                 _nophone_settled_path(), _nothread_path()):
        path = str(path)
        if os.path.exists(path):
            try:
                shutil.move(path, f"{path}.{stamp}.bak")
                moved.append(os.path.basename(path))
            except Exception as e:  # noqa: BLE001
                _log(f"[recheck] could not archive {path}: {type(e).__name__}")
    _NOPHONE_CHECKED = None
    _NOPHONE_BLOCKED = None
    _NOTHREAD = None
    _log(f"[recheck] cleared {len(moved)} no-number cache file(s) for office "
         f"{config.OFFICE_ID} -> {moved}; this walk re-reads those resumes")
    return len(moved)


def _flush_queues() -> None:
    _flush_csv(config.NO_PHONE_FLAG_CSV,
               ["flagged_date", "first_name", "last_name", "email", "job_board",
                "position"], _NO_PHONE_ROWS, "no-phone applicant(s)")
    _flush_csv("output/oat-retext-queue.csv",
               ["flagged_date", "first_name", "last_name", "email", "position",
                "phone", "days_since_contact"], _RETEXT_ROWS, "re-text applicant(s)")
    # Daily activity log — accumulates across every run of the day; the scorecard
    # reads the whole file and tallies.
    _flush_csv(_activity_csv(),
               ["time", "applicant", "source", "position", "action", "outcome",
                "reason"], _ACTIVITY_ROWS, "activity row(s)")


_DISPATCH = {
    Action.SEND_AI: do_send_ai,
    Action.OVERRIDE_SEND_AI: do_override_send_ai,
    Action.REMOVE_DUPLICATE: do_remove_duplicate,
    Action.REMOVE_FUTURE_INTERVIEW: do_remove_duplicate,  # same "remove" control
    Action.RETEXT_THEN_REMOVE: do_retext_then_remove,
    Action.FLAG_NO_PHONE: flag_no_phone,
}


# --------------------------------------------------------------------------- #
# Debug health check
# --------------------------------------------------------------------------- #
def health_check(page) -> None:
    """Dump the controls on the OAT page so we can fill the stubbed selectors.

    The remote `logtail` reader caps each read at ~470 chars, so we DON'T print a
    tall tree. Each category is joined with ' | ', split into <=380-char chunks,
    and every chunk gets a UNIQUE greppable tag ('HC BTN 0:', 'HC SEL 0:', ...).
    From the laptop: `lucy logtail oat_processing "HC INDEX"` for the counts, then
    `... "HC BTN 0"`, `"HC SEL 0"`, etc. to page each category cleanly."""
    info = page.evaluate(
        """() => {
            const txt = el => (el.innerText||el.value||'').replace(/\\s+/g,' ').trim();
            const uniq = a => [...new Set(a.filter(Boolean))];
            const btns = uniq([...document.querySelectorAll(
                "button, input[type=button], input[type=submit], a")]
                .map(e => txt(e).slice(0,45)).filter(t => t && t.length<=45));
            const sels = [...document.querySelectorAll('select')].map(s => {
                const opts = [...s.options].slice(0,12).map(o => txt(o).slice(0,30));
                return (s.name||s.id||'?') + '=[' + opts.join(',') + ']';
            });
            const inps = [...document.querySelectorAll('input,textarea')].map(i =>
                (i.name||i.id||'?') + ':' + (i.type||'text')
                + (i.value ? '(has-val)' : ''));
            // label -> the input in its row: the map read_current_applicant needs.
            const rows = [];
            [...document.querySelectorAll('td,th,label')].forEach(n => {
                const t = txt(n); if (!t || t.length>28) return;
                const row = n.closest('tr') || n.parentElement;
                const inp = row && row.querySelector('input,select,textarea');
                if (inp) rows.push(t.replace(/:$/,'') + '->' + (inp.name||inp.id||inp.type||'?'));
            });
            return {url: location.href, buttons: btns, selects: sels,
                    inputs: inps, rows: uniq(rows)};
        }"""
    )

    def emit(tag, items):
        joined = " | ".join(str(x) for x in items) or "(none)"
        chunks, cur = [], ""
        for piece in joined.split(" | "):
            if len(cur) + len(piece) + 3 > 380 and cur:
                chunks.append(cur); cur = ""
            cur += (" | " if cur else "") + piece
        if cur:
            chunks.append(cur)
        for i, ch in enumerate(chunks):
            _log(f"HC {tag} {i}: {ch}")
        return len(chunks)

    _log("=== OAT page health check ===")
    _log(f"HC url: {info.get('url')}")
    nb = emit("BTN", info.get("buttons", []))
    ns = emit("SEL", info.get("selects", []))
    ni = emit("INP", info.get("inputs", []))
    nr = emit("ROW", info.get("rows", []))
    _log(f"HC INDEX: BTN={nb} SEL={ns} INP={ni} ROW={nr} "
         f"(counts: buttons={len(info.get('buttons',[]))} "
         f"selects={len(info.get('selects',[]))} inputs={len(info.get('inputs',[]))} "
         f"rows={len(info.get('rows',[]))})")


_PHONE_RE = re.compile(r"\+?1?[\s\-.]*\(?\d{3}\)?[\s\-.]*\d{3}[\s\-.]*\d{4}")


def _view_resume_href(page):
    """Find the 'View resume →' link (in the Resume panel / embedded Indeed email,
    which may be an iframe) and return its href — the signed employers.indeed.com
    resume URL that shows the applicant's real phone (Megan 2026-07-28)."""
    for fr in page.frames:
        try:
            h = fr.evaluate(
                "() => { const a = [...document.querySelectorAll('a')].find("
                "e => /view\\s*resume/i.test(e.innerText||'') && /indeed/i.test(e.href||''));"
                " return a ? a.href : null; }")
            if h:
                return h
        except Exception:  # noqa: BLE001
            continue
    # fallback: any indeed candidates/resume link on the page
    for fr in page.frames:
        try:
            h = fr.evaluate(
                "() => { const a = [...document.querySelectorAll('a')].find("
                "e => /candidates\\/resume/i.test(e.href||'')); return a ? a.href : null; }")
            if h:
                return h
        except Exception:  # noqa: BLE001
            continue
    return None


def _view_resume_link(page):
    """Return (frame, locator) for the clickable 'View resume →' link, or (None, None)."""
    for xp in ("xpath=//a[contains(@href,'indeed') and contains(translate("
               "normalize-space(.),'VIEWRESUME','viewresume'),'view resume')]",
               "xpath=//a[contains(@href,'candidates/resume')]",
               "xpath=//a[contains(translate(normalize-space(.),'VIEWRESUME',"
               "'viewresume'),'view resume')]"):
        for fr in page.frames:
            try:
                loc = fr.locator(xp).first
                if loc.count() > 0:
                    return fr, loc
            except Exception:  # noqa: BLE001
                continue
    return None, None


# Logins this fleet browses AppStream/Indeed with. The resume viewer renders the
# logged-in account's address in its chrome, which is how carloshidalgo349
# ended up typed into an applicant record — twice. These can never be an
# applicant's email, no matter where they appear.
_FLEET_EMAILS = {
    "carloshidalgo349@gmail.com",
    "raffi127@gmail.com",
}


def _office_emails(page) -> set:
    """Addresses that must NEVER be written into an applicant record: the office
    inbox the application was sent to, whatever is already in the panel's email
    field, and the fleet's own logins. Read off the ORIGINAL p=604 page."""
    out = set(_FLEET_EMAILS)
    try:
        d = page.evaluate(_EXTRACT_JS) or {}
        for k in ("account", "email"):
            v = (d.get(k) or "").strip().lower()
            if "@" in v:
                out.add(v)
    except Exception:  # noqa: BLE001
        pass
    return out


def _rd_email(text: str) -> str:
    from automations.oat_processing.resume_download import email_from_text
    return email_from_text(text)


def lookup_resume_phone(page):
    """Open the applicant's Indeed resume and pull the first phone number. Prefer
    CLICKING the 'View resume' link (real gesture + referer + in-session nav — the
    way Megan opens it), which gets past Cloudflare where a cold page.goto now hits
    the 'Just a moment…' block (2026-08-02). Falls back to loading the signed href."""
    global _LAST_RESUME_EMAIL
    _LAST_RESUME_EMAIL = ""
    # DOWNLOAD FIRST (Carlos, 2026-09-20/23: "what if you download the resume?
    # when you open it on the right there's a download option"). The AppStream
    # attachment is a same-origin file fetched with the session cookies — NO
    # Cloudflare, nothing on screen moves — so it never hits the "Just a
    # moment…" wall the Indeed viewer does. Try it before touching the viewer;
    # only fall through to the Cloudflare-walled View-resume path when the panel
    # genuinely has no attachment.
    try:
        _aph, _adet = _rd_mod().phone_from_attachment(page)
    except Exception as _e:  # noqa: BLE001
        _aph, _adet = None, "attachment path errored: %s" % type(_e).__name__
    if _aph:
        _LAST_RESUME_EMAIL = getattr(_rd_mod(), "LAST_EMAIL", "") or ""
        _log("    \U0001f4ce phone from the DOWNLOADED attachment: %s (%s)"
             % (_aph, _adet))
        return _aph, "from attachment (%s)" % _adet[:60]
    _log("    [resume] no number from attachment (%s) — trying the viewer"
         % _adet[:60])
    _shot(page, "panel-no-attachment")
    fr, loc = _view_resume_link(page)
    href = _view_resume_href(page)
    if loc is None and not href:
        return None, "no view-resume link"
    newpg = None
    try:
        # Open the resume the way a HUMAN does — a REAL CLICK carries a user
        # gesture, and Cloudflare waves a user-gesture navigation through; the
        # old cold `goto(href)` fallback had no gesture, so Cloudflare challenged
        # EVERY one and it burned the full 40s wall (Carlos, 2026-09-20: "when
        # you right-click View Resume and open a new tab, it opens immediately,
        # no Cloudflare"). So: try a real click a few times; only cold-goto as a
        # LAST resort, and log it, because that's the path that stalls.
        for _attempt in range(3):
            if loc is None:
                break
            try:
                with page.context.expect_page(timeout=15000) as pi:
                    # Ctrl/Cmd+click = "open link in new tab" with a real gesture.
                    loc.click(timeout=8000, modifiers=["Meta"])
                newpg = pi.value
                break
            except Exception:  # noqa: BLE001
                # re-find the link (the panel may have re-rendered) and retry
                try:
                    _fr2, loc = _view_resume_link(page)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(600)
        # LAST resort only: the cold load that Cloudflare stops. Logged so we can
        # see when we're paying the 40s wall.
        if newpg is None and href:
            _log("    [resume] real-click failed — cold-loading href (Cloudflare "
                 "may wall this)")
            newpg = page.context.new_page()
            try:
                newpg.goto(href, wait_until="domcontentloaded", timeout=45000)
            except Exception:  # noqa: BLE001
                pass
        if newpg is None:
            # Neither the click nor the cold load produced a tab — the resume was
            # never seen, so this is retryable, not a confirmed empty resume.
            return None, f"{_BLOCKED_PREFIX}could not open resume tab"
        # Cloudflare's challenge JS only runs in a FOREGROUND tab (browsers throttle
        # background tabs), so bring the resume tab to front. OAT tab restored below.
        try:
            newpg.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        # employers.indeed.com throws a Cloudflare 'Just a moment…' interstitial;
        # patchright clears it if we wait. Poll until real content appears (title/
        # body no longer the challenge), THEN scan the WHOLE page for the phone —
        # it can be in the header ("City, ST ZIP | +1… | email") while the body
        # shows "[Información reservada]" (Megan 7/30: Yelitza + Cloudflare misses).
        # Fail fast: when the page DOES load (Cloudflare lenient) the phone renders
        # in a few seconds; when CF is blocking it never clears (verified 60s), so a
        # long wait just wastes ~1min/applicant. ~12s covers the good case.
        title, body = "", ""
        # 40s, up from 12 (2026-09-17): Cloudflare's interstitial still clears
        # on its own but now takes ~15-30s fleet-wide; at 12s every resume read
        # in every office reported "challenge never cleared" (Carlos: 296
        # walked, 0 sent). A read that clears returns the moment it finds the
        # number, so the higher ceiling is free on healthy days.
        #
        # THE FIRST READ OF A SESSION PAYS FOR ALL OF THEM (2026-09-22). Measured
        # on Lucy 4, office 11280: Indeed challenges the FIRST resume a browser
        # opens and, once that one is past, every later resume in the SAME
        # browser renders immediately — 6 of 6, no second challenge. So the
        # challenge is per-session, not per-applicant, and the 40s ceiling was
        # being applied to the only read that ever needed more: an untouched
        # challenge cleared itself at ~40s, i.e. right at the edge, and when it
        # missed, the tick relaunched Chrome and met a brand-new challenge. That
        # is how every office logged 0 numbers filled on 2026-09-22 while
        # yesterday's identical code filled 40+ each.
        #
        # So: give the session's FIRST read a long ceiling, and once anything has
        # rendered, drop back to 40s (the rest of the session is not challenged,
        # so a slow read there is a slow resume, not a challenge).
        _first_of_session = not _cf_session_cleared()
        _polls = _CF_FIRST_READ_POLLS if _first_of_session else 40
        if _first_of_session:
            _log(f"    [cf] first resume read of this session — waiting up to "
                 f"{_polls}s for Indeed's check to clear itself")
        for _i in range(_polls):
            try:
                title = (newpg.title() or "").lower()
                # READ THE FRAMES TOO, not just the top document. Indeed's resume
                # viewer renders the resume itself in a nested frame; the TOP page
                # holds only the viewer chrome ("<Name>'s Resume", "View candidate",
                # nav, footer). That chrome is real text and comfortably over the
                # blocked-read length floor, so a frame-blind read looked like a
                # page that loaded fine and simply had no number on it — and every
                # such applicant was written off for the day as "no phone on
                # resume" while a human opening the same link saw the number in the
                # header immediately (Megan 2026-08-27: Carlos Nevarez, office
                # 23467, "(303) 710-6301 ... his number is right there"). It was not
                # rare: 24 of Atef's and 19 of Carlos's applicants sat in that state
                # that morning alone. _view_resume_href already walks page.frames to
                # FIND this link — only the reader was frame-blind.
                #
                # Top document FIRST so a resume whose number is in the main
                # document keeps resolving exactly as it did before; frames are
                # only consulted when that finds nothing. Ordering matters beyond
                # compatibility: résumés list former employers' phone numbers in the
                # work history, and the applicant's own number is in the header, so
                # first-match-nearest-the-top is what keeps us texting the candidate
                # rather than one of their old bosses.
                texts = []
                try:
                    texts.append(newpg.evaluate(
                        "() => (document.body.innerText || '')") or "")
                except Exception:  # noqa: BLE001
                    texts.append("")
                for _fr in newpg.frames:
                    try:
                        t = _fr.evaluate("() => (document.body.innerText || '')")
                    except Exception:  # noqa: BLE001
                        continue    # cross-origin / detached frame — skip, not fatal
                    if t and t not in texts:
                        texts.append(t)
                # `body` stays the ALL-FRAMES text: it is what the challenge check
                # and _blocked_reason below judge, and judging those on the chrome
                # alone is the same blindness one level down.
                body = "\n".join(texts)
            except Exception:  # noqa: BLE001
                title, body, texts = "", "", []
            challenged = ("just a moment" in title or "just a moment" in body.lower()
                          or "verify you are human" in body.lower())
            if not challenged and body:
                # Past the gate. Remember it for the REST of this browser session:
                # later reads need no long wait, and a later block is a real block
                # rather than the session's opening challenge.
                _mark_cf_cleared()
                for _t in texts:
                    for m in _PHONE_RE.finditer(_t):
                        digits = re.sub(r"\D", "", m.group(0))
                        if 10 <= len(digits) <= 11:     # a real US number
                            # Email ONLY when it sits right next to the phone
                            # (same contact header, within ~300 chars). "Same
                            # frame" was NOT enough: the resume tab's top
                            # document holds the viewer chrome AND the content,
                            # so the LOGGED-IN Indeed account's address (the
                            # office owner's own gmail) shared a block with the
                            # phone and got typed into Moises Santamaria's
                            # record TWICE (Carlos, 2026-08-29). Proximity plus
                            # the hard blocklist, or no email at all.
                            _near = _t[max(0, m.start() - 300):m.end() + 300]
                            _cand = _rd_email(_near)
                            _LAST_RESUME_EMAIL = (
                                "" if _cand.lower() in _office_emails(page)
                                else _cand)
                            return (m.group(0).strip(),
                                    f"from resume ({newpg.url[:50]})")
            newpg.wait_for_timeout(1000)
        # The poll ran out. Two VERY different endings look identical from here, and
        # calling both "no phone" is what burned 90 applicants on 2026-08-25:
        #   (a) the resume really rendered and has no number  -> settled, don't re-read
        #   (b) the page never rendered — Cloudflare's 'Just a moment…' never cleared,
        #       or we got the 'Indeed for Employers' sign-in wall -> BLOCKED, transient
        # Say which, so the caller can retry (b) later instead of writing the applicant
        # off for the whole day. See _BLOCKED_PREFIX.
        reason = _blocked_reason(title, body)
        _shot(newpg, "viewer-" + ("blocked" if reason else "no-number"))
        if reason and _first_of_session:
            # The session never got in. Wall the tick (see _mark_cf_walled) rather
            # than letting every remaining applicant spend a retry on the same gate:
            # on 2026-09-22 that turned ONE closed gate into 162 "blocked" reads and
            # 57 people written off for the day in Raf's office alone.
            _mark_cf_walled(reason)
        if reason:
            return None, f"{_BLOCKED_PREFIX}{reason} (title={newpg.title()[:40]!r})"

        # LAST RESORT BEFORE ANY VERDICT: the viewer sometimes renders blank but
        # offers "Download original message" — the number is in that file, and a
        # human just clicks it (Carlos 2026-08-27). A page we could not READ is
        # not a resume without a number, so try the download before concluding
        # anything, and treat every failure of it as BLOCKED (retryable, the
        # applicant stays put) rather than as a confirmed-empty resume. Carlos's
        # rule: "If that doesn't work, then just leave it there. Don't remove
        # that applicant."
        try:
            from automations.oat_processing import resume_download as _rd
            _dl_phone, _dl_detail = _rd.download_and_read_phone(newpg)
        except Exception as _e:  # noqa: BLE001
            _dl_phone, _dl_detail = None, f"download path errored: {type(_e).__name__}"
        if _dl_phone:
            _cand = (getattr(_rd, "LAST_EMAIL", "") or "").strip()
            _LAST_RESUME_EMAIL = ("" if _cand.lower() in _office_emails(page)
                                  else _cand)
            _log(f"    \U0001f4c4 phone from the DOWNLOADED resume: {_dl_phone} "
                 f"({_dl_detail})")
            return _dl_phone, f"from downloaded resume ({_dl_detail[:60]})"
        if "no download link" not in _dl_detail:
            # There WAS something to download and it still did not yield a number.
            # Deliberately BLOCKED, not "no phone": we never actually read a
            # rendered resume, so this must never cost the applicant their record.
            return None, (f"{_BLOCKED_PREFIX}blank viewer; download attempted "
                          f"({_dl_detail[:70]})")
        return None, f"no phone on resume (title={newpg.title()[:40]!r})"
    except Exception as e:  # noqa: BLE001
        # An exception means we never got a clean look at the resume — transient by
        # definition, so it's blocked (retryable), not a confirmed empty resume.
        return None, f"{_BLOCKED_PREFIX}resume open err: {type(e).__name__}"
    finally:
        if newpg:
            try:
                newpg.close()
            except Exception:  # noqa: BLE001
                pass
        # Restore the OAT tab to the foreground — the new resume tab backgrounded
        # it, which left 'Send to AI' unclickable afterward.
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass


def probe_resume(page) -> None:
    """Diagnostic: on the current (no-phone) applicant, find the View-resume link,
    open the resume, and dump what we can pull — to validate the phone-lookup."""
    a = read_current_applicant(page)
    _log(f"[resume] current: {a.first_name} {a.last_name} phone={a.phone!r} "
         f"cell={a.cell_phone!r}")
    href = _view_resume_href(page)
    _log(f"[resume] view-resume href: {str(href)[:110]}")
    if href:
        # Also stash the FULL url to a Sheet cell so it can be opened/tested in a
        # real browser (Cloudflare-passing) — the 'route through your browser' path.
        try:
            from automations.recruiting_report import fill as _fill
            sh = _fill._client().open_by_key(
                "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
            try:
                wsx = sh.worksheet("OAT_Resume_URL")
            except Exception:  # noqa: BLE001
                wsx = sh.add_worksheet(title="OAT_Resume_URL", rows=10, cols=3)
            wsx.update([["name", "resume_url"],
                        [f"{a.first_name} {a.last_name}", href]], "A1",
                       value_input_option="RAW")
            _log("[resume] wrote full url to tab OAT_Resume_URL")
        except Exception as e:  # noqa: BLE001
            _log(f"[resume] url-write err: {type(e).__name__}")
    if not href:
        # dump anchor texts across frames for diagnosis
        for i, fr in enumerate(page.frames):
            try:
                anchors = fr.evaluate(
                    "() => [...document.querySelectorAll('a')].map(e=>"
                    "(e.innerText||'').trim().slice(0,24)).filter(Boolean).slice(0,20)")
                if anchors:
                    _log(f"[resume] frame {i} anchors: {anchors}")
            except Exception:  # noqa: BLE001
                continue
        return
    phone, detail = lookup_resume_phone(page)
    _log(f"[resume] RESULT phone={phone!r} :: {detail}")


def _open_sms_panel(page) -> bool:
    """Click the always-on 'SMS' button (top-right). Its text is 'SMS' + an unread
    badge number ('SMS\\n13'), so match the anchor whose text is 'SMS' once digits
    are stripped — excludes 'SMS/Email', 'SMS Templates', 'SMS List Report'."""
    _excl = ("not(contains(.,'/')) and not(contains(.,'List')) and "
             "not(contains(.,'Templates')) and not(contains(.,'Report')) and "
             "not(contains(.,'Email'))")
    for xp in (f"xpath=//a[starts-with(normalize-space(.),'SMS') and {_excl}]",
               f"xpath=//span[starts-with(normalize-space(.),'SMS') and {_excl}]/ancestor::a[1]",
               f"xpath=//*[@role='button'][starts-with(normalize-space(.),'SMS') and {_excl}]"):
        try:
            loc = page.locator(xp).first
            if loc.count() > 0:
                loc.click(timeout=6000, no_wait_after=True)
                _log(f"[sms] opened SMS panel via {xp[:55]}")
                page.wait_for_timeout(4000)
                return True
        except Exception as e:  # noqa: BLE001
            _log(f"[sms] click attempt failed: {type(e).__name__}")
            continue
    return False


def probe_sms(page) -> None:
    """Open the always-on SMS panel (top-right 'SMS' button — a Bandwidth widget)
    and dump its structure (frames, inputs, buttons, textareas) so we can wire the
    re-text send flow: search phone -> Load Template 'FOR LUCY' -> fill -> Send."""
    clicked = _open_sms_panel(page)
    if not clicked:
        try:
            cands = page.evaluate(
                "() => [...document.querySelectorAll('a,button,div,span')]"
                ".filter(e=>/^SMS/i.test((e.innerText||'').trim()))"
                ".map(e=>e.tagName+\":'\"+(e.innerText||'').trim().slice(0,20)+\"'\").slice(0,20)")
            _log(f"[sms] SMS button not found; candidates: {cands}")
        except Exception as e:  # noqa: BLE001
            _log(f"[sms] SMS button not found; probe err {e}")
        return
    page.wait_for_timeout(4500)
    _log(f"[sms] frames after open: {len(page.frames)}")
    for i, fr in enumerate(page.frames):
        try:
            info = fr.evaluate(
                """() => ({
                    url: (location.href||'').slice(0,90),
                    inputs: [...document.querySelectorAll('input')]
                        .map(e=>(e.name||e.id||e.placeholder||e.type||'?')).slice(0,30),
                    buttons: [...document.querySelectorAll('button,input[type=button],input[type=submit],a')]
                        .map(e=>(e.innerText||e.value||'').trim()).filter(t=>t&&t.length<28).slice(0,30),
                    textareas: [...document.querySelectorAll('textarea')]
                        .map(e=>(e.name||e.id||e.placeholder||'?')),
                })""")
            if info.get("inputs") or info.get("textareas") or (
                    info.get("buttons") and any("Send" in b or "Template" in b
                                                for b in info.get("buttons", []))):
                _log(f"SMS FRAME {i} url={info.get('url')}")
                _log(f"SMS FRAME {i} inputs={info.get('inputs')}")
                _log(f"SMS FRAME {i} buttons={info.get('buttons')}")
                _log(f"SMS FRAME {i} textareas={info.get('textareas')}")
                # Focused, short-line dump of the send-flow controls (logtail
                # caps ~470 chars/read, so keep each line small & greppable).
                try:
                    # Try to expand a "Load Template" control first so the
                    # template list (where 'FOR LUCY' lives) enters the DOM.
                    for tsel in ("a", "button"):
                        el = fr.query_selector(
                            f"xpath=//{tsel}[contains(translate(.,"
                            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                            "'template')]")
                        if el:
                            try:
                                el.click(timeout=2500)
                                page.wait_for_timeout(1200)
                            except Exception:  # noqa: BLE001
                                pass
                            break
                    focus = fr.evaluate(
                        """() => {
                            const g = s => (s.name||s.id||s.placeholder||'?');
                            return {
                              sels: [...document.querySelectorAll('select')].map(s =>
                                g(s)+':['+[...s.options].map(o=>(o.text||'').trim())
                                .filter(Boolean).slice(0,15).join('|')+']').slice(0,8),
                              tmpl: [...document.querySelectorAll('a,button,li,option,div')]
                                .map(e=>(e.innerText||e.value||'').trim())
                                .filter(t=>/lucy|template/i.test(t)&&t.length<40).slice(0,15),
                              send: [...document.querySelectorAll(
                                'a,button,input[type=submit],input[type=button]')]
                                .filter(e=>/^send/i.test((e.innerText||e.value||'').trim()))
                                .map(e=>e.tagName+':'+(e.name||e.id||'')+':'
                                  +(e.innerText||e.value||'').trim()).slice(0,8),
                              msg: [...document.querySelectorAll('textarea,[contenteditable]')]
                                .map(e=>(e.name||e.id||e.placeholder||e.tagName||'?')).slice(0,8),
                            };
                        }""")
                    _log(f"SMSF sels={focus.get('sels')}")
                    _log(f"SMSF tmpl={focus.get('tmpl')}")
                    _log(f"SMSF send={focus.get('send')}")
                    _log(f"SMSF msg={focus.get('msg')}")
                except Exception as e:  # noqa: BLE001
                    _log(f"SMSF focus err: {type(e).__name__}")
        except Exception as e:  # noqa: BLE001
            _log(f"SMS FRAME {i} err: {type(e).__name__}")

    # The name= fields (sms_name_filter/sms_date_filter) turned out to be HIDDEN
    # backing fields (page.fill timed out on them). Dump the VISIBLE widget
    # controls (what a user actually types into) so we target those instead.
    try:
        vis = page.evaluate(
            r"""() => {
                const seen = e => { const r = e.getBoundingClientRect();
                    return e.offsetParent !== null && r.width > 2 && r.height > 2; };
                const lbl = e => {
                    let p = e.previousElementSibling;
                    let t = (p && (p.innerText||'').trim()) || '';
                    if (!t && e.closest('label')) t = e.closest('label').innerText||'';
                    return t.replace(/\s+/g,' ').slice(0, 18);
                };
                const inps = [...document.querySelectorAll('input')].filter(seen)
                    .filter(e => !/hidden/.test(e.type))
                    .map(e => `${e.type}|${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,14)}|L:${lbl(e)}`)
                    .slice(0, 16);
                const sels = [...document.querySelectorAll('select')].filter(seen)
                    .map(e => `${e.name||e.id||'?'}|L:${lbl(e)}|opts:${[...e.options].map(o=>(o.text||'').trim()).slice(0,7).join(',')}`)
                    .slice(0, 8);
                const tas = [...document.querySelectorAll('textarea')].filter(seen)
                    .map(e => `${e.name||e.id||'?'}|ph:${(e.placeholder||'').slice(0,20)}`).slice(0, 6);
                const btns = [...document.querySelectorAll('button,input[type=button],input[type=submit],a')]
                    .filter(seen).map(e => `${(e.innerText||e.value||'').trim().slice(0,20)}#${e.id||''}`)
                    .filter(t => t && t.length < 26).slice(0, 24);
                return {inps, sels, tas, btns};
            }""")
        for tag, arr in (("VISW inp", vis.get("inps")), ("VISW sel", vis.get("sels")),
                         ("VISW ta", vis.get("tas")), ("VISW btn", vis.get("btns"))):
            for item in (arr or []):
                _log(f"{tag} :: {item}")
    except Exception as e:  # noqa: BLE001
        _log(f"VISW dump err: {type(e).__name__}")
    # Hunt for a 'new conversation / compose' control (icon buttons often carry it
    # in title/aria-label/class, not visible text).
    try:
        nc = page.evaluate(
            r"""() => {
                const hint = e => ((e.innerText||'')+' '+(e.title||'')+' '
                    +(e.getAttribute('aria-label')||'')+' '+(e.className||'')+' '+(e.id||''));
                return [...document.querySelectorAll('a,button,i,span,div,[role=button]')]
                    .filter(e => /new|compose|create|start|pencil|plus|\+|newmsg|new-msg/i.test(hint(e)))
                    .filter(e => (e.innerText||e.title||e.getAttribute('aria-label')||e.className||'').length < 70)
                    .map(e => `${e.tagName}|t:${(e.innerText||'').trim().slice(0,14)}|ttl:${(e.title||'').slice(0,22)}|al:${(e.getAttribute('aria-label')||'').slice(0,22)}|cls:${(e.className||'').slice(0,28)}|id:${(e.id||'').slice(0,20)}`)
                    .slice(0, 22);
            }""")
        for x in nc:
            _log(f"NEWCONV :: {x}")
        if not nc:
            _log("NEWCONV :: (none matched)")
    except Exception as e:  # noqa: BLE001
        _log(f"NEWCONV err: {type(e).__name__}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def office_on_page(page):
    """Which office the ATS page is CURRENTLY showing, or None if we can't tell.

    The OAT header renders "Office ID: 23467   Owner: Atef Choudhury". That string
    is the only trustworthy statement of whose queue we are about to act on."""
    body = _body(page)
    m = re.search(r"office\s*id\s*:?\s*([0-9]{3,6})", body)
    return m.group(1) if m else None


# Which condition the guard refused on. Read by the callers to tag the walk's
# outcome, so the diag tab says WHICH and nobody has to go log-hunting for it.
_LAST_OFFICE_GUARD = ""


def _guard_office_now(page, action: str) -> bool:
    """Re-check the on-page 'Office ID:' banner IMMEDIATELY before any mutating
    click. The walk-start check is not enough: another automation sharing the
    browser can switch offices mid-walk (Carlos, 2026-08-30, after captain-login
    sends appeared in Vincent's office 23318 that nobody could account for —
    "before hitting Send to AI you should be checking at the top to see the
    office ID"). FAILS CLOSED: mismatch or unreadable header refuses the action.

    TWO CONDITIONS, AND THEY MEAN DIFFERENT THINGS (2026-09-13). Khalil's office
    logged office_guard_refused=14 in one walk while another session was
    hand-running a live push on the same office, and the single outcome tag could
    not say which had happened:

      * WRONG OFFICE — the banner names a different office. Something really did
        switch this session underneath us. That is the irreversible-send hazard.
      * UNREADABLE — no "Office ID:" in the body at all. The page is not what we
        think it is (mid-render, an error page, a lost session). Refusing is
        still right, but it is not evidence of a crossed session.

    Both still refuse. `_LAST_OFFICE_GUARD` records which, so the walk can tag the
    outcome and the diag tab answers the question on its own."""
    global _LAST_OFFICE_GUARD
    want = str(getattr(config, "OFFICE_ID", "") or "")
    got = office_on_page(page)
    if want and got == want:
        _LAST_OFFICE_GUARD = ""
        return True
    if got is None:
        _LAST_OFFICE_GUARD = "unreadable"
        _log(f"    ⛔ OFFICE GUARD: no 'Office ID:' on the page at all (expected "
             f"{want!r}) — REFUSING {action}. The page is not what we think it "
             f"is; this is NOT evidence of another automation.")
    else:
        _LAST_OFFICE_GUARD = "wrong_office"
        _log(f"    ⛔ OFFICE GUARD: page shows office {got!r}, expected {want!r} "
             f"— REFUSING {action}. Another automation switched this session.")
    return False


def _office_guard_outcome() -> str:
    """The outcome tag for the refusal that just happened, e.g.
    'office_guard_wrong_office'. Falls back to the old flat tag if somehow
    unset, so a refusal is never recorded as a success."""
    return "office_guard_" + (_LAST_OFFICE_GUARD or "refused")


def assert_on_expected_office(page, tries: int = 3) -> bool:
    """Refuse to work a queue that is not the office we were told to work.

    WHY THIS HAS TO EXIST: the office switch happens once, when the session opens.
    `run_walk` — the thing that actually SENDS, REMOVES and TEXTS — never checked
    which office it had landed on. The standalone `run()` path aborts on a failed
    switch; the applicant_push path we actually run does not, so a switch that
    silently did not take would have this walk process someone else's applicants,
    irreversibly, every ten minutes. That hole was harmless while one office was
    ever worked; it stopped being harmless the day a second office was added
    (2026-08-26) and the session started switching between them.

    FAILS CLOSED. A mismatch aborts, and so does a header we cannot read after a
    few tries — "I don't know whose queue this is" is not a licence to send. The
    header is on the OAT page in every screenshot we have, so an unreadable one
    means the page is not what we think it is, which is exactly when to stop."""
    want = str(config.OFFICE_ID)
    seen = None
    for _ in range(tries):
        seen = office_on_page(page)
        if seen == want:
            return True
        if seen is not None:
            _log(f"[oat] ABORT: this page is office {seen}, expected {want} — "
                 f"refusing to process another office's applicants")
            return False
        page.wait_for_timeout(700)   # header may still be rendering
    _log(f"[oat] ABORT: could not read an Office ID off the page (expected "
         f"{want}) — refusing to act on a queue we cannot identify")
    return False


def run_walk(page, live: bool = False, limit: int = None,
             max_actions: int = None, today=None) -> int:
    """Walk the One-App-at-a-time queue on an ALREADY-OPEN, logged-in, office-11580
    page and process every applicant (read → classify → send/remove/re-text/flag).

    This is the live cleanup core, factored out of ``run`` so it can run on EITHER
    session: the standalone patchright session ``run`` opens, or the shared
    real-Chrome/CDP page the ``applicant_push`` merge hands over after the batch
    stage. The caller is responsible for having attached the dialog-accept handlers
    and switched to office 11580 before calling this (``run`` does both above; the
    orchestrator does the same on the CDP page).

    Returns 0 on a normal walk, 2 if the OAT page can't be opened."""
    if today is None:
        today = dt.date.today()
    limit = limit if limit is not None else config.MAX_PER_RUN

    if not open_oat(page):
        _log("[oat] FATAL: could not open the One-App-at-a-time page")
        return 2

    # WHOSE queue is this? Checked BEFORE a single applicant is read, because
    # everything past this point sends, removes or texts a real person.
    if not assert_on_expected_office(page):
        return 2

    if os.environ.get("OAT_WALK_FROM_END") == "1":
        if jump_to_last(page):
            page.wait_for_timeout(2000)
            _log("[oat] WALK_FROM_END: jumped to the last applicant; walking backward")
        else:
            _log("[oat] WALK_FROM_END requested but no jump-to-last control found")
    _start_total = getattr(read_current_applicant(page, today), "_total", None)
    # Log the URL with the pager count. The count comes from the PAGE's own
    # "<page> of <N> Emails", so it is only ever the total for the view we happen
    # to be on — and that view carries filters (numDays / matchedOnly / job board
    # / entered-date) that we never set and do not control. On 2026-08-27 the
    # walk reported "13 -> 0" for Carlos while his actual inbox held 15, so the
    # bot's idea of "the queue" and the human's disagree, and until we can SEE the
    # filter state we cannot tell which is right. Cheap to log, and it is the one
    # fact that settles it.
    try:
        _oat_url = (page.url or "")[-120:]
    except Exception:  # noqa: BLE001
        _oat_url = "?"
    _log(f"[oat] QUEUE at start: {_start_total} emails | view: {_oat_url}")

    _ONLY_NAMES = _load_only_names()
    if _ONLY_NAMES is not None:
        _log(f"[oat] ALLOWLIST active: only {len(_ONLY_NAMES)} named applicant(s) "
             f"will be touched; everyone else is skipped untouched")
    processed = 0               # applicants READ this walk (coverage)
    # `limit` caps applicants we actually WORK, not applicants we look at. A
    # settled case (resume already read today and it had no number; no reachable
    # SMS thread) is handled by a cache hit and a page-turn — no resume opened, no
    # widget, no mutation — so charging it a slot only shortened our reach. On
    # 2026-09-03 that is exactly what it did: Atef's queue was 104, ~50 of every
    # 60 slots went to settled skips, and applicants 61-104 were never read once
    # in 74 walks. Now settled skips are free and `worked` is what the cap counts.
    worked = 0                  # applicants that consumed a real slot
    touch_cap = max(limit, getattr(config, "MAX_TOUCH_PER_RUN", 300))
    global _SETTLED_SKIPS
    _SETTLED_SKIPS = 0
    actions = 0                 # live mutations (sent/removed) this run
    MUTATIONS = ("sent", "sent_override", "removed")
    # Fresh browser, fresh Cloudflare verdict: this walk opens its own Chrome, so
    # neither a previous tick's clearance nor its wall carries over.
    reset_cf_session()
    counts: dict = {}
    seen: set = set()          # applicant keys already handled this run
    no_progress = 0            # consecutive already-seen reads (end guard)
    # Was the LAST applicant we handled a send/remove? If so, the blank reads that
    # follow are the ATS list re-rendering, not an empty queue — see
    # config.POST_MUTATION_STRIKES.
    after_mutation = False
    # CURRENT snapshot of who's still flagged (needs a human) THIS walk — the
    # noon/4pm Slack post reads this, NOT the day-cumulative activity log, so the
    # counts match what's actually in the queue right now (Megan 2026-08-06: the
    # cumulative log over-counted apps already handled since).
    flagged_now = {"nophone": [], "retext": []}
    # See config.MAX_WALK_SECONDS: stop under our own power before the wrapper's
    # SIGKILL, so the snapshot and the diag row still get written.
    # Two clocks, and we stop at whichever runs out first: our own budget from
    # here, and the wrapper's absolute wall-clock deadline (which also covers the
    # Chrome launch, login and office switch that happened before this function
    # was ever called). Expressed as SECONDS REMAINING so they are comparable.
    _budget_s = (config.MAX_WALK_SECONDS
                 if getattr(config, "MAX_WALK_SECONDS", 0) > 0 else None)
    _wall = getattr(config, "WALK_DEADLINE_EPOCH", 0) or 0
    if _wall > 0:
        _left = _wall - time.time()
        _budget_s = _left if _budget_s is None else min(_budget_s, _left)
        _log(f"[oat] walk deadline: {int(_left)}s left of the wrapper's tick "
             f"(own budget {config.MAX_WALK_SECONDS}s)")
    _walk_deadline = (time.monotonic() + _budget_s) if _budget_s is not None else None
    global _WALK_DEADLINE
    _WALK_DEADLINE = _walk_deadline
    _out_of_time = False
    while worked < limit and processed < touch_cap:
        if _walk_deadline is not None and time.monotonic() >= _walk_deadline:
            _out_of_time = True
            _log(f"[oat] {config.MAX_WALK_SECONDS}s walk budget reached — "
                 f"stopping cleanly after {processed} read / {worked} worked "
                 f"(the next tick picks up where this left off)")
            break
        a = read_current_applicant(page, today)
        key = f"{a.email}|{a.first_name} {a.last_name}".strip().lower()
        # Walk logic that survives the queue shifting under us: after a
        # REMOVE/SEND the app leaves its slot, so the NEXT app becomes
        # current (fresh key → handled below, no Next needed); after a
        # non-mutation the SAME app stays current, so we page Next to move
        # past it. Stop only when we can't reach a fresh applicant (the
        # true end), not on the first re-seen one.
        if not key or key == "|" or key in seen:
            no_progress += 1
            # With an allowlist active, paging through junk is NORMAL: Rafael's
            # office (11280) fronts its 777-email queue with nameless AD-receipt
            # records, and the 4-strike guard called that "end of queue after 0
            # processed" — twice (2026-08-30). Give the walk room to pass them;
            # a real end still trips the guard, just later.
            if _ONLY_NAMES is not None:
                _strikes = 40
            elif after_mutation:
                # We just sent or removed someone; the list is re-rendering and
                # the current-applicant read comes back blank or as the person we
                # just handled. Reading that as "the queue ended" cost seven of
                # Carlos's walks on 2026-09-04 — each stopped after ONE applicant
                # against a queue of eight.
                _strikes = getattr(config, "POST_MUTATION_STRIKES", 8)
            else:
                _strikes = getattr(config, "END_OF_QUEUE_STRIKES", 3)
            if no_progress > _strikes:
                _log(f"[oat] no fresh applicants ({no_progress} blank/seen reads"
                     + (" after a mutation" if after_mutation else "")
                     + f") — end of queue after {processed} processed")
                break
            if not advance_to_next(page):
                _log(f"[oat] no next control — end of queue after "
                     f"{processed} processed")
                break
            if after_mutation:
                # Give the re-render room before looking again, or the extra
                # strikes just burn through at full speed and buy nothing.
                page.wait_for_timeout(
                    getattr(config, "POST_MUTATION_SETTLE_MS", 700))
            continue
        no_progress = 0
        after_mutation = False   # we reached a fresh applicant; re-render is over
        seen.add(key)
        # OPTIONAL ALLOWLIST (OAT_ONLY_NAMES=/path/to/names.txt, one name per
        # line). When set, every applicant NOT on the list is skipped without a
        # single mutation — the walk still pages past them. Added 2026-08-29 so a
        # restore-and-push audit can touch ONLY the applicants it restored: the
        # office's other queued applicants belong to that office's own schedule
        # and must not be pushed as a side effect of an audit.
        if _ONLY_NAMES is not None:
            _nm = f"{a.first_name} {a.last_name}".strip().lower()
            if _norm_name(_nm) not in _ONLY_NAMES:
                _log(f"[skip] not on the allowlist: {_nm}")
                if not advance_to_next(page):
                    break
                continue
        d: Decision = classify(a, today)
        sig = (f"phone={'Y' if (a.phone or a.cell_phone) else 'N'} "
               f"ovr={int(a.override_button)} blk={int(a.correspondence_blocked)} "
               f"intF={int(a.interview_future)} intN={int(a.interview_past_noshow)} "
               f"sent={int(a.sent_to_call_list_today)} "
               f"lc={a.last_correspondence or '-'}")
        _log(f"[{processed + 1}] {d.action.value.upper()} — {d.reason}  [{sig}]")
        _skips_before = _SETTLED_SKIPS
        try:
            outcome = _DISPATCH[d.action](page, a, live)
        except Exception as e:  # noqa: BLE001
            _log(f"    ERROR performing {d.action.value}: "
                 f"{type(e).__name__}: {e}")
            outcome = "error"
        counts[outcome or d.action.value] = counts.get(outcome or d.action.value, 0) + 1
        # Activity log — one row per applicant, for the daily scorecard.
        if live:
            _ACTIVITY_ROWS.append([
                dt.datetime.now().strftime("%H:%M"),
                f"{a.first_name} {a.last_name}".strip(),
                a.job_board, a.position[:60],
                d.action.value, outcome or "", d.reason[:140],
            ])
        # CURRENT-queue snapshot: record who ended THIS walk still needing a human
        # (couldn't get a number off the resume, or the SMS thread is too old to
        # text). Deduped by the walk's `seen` set, so this = who's flagged right now.
        _nm = f"{a.first_name} {a.last_name}".strip()
        if not _nm:
            # The record read came back without a name — it happens when the ATS
            # re-renders mid-walk (the log shows it as "filled + sending:" with
            # nothing after the colon). This used to fall through the `if _nm`
            # guard and DROP the applicant from the to-do post altogether:
            # processed, flagged, and invisible to the person who has to act on
            # them. Same failure as the bucket bug fixed earlier today — a person
            # who needs a hand, silently absent from the list of people who need a
            # hand. Identify them by whatever we DO have so they always appear.
            _nm = (a.email or "").strip() or "(name unreadable — find them in the queue)"
        _days = (today - a.applied_date).days if a.applied_date else None
        _entry = {"name": _nm, "account": a.account or "", "days": _days}
        # OUTCOME first, action only as a fallback. `d.action` is where the
        # applicant ENTERED the flow; `outcome` is where they ended up, and for
        # this post only the ending matters — it tells a human what to DO.
        # Most re-text fallbacks arrive via the no-phone path (no number on
        # file, we read one off the resume, the ATS then refuses the send
        # because that number was already contacted, and the SMS thread is too
        # old for the widget to see). The old `or d.action.value ==
        # "flag_no_phone"` clause claimed all of them for the no-phone bucket
        # before the flag_retext branch could be reached, so "need a manual
        # text" was **0 in all 37 snapshots on 2026-08-27** while the log
        # recorded 103 re-text fallbacks in that office alone. Those people
        # were shown to a human as "go pull their number from Indeed" — advice
        # already carried out, and useless: their number is on file, what they
        # need is a fresh message. Victor Renteria and Claudia Ceniceros were
        # both in that state (Megan 8/27).
        if outcome == "flag_retext":
            flagged_now["retext"].append(_entry)
        elif outcome == "flag_no_phone" or (
                not outcome and d.action.value == "flag_no_phone"):
            flagged_now["nophone"].append(_entry)

        processed += 1
        # Did the handler do real work, or just recognise a case already settled
        # today and page past it? Only the former spends a slot. Read off the
        # skip counter rather than re-deriving the condition here, so the two
        # settled paths (no-number cache, no-thread cache) stay the single source
        # of truth for what "settled" means.
        if _SETTLED_SKIPS == _skips_before:
            worked += 1
        # The next few reads will land mid-re-render — widen the end-of-queue
        # guard until we reach a fresh applicant again.
        after_mutation = outcome in MUTATIONS
        # Throttle live mutations (a controlled test uses --max-actions 1).
        if live and outcome in MUTATIONS:
            actions += 1
            if max_actions is not None and actions >= max_actions:
                _log(f"[oat] reached --max-actions {max_actions} — stopping")
                break
        if worked >= limit:
            break
        if processed >= touch_cap:
            _log(f"[oat] read {processed} applicants (touch cap {touch_cap}) — "
                 f"stopping; raise OAT_MAX_TOUCH_PER_RUN if the queue is bigger")
            break
        # Do NOT page Next here. Re-read on the next loop: a removed/sent
        # app has left its slot (a fresh app is now current → handled), and
        # an app that stayed re-reads as already-seen so the guard at the
        # top pages Next past it. This walks the WHOLE queue instead of
        # stopping after the first mutation.
        page.wait_for_timeout(1200 if outcome in MUTATIONS else 400)

    _flush_queues()
    try:
        _end_total = getattr(read_current_applicant(page, today), "_total", None)
    except Exception:  # noqa: BLE001
        _end_total = None
    _log(f"[oat] QUEUE at end: {_end_total} emails "
         f"(was {_start_total} — a persisted send/remove drops this)")
    _log(f"[oat] done — {processed} applicant(s) this run "
         f"({worked} worked, {_SETTLED_SKIPS} settled skips; cap {limit}): "
         + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    # Only overwrite the snapshot when this walk actually reached the end of the
    # queue (no early --max-actions/limit bail), so a partial walk can't post a
    # too-short list. A full walk of a small queue always ends via the no-progress
    # guard well before `limit`, so processed < limit == "walked the whole queue".
    # `processed < limit` only rules out the ONE early exit it was written for —
    # hitting the per-run cap. Every OTHER early exit (the pager control going
    # missing, the no-progress guard tripping, an error mid-queue) also satisfies
    # it, so those walks were calling themselves complete and overwriting the
    # snapshot with only the applicants they happened to reach. On 2026-08-27 that
    # was routine: 21-in-queue/11-touched, 22/15, 23/15, and Carlos twice at
    # 13/2 and 13/3. Megan spotted it from the outside — "you have follow up need
    # for 6 on atef but his inbox is 23, that doesn't line up" — and she was right:
    # the post was publishing a partial walk as the whole picture, so the to-do
    # list UNDERSTATED the backlog and the people deeper in the queue were
    # invisible rather than handled.
    #
    # So also require that we actually covered the queue we started with. When the
    # ATS never gave us a start count (it reads None often) we cannot tell, and we
    # keep the old behaviour rather than freeze the snapshot for the rest of the
    # day — a stale list is its own kind of lie.
    # Coverage is still measured in applicants READ (`processed`) — that is what
    # "did we see the whole queue" means, and settled cases were seen. What the
    # cap-exit test changes to is `worked`, because `worked` is now what `limit`
    # bounds; testing `processed < limit` here would call a 104-applicant walk
    # partial the moment it read its 61st person.
    _covered = _start_total is None or processed >= _start_total
    # Running out of time is an early exit like any other: the walk did NOT cover
    # the queue, so the snapshot must not be published as the whole picture (the
    # 2026-08-27 understated-backlog lesson above applies exactly).
    walked_all = ((worked < limit) and (processed < touch_cap)
                  and _covered and not _out_of_time)
    if not _covered:
        _log(f"[oat] PARTIAL walk: touched {processed} of {_start_total} in the "
             f"queue — keeping the last full snapshot instead of publishing a "
             f"short list")
    _write_flagged_snapshot(flagged_now, _end_total, today, complete=walked_all,
                            covered=processed, queue_start=_start_total)
    # Queue-independent proof of the walk (readable from the Sheet directly).
    # The cache column also carries how many applicants are still owed a blocked-read
    # retry, so a Cloudflare day is visible from the Sheet alone (a big "+N blocked"
    # is the signature of 2026-08-25, where blocked reads were silently filed as
    # "no number" and 90 applicants were written off).
    _pending = _blocked_pending_count()
    _cache_col = len(_load_nophone_checked())
    _write_walk_diag(_start_total, _end_total,
                     f"{_cache_col} (+{_pending} blocked)" if _pending else _cache_col,
                     _NOPHONE_SKIPS, counts)
    return 0


def _write_flagged_snapshot(flagged: dict, queue_total, today, complete: bool,
                            covered=None, queue_start=None) -> None:
    """Overwrite output/oat-flagged-<date>.json with THIS walk's still-flagged apps
    (no-phone + needs-manual-text) so the Slack post reflects the CURRENT queue, not
    the day's cumulative log. Deduped, order-preserved.

    A PARTIAL walk is now recorded too, carrying how much of the queue it actually
    covered, and the post labels it (2026-09-13, Megan: "yes do both").

    WHY THIS CHANGED. A partial walk used to write nothing at all, so the to-do post
    found no snapshot and skipped. That is safe but it fails SILENTLY, and it fails
    exactly where the list matters most: a walk is partial whenever the queue is
    bigger than MAX_PER_RUN, so the office with the biggest backlog is the one whose
    humans stop being told who to chase. Carlos's queue crossed 60 and his noon AND
    4pm lists simply stopped, with nothing saying so.

    The 2026-08-27 bug that the all-or-nothing rule was written for is still guarded,
    just differently: the danger was a short list being passed off as the WHOLE
    backlog ("you have follow up need for 6 on atef but his inbox is 23"). A partial
    snapshot that states its own coverage cannot do that.

    Best-available wins, so a partial never overwrites something better: a COMPLETE
    snapshot from earlier today is kept, and between two partials the one that
    covered more of the queue is kept.
    """
    import json as _json
    path = f"output/oat-flagged-{today.isoformat()}{config.FILE_SUFFIX}.json"
    if not complete:
        prev = {}
        try:
            with open(path) as _fh:
                prev = _json.load(_fh) or {}
        except Exception:  # noqa: BLE001 — no snapshot yet today
            prev = {}
        if prev.get("complete"):
            _log("[oat] partial walk — keeping today's COMPLETE snapshot")
            return
        if prev and int(prev.get("covered") or 0) >= int(covered or 0):
            _log(f"[oat] partial walk covered {covered} — keeping the better "
                 f"partial snapshot ({prev.get('covered')})")
            return

    def _dedup(entries):
        seen, out = set(), []
        for e in entries:
            # entries are {"name","account"} dicts (older snapshots were bare names)
            nm = (e.get("name") if isinstance(e, dict) else e) or ""
            k = nm.strip().lower()
            if nm and k not in seen:
                seen.add(k)
                out.append(e if isinstance(e, dict) else {"name": nm, "account": ""})
        return out

    snap = {
        "nophone": _dedup(flagged.get("nophone", [])),
        "retext": _dedup(flagged.get("retext", [])),
        "queue_total": queue_total,
        "at": dt.datetime.now().strftime("%H:%M"),
        "date": today.isoformat(),
        # What the post needs to label itself honestly.
        "complete": bool(complete),
        "covered": int(covered or 0),
        # COVERAGE IS MEASURED AGAINST THE QUEUE WE STARTED ON, not the one we
        # ended with. `queue_total` above is the END size — it is what the post
        # means by "the queue right now", and it is SMALLER than what we walked
        # through precisely because the walk sent and removed people out of it.
        # Using it as the denominator printed "walk covered 23 of 10 in the
        # queue" into Carlos's channel (2026-09-13). The walk's own PARTIAL log
        # line has always used the start total ("touched 62 of 183"); the
        # snapshot now carries the same number.
        "queue_start": (int(queue_start) if queue_start is not None else None),
    }
    try:
        os.makedirs("output", exist_ok=True)
        with open(path, "w") as fh:
            _json.dump(snap, fh)
        # Built BEFORE the f-string on purpose: Lucy 2 runs Python 3.9, where a
        # replacement field cannot span lines (PEP 701 is 3.12+). Inline it and
        # the module raises SyntaxError on import and every walk exits 1.
        _how = ("complete" if complete
                else "PARTIAL, covered %s of %s" % (covered, queue_start))
        _log(f"[oat] flagged snapshot ({_how}): "
             f"{len(snap['nophone'])} need a number, "
             f"{len(snap['retext'])} need a manual text (queue={queue_total})")
    except Exception as e:  # noqa: BLE001
        _log(f"[oat] could not write flagged snapshot: {e}")


def attach_dialog_accept(page) -> None:
    """Accept every JS confirm() on this page and any popup it opens.

    ApplicantStream pops a confirm() on Save/remove/send; Playwright (patchright AND
    real-Chrome-over-CDP) auto-DISMISSES unhandled dialogs, which silently cancels the
    action (it logs 'done' but the queue never drops — Megan 7/27). Both the
    standalone ``run`` and the ``applicant_push`` orchestrator call this before the
    walk so removes/sends actually persist."""
    page.on("dialog", lambda d: d.accept())
    page.context.on("page", lambda p: p.on("dialog", lambda d: d.accept()))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(live: bool = False, limit: int = None, debug: bool = False,
        headed: bool = False, max_actions: int = None, probe_sms_flag: bool = False,
        probe_resume_flag: bool = False,
        retext_test: str = None, retext_send: str = None,
        remove_applicant: str = None, retext_names: str = None,
        probe_search_term: str = None, emit_nophone: bool = False,
        fill_nophone: bool = False, _attempt: int = 1) -> int:
    limit = limit if limit is not None else config.MAX_PER_RUN
    today = dt.date.today()

    mode = "LIVE" if live else "DRY-RUN"
    _log(f"[oat] OAT Processing — office {config.OFFICE_ID} "
         f"({config.OFFICE_HINT}) — {mode}")

    try:
        # Same holder-warmed AppStream session resume_pushing rides. No
        # extensions needed (OAT doesn't use the resume-extractor plugin).
        # yield_if_busy so we step aside if another Carlos-session run holds it.
        with appstream_direct_session(yield_if_busy=True) as page:
            # Accept ApplicantStream's confirm() dialogs so removes/sends persist
            # (see attach_dialog_accept — auto-dismiss otherwise cancels them).
            attach_dialog_accept(page)
            if not fetch_office._switch_office(page, config.OFFICE_ID,
                                               config.OFFICE_HINT):
                _log(f"[oat] FATAL: office switch to {config.OFFICE_ID} failed")
                return 2
            _log(f"[oat] on office {config.OFFICE_ID} ({config.OFFICE_HINT})")

            if probe_sms_flag:
                open_oat(page)
                probe_sms(page)
                return 0

            if probe_resume_flag:
                open_oat(page)
                probe_resume(page)
                return 0

            if probe_search_term:
                open_oat(page)
                probe_search(page, probe_search_term)
                return 0

            if emit_nophone:
                open_oat(page)
                return emit_nophone_resumes(page)

            if fill_nophone:
                _open_oat_ready(page)
                return fill_nophone_from_tab(page)

            if retext_names:
                # Re-text applicants who've left the OAT queue. Semicolon list of
                # 'First Last|Phone' (phone optional — read from their record).
                open_oat(page)
                for spec in retext_names.split(";"):
                    parts = [p.strip() for p in spec.split("|")]
                    nm = parts[0].split()
                    if not nm:
                        continue
                    first = nm[0]
                    last = " ".join(nm[1:]) if len(nm) > 1 else ""
                    ph = parts[1] if len(parts) > 1 else ""
                    st, det = retext_by_name(page, first, last, ph)
                    _log(f"[oat] RETEXT-BY-NAME {first} {last!r} -> {st} :: {det[:90]}")
                    open_oat(page)  # back to a clean OAT page for the next one
                return 0

            if retext_test or retext_send:
                # Validate the FULL re-text chain on ONE named person. --retext-test
                # stops before Send (dry); --retext-send-live actually sends ONE real
                # message (controlled Send-button validation). 'First Last' or
                # 'First Last|Role|Phone'.
                spec = retext_send or retext_test
                do_send = bool(retext_send)
                parts = [p.strip() for p in spec.split("|")]
                nm = parts[0].split()
                first = nm[0] if nm else ""
                last = " ".join(nm[1:]) if len(nm) > 1 else ""
                role = parts[1] if len(parts) > 1 and parts[1] else "Event Marketing"
                phone = parts[2] if len(parts) > 2 else ""
                open_oat(page)  # land on p=604 — the SMS widget injects there
                _log(f"[oat] RETEXT-{'SEND-LIVE' if do_send else 'TEST(no send)'} "
                     f"name={first} {last!r} role={role!r} phone={phone!r}")
                status, detail = retext_applicant(page, first, last, phone, role,
                                                  do_send=do_send)
                _log(f"[oat] RETEXT result: {status} :: {detail[:160]!r}")
                # Mirror the real flow: after a live send, remove that applicant
                # (walk to their record — the SMS widget left us elsewhere).
                if do_send and status == "retext_sent":
                    rr = _walk_to_and_remove(page, first, last)
                    _log(f"[oat] RETEXT post-send remove: {rr}")
                return 0

            if remove_applicant:
                # Utility: walk OAT to a named applicant and remove them (no text).
                open_oat(page)
                nm = remove_applicant.split()
                first = nm[0] if nm else ""
                last = " ".join(nm[1:]) if len(nm) > 1 else ""
                rr = _walk_to_and_remove(page, first, last)
                _log(f"[oat] REMOVE-APPLICANT {first} {last!r} -> {rr}")
                return 0

            if debug:
                # Dump the LANDING console first (shows the real nav anchors),
                # then attempt OAT and dump that page too if we get there.
                _log("[oat] --- health check: LANDING console ---")
                health_check(page)
                opened = open_oat(page)
                _log(f"[oat] open_oat -> {opened}")
                if opened:
                    _log("[oat] --- health check: OAT page ---")
                    health_check(page)
                    # Validate the read/classify layer on the current applicant.
                    a = read_current_applicant(page, today)
                    d = classify(a, today)
                    _log(f"HC STATE: name={a.first_name} {a.last_name!r} "
                         f"phone={a.phone!r} cell={a.cell_phone!r} jb={a.job_board!r} "
                         f"pos={a.position[:40]!r}")
                    _log(f"HC STATE2: override_btn={a.override_button} "
                         f"corr_blocked={a.correspondence_blocked} "
                         f"last_corr={a.last_correspondence} "
                         f"intv_future={a.interview_future} "
                         f"intv_noshow={a.interview_past_noshow} "
                         f"sent_today={a.sent_to_call_list_today} "
                         f"total={getattr(a,'_total',None)}")
                    _log(f"HC STATE3: status={a.raw_status[:200]!r}")
                    _log(f"HC DECISION: {d.action.value} — {d.reason}")
                    # Diagnostic: is the state content actually on the page, and
                    # is our parser missing it, or is it genuinely absent?
                    try:
                        mk = page.evaluate(r"""() => {
                          const b=(document.body.innerText||'');
                          const has=s=>b.toLowerCase().includes(s.toLowerCase());
                          return {
                            following: has('Following Applicants'),
                            cannotOverride: has('Cannot override'),
                            overwrite: has('Overwrite Old Applicants'),
                            lastCorr: has('last correspondence was on'),
                            emails: (b.match(/of\s+\d+\s+emails/i)||[''])[0],
                            heads: [...document.querySelectorAll('table')]
                              .map(t=>(t.querySelector('tr')?.innerText||'').replace(/\s+/g,' ').slice(0,70))
                              .filter(Boolean).slice(0,18),
                            // pager controls: anything clickable/selectable whose
                            // text or nearby text mentions Emails/page navigation.
                            pager: (()=>{
                              const out=[];
                              document.querySelectorAll('a,input,select,img,button').forEach(e=>{
                                const t=(e.innerText||e.value||e.alt||e.title||'').trim();
                                const oc=(e.getAttribute('onclick')||'').slice(0,50);
                                const nm=e.name||e.id||'';
                                if(/next|prev|page|email|›|»|◄|►|>|</i.test(t+' '+oc+' '+nm) && (t.length<25))
                                  out.push(`${e.tagName}<${nm}> '${t}' oc=${oc}`);
                              });
                              return [...new Set(out)].slice(0,20);
                            })(),
                          };
                        }""")
                        _log(f"HC MARK: following={mk.get('following')} "
                             f"cannotOverride={mk.get('cannotOverride')} "
                             f"overwrite={mk.get('overwrite')} lastCorr={mk.get('lastCorr')} "
                             f"emails={mk.get('emails')!r}")
                        for i, h in enumerate(mk.get("heads", [])):
                            _log(f"HC THEAD {i}: {h}")
                        for i, pg in enumerate(mk.get("pager", [])):
                            _log(f"HC PAGER {i}: {pg}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC MARK failed: {e}")
                    # Resume probe: is a missing phone recoverable from the resume
                    # panel / email on-page (across iframes)? Answers "can we fill
                    # the number ourselves and send them through?".
                    try:
                        phones = set()
                        for fr in page.frames:
                            try:
                                txt = fr.inner_text("body")
                            except Exception:  # noqa: BLE001
                                continue
                            for m in re.findall(
                                    r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", txt or ""):
                                phones.add(m.strip())
                        _log(f"HC RESUME: phones found across {len(page.frames)} "
                             f"frame(s): {sorted(phones)[:8]}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC RESUME failed: {e}")
                    # Remove mechanism: dump ALL rmvReason options (is there a
                    # 'Duplicate'?) + the Save/remove-related controls, so we wire
                    # the RIGHT "remove for duplicate" action. Read-only.
                    try:
                        rm = page.evaluate(r"""() => {
                          const s=document.querySelector("select[name='rmvReason']");
                          const opts = s ? [...s.options].map(o=>o.text.trim()) : [];
                          const save = [...document.querySelectorAll('button,input,a')]
                            .filter(e=>/save applicant|remove|overwrite|duplicate/i.test(e.innerText||e.value||''))
                            .map(e=>`${e.tagName}[${e.name||e.id||''}]='${(e.innerText||e.value||'').trim().slice(0,32)}'`);
                          return {rmvReason: opts, controls: [...new Set(save)].slice(0,20),
                                  hasRemovApp: !!document.querySelector("[name='removApp']")};
                        }""")
                        _log(f"HC RMVREASON ({len(rm.get('rmvReason',[]))}): {rm.get('rmvReason')}")
                        _log(f"HC REMOVE hasRemovApp={rm.get('hasRemovApp')} controls={rm.get('controls')}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC RMVREASON failed: {e}")
                    # Re-text/await MESSAGE templates — the exact copy that would go
                    # out, for Megan to confirm before re-text auto-send is armed.
                    try:
                        msg = page.evaluate(r"""() => {
                          const v = n => { const e=document.querySelector(`[name='${n}']`);
                            return e ? (e.value||e.innerText||'').trim() : ''; };
                          const optsOf = n => { const s=document.querySelector(`[name='${n}']`);
                            return s && s.options ? [...s.options].map(o=>o.text.trim()) : []; };
                          // 'Await Call Email' + Quick Notes may be selects; the
                          // Email-Applicant compose holds the message body.
                          const await_ = document.querySelector("[name='emailType'],[name='awaitType'],[name='awaitCallEmail']");
                          return {
                            subject: v('emailApplicantSubject'),
                            message: v('emailApplicantMessage'),
                            qNotes: optsOf('qNotes'),
                            awaitName: await_ ? (await_.name||await_.id) : '',
                            awaitOpts: await_ && await_.options ? [...await_.options].map(o=>o.text.trim()) : [],
                            sendEmail: (document.querySelector("[name='sendEmail']")||{}).checked,
                            sendSMS: (document.querySelector("[name='sendSMS']")||{}).checked,
                          };
                        }""")
                        _log(f"HC MSG subject={msg.get('subject')!r}")
                        _log(f"HC MSG body={msg.get('message')!r}")
                        _log(f"HC MSG await={msg.get('awaitName')!r} opts={msg.get('awaitOpts')}")
                        _log(f"HC MSG qNotes={msg.get('qNotes')}")
                        _log(f"HC MSG sendEmail={msg.get('sendEmail')} sendSMS={msg.get('sendSMS')}")
                    except Exception as e:  # noqa: BLE001
                        _log(f"HC MSG failed: {e}")
                return 0

            return run_walk(page, live=live, limit=limit,
                            max_actions=max_actions, today=today)
    except AppStreamBusy:
        _log("[oat] AppStream session busy (another run holds Carlos's "
             "session) — stepping aside; try again shortly")
        return 3
    except RuntimeError as e:
        # The patchright session intermittently gets a Cloudflare re-challenge
        # ("console never rendered #searchMC"). A fresh session launch self-heals
        # it (every retry has worked), so retry the whole run up to 3x before
        # giving up. This failure happens during session setup, BEFORE any
        # applicant is touched, so retrying never double-acts.
        msg = str(e).lower()
        if (("never rendered" in msg or "searchmc" in msg) and _attempt < 3):
            _log(f"[oat] session didn't establish (Cloudflare re-challenge?) — "
                 f"retry {_attempt + 1}/3 with a fresh session")
            return run(live=live, limit=limit, debug=debug, headed=headed,
                       max_actions=max_actions, _attempt=_attempt + 1)
        raise
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="OAT Processing (office 11580, Lucy 2)")
    p.add_argument("--live", action="store_true",
                   help="Actually perform send/remove/override clicks "
                        "(default is dry-run: read + classify + print only)")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (this is already the default)")
    p.add_argument("--limit", type=int, default=None,
                   help=f"Max applicants this run (default {config.MAX_PER_RUN})")
    p.add_argument("--debug", action="store_true",
                   help="Land on the OAT page, print a health check, then stop")
    p.add_argument("--headed", action="store_true", help="Force a visible browser")
    p.add_argument("--max-actions", type=int, default=None, dest="max_actions",
                   help="Cap live mutations (send/overwrite-send/remove) this run "
                        "(safety throttle; use --max-actions 1 for a controlled test)")
    p.add_argument("--probe-sms", action="store_true", dest="probe_sms",
                   help="Open the SMS panel and dump its structure (for re-text), stop")
    p.add_argument("--probe-resume", action="store_true", dest="probe_resume",
                   help="On the current applicant, open the Indeed resume and try to "
                        "pull the phone (for the no-phone lookup), stop")
    p.add_argument("--retext-test", default=None, dest="retext_test",
                   metavar="'First Last[|Role|Phone]'",
                   help="Validate the full re-text chain on one named person "
                        "WITHOUT sending (Load Template -> FOR LUCY -> compose), stop")
    p.add_argument("--retext-send-live", default=None, dest="retext_send",
                   metavar="'First Last[|Role|Phone]'",
                   help="ACTUALLY SEND one real re-text to the named person, then "
                        "remove them (mirrors text-then-remove). Sends an SMS.")
    p.add_argument("--remove-applicant", default=None, dest="remove_applicant",
                   metavar="'First Last'",
                   help="Walk OAT to the named applicant and remove them (no text)")
    p.add_argument("--retext-by-name", default=None, dest="retext_names",
                   metavar="'First Last|Phone;First Last|Phone'",
                   help="Re-text applicants who left the queue: search AS, read their "
                        "role, and SEND the FOR LUCY text. Semicolon-separated list.")
    p.add_argument("--probe-search", default=None, dest="probe_search_term",
                   metavar="'First Last'",
                   help="Diagnostic: map AS search + dump results for a name, stop")
    p.add_argument("--reset-activity", action="store_true", dest="reset_activity",
                   help="Archive today's activity log + flag queues (.bak) so the "
                        "scorecard restarts fresh; no browser, stop")
    p.add_argument("--emit-nophone-resumes", action="store_true",
                   dest="emit_nophone",
                   help="Walk the queue; write every no-phone applicant + resume URL "
                        f"to the {_NOPHONE_TAB} tab for a real browser to scrape; stop")
    p.add_argument("--fill-nophone-from-tab", action="store_true",
                   dest="fill_nophone",
                   help=f"Read {_NOPHONE_TAB}; for each applicant whose phone was "
                        "filled by the browser scrape, type it in + Send to AI; stop")
    args = p.parse_args(argv)

    if args.reset_activity:
        return reset_activity()

    live = args.live and not args.dry_run
    return run(live=live, limit=args.limit, debug=args.debug, headed=args.headed,
               max_actions=args.max_actions, probe_sms_flag=args.probe_sms,
               probe_resume_flag=args.probe_resume,
               retext_test=args.retext_test, retext_send=args.retext_send,
               remove_applicant=args.remove_applicant, retext_names=args.retext_names,
               probe_search_term=args.probe_search_term,
               emit_nophone=args.emit_nophone, fill_nophone=args.fill_nophone)


if __name__ == "__main__":
    sys.exit(main())
