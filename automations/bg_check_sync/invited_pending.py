"""Invited-but-not-taken tracker.

The rest of bg_check_sync reads fadv RESULT emails: it only lights up once a
candidate has actually taken the background check. But a Sterling e-invite being
*Delivered* never emails our reporting inbox at all — it lives only in the
Sterling / First Advantage portal ("Find Background Checks/E-Invites" → the
"Invited Applicants" table). So a new start can sit invited-but-not-started for
days, silently, and the first anyone notices is when onboarding stalls waiting
on a check nobody knew hadn't begun (Rizul Chauhan, invited 9/25 AND 9/28, both
"Delivered", zero fadv mail — Raf 2026-09-28, the reason this exists).

WHAT "PENDING" MEANS HERE. Someone the portal shows as invited who has NOT yet
produced a result. Two ways we know they've moved on and should drop off:
  * a fadv event exists for them (email_source) — they've at least started, so
    the rest of the pipeline already owns them; and
  * the portal's own "My Background Checks" (completed) table lists them.
Everyone left is genuinely still sitting on the invite.

TWO BUCKETS, because they need different chasing:
  * WAITING — Delivered / Sent / Opened / Started: the invite reached them and
    the ball is in their court. Age is how long they've stalled.
  * STUCK — Bounced / Expired / Cancelled / Declined: the invite itself is dead
    and re-sending (or a new address) is needed before they even *can* take it.

DEDUP. One person can hold several invites (Rizul's two). They collapse to a
single line — first invite, latest invite, and the count — so the report chases
a person, not a row, and the age that matters is *how long they've been
outstanding* (since the FIRST invite), not since the most recent re-send.

NO PORTAL YET. The live fetch needs a logged-in Sterling session (see
`fetch_invited`); until that's wired the whole thing runs offline from a saved
rows file, exactly like run.py's `--events` sample. Everything except the
scrape is testable today.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from automations.bg_check_sync.parse import norm
from automations.shared.name_case import titlecase_name

# --- portal invite-status vocabulary ----------------------------------------
# Lower-cased, matched by substring so "Email Delivered" and "Delivered" both
# land. Anything we don't recognise is treated as WAITING (surface it, don't
# silently drop a real person over an unseen status word) but flagged unknown.
WAITING_STATUSES = ("delivered", "sent", "opened", "viewed", "started",
                    "in progress", "pending", "not started")
STUCK_STATUSES = ("bounced", "expired", "cancelled", "canceled", "declined",
                  "failed to send", "undeliverable", "revoked")
DONE_STATUSES = ("complete", "completed", "finished", "closed")


def bucket_for(status: str) -> str:
    """WAITING / STUCK / DONE / UNKNOWN for one raw portal status string."""
    low = (status or "").strip().lower()
    if not low:
        return "UNKNOWN"
    for s in DONE_STATUSES:
        if s in low:
            return "DONE"
    for s in STUCK_STATUSES:
        if s in low:
            return "STUCK"
    for s in WAITING_STATUSES:
        if s in low:
            return "WAITING"
    return "UNKNOWN"


# --- one invite row ----------------------------------------------------------
@dataclass
class Invite:
    """One row of the portal's Invited Applicants table."""
    first: str
    last: str
    email: str = ""
    sent: str = ""          # ISO date (YYYY-MM-DD) when the invite was sent
    status: str = ""        # raw portal status, e.g. "Delivered"
    source: str = ""        # "Email" / "SMS"
    bill_code: str = ""
    job_title: str = ""

    @property
    def key(self) -> str:
        """last|first, normalized — same shape match.py/name_gate key on, so an
        invite can be cross-referenced against a fadv BGEvent for the person."""
        return f"{norm(self.last)}|{norm(self.first)}"

    @property
    def bucket(self) -> str:
        return bucket_for(self.status)

    def sent_date(self) -> Optional[dt.date]:
        return _parse_date(self.sent)


# --- one person, after collapsing their invites ------------------------------
@dataclass
class Pending:
    first: str
    last: str
    email: str
    bucket: str                       # WAITING / STUCK / UNKNOWN
    status: str                       # the newest invite's raw status
    first_sent: Optional[dt.date]
    last_sent: Optional[dt.date]
    count: int
    invites: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{titlecase_name(self.first)} {titlecase_name(self.last)}".strip()

    def days_outstanding(self, today: Optional[dt.date] = None) -> Optional[int]:
        """How long since the FIRST invite — the number that says how long
        onboarding has been waiting on this person."""
        if not self.first_sent:
            return None
        return ((today or dt.date.today()) - self.first_sent).days

    def days_since_last(self, today: Optional[dt.date] = None) -> Optional[int]:
        if not self.last_sent:
            return None
        return ((today or dt.date.today()) - self.last_sent).days


