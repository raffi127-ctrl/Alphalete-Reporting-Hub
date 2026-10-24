"""NDS Sales Board fill from Carlos's NDS SaraPlus -- the ICD relay when it
carries an NDS read, else a direct SaraPlus read from this machine.

THE RULE, IN CARLOS'S WORDS (2026-10-23): "use sara plus [to fill the NDS Sales
Board] but look at the way that Lucy uses sara plus for the order log to make
sure you include the correct sales. upgrades, tablets, and wearables shouldn't
get added." -- "We just started selling under my NDS SaraPlus this Monday
[10/19]."

WHAT A REP'S DAY IS:            units = Int + NL + Air

    Int   = Internet Sales - Internet Upgrades - AIA        (shared/sale_hype.metrics_for)
    NL    = New Lines + Port Lines - Tablets - Wearables    (icd_alerts/relay._nds_lines,
            read off the Wireless grid -- the way Lucy already reads an NDS
            office for the sale alerts and the text scoreboard)
    Air   = AIA                                             (Carlos 2026-10-23: Internet
            Air is a new internet sale under NDS, not an upgrade)

WHAT IS NOT:
    Int Up   = Internet Upgrades + AIA + Upgrade Lines   -- upgrades, never a unit
    Tablets, Wearables                                    -- already taken out of NL
    DTV                                                   -- not counted; shown per rep

So upgrades, tablets and wearables cannot reach the board by construction:
they are not inside any number that gets added up. (UNIT_KEYS is the one
place to change if Carlos ever wants DTV counted.)

TWO SOURCES, ONE SET OF NUMBERS (--source auto | relay | sara, default auto):

  relay  Carlos's office Mac mini runs the icd_alerts agent against his
         SaraPlus and relays every rep's totals-so-far-today, every few
         minutes, to the 'ICD Relay' tab of the Lucy Access App workbook
         (icd_alerts/post.RELAY_SPREADSHEET_ID / RELAY_TAB). ONE ROW PER
         OFFICE PER DAY, updated in place; the newest 'Received At' wins.
         Only an office enrolled as campaign "nds" counts (key starting with
         "carlos"; `--office KEY` pins it): relay._nds_lines takes tablets,
         wearables and upgrade lines out of NL for THAT campaign only, so an
         "att" / "b2b_att" enrolment's NL still carries them -- exactly what
         Carlos does not want on the board. The 2am catch-up on the mini
         re-reads yesterday whole, so the 5am pass closes the day on final
         numbers.

  sara   This machine logs into the NDS SaraPlus itself (shared/saraplus,
         patchright, headless, the login_healing pattern alphalete_sales_board
         uses) and makes the SAME two reads the relay's agent makes for an
         NDS office, for the one day:
           'AT&T'    -> GRID_ATT     -> parse_att   -> Int / Int Up / Air per rep
           'Wireless'-> GRID_WIRELESS-> parse_lines -> New / Port / Upgrade Lines,
                                                       Tablets, Wearables per rep
         and derives the identical per-rep dict (metrics_from_grids): Int,
         Int Up, DTV (0 -- the 'All' pass is not made; DTV is not counted),
         NL, Air. A rep only on the Wireless grid has Int / Air 0; a rep only
         on the AT&T grid has NL 0 -- never SaraPlus's raw line count, which
         includes the tablets. If the Wireless grid's labels are not found
         (parse_lines None), the run HOLDS: falling back to the raw count
         would re-include the very things Carlos excluded. A sales grid that
         is drawn but has no agent rows is re-read once and then HELD too
         (shared.saraplus.att_shape_problem) -- an unparseable grid must not
         read as a quiet day under a rule that SETS reps down.
         Login: ~/.config/recruiting-report/saraplus-nds-creds.json
         ({"email", "password"}; or SARAPLUS_NDS_EMAIL / SARAPLUS_NDS_PASSWORD),
         profile ~/.config/recruiting-report/saraplus-nds-profile -- see
         config.py for why neither is shared with any other SaraPlus reader.
         On the laptop: python -m automations.vantura_nds_sara.set_credentials
         --push "Lucy 2".

  auto   relay when an nds enrolment relayed for the day; else sara when the
         login exists; else HOLD naming both ("no nds relay ...; no creds
         file at ..."). The registry's base_args stay --fill --yes; the module
         decides the source, so the launchd wrapper never changed.

HOW IT WRITES -- Megan's SaraPlus-is-the-truth design (2026-07-26,
vantura_slack_sales/sara.plan_overwrite, reused, not copied):
  * a matched rep is SET to SaraPlus's count, up OR down;
  * a board rep absent from SaraPlus is LEFT as-is, flagged;
  * a SaraPlus rep with no board row is flagged, never guessed, never written.
Plus the board's own conventions, the BOX order-log fill's exact rule
(vantura_orderlog_sales.fill_plan): a hand-typed marker (T / X / F / any
non-number) is kept unless SaraPlus shows sales; a count of 0 writes a BLANK
(the board's convention: blank = none).

NAMES. SaraPlus writes legal names in caps ("JACOB ISAIAH ORTEGA"); the board
writes the name the rep goes by ("Jacob Ortega"). ALIASES below first, then
vantura_slack_sales.run.match_rep (exact, then first + last token), then the
order-log fill's legal-first-name map (NICOLAS -> nico). Nothing guesses:
a name that reaches no row is flagged with its count and left for a person.

WHEN. Same clock as the Slack fill: before 10am (OFFICE_DAY_START) the run
closes out YESTERDAY, after it it fills TODAY; --date overrides. Holds, all
exit 75 and nothing written: no source for the day (no nds relay and no
login; "the office mini may be off"), the Wireless labels not found, the
sales grid unreadable twice, the board's gold WE cell on another week, no
column for the day. A SaraPlus login / read that FAILS outright (SaraError:
bounced login, passcode wall, site down) exits 1 -- red, not amber -- with
the site's own words, nothing written.

  python -m automations.vantura_nds_sara.run --preflight    # patchright? creds file? profile dir? exit 0/1 -- nothing else touched
  python -m automations.vantura_nds_sara.run --probe        # which source, the raw numbers, the board column; no writes
  python -m automations.vantura_nds_sara.run --probe --source sara   # force the direct read for the probe
  python -m automations.vantura_nds_sara.run                # dry report
  python -m automations.vantura_nds_sara.run --fill         # plan the write
  python -m automations.vantura_nds_sara.run --fill --yes   # write
  python -m automations.vantura_nds_sara.run --date 2026-10-22 --probe
  python -m automations.vantura_nds_sara.run --office carlos-b2batt --probe

  lucy rerun vantura_nds_sara --preflight
  lucy rerun vantura_nds_sara --probe --date 2026-10-23
  lucy rerun vantura_nds_sara --probe --source sara --date 2026-10-23

--preflight, --probe and --dry win over --fill --yes (so `lucy rerun
vantura_nds_sara --probe` is safe: the registry's base_args are --fill --yes).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Callable, Dict, List, Optional, Tuple

from automations.icd_alerts import post as P
from automations.shared import sale_hype as H
from automations.shared import saraplus as SP
from automations.vantura_nds_sara import config as CFG
from automations.vantura_orderlog_sales.run import FIRST_NAME_ALIASES
from automations.vantura_slack_sales import run as R
from automations.vantura_slack_sales import sara as S
from automations.vantura_slack_sales.parse import TZ

REPORT_ID = "vantura_nds_sara"                  # schedule_config id
# The board's campaign key. Still "B2B" inside the Lucy modules; vantura_boards
# .tab_for("B2B") lands on the "NDS Sales Board" tab (NDS on the sheet since
# 2026-10-03), and campaign_rows reads the rows that say NDS (or legacy B2B).
CAMPAIGN = "B2B"
# The enrolment campaign the relay must carry. relay._nds_lines only takes
# tablets / wearables / upgrade lines out of NL for THIS campaign.
RELAY_CAMPAIGN = "nds"
OFFICE_KEY_PREFIX = "carlos"
# What is added up. Everything else in the relay JSON is shown, never summed.
UNIT_KEYS = ("Int", "NL", "Air")   # 2026-10-23: AT&T Internet Air is a new internet sale under NDS, not an upgrade - it counts
SHOWN_KEYS = ("Int", "NL", "Int Up", "Air", "DTV")
# 75 = EX_TEMPFAIL, the hold code every Vantura fill uses: nothing written,
# the next pass retries, the wrapper publishes `partial` (amber), not failed.
EXIT_HOLD = 75
# A SaraPlus login or read that failed outright: nothing written, and the
# wrapper publishes `failed` (red) -- somebody has to look, waiting will not fix it.
EXIT_FAIL = 1
SOURCES = ("auto", "relay", "sara")
# The two reads the direct source makes, by the shared module's own names.
SERVICE_ATT = "AT&T"

# SaraPlus spelling (UPPER, as the relay keys it) -> the board's REP cell.
# Only what match_rep's exact / first + last rule and the legal-first-name map
# cannot reach. Justified off the live NDS board roster (read 2026-10-23, WE
# 10.25): every other row -- "JACOB ISAIAH ORTEGA" -> "Jacob Ortega", "DIEGO
# JAVIER DEL POZO BORRES" -> "Diego Borres", "AARON DE LA TORRE" vs "ANDREW
# DE LA TORRE", "JOSE MANUEL PIMENTEL LUGO", "BRAYAN VAZQUEZ ESPINOZA" --
# resolves on first + last token by itself.
ALIASES = {
    "NICHOLAS SMEDRA": "Nick Smedra",        # board row 7, 27th Wk
    "NICOLAS MURRUGARRA": "Nico Murrugarra",  # runs the office; sells one now and then
}


def _log(msg: str) -> None:
    R._log(msg)


def _n(v) -> int:
    """A relay metric as a count: ints and numeric strings, floored at 0
    (metrics_for already floors; a revised-down SaraPlus number has no board
    representation), anything unreadable is 0."""
    try:
        return max(int(float(str(v).strip() or 0)), 0)
    except (TypeError, ValueError):
        return 0


# ----------------------------------------------------------------- units --
def units_for(sales: Optional[Dict]) -> Dict[str, Dict[str, int]]:
    """{SaraPlus name: {units, Int, NL, Int Up, Air, DTV[, Credit Checked,
    Credit Passed]}} off one relay 'Sales JSON' blob.

    units = Int + NL, nothing else (see the module docstring). The other
    metrics ride along so the log can say what was NOT counted and why a rep
    with activity shows 0 units.
    """
    out: Dict[str, Dict[str, int]] = {}
    for rep, m in sorted((sales or {}).items()):
        m = m if isinstance(m, dict) else {}
        row = {k: _n(m.get(k, 0)) for k in SHOWN_KEYS}
        for k in P.CREDIT_KEYS:
            if k in m:
                row[k] = _n(m.get(k))
        row["units"] = sum(row[k] for k in UNIT_KEYS)
        name = str(rep).strip()
        if name:
            out[name] = row
    return out


# ----------------------------------------------------------------- relay --
def office_of(row: List[str]) -> str:
    return (row[P.COL_OFFICE] if len(row) > P.COL_OFFICE else "").strip().lower()


def snapshot_of(rownum: int, row: List[str]) -> Dict:
    """One relay row, by the column positions post.py reads."""
    def col(i: int) -> str:
        return (row[i] if len(row) > i else "").strip()
    return {
        "rownum": rownum,
        "office": office_of(row),
        "received_raw": col(P.COL_RECEIVED),
        "received": P._parse_received(col(P.COL_RECEIVED)),
        "local_time": col(P.COL_LOCAL_TIME),
        "agent": col(P.COL_AGENT),
        "sales": P._loads(col(P.COL_SALES)) or {},
        "records": P._loads(col(P.COL_RECORDS)) or {},
    }


def _order(snap: Dict) -> tuple:
    # An unparseable 'Received At' sorts before any parsed one; a tie (two
    # rows stamped alike) goes to the lower row -- the one the Apps Script
    # upsert actually updates.
    return (snap["received"] or dt.datetime.min, -snap["rownum"])


def latest_snapshot(rows: List[Tuple[int, List[str]]],
                    office_key: str) -> Optional[Dict]:
    """The newest relay row of `office_key` among `rows` (post._rows_for's
    (rownum, row) pairs for one day), or None when the office has none."""
    key = (office_key or "").strip().lower()
    best = None
    for rownum, row in rows:
        if office_of(row) != key:
            continue
        snap = snapshot_of(rownum, row)
        if best is None or _order(snap) > _order(best):
            best = snap
    return best


def office_campaign(key: str) -> Optional[str]:
    """The enrolment campaign of an office that exists AND is switched on
    (icd_alerts/offices.py + the ICD Signup tab); None for anything else, the
    same offices post.run ignores."""
    from automations.icd_alerts import offices as O
    o = O.get(key)
    return str(o.campaign or "").strip().lower() if (o and o.active) else None


def pick_office(rows: List[Tuple[int, List[str]]], office_key: str = "",
                lookup: Callable[[str], Optional[str]] = office_campaign
                ) -> Tuple[Optional[str], str, Dict[str, Optional[str]]]:
    """(office key, why-not, {relayed key: campaign}).

    With `office_key` the pick is pinned but still has to be the NDS campaign.
    Without it: the one key starting with OFFICE_KEY_PREFIX whose enrolment
    says RELAY_CAMPAIGN. None with a reason when there is no such office or
    more than one -- never a guess.
    """
    seen: Dict[str, Optional[str]] = {}
    for _rownum, row in rows:
        k = office_of(row)
        if k and k not in seen:
            seen[k] = lookup(k)
    if office_key:
        k = office_key.strip().lower()
        if k not in seen:
            return None, "%s has not relayed for this day" % k, seen
        camp = seen[k]
        if (camp or "") != RELAY_CAMPAIGN:
            return None, ("%s relays as campaign %r, not %r -- its NL would "
                          "still carry tablets and upgrade lines; fix the "
                          "enrolment before filling from it"
                          % (k, camp or "unknown / not enrolled",
                             RELAY_CAMPAIGN)), seen
        return k, "", seen
    cands = sorted(k for k, c in seen.items()
                   if k.startswith(OFFICE_KEY_PREFIX) and (c or "") == RELAY_CAMPAIGN)
    if len(cands) == 1:
        return cands[0], "", seen
    ours = ", ".join("%s (%s)" % (k, c or "not enrolled")
                     for k, c in sorted(seen.items())
                     if k.startswith(OFFICE_KEY_PREFIX))
    if not cands:
        return None, ("no %s* office enrolled as %r relayed for this day%s"
                      % (OFFICE_KEY_PREFIX, RELAY_CAMPAIGN,
                         " -- relayed: " + ours if ours else "")), seen
    return None, ("%d %s* offices relay as %r (%s) -- pass --office"
                  % (len(cands), OFFICE_KEY_PREFIX, RELAY_CAMPAIGN,
                     ", ".join(cands))), seen


def relay_rows(day: dt.date) -> List[Tuple[int, List[str]]]:
    """Every relay row of `day`, through post.py's own reader (one read of
    the tab, retried like every other Sheets read)."""
    from automations.recruiting_report.fill import _retry
    tab = P._relay_tab()
    return _retry(P._rows_for, day, tab)


# -------------------------------------------------------- direct SaraPlus --
def metrics_from_grids(att: List[Dict], lines: Optional[Dict[str, Dict[str, int]]]
                       ) -> Dict[str, Dict[str, int]]:
    """{UPPER NAME: {Int, Int Up, DTV, NL, Air}} off the two grids -- the dict
    the relay's agent would have sent for an NDS office, built the same way:

        AT&T grid row  -> sale_hype.metrics_for   (Int / Int Up / Air; floored)
        Wireless row   -> relay._nds_lines' rule  NL = New + Port - Tablets - Wearables
                                                  (floored), Int Up += Upgrade Lines

    The AT&T grid's own 'Wireless Lines Sold' is NEVER used for NL: that count
    is the one with the tablets and the upgrade lines in it. A rep on the
    Wireless grid only has Int / Air 0; a rep on the AT&T grid only has NL 0.
    DTV is 0 -- the 'All' pass is not made (not counted; shown).

    `lines` None means the Wireless grid could not be read by label, and
    there is no honest number to put in NL -- so it is refused here, not
    papered over: the caller holds (sara_problem) before ever getting here.
    Names go through strip_office (upper, office code off) on both sides, the
    way sara_read keys the relay. A name on two AT&T rows (a rep under two
    campaign nodes) is summed, like every other shared parser does.
    """
    if lines is None:
        raise ValueError("the Wireless grid was not read by label -- no NL to derive")
    out: Dict[str, Dict[str, int]] = {}

    def row_for(name: str) -> Optional[Dict[str, int]]:
        key = SP.strip_office(name)
        if not key:
            return None
        return out.setdefault(key, {k: 0 for k in SHOWN_KEYS})

    for a in att or []:
        row = row_for(str(a.get("name") or ""))
        if row is None:
            continue
        m = H.metrics_for(a)
        row["Int"] += m["Int"]
        row["Int Up"] += m["Int Up"]
        row["Air"] += m["Air"]
        # m["NL"] is wireless_lines_sold: deliberately dropped (see above).
        # m["DTV"] is 0 off the AT&T grid (parse_att sets it so).
    for name, got in sorted((lines or {}).items()):
        row = row_for(str(name))
        if row is None:
            continue
        got = got or {}
        row["NL"] += max(_n(got.get("New Lines", 0)) + _n(got.get("Port Lines", 0))
                         - _n(got.get("Tablets", 0)) - _n(got.get("Wearables", 0)), 0)
        row["Int Up"] += _n(got.get("Upgrade Lines", 0))
    return out


def sara_problem(read: Dict) -> str:
    """Why a direct read must NOT be turned into a board write. "" when it may.

    Both are holds, not failures: the site answered, but not in a shape the
    numbers can be trusted from, and the next pass may well read it fine."""
    if read.get("shape_problem"):
        return ("the AT&T sales grid could not be read as rep rows, twice (%s) "
                "-- not treating that as a day with no sales"
                % str(read["shape_problem"])[:200])
    if read.get("lines") is None:
        return ("the Wireless grid has no %s labels (headers read: %s) -- "
                "NL cannot be derived without them, and SaraPlus's raw line "
                "count would put the tablets, wearables and upgrade lines back "
                "in, so nothing is written"
                % (" / ".join(SP.LINE_LABELS),
                   ", ".join(h for h in (read.get("wireless_headers") or []) if h) or "none"))
    return ""


def _login(playwright, profile_dir, creds: Dict[str, str], *, headless: bool = True,
           log=_log):
    """(ctx, page, base) -- shared.saraplus.login_healing on this module's
    own profile, exactly the way alphalete_sales_board signs in (a stuck
    profile heals itself there). The caller owns ctx.

    ONE EXTRA STEP, for the day the profile is brand new. SaraPlus challenges
    a browser it has never seen with an emailed passcode -- SaraPasscodeWall;
    Khalil's laptop 2026-09-18, nds_metrics' first Lucy 2 login 2026-10-22 --
    and the shared login cannot answer it (its own docstring: a person has to
    type the code). rc_contact_sync.sara.login CAN, by reading the code from
    the reporting inbox, which is how nds_metrics got through. So the wall is
    handed to it once, on the same profile; after that the profile is trusted
    and the shared login carries on alone. If the code never reaches that
    inbox (no forward on this account), rc's own clear error comes back
    inside the wall's, and nothing was read.
    """
    # 2026-10-23: a COPY of nds_metrics' profile did not carry SaraPlus's
    # browser trust (the passcode wall came back on the copy). So when that
    # trusted profile exists on this box, sign in ON IT, the way nds_metrics
    # does every morning (rc_contact_sync.sara.login on
    # automations/uploaded/.saraplus_nds_profile). The two never run at the
    # same time (nds_metrics ~7am, this fill 4-9pm + 5am).
    # 2026-10-24: SaraPlus mails THIS login's passcode to alphaletegp's own
    # inbox (config.CODE_INBOX_ACCOUNT) -- read there directly when its app
    # password is on this box, else from the reporting inbox the forward feeds.
    inbox = CFG.code_inbox()
    log(CFG.code_inbox_status())
    seed = CFG.seed_profile_dir()
    if (seed / "Default").exists():
        from automations.rc_contact_sync import sara as RC
        ctx = playwright.chromium.launch_persistent_context(
            str(seed), headless=headless, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = RC.login(page, creds["email"], creds["password"], log=log,
                            code_inbox=inbox)
        except Exception as e:  # noqa: BLE001 -- say which profile, then fall through to ours
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
            log("login on nds_metrics' trusted profile failed (%s: %s) -- trying this module's own profile"
                % (type(e).__name__, str(e)[:200]))
        else:
            log("logged in on nds_metrics' trusted profile %s" % seed)
            return ctx, page, base
    try:
        return SP.login_healing(playwright, profile_dir, creds["email"],
                                creds["password"], headless=headless,
                                creds_hint=str(CFG.creds_path()), log=log)
    except SP.SaraPasscodeWall as wall:
        log("SaraPlus wants an emailed passcode for this browser -- answering "
            "it from %s (rc_contact_sync.sara.login), once"
            % (inbox[0] if inbox else "the reporting inbox"))
        from automations.rc_contact_sync import sara as RC
        ctx = SP.open_context(playwright, profile_dir, headless=headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = RC.login(page, creds["email"], creds["password"], log=log,
                            code_inbox=inbox)
        except Exception as e:  # noqa: BLE001 -- the wall stands; say both
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
            raise SP.SaraPasscodeWall(
                "%s -- and the reporting-inbox route could not clear it either "
                "(%s: %s)" % (wall, type(e).__name__, str(e)[:300])) from e
        log("  passcode cleared -- this profile is trusted from here on")
        return ctx, page, base


def read_sara(day: dt.date, creds: Dict[str, str], *, profile_dir=None,
              headless: bool = True, log=_log) -> Dict:
    """One browser session, two passes, for ONE day:

        {'att': parse_att rows, 'lines': parse_lines dict or None,
         'wireless_headers': [...], 'att_rows': n, 'wireless_rows': n,
         'shape_problem': '', 'read_at': datetime, 'timings': '...'}

    Raises SaraError (login bounced, passcode wall, a pass that failed every
    retry). The mechanics -- Telerik date blob, service combo, grid waits,
    retries -- are all shared.saraplus's; nothing here re-derives a selector.
    """
    from patchright.sync_api import sync_playwright

    profile_dir = profile_dir or CFG.ensure_profile_seeded(_log)
    try:
        SP.reset_pass_timings()
    except Exception:  # noqa: BLE001 -- instrumentation must never cost a read
        pass
    out: Dict = {"att": [], "lines": None, "wireless_headers": [], "att_rows": 0,
                 "wireless_rows": 0, "shape_problem": "", "read_at": None,
                 "timings": ""}
    with sync_playwright() as p:
        ctx, page, base = _login(p, profile_dir, creds, headless=headless, log=log)
        try:
            log("logged in: %s" % base)
            att_rows = SP._run_report(page, base, day, SERVICE_ATT, SP.GRID_ATT, log=log)
            # ASKED TWICE BEFORE IT IS BELIEVED (sara_read's rule): a grid of
            # history rows with no agent rows is usually a page caught
            # mid-render, and SaraPlus is slow enough for that to be common.
            problem = SP.att_shape_problem(att_rows)
            if problem:
                log("sales grid looks wrong (%s) -- reading it again" % problem[:60])
                att_rows = SP._run_report(page, base, day, SERVICE_ATT, SP.GRID_ATT, log=log)
                problem = SP.att_shape_problem(att_rows)
                if not problem:
                    log("second read was fine -- the first was still rendering")
            out["shape_problem"] = problem
            out["att_rows"] = len(att_rows)
            out["att"] = SP.parse_att(att_rows)
            log("AT&T pass: %d row(s), %d rep(s)" % (len(att_rows), len(out["att"])))

            w_rows = SP._run_report(page, base, day, SP.SERVICE_WIRELESS,
                                    SP.GRID_WIRELESS, log=log)
            out["wireless_headers"] = SP.grid_headers(page, SP.GRID_WIRELESS) or []
            out["wireless_rows"] = len(w_rows)
            out["lines"] = SP.parse_lines(out["wireless_headers"], w_rows)
            if out["lines"] is None:
                log("Wireless pass: %d row(s) but the %s labels were NOT found"
                    % (len(w_rows), " / ".join(SP.LINE_LABELS)))
            else:
                log("Wireless pass: %d row(s), lines for %d rep(s)"
                    % (len(w_rows), len(out["lines"])))
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    out["read_at"] = dt.datetime.now(TZ)
    try:
        out["timings"] = SP.pass_timings_summary()
    except Exception:  # noqa: BLE001
        pass
    return out


def choose_source(source: str, relay_key: Optional[str], relay_why: str,
                  have_creds: bool, creds_why: str) -> Tuple[Optional[str], str]:
    """('relay' | 'sara' | None, why-not).

    auto: the relay when an nds enrolment relayed for the day, else the direct
    read when the login exists, else nothing -- and the reason names BOTH, so
    the log says what to fix. A pinned source never touches the other one.
    """
    no_relay = "no nds relay for the day (%s)" % (relay_why or "nothing relayed")
    if source == "relay":
        if relay_key:
            return "relay", ""
        return None, no_relay + " -- --source relay never reads SaraPlus directly"
    if source == "sara":
        if have_creds:
            return "sara", ""
        return None, creds_why + " -- --source sara never reads the relay"
    if relay_key:
        return "relay", ""
    if have_creds:
        return "sara", ""
    return None, "%s; %s" % (no_relay, creds_why)


def _patchright_status() -> Tuple[bool, str]:
    try:
        import patchright
        from patchright.sync_api import sync_playwright  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])
    return True, getattr(patchright, "__version__", None) or "version unknown"


def preflight(log=_log) -> int:
    """Can the direct read run HERE? patchright importable, the login present
    (never the password), the profile dir -- and nothing else: no Sheets, no
    relay, no browser, no network. 0 when it can, 1 when it cannot."""
    ok = True
    good, detail = _patchright_status()
    if good:
        log("patchright: ok (%s)" % detail)
    else:
        ok = False
        log("patchright: MISSING (%s) -- the direct SaraPlus read cannot run on "
            "this machine" % detail)
    cr, why, _exists = CFG.creds_status()
    if cr:
        log("creds: ok -- %s" % why)
    else:
        ok = False
        log("creds: MISSING -- %s" % why)
    prof = CFG.ensure_profile_seeded(_log)
    log("profile dir: %s (%s)" % (prof, "exists" if prof.exists()
                                  else "not yet -- created on the first login"))
    log(CFG.code_inbox_status())
    log("PREFLIGHT %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def passcode_mail(log=_log, days: int = 3, limit: int = 12,
                  query: Optional[str] = None) -> int:
    """WHERE THE CODES ARE LANDING. The last `limit` SaraPlus passcode mails
    in the inbox the login reads (config.code_inbox() or the reporting inbox):
    when SaraPlus sent each (its Date header), the address it was sent TO
    (which SaraPlus account it belongs to) and when it ARRIVED in this inbox
    (IMAP INTERNALDATE) -- the gap is the forward's delay. Never the code
    itself. 0 when the inbox could be read, 1 when it could not.

    `query` swaps the Gmail search (--mail-query) -- e.g. the forwarding
    confirmation Google sends the reporting inbox when a forward to it is
    set up elsewhere and still unconfirmed. Headers only, never bodies."""
    import email as _email
    import imaplib
    import time as _time
    from email.utils import parsedate_to_datetime
    from automations.rc_contact_sync import verify_code as VC
    log(CFG.code_inbox_status())
    try:
        account, password = VC._inbox(CFG.code_inbox())
    except Exception as e:  # noqa: BLE001 -- no password here, or no file
        log("passcode inbox unreadable: %s" % str(e)[:300])
        return EXIT_FAIL
    M = imaplib.IMAP4_SSL(VC._ing.IMAP_HOST)
    try:
        M.login(account, password)
        M.select('"[Gmail]/All Mail"', readonly=True)
        q = query or ("from:security.info@saraplus.com newer_than:%dd" % days)
        typ, data = M.search(None, "X-GM-RAW", '"%s"' % q.replace('"', "'"))
        uids = (data[0] or b"").split() if typ == "OK" else []
        log("mail in %s matching %r: %d" % (account, q, len(uids)))
        for uid in list(reversed(uids))[:limit]:
            typ, d = M.fetch(uid, "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (DATE TO SUBJECT)])")
            if typ != "OK" or not d or not d[0]:
                continue
            meta = d[0][0] if isinstance(d[0][0], bytes) else b""
            msg = _email.message_from_bytes(d[0][1])
            arrived = None
            try:
                tup = imaplib.Internaldate2tuple(meta)
                if tup:
                    arrived = dt.datetime.fromtimestamp(_time.mktime(tup))
            except Exception:  # noqa: BLE001
                pass
            try:
                sent = parsedate_to_datetime(msg.get("Date"))
                sent_local = sent.astimezone().replace(tzinfo=None) if sent.tzinfo else sent
            except Exception:  # noqa: BLE001
                sent_local = None
            gap = ("%+ds" % (arrived - sent_local).total_seconds()
                   if arrived and sent_local else "?")
            log("  sent %s  to %s  arrived here %s  (%s)  %s"
                % (sent_local.strftime("%m/%d %H:%M:%S") if sent_local else "?",
                   (msg.get("To") or "?").strip()[:60],
                   arrived.strftime("%m/%d %H:%M:%S") if arrived else "?",
                   gap, (msg.get("Subject") or "").strip()[:40]))
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return 0


# ----------------------------------------------------------------- names --
def _legal_first(name: str) -> str:
    """'NICOLAS MURRUGARRA' -> 'nico murrugarra': the order-log fill's map of
    legal first names to the ones the board uses (william/nicholas/nicolas/
    jeffrey), applied to the normalised name."""
    parts = R._norm(name).split()
    if parts and parts[0] in FIRST_NAME_ALIASES:
        parts[0] = FIRST_NAME_ALIASES[parts[0]]
    return " ".join(parts)


def candidates(sara_name: str) -> List[str]:
    """The spellings to try on the board, in order: the alias, the SaraPlus
    name itself, the name with its legal first name swapped."""
    name = str(sara_name or "").strip()
    out = []
    alias = ALIASES.get(name.upper())
    if alias:
        out.append(alias)
    out.append(name)
    legal = _legal_first(name)
    if legal and legal != R._norm(name):
        out.append(legal)
    return out


def board_key(sara_name: str, rows: Dict[str, int]) -> Optional[str]:
    """SaraPlus name -> campaign_rows key, or None (flagged by the caller)."""
    for cand in candidates(sara_name):
        key = R.match_rep(cand, rows)
        if key:
            return key
    return None


# ------------------------------------------------------------------ plan --
def board_rules(writes: List[tuple]) -> List[tuple]:
    """plan_overwrite's (name, a1, old, new) writes, through the board's own
    conventions -- the BOX order-log fill's exact rule: a hand-typed marker
    (T / X / F / anything non-numeric) is kept unless SaraPlus shows sales;
    a count of 0 writes a BLANK (the board's convention: blank = none).
    Returns (name, a1, current, new, note) like every other Vantura fill."""
    plan = []
    for name, a1, old, new in writes:
        cur = "" if str(old) == "(blank)" else str(old).strip()
        new = int(new)
        note = ""
        if cur.isdigit():
            if new == int(cur):
                continue
            if new < int(cur):
                note = ("  (LOWERED to SaraPlus)" if new
                        else "  (cleared -- SaraPlus shows 0 units)")
        elif cur:
            if not new:
                continue                      # keep the marker (T/X/F...)
            note = "  (replaces marker %r)" % cur
        elif not new:
            continue                          # blank -> blank
        plan.append((name, a1, cur or "(blank)",
                     str(new) if new else "(blank)", note))
    return plan


def plan(g, col: int, rows: Dict[str, int],
         per_rep: Dict[str, Dict[str, int]]) -> Tuple[List[tuple], List[str]]:
    """(plan, flags) for setting the day column from the relay snapshot.

    The overwrite itself is sara.plan_overwrite -- matched rep SET up or
    down, board rep absent from SaraPlus LEFT as-is and flagged, SaraPlus rep
    on no row flagged. Here: the names are resolved first (ALIASES, match_rep,
    legal first name) and matched reps are keyed by the board's own REP cell,
    so two SaraPlus spellings landing on one row are summed, not raced; a rep
    with 0 units and no row is nothing to flag; then board_rules.
    """
    counts: Dict[str, int] = {}
    flags: List[str] = []
    by_row: Dict[str, List[str]] = {}
    for sara_name, m in sorted(per_rep.items()):
        key = board_key(sara_name, rows)
        if key is None:
            if m["units"]:
                counts[sara_name] = counts.get(sara_name, 0) + int(m["units"])
            continue
        disp = R._cell(g, rows[key], R.NAME_COL).strip() or key
        by_row.setdefault(disp, []).append(sara_name)
        counts[disp] = counts.get(disp, 0) + int(m["units"])
    for disp, names in sorted(by_row.items()):
        if len(names) > 1:
            flags.append("%s is %d SaraPlus names (%s) -- their units are "
                         "summed on the one row" % (disp, len(names),
                                                     ", ".join(names)))
    writes, oflags = S.plan_overwrite(g, col, rows, counts)
    return board_rules(writes), flags + oflags


def batch_values(plan_rows: List[tuple]) -> List[Dict]:
    """The batch_update payload: a number, or "" for a cleared cell."""
    return [{"range": a1,
             "values": [[int(new) if new != "(blank)" else ""]]}
            for _name, a1, _cur, new, _note in plan_rows]


# ------------------------------------------------------------------- day --
def target_day(now: Optional[dt.datetime] = None) -> dt.date:
    """Before OFFICE_DAY_START the run is closing out YESTERDAY; after it,
    filling TODAY (the Slack fill's rule, same constant)."""
    now = now or dt.datetime.now(TZ)
    if now.hour >= R.OFFICE_DAY_START:
        return now.date()
    return now.date() - dt.timedelta(days=1)


# ---------------------------------------------------------------- report --
def load_board():
    """(worksheet, grid) of the NDS board -- the Slack fill's own reader."""
    return R.board_grid(CAMPAIGN)


def describe_relay(snap: Dict, log=_log) -> None:
    """Where the relay numbers came from: the row, the office, the stamp."""
    when = snap["received"].strftime("%m/%d %H:%M:%S") if snap["received"] \
        else (snap["received_raw"] or "?")
    log("relay row %d: %s relayed at %s (agent %s, mini clock %s) -- "
        "%d rep(s) with sales, %d with credit checks"
        % (snap["rownum"], snap["office"], when, snap["agent"] or "?",
           snap["local_time"] or "?", len(snap["sales"]),
           len(snap["records"])))


def describe_sara(read: Dict, day: dt.date, log=_log) -> None:
    """The direct read, RAW, both grids, rep by rep -- what --probe shows so
    the derived numbers can be checked against the dashboard by eye."""
    when = read["read_at"].strftime("%m/%d %H:%M:%S") if read.get("read_at") else "?"
    log("SaraPlus direct read for %s at %s: AT&T grid %d row(s) / %d rep row(s); "
        "Wireless grid %d row(s) / %s"
        % (R._md(day), when, read.get("att_rows", 0), len(read.get("att") or []),
           read.get("wireless_rows", 0),
           "labels NOT found" if read.get("lines") is None
           else "%d rep(s) with lines" % len(read["lines"])))
    if read.get("shape_problem"):
        log("  ! %s" % read["shape_problem"])
    log("  %-30s %8s %8s %6s %10s" % ("AT&T grid (raw)", "IntSales", "IntUpgr",
                                      "AIA", "LinesSold*"))
    for a in sorted(read.get("att") or [], key=lambda a: str(a.get("name") or "")):
        log("  %-30s %8d %8d %6d %10d"
            % (str(a.get("name") or "")[:30], _n(a.get("internet_sales")),
               _n(a.get("internet_upgrades")), _n(a.get("aia_sales")),
               _n(a.get("wireless_lines_sold"))))
    log("  (* LinesSold is SaraPlus's own line count -- tablets, wearables and "
        "upgrade lines included -- shown, never used)")
    if read.get("lines") is None:
        log("  Wireless grid (raw): the %s labels were not found; headers read: %s"
            % (" / ".join(SP.LINE_LABELS),
               ", ".join(h for h in (read.get("wireless_headers") or []) if h) or "none"))
    else:
        log("  %-30s %5s %5s %5s %8s %9s" % ("Wireless grid (raw)", "New", "Port",
                                             "Upgr", "Tablets", "Wearables"))
        for name, got in sorted(read["lines"].items()):
            got = got or {}
            log("  %-30s %5d %5d %5d %8d %9d"
                % (str(name)[:30], _n(got.get("New Lines")), _n(got.get("Port Lines")),
                   _n(got.get("Upgrade Lines")), _n(got.get("Tablets")),
                   _n(got.get("Wearables"))))
    if read.get("timings"):
        log("  passes: %s" % read["timings"])


def describe(snap: Dict, per_rep: Dict[str, Dict[str, int]], g,
             rows: Dict[str, int], col: Optional[int], log=_log) -> None:
    """The relay snapshot next to the board, rep by rep -- what every mode
    prints before deciding anything."""
    describe_relay(snap, log=log)
    describe_reps(per_rep, g, rows, col, log=log)


def describe_reps(per_rep: Dict[str, Dict[str, int]], g, rows: Dict[str, int],
                  col: Optional[int], log=_log) -> None:
    """The derived per-rep numbers next to the board, whichever source they
    came from: units, what counted, what did not, where it lands."""
    log("  %-30s %5s   %s   %s   %s" % ("SaraPlus rep", "units", "counted",
                                        "not counted", "board"))
    matched = set()
    for name, m in sorted(per_rep.items(), key=lambda kv: (-kv[1]["units"], kv[0])):
        key = board_key(name, rows)
        if key:
            matched.add(key)
            on = str(R._cell(g, rows[key], col)).strip() if col else "?"
            where = "%s = %s" % (R._cell(g, rows[key], R.NAME_COL).strip(),
                                 on or "(blank)")
        elif m["units"]:
            where = "! NO ROW on the NDS board"
        else:
            where = "(0 units, not on the board)"
        cc = ""
        if "Credit Checked" in m or "Credit Passed" in m:
            cc = "  cc %d/%d" % (m.get("Credit Checked", 0),
                                 m.get("Credit Passed", 0))
        log("  %-30s %5d   Int %d + NL %d   Up %d Air %d DTV %d%s   -> %s"
            % (name, m["units"], m["Int"], m["NL"], m["Int Up"], m["Air"],
               m["DTV"], cc, where))
    log("  %-30s %5d" % ("TOTAL", sum(m["units"] for m in per_rep.values())))
    if col:
        rest = [(R._cell(g, r, R.NAME_COL).strip(), str(R._cell(g, r, col)).strip())
                for key, r in sorted(rows.items(), key=lambda kv: kv[1])
                if key not in matched]
        if rest:
            log("  on the board, not in SaraPlus today (left as-is): "
                + ", ".join("%s = %s" % (n, v or "(blank)") for n, v in rest))


def _column_dump(g, rows: Dict[str, int], col: Optional[int], day: dt.date,
                 log=_log) -> None:
    log("board column for %s: %s" % (R._md(day), "none" if not col else
                                     "col %d" % col))
    if col:
        for key, r in sorted(rows.items(), key=lambda kv: kv[1]):
            log("  %-30s %s" % (R._cell(g, r, R.NAME_COL).strip(),
                                str(R._cell(g, r, col)).strip() or "(blank)"))


# ------------------------------------------------------------------ main --
def _summary_line(source, note, day, per_rep) -> str:
    """One line with everything that matters, because the Mini Control queue
    shows only a log's LAST few lines: the source, the login file, and every
    rep with units as name=units(int/nl/air upN); zero reps are counted."""
    parts, zeros = [], 0
    for name in sorted(per_rep or {}):
        m = per_rep[name]
        if int(m.get("units", 0) or 0) > 0 or int(m.get("Int Up", 0) or 0) > 0:
            parts.append("%s=%d(%d/%d/%d up%d)" % (
                name.title()[:22], int(m.get("units", 0) or 0), int(m.get("Int", 0) or 0),
                int(m.get("NL", 0) or 0), int(m.get("Air", 0) or 0), int(m.get("Int Up", 0) or 0)))
        else:
            zeros += 1
    line = "SUMMARY %s%s %s: %s; %d rep(s) at 0" % (
        source or "none", (" [%s]" % note) if note else "", day.isoformat(),
        " | ".join(parts) or "nobody with units", zeros)
    return line[:900]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default from the "
                                   "clock (before 10am = yesterday)")
    ap.add_argument("--office", default="",
                    help="relay office key to read (default: the one carlos* "
                         "office enrolled as nds)")
    ap.add_argument("--source", choices=SOURCES, default="auto",
                    help="auto (default): the nds relay when it relayed for "
                         "the day, else the direct SaraPlus read when the "
                         "login exists, else hold; relay / sara pin one and "
                         "never touch the other")
    ap.add_argument("--creds-file", default="",
                    help="explicit NDS SaraPlus login JSON {email,password}; "
                         "overrides the standard file (probe which dealer "
                         "shows the crew before trusting a login)")
    ap.add_argument("--passcode-mail", action="store_true",
                    help="list where SaraPlus's recent passcode mails landed in the "
                         "inbox the login reads (sent / to / arrived; never the code) "
                         "-- nothing else touched")
    ap.add_argument("--mail-query", metavar="GMAIL_SEARCH",
                    help="like --passcode-mail but for this Gmail search in the "
                         "inbox the login reads (headers only)")
    ap.add_argument("--preflight", action="store_true",
                    help="report patchright, the creds file (never the "
                         "password) and the profile dir, then exit 0/1 -- "
                         "touches nothing else; wins over every other flag")
    ap.add_argument("--probe", action="store_true",
                    help="print which source, its raw numbers, the derived "
                         "metrics and the board's current column; never "
                         "writes, never holds")
    ap.add_argument("--fill", action="store_true",
                    help="plan the board write (dry-run without --yes)")
    ap.add_argument("--yes", action="store_true", help="actually write")
    ap.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                    help="never write, whatever else is passed")
    a = ap.parse_args(argv)

    if a.passcode_mail or a.mail_query:
        return passcode_mail(query=a.mail_query)
    if a.preflight:
        return preflight()

    now = dt.datetime.now(TZ)
    if a.date:
        day = dt.date.fromisoformat(a.date)
    else:
        day = target_day(now)
        _log("no --date given; at %s that means %s" % (now.strftime("%H:%M"),
                                                       R._md(day)))
    write = bool(a.fill and a.yes and not a.probe and not a.dry)
    mode = ("PROBE" if a.probe else "WRITE" if write
            else "PLAN (dry)" if a.fill else "DRY REPORT")
    _log("NDS Sales Board <- SaraPlus (source %s), %s, %s" % (a.source, R._md(day), mode))

    # --- the relay, unless the source is pinned away from it ----------------
    key, why, snap = None, "", None
    if a.source in ("auto", "relay"):
        rows = relay_rows(day)
        key, why, seen = pick_office(rows, a.office, lookup=office_campaign)
        if a.probe:
            _log("offices that relayed for %s: %s" % (
                day.isoformat(),
                ", ".join("%s (%s)" % (k, c or "not enrolled")
                          for k, c in sorted(seen.items())) or "none"))
        snap = latest_snapshot(rows, key) if key else None
        if snap is None:
            why = why or "no row for %s" % key
            key = None
            _log("no relay for %s -- the office mini may be off (%s)"
                 % (day.isoformat(), why))
    else:
        why = "--source sara: the relay was not read"

    # --- the login, unless the source is pinned away from it ----------------
    cr, cr_why, cr_exists = (None, "--source relay: the login was not looked for", False)
    if a.source in ("auto", "sara"):
        cr, cr_why, cr_exists = CFG.creds_status()
        if a.creds_file:
            import json as _json
            from pathlib import Path as _Path
            _cp = _Path(a.creds_file).expanduser()
            try:
                _d = _json.loads(_cp.read_text())
                cr = {"email": str(_d["email"]), "password": str(_d["password"])}
                cr_why, cr_exists = "login from --creds-file %s" % _cp.name, True
            except Exception as _e:  # noqa: BLE001 -- a bad explicit file is a fault
                _log("--creds-file %s is unusable (%s)" % (_cp, type(_e).__name__))
                return EXIT_FAIL
        if cr is None and cr_exists:
            # A file that is there but unreadable is a fault to fix, not a
            # wait: a hold would sit amber on every pass until somebody read
            # the log.
            _log("the NDS SaraPlus login file is unusable: %s" % cr_why)
            if not a.probe:
                _log("nothing written")
                return EXIT_FAIL

    source, why_not = choose_source(a.source, key, why, cr is not None, cr_why)
    per_rep: Dict[str, Dict[str, int]] = {}
    show_reps = False                 # per_rep came from a usable read
    if source is None:
        _log("no source for %s: %s" % (day.isoformat(), why_not))
        if not a.probe:
            _log("HOLDING -- nothing written; the next pass retries")
            return EXIT_HOLD
    elif source == "relay":
        _log("source: relay -- %s relayed as %r" % (key, RELAY_CAMPAIGN))
        per_rep, show_reps = units_for(snap["sales"]), True
    else:
        _log("source: direct SaraPlus read -- %s" % cr_why)
        try:
            read = read_sara(day, cr)
        except SP.SaraError as e:
            _log("SaraPlus read FAILED -- %s" % e)
            _log("nothing written")
            return EXIT_FAIL
        describe_sara(read, day)
        problem = sara_problem(read)
        if problem:
            _log("HOLDING -- %s" % problem)
            if not a.probe:
                _log("nothing written; the next pass retries")
                return EXIT_HOLD
        else:
            per_rep = units_for(metrics_from_grids(read["att"], read["lines"]))
            show_reps = True

    ws, g = load_board()
    board_rows = R.campaign_rows(g, CAMPAIGN)
    col = R.day_column(g, day)
    ok, shown, want = R.week_ok(g, day)
    _log("board %r: WE cell reads %r, %s needs %r -> %s; %d NDS row(s)"
         % (ws.title, shown, R._md(day), want,
            "ok" if ok else "WRONG WEEK", len(board_rows)))
    if source == "relay":
        describe(snap, per_rep, g, board_rows, col)
    elif show_reps:
        describe_reps(per_rep, g, board_rows, col)
    _log(_summary_line(source, cr_why if source == "sara" else "", day, per_rep))
    if a.probe:
        _column_dump(g, board_rows, col, day)
        _log(_summary_line(source, cr_why if source == "sara" else "", day, per_rep))
        _log("PROBE -- nothing written")
        return 0

    if not a.fill:
        _log("DRY REPORT -- add --fill to plan the write, --fill --yes to write")
        return 0

    if not ok:
        _log("WRONG WEEK -- holding. The gold WE cell reads %r but %s's "
             "sales belong to week %r. Roll the board (lucy rerun "
             "vantura_week_roll --apply --machine \"Lucy 2\") and re-run; "
             "writing now would land on the previous week's column."
             % (shown, R._md(day), want))
        _log("HELD DAY: %s" % day.isoformat())
        return EXIT_HOLD
    if col is None:
        _log("no column for %s on the board -- holding." % day.strftime("%A"))
        return EXIT_HOLD

    plan_rows, flags = plan(g, col, board_rows, per_rep)
    for f in flags:
        _log("  ! %s" % f)
    _log("%d cell(s) would change on %r (SaraPlus overwrites, up or down):"
         % (len(plan_rows), ws.title))
    for name, a1, cur, new, note in plan_rows:
        _log("  %s  %-28s %s -> %s%s" % (a1, name, cur, new, note))
    if not write:
        _log("DRY RUN -- re-run with --fill --yes to write")
        return 0
    if plan_rows:
        from automations.recruiting_report.fill import _retry
        _retry(ws.batch_update, batch_values(plan_rows))
        _log("wrote %d cell(s)" % len(plan_rows))
    else:
        _log("board already matches SaraPlus -- nothing to write")
    _log(_summary_line(source, cr_why if source == "sara" else "", day, per_rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
