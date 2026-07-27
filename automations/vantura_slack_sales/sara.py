"""Nightly Sara Plus reconcile — make the AT&T (B2B) column authoritative.

Slack parsing fills the board live all day (raise-only), but B2B is the messiest
campaign to read out of chat. Sara Plus is the AT&T order system, so once a day
— after the reps are done — we pull the true per-rep AT&T counts from Sara and
FINALIZE the B2B column (Megan 2026-07-26). Runs before the 5:10am board post so
the morning board is correct.

TWO DECISIONS Megan made (2026-07-26):
  * Sara OVERWRITES — it may LOWER a B2B number, unlike the Slack raise-only
    rule, because Sara is the truth for AT&T.
  * A board rep NOT in Sara that night is LEFT as-is (flagged, never zeroed) —
    Sara may just omit reps with no sales, and we won't wipe a real number.

SCOPE: B2B / AT&T ONLY. Sara does NOT carry BOX (Megan confirmed) and never had
Base — those stay Slack-only forever.

Credentials: read from ~/.config/recruiting-report/saraplus-login (line 1 user,
line 2 password) or SARAPLUS_USER / SARAPLUS_PASS. NEVER hardcoded, NEVER
committed. Carlos's login; must run on Lucy 2 with the VPN on (Sara won't load
otherwise — his Loom).

  python -m automations.vantura_slack_sales.sara --preflight   # check prereqs
  python -m automations.vantura_slack_sales.sara --date 2026-07-27        # dry
  python -m automations.vantura_slack_sales.sara --date 2026-07-27 --yes  # write
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from automations.vantura_slack_sales import run as R
from automations.vantura_slack_sales.parse import TZ

CAMPAIGN = "B2B"
LOGIN_FILE = Path.home() / ".config" / "recruiting-report" / "saraplus-login"
# Sara Plus (Carlos 2026-07-27). This is the site ROOT; the actual login/app
# path gets pinned when we build the scrape off Carlos's walkthrough. Reaching
# the root is a basic connectivity check, not a full VPN verdict — the login
# page is the real test.
SARA_URL = os.environ.get("SARAPLUS_URL", "https://www.saraplus.com/").strip()


def _log(m: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {m}",
          flush=True)


def load_login() -> tuple[str, str]:
    """(user, password) from env or the local secret file. This function is the
    ONLY place the credential is read, and it never logs or returns it anywhere
    but to the login call."""
    u, p = os.environ.get("SARAPLUS_USER"), os.environ.get("SARAPLUS_PASS")
    if u and p:
        return u.strip(), p
    if LOGIN_FILE.exists():
        lines = LOGIN_FILE.read_text(encoding="utf-8-sig").splitlines()
        if len(lines) >= 2 and lines[0].strip() and lines[1].strip():
            return lines[0].strip(), lines[1]
    raise SystemExit(
        f"No Sara Plus login found. On Lucy 2, write it to {LOGIN_FILE} "
        "(line 1 = email, line 2 = password) and chmod 600, or set "
        "SARAPLUS_USER / SARAPLUS_PASS.")


# ------------------------------------------------------------------ scrape
def fetch_b2b(day: dt.date, log=_log) -> dict[str, int]:
    """Per-rep AT&T counts from Sara Plus for one day: {agent name: count}.

    SPEC (mapped from the live Sales Dashboard 2026-07-27, no VPN needed):
      login  https://www.saraplus.com/e/servicepages/login.aspx
             fields: ctl00$MainContent$txtUserName / $txtPassword / $btnLogin
             (ASP.NET WebForms; session id sits in the URL path). Then the app
             lands on the Sales Dashboard.
      set    Date Range = day..day (both date boxes), Service = All, Submit.
      read   the "Agent" group rows. **Per-rep AT&T count = the "AT&T Internet"
             column + the "Wireless New Lines" column.** NOT "Total Sales"
             (that counts DEALS, ~2/rep; the board counts LINES). NOT "Total
             Wireless" (that's not new-lines-only).

    VERIFIED: AT&T Internet + Wireless New Lines reconciles with the board's B2B
    total EXACTLY on 4 completed days — 7/22=1+20=21, 7/23=1+14=15,
    7/24=1+10=11, 7/25=0+1=1 — i.e. the reps' "NL" = Wireless New Lines and
    "Fiber"/internet = AT&T Internet. (AT&T UV / DIRECTV cols are 0 for these
    reps; if one ever goes non-zero, re-check whether the board should include
    it.)

    BUILD: prefer the CSV export (Export Options -> CSV) over grid scraping —
    download + parse the Agent rows. Build with patchright on Lucy 2, dumping
    HTML/CSV to the log to nail the date-field + export selectors. Until then a
    --yes run fails loudly rather than writing guesses.
    """
    raise NotImplementedError(
        "Sara Plus scrape not built yet — formula + selectors are spec'd above; "
        "build fetch_b2b against the live site on Lucy 2.")


# --------------------------------------------------------------- reconcile
def plan_overwrite(g, col, rows, sara_counts):
    """(writes, flags) for finalizing the B2B column from Sara.

    Pure — no Slack, no sheet — so the two decisions are unit-tested:
      * a matched rep is SET to Sara's count, up OR down (overwrite);
      * a board rep absent from Sara is LEFT as-is, only flagged;
      * a Sara rep with no board row is flagged (roster gap).
    """
    from gspread.utils import rowcol_to_a1
    writes, flags, seen = [], [], set()
    for author, cnt in sorted(sara_counts.items()):
        key = R.match_rep(author, rows)
        if not key:
            flags.append(f"Sara has {author} ({cnt}) but no B2B row on the board")
            continue
        seen.add(key)
        row = rows[key]
        old = str(R._cell(g, row, col)).strip()
        if old != str(cnt):
            writes.append((R._cell(g, row, R.NAME_COL), rowcol_to_a1(row, col),
                           old or "(blank)", cnt))
    for key, row in rows.items():
        if key in seen:
            continue
        val = str(R._cell(g, row, col)).strip()
        if val and val != "0":
            flags.append(f"{R._cell(g, row, R.NAME_COL)} has {val} on the board "
                         "but isn't in Sara — LEFT as-is")
    return writes, flags


def reconcile(day: dt.date, write: bool, log=_log) -> int:
    ws, g = R.board_grid()
    rows = R.campaign_rows(g, CAMPAIGN)
    ok, shown, want = R.week_ok(g, day)
    if not ok:
        log(f"WRONG WEEK — board WE={shown!r}, {day} needs {want!r}. Holding.")
        return 75
    col = R.day_column(g, day)
    if col is None:
        log(f"no column for {day:%A} on the board — holding.")
        return 75

    sara = fetch_b2b(day, log)
    log(f"Sara returned {len(sara)} rep(s), {sum(sara.values())} AT&T sales")
    writes, flags = plan_overwrite(g, col, rows, sara)
    for f in flags:
        log(f"  ! {f}")
    log(f"{len(writes)} B2B cell(s) would change (Sara overwrites, up or down):")
    for name, a1, old, new in writes:
        log(f"  {a1}  {name:<24} {old} -> {new}")
    if not write:
        log("DRY RUN — re-run with --yes to write")
        return 0
    if writes:
        from automations.recruiting_report.fill import _retry
        _retry(ws.batch_update, [{"range": a1, "values": [[int(new)]]}
                                 for _n, a1, _o, new in writes])
        log(f"wrote {len(writes)} cell(s)")
    return 0


# --------------------------------------------------------------- preflight
def preflight(log=_log) -> int:
    """Are the prerequisites in place on THIS machine? The email (not a secret)
    is shown to confirm the right account; the password is NEVER printed — only
    whether it's filled in."""
    if os.environ.get("SARAPLUS_USER") and os.environ.get("SARAPLUS_PASS"):
        log("credential: YES (from env SARAPLUS_USER/PASS)")
    elif LOGIN_FILE.exists():
        lines = LOGIN_FILE.read_text(encoding="utf-8-sig").splitlines()
        user = lines[0].strip() if lines else ""
        pw = lines[1] if len(lines) > 1 else ""
        if user and pw.strip():
            log(f"credential: YES — file has user {user} + a password ({len(pw)} chars)")
        else:
            u_state = "set" if user else "MISSING"
            p_state = "set" if pw.strip() else ("EMPTY — re-run the save command "
                                                "and paste the password at the prompt")
            log(f"credential: INCOMPLETE — user {u_state}, password {p_state}")
    else:
        log("credential: NO — file not found; run the save command on Lucy 2")
    log(f"Sara URL set: {'YES ('+SARA_URL+')' if SARA_URL else 'NO'}")
    if SARA_URL:
        try:
            import requests
            r = requests.get(SARA_URL, timeout=15)
            log(f"reachable: HTTP {r.status_code} — Sara loads from here, "
                f"so NO VPN needed on Lucy 2" if r.ok else
                f"reachable: HTTP {r.status_code} (responded but non-200)")
        except Exception as e:  # noqa: BLE001
            log(f"NOT reachable: {type(e).__name__} — Sara needs the VPN on "
                "Lucy 2, or the login is at a different path")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default yesterday")
    ap.add_argument("--yes", action="store_true", help="actually write")
    a = ap.parse_args(argv)
    if a.preflight:
        return preflight()
    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.datetime.now(TZ).date() - dt.timedelta(days=1))
    _log(f"Sara reconcile for {day:%A %m/%d} — B2B only")
    return reconcile(day, a.yes)


if __name__ == "__main__":
    sys.exit(main())