def _parse_date(s: str) -> Optional[dt.date]:
    """Parse the portal's date. Accepts ISO (YYYY-MM-DD) and US M/D/YYYY."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def collapse(invites: list) -> list:
    """One Pending per person. Oldest-outstanding first.

    A person's bucket is STUCK only if EVERY invite is stuck — a later re-send
    that's merely Delivered means the ball is back in their court, so the newest
    non-stuck invite wins. If all their invites are stuck, so are they.
    """
    by_person: dict = {}
    for inv in invites:
        by_person.setdefault(inv.key, []).append(inv)

    out = []
    for _key, group in by_person.items():
        dated = sorted(group, key=lambda i: i.sent_date() or dt.date.min)
        first_sent = next((i.sent_date() for i in dated if i.sent_date()), None)
        last_sent = next((i.sent_date() for i in reversed(dated) if i.sent_date()), None)
        newest = dated[-1]
        # Prefer the newest invite that isn't stuck for the person's live status.
        live = next((i for i in reversed(dated) if i.bucket != "STUCK"), newest)
        buckets = {i.bucket for i in group}
        person_bucket = "STUCK" if buckets == {"STUCK"} else live.bucket
        out.append(Pending(
            first=newest.first, last=newest.last, email=newest.email,
            bucket=person_bucket, status=live.status,
            first_sent=first_sent, last_sent=last_sent,
            count=len(group), invites=dated,
        ))
    out.sort(key=lambda p: (p.first_sent or dt.date.max, p.last.lower()))
    return out


def pending(invites: list, *, done_keys: Optional[set] = None,
            event_keys: Optional[set] = None) -> list:
    """Collapse invites, then drop anyone who has actually moved on.

    done_keys:  keys from the portal's completed ("My Background Checks") table.
    event_keys: keys we hold a fadv BGEvent for (email_source) — a result email
                means they at least took it, so the main pipeline owns them.
    Either signal is enough to exclude someone; both are belt-and-suspenders
    against a portal snapshot that lags the moment a check comes back.
    """
    done = (done_keys or set()) | (event_keys or set())
    collapsed = collapse(invites)
    return [p for p in collapsed if f"{norm(p.last)}|{norm(p.first)}" not in done]


def split_buckets(people: list) -> tuple:
    """(waiting, stuck) — UNKNOWN rides with waiting so it's never hidden."""
    waiting = [p for p in people if p.bucket in ("WAITING", "UNKNOWN")]
    stuck = [p for p in people if p.bucket == "STUCK"]
    return waiting, stuck


# --- report text -------------------------------------------------------------
TITLE = "📋 BG-Check Invites — Sent, Not Yet Taken"


def render(people: list, *, today: Optional[dt.date] = None,
           stale_days: int = 3) -> str:
    """A plain-text block for Slack/preview. Leads with the workflow title, then
    WAITING (oldest first, ⏰ past `stale_days`) and STUCK (needs a re-send)."""
    today = today or dt.date.today()
    waiting, stuck = split_buckets(people)
    lines = [f"*{TITLE}*"]

    if not waiting and not stuck:
        lines.append("_Everyone invited has started their check. Nothing outstanding._")
        return "\n".join(lines)

    if waiting:
        lines.append("")
        lines.append(f"*Waiting on the applicant* ({len(waiting)})")
        for p in waiting:
            lines.append("   •  " + _line(p, today, stale_days))
    if stuck:
        lines.append("")
        lines.append(f"*Invite stuck — re-send needed* ({len(stuck)})")
        for p in stuck:
            lines.append("   •  " + _line(p, today, stale_days))
    return "\n".join(lines)


def _line(p: "Pending", today: dt.date, stale_days: int) -> str:
    age = p.days_outstanding(today)
    when = _fmt(p.first_sent)
    tail = ""
    if p.count > 1:
        tail = f" · invited {p.count}× (latest {_fmt(p.last_sent)})"
    agestr = f"{age}d" if age is not None else "?"
    flag = "⏰ " if (age is not None and age >= stale_days) else ""
    extra = "" if p.bucket in ("WAITING",) else f" [{p.status}]"
    return f"{flag}{p.name} — invited {when} ({agestr} ago){tail}{extra}"


def _fmt(d: Optional[dt.date]) -> str:
    # Explicit ints — %-m / %-d aren't portable to Windows.
    return f"{d.month}/{d.day}" if d else "?"


# --- portal fetch (needs a logged-in Sterling session) -----------------------
# The Sterling / First Advantage portal that shows "Find Background Checks/
# E-Invites". Set once known; kept in env so a machine can point at the real
# portal without a code change, and so the offline tests never need it.
import os

PORTAL_URL = os.environ.get("BGSYNC_PORTAL_URL", "")


def _rows_by_label(table, want: dict) -> list:
    """Read a portal <table> into dicts keyed by our field names.

    `table` is a Playwright locator for one <table>. `want` maps our field name
    -> the header label to find it under (lower-cased substring match). By label,
    never by index — the portal has ~7 columns today and the day one is added,
    position-based parsing reads a Bill Code as a job title. Mirrors
    ov_name_sync._columns / _row_fields.
    """
    heads = [h.strip().lower() for h in table.locator("thead th").all_inner_texts()]
    idx = {}
    for fieldname, label in want.items():
        for i, h in enumerate(heads):
            if label in h:
                idx[fieldname] = i
                break
    out = []
    body_rows = table.locator("tbody tr")
    for r in range(body_rows.count()):
        cells = body_rows.nth(r).locator("td").all_inner_texts()
        if not any(c.strip() for c in cells):
            continue
        row = {}
        for fieldname, i in idx.items():
            row[fieldname] = cells[i].strip() if i < len(cells) else ""
        # Skip the DataTables "No ... to display" placeholder row.
        if not (row.get("name") or row.get("first") or row.get("last")):
            continue
        out.append(row)
    return out


