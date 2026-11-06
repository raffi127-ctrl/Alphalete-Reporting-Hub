"""Sean Balderrama's "Double Tier Bonus - <date>" days, read off Carlos's inbox.

Carlos 2026-11-06: "Double tiers you can see off of my email and then you'll
know sales from that date are double tiers." Every eligible sale on such a
day counts twice toward the rep tier (line_revenue.tier_order_counts). The
mini's inbox manager already holds Carlos's Gmail app password; the same file
is pushed to Lucy 2 (push_cred_file), and Raf's inbox is the fallback on a
box that has his file. The search: sender sbalderrama@thesmartcircle.com, subject
"Double Tier Bonus  - 10/31" (the date in the subject IS the double day --
the 10/30 evening email says "tomorrow, 10/31", the 10/9 morning one says
"today, 10/9"). Known days are cached in output/nds_metrics/double_tier_days.json
and unioned with sow_rates.json's seed list, so an inbox outage never
forgets a day.

    lucy rerun nds_metrics_probe --double-days      # what the inbox says
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import email
import email.utils
import imaplib
import json
import re
from pathlib import Path
from typing import Iterable, Optional, Set

from automations.fiber_owners_distro.roster import IMAP_HOST, _decode
from automations.nds_metrics.run import OUT_DIR

# Carlos's own inbox (he is on Smart Circle's NDS distribution); the app
# password travels with `push_cred_file gmail-app-password-carloshidalgo349
# "Lucy 2"` from the mini. Raf's file is the fallback on a box that has it.
_CFG = Path.home() / ".config" / "recruiting-report"
INBOXES = (("carloshidalgo349@gmail.com", _CFG / "gmail-app-password-carloshidalgo349"),
           ("raffi127@gmail.com", _CFG / "gmail-app-password-raffi127"))
SENDER = "sbalderrama@thesmartcircle.com"
SUBJECT_WORD = "Double Tier"
SINCE = dt.date(2026, 10, 1)
CACHE = OUT_DIR / "double_tier_days.json"
_RE = re.compile(r"double\s+tiers?\s+bonus\s*[-–—:]*\s*(\d{1,2})\s*/\s*(\d{1,2})"
                 r"(?:\s*/\s*(\d{2,4}))?", re.I)


def parse_subject(subject: str, sent: Optional[dt.date]) -> Optional[dt.date]:
    """'Double Tier Bonus  - 10/31' (+ the email's send date for the year)
    -> 2026-10-31. None when the subject carries no date."""
    m = _RE.search(subject or "")
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    if m.group(3):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
    else:
        y = (sent or dt.date.today()).year
        if sent and mo < sent.month - 6:      # a December email about January
            y += 1
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def _inbox():
    for account, path in INBOXES:
        if path.exists():
            return account, path.read_text(encoding="utf-8-sig").strip().replace(" ", "")
    raise RuntimeError("no Gmail app password on this box for any of: "
                       + ", ".join(a for a, _ in INBOXES))


def fetch(log=print) -> Set[str]:
    """The inbox, live: every double-tier day Sean has announced since SINCE."""
    account, password = _inbox()
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    M.login(account, password)
    try:
        M.select('"[Gmail]/All Mail"', readonly=True)
        _typ, data = M.search(None, '(FROM "%s" SUBJECT "%s" SINCE "%s")'
                              % (SENDER, SUBJECT_WORD, SINCE.strftime("%d-%b-%Y")))
        ids = (data[0] or b"").split()
        out: Set[str] = set()
        for mid in ids:
            _typ, md = M.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
            raw = b"".join(p[1] for p in md if isinstance(p, tuple))
            msg = email.message_from_bytes(raw)
            subj = _decode(msg.get("Subject", ""))
            try:
                sent = email.utils.parsedate_to_datetime(msg.get("Date")).date()
            except Exception:  # noqa: BLE001
                sent = None
            d = parse_subject(subj, sent)
            if d:
                out.add(d.isoformat())
        log("[nds] double tier: %d email(s) from Sean in %s since %s -> %s"
            % (len(ids), account, SINCE, ", ".join(sorted(out)) or "none"))
        return out
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def days(seed: Iterable[str] = (), log=print) -> Set[str]:
    """seed (sow_rates) + the cache + whatever the inbox says now. An inbox
    error keeps what is known and says so."""
    known: Set[str] = set(seed)
    try:
        known |= set(json.loads(CACHE.read_text()).get("days", []))
    except Exception:  # noqa: BLE001
        pass
    try:
        known |= fetch(log=log)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"days": sorted(known),
                                     "checked": dt.datetime.now().isoformat(timespec="seconds")}))
    except Exception as e:  # noqa: BLE001
        log("[nds] double tier: inbox unreadable (%s: %s) -- using the %d known day(s)"
            % (type(e).__name__, str(e)[:80], len(known)))
    return known


if __name__ == "__main__":
    print(sorted(days()))
