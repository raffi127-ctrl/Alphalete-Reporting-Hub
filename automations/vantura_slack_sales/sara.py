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
LOGIN_URL = "https://www.saraplus.com/e/servicepages/login.aspx"
# Persistent profile so the "Remember Me" session sticks and most runs skip the
# login. Per-machine, under the git-ignored config area.
USER_DATA_DIR = str(Path.home() / ".config" / "recruiting-report" / "sara-profile")

# Login form (mapped from the live page 2026-07-27 — ASP.NET WebForms).
_SEL_USER = "#ctl00_MainContent_txtUserName"
_SEL_PASS = "#ctl00_MainContent_txtPassword"
_SEL_LOGIN = "#MainContent_btnLogin"


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
#
# Per-rep board B2B count = the "AT&T Internet" column + the "Wireless New
# Lines" column. NOT "Total Sales" (deals, ~2/rep — the board counts LINES),
# NOT "Total Wireless". VERIFIED to reconcile with the board B2B total exactly
# on 4 days: 7/22 1+20=21, 7/23 1+14=15, 7/24 1+10=11, 7/25 0+1=1.
_COL_INTERNET = "AT&T Internet"
_COL_WIRELESS = "Wireless New Lines"


def _mdy(d: dt.date) -> str:
    """M/D/YYYY, the format Sara's date boxes show (7/27/2026)."""
    return f"{d.month}/{d.day}/{d.year}"


def _launch(log):
    from patchright.sync_api import sync_playwright
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=True,
        viewport={"width": 1600, "height": 1000},
        accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, ctx, page


def _login(page, log) -> None:
    """Log in if the persistent session isn't already authenticated."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    # If Remember-Me already carried us past login, the username box is absent.
    if page.query_selector(_SEL_USER) is None:
        log("  already authenticated (persistent session)")
        return
    user, pw = load_login()
    page.fill(_SEL_USER, user)
    page.fill(_SEL_PASS, pw)
    log("  submitting login…")
    page.click(_SEL_LOGIN)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)
    if page.query_selector(_SEL_USER) is not None:
        raise SystemExit("Sara login failed — still on the login form. Check "
                         "the saraplus-login file (email line 1, password "
                         "line 2), then re-run.")
    log(f"  logged in — now at {page.url}")


def _dump(page, log, label: str) -> None:
    """Recon: print the page's selectors + grid so the extractor can be built
    from the log (no file access to Lucy 2 needed)."""
    import json
    info = page.evaluate("""() => {
      const t = e => (e.innerText||e.value||'').trim().slice(0,40);
      return {
        url: location.href,
        links: [...document.querySelectorAll('a')].map(a=>({t:t(a),h:a.getAttribute('href')})).filter(x=>x.t).slice(0,60),
        inputs: [...document.querySelectorAll('input,select')].map(e=>({tag:e.tagName,type:e.type,id:e.id,name:e.name,val:(e.value||'').slice(0,20)})).filter(e=>e.id||e.name).slice(0,60),
        buttons: [...document.querySelectorAll('button,input[type=submit],input[type=button],a.rbButton')].map(e=>({id:e.id,t:t(e)})).filter(e=>e.t).slice(0,40),
        headers: [...document.querySelectorAll('th')].map(t2=>t2.innerText.trim()).filter(Boolean).slice(0,40),
        rows: [...document.querySelectorAll('tr')].map(tr=>[...tr.querySelectorAll('td')].map(td=>td.innerText.trim())).filter(r=>r.filter(Boolean).length).slice(0,50),
      };
    }""")
    log(f"=== RECON [{label}] {info['url']} ===")
    for k in ("links", "inputs", "buttons", "headers", "rows"):
        log(f"--- {k} ---")
        for item in info[k]:
            log("  " + json.dumps(item, ensure_ascii=False))


def _open_dashboard(page, day: dt.date, log) -> None:
    """Get onto the Sales Dashboard for one day and Submit. Selectors are
    discovered on the first recon run and pinned here."""
    # Best-effort navigation: the app usually lands on/near the dashboard after
    # login. Recon confirms the real URL/nav; pinned once known.
    page.wait_for_timeout(1500)


def _scrape(day: dt.date, recon: bool, log=_log) -> dict:
    pw, ctx, page = _launch(log)
    try:
        _login(page, log)
        if recon:
            _dump(page, log, "post-login")
            return {}
        _open_dashboard(page, day, log)
        return _extract(page, day, log)
    finally:
        try:
            ctx.close(); pw.stop()
        except Exception:  # noqa: BLE001
            pass


def _extract(page, day: dt.date, log) -> dict:
    """Read per-agent AT&T Internet + Wireless New Lines from the grid.

    Built against the grid structure once recon pins the column order; guarded
    so it refuses to return a silent-empty result (which would look like 'no
    sales' and, with overwrite, could wrongly hold numbers). Not yet pinned.
    """
    raise NotImplementedError(
        "extractor not pinned yet — run `--recon` on Lucy 2 first; this dumps "
        "the dashboard selectors + grid so _open_dashboard/_extract can be "
        "finished. Refusing to write from an unbuilt extractor.")


def fetch_b2b(day: dt.date, log=_log) -> dict[str, int]:
    """Per-rep AT&T counts from Sara Plus for one day: {agent name: count}.

    count per agent = the "AT&T Internet" column + the "Wireless New Lines"
    column (see the block above for why + the 4-day reconciliation proof).
    """
    return _scrape(day, recon=False, log=log)


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
    ap.add_argument("--recon", action="store_true",
                    help="log in and DUMP the dashboard selectors/grid (build aid)")
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default yesterday")
    ap.add_argument("--yes", action="store_true", help="actually write")
    a = ap.parse_args(argv)
    if a.preflight:
        return preflight()
    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.datetime.now(TZ).date() - dt.timedelta(days=1))
    if a.recon:
        _log(f"Sara RECON for {day:%A %m/%d}")
        _scrape(day, recon=True)
        return 0
    _log(f"Sara reconcile for {day:%A %m/%d} — B2B only")
    return reconcile(day, a.yes)


if __name__ == "__main__":
    sys.exit(main())