def _split_name(name: str) -> tuple:
    """Portal shows "Chauhan, Rizul" (Last, First) in the invited table."""
    name = (name or "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        return first.strip(), last.strip()
    parts = name.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return name, ""


def fetch_invited(page, *, verbose: bool = True) -> tuple:
    """Scrape (invited, done_keys) from the portal's E-Invites page.

    invited: list[Invite] from the "Invited Applicants" table.
    done_keys: {last|first} from the "My Background Checks" (completed) table on
               the same page, so a completed person is never reported pending.

    Requires PORTAL_URL and a logged-in session on `page`. Raises if the URL is
    not configured yet — the offline path (read_rows_file) needs neither.
    """
    if not PORTAL_URL:
        raise RuntimeError(
            "BGSYNC_PORTAL_URL is not set — the Sterling e-invites portal URL is "
            "still unknown. Run offline with --rows <file> until it's wired.")
    page.set_default_navigation_timeout(90000)
    page.goto(PORTAL_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass

    invited_rows = _rows_by_label(
        _named_table(page, "Invited Applicants"),
        {"name": "name", "email": "mail", "sent": "sent",
         "source": "source", "status": "status",
         "bill_code": "bill", "job_title": "job"},
    )
    invites = []
    for r in invited_rows:
        first, last = _split_name(r.get("name", ""))
        invites.append(Invite(
            first=first, last=last, email=r.get("email", ""),
            sent=_iso(r.get("sent", "")), status=r.get("status", ""),
            source=r.get("source", ""), bill_code=r.get("bill_code", ""),
            job_title=r.get("job_title", ""),
        ))

    done_keys = set()
    try:
        done_rows = _rows_by_label(
            _named_table(page, "My Background Checks"),
            {"name": "name", "status": "status"},
        )
        for r in done_rows:
            first, last = _split_name(r.get("name", ""))
            done_keys.add(f"{norm(last)}|{norm(first)}")
    except Exception as e:  # noqa: BLE001 — completed table is a bonus, not required
        if verbose:
            print(f"[invited_pending] couldn't read completed table: {e}")

    if verbose:
        print(f"[invited_pending] portal: {len(invites)} invited, "
              f"{len(done_keys)} already completed")
    return invites, done_keys


def _named_table(page, caption_text: str):
    """The <table> under the section whose heading/caption contains `caption_text`.

    The portal wraps each list in a titled panel; find the panel by its visible
    title and return the table inside it. Left deliberately loose (heading OR a
    nearby table) so a small markup change doesn't break the read — tightened
    against the live DOM once we can see it.
    """
    # Placeholder selector strategy — refined against the live portal DOM.
    panel = page.locator(
        f"xpath=//*[contains(normalize-space(.), '{caption_text}')]"
        f"/following::table[1]"
    ).first
    panel.wait_for(state="visible", timeout=20000)
    return panel


def _iso(us_date: str) -> str:
    d = _parse_date(us_date)
    return d.isoformat() if d else (us_date or "")


# --- offline sample I/O ------------------------------------------------------
def read_rows_file(path: str) -> list:
    """Load a saved invited-rows JSON (list of dicts) into Invites. Field names
    match Invite's, so a scraped snapshot round-trips through this for testing."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("invited", raw) if isinstance(raw, dict) else raw
    return [Invite(**{k: r.get(k, "") for k in
                      ("first", "last", "email", "sent", "status",
                       "source", "bill_code", "job_title")})
            for r in rows]


# --- CLI ---------------------------------------------------------------------
def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Invited-but-not-taken BG-check tracker")
    ap.add_argument("--rows", help="offline: JSON of invited rows (no portal)")
    ap.add_argument("--stale-days", type=int, default=3,
                    help="flag ⏰ once outstanding this many days (default 3)")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (testing)")
    ap.add_argument("--cross-email", action="store_true",
                    help="also read fadv inbox to drop anyone with a result")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="print only; never posts (default, and the only mode today)")
    args = ap.parse_args(argv)

    today = _parse_date(args.today) if args.today else dt.date.today()

    if args.rows:
        invites = read_rows_file(args.rows)
        done_keys: set = set()
    else:
        print("Live portal fetch isn't wired yet (no PORTAL_URL). "
              "Run with --rows <file> for an offline preview.", file=sys.stderr)
        return 2

    event_keys = set()
    if args.cross_email:
        from automations.bg_check_sync import email_source
        for ev in email_source.fetch_events(since_days=45, verbose=False):
            event_keys.add(f"{norm(ev.last)}|{norm(ev.first)}")

    people = pending(invites, done_keys=done_keys, event_keys=event_keys)
    print(render(people, today=today, stale_days=args.stale_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
