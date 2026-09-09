"""Pull — scrape Ownerville 'TeleMapper Leads → Disposition by Rep' (p=89)
for a single day and return one record per rep, keyed by the canonical
Total Knocks Sheet headers.

Source of truth for columns is the LIVE table header row, matched by
normalized header text — never fixed cell indices (the repo rule:
templates change, label/header lookup survives, indices don't).

Run standalone to preview yesterday's scrape WITHOUT touching the Sheet:
    .venv/Scripts/python.exe -m automations.total_knocks.pull            # yesterday
    .venv/Scripts/python.exe -m automations.total_knocks.pull 2026-05-28 # a date
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Optional
from zoneinfo import ZoneInfo

from automations.shared.tableau_patchright import ownerville_session

# Raf's Local Office is in Texas — anchor "today"/"yesterday" to Central Time,
# NOT the machine clock (which may run in another tz). This keeps the data date
# (yesterday) and the Slack Metrics-thread date (today) correct regardless of
# where/when the run fires. tzdata ships in the venv, so it works on Windows.
CENTRAL = ZoneInfo("America/Chicago")


def central_today() -> dt.date:
    return dt.datetime.now(CENTRAL).date()

# ---------------------------------------------------------------------------
# Canonical Sheet columns (exactly as they appear in 'Rep Total Knocks
# Template' row 1, left→right). 'Total Talk to' is CALCULATED here, not
# scraped — every other column is pulled straight from Disposition by Rep.
# ---------------------------------------------------------------------------
COL_ID                  = "ID"
COL_REP                 = "Rep"
COL_TOTAL_LEADS_KNOCKED = "Total Leads Knocked"
COL_TOTAL_KNOCKS        = "Total Knocks"
COL_TOTAL_TALK_TO       = "Total Talk to"     # calculated
COL_FIRST_KNOCK         = "First Knock"
COL_LAST_KNOCK          = "Last Knock"
COL_NO_ANSWER           = "No answer"
COL_TALK_TO_NI          = "Talk To - Not Interested"
COL_PRES_NI             = "Presentation – Not Interested"
COL_COME_BACK           = "Come Back"
COL_SALE                = "Sale"
COL_INACCESSIBLE        = "Inaccessible"
COL_DO_NOT_KNOCK        = "Do Not Knock"
# Wireless (NDS) dispositions collapse the Talk-To split into one bucket and
# have no Sale column. Only the wireless-shaped scrape/board uses this.
COL_NOT_INTERESTED      = "Not Interested"
# Energy Wells (RES-ENERGYWELL, invD2DClientId=40) dispositions. Its grid is the
# wireless shape PLUS these two: no Talk-To split, no Sale, but a Presentation
# bucket and VL. Raf 2026-08-28: "talk-tos are all the same as a fiber, but VL
# is also a talk-to."
COL_VL                  = "VL"
COL_PRESENTATION        = "Presentation"
# --- B2B ---------------------------------------------------------------------
# The two B2B campaigns knock BUSINESSES, and their disposition vocabularies are
# their own — not the fiber set, not the wireless set, and NOT each other's.
# Read live off p=89 on 2026-09-02 with the campaign pinned (the campaign is a
# sticky session-global, so an unpinned dump proves nothing about which campaign
# produced it); both header dumps are kept in
# output/probes/b2b-disposition-headers-campaign{2,16}-2026-09-02.log.
#
# Both sets are CONFIRMED against a real office that runs the campaign, not just
# against the master account's view of it: AT&T on Carlos Hidalgo (11580) and
# Box on Roshan Amin Ahmad (19833), each pulling real rep rows on 2026-09-02.
#
# B2B AT&T SBS (invD2DClientId=2), 22 headers. Note "Talked To" (past tense) and
# "Presentation" WITHOUT the house's "Talk To - " prefix: near-identical English
# to the fiber columns, different strings, which is exactly why the house scrape
# raised "missing: No answer, Talk To - Not Interested, Inaccessible" on it.
# It has NO No-answer and NO Inaccessible bucket at all.
COL_B2B_TALKED_TO_NI    = "Talked To - Not Interested"
# NO COL_B2B_PRES_NI. B2B AT&T's "Presentation - Not Interested" (hyphen) and
# the house COL_PRES_NI (en-dash) are different STRINGS that _norm() flattens to
# the same key, and that is not a cosmetic clash — render._records_to_table
# seeds its header with SHEET_COLUMNS (fiber's set) and appends any extra key
# the records carry, then indexes it by normalized name FIRST-WINS. So the B2B
# column resolved to the house column's position, which no B2B row fills, and
# the board drew Presentation blank for every rep with 0 in the totals. Exactly
# the failure the comment in _records_to_table already records for Energy Wells,
# arriving by a different route (2026-09-02, caught by rendering realistic
# numbers rather than a fixture where every bucket held the same value).
#
# The scrape resolves columns by _norm, so the house constant matches B2B's live
# header on its own. Note COL_B2B_TALKED_TO_NI above does NOT collide —
# "talked to not interested" vs "talk to not interested" — and must stay its own
# constant, because _is_wireless_dispo keys on the house one being ABSENT.
COL_B2B_CORP_LOCAL      = "Corp Franchise Local"
COL_B2B_CORP_NO_OPP     = "Corp Franchise No Opp"
COL_B2B_NONE            = "None"           # knocked, no disposition recorded
# B2B Box Energy (invD2DClientId=16), 24 headers. Shares only the spine and
# Come Back / Inaccurate Lead with AT&T above.
COL_BOX_TALKED_TO       = "Talked To"
COL_BOX_OWNER_TALKED_TO = "Owner Talked To"
COL_BOX_CONTRACT_SIGNED = "Contract Signed"
COL_BOX_BILL_NO_SALE    = "Bill Collected - No Sale"
COL_BOX_AM_COME_BACK    = "AM Come Back"
COL_BOX_CORP_NO_OPP     = "Corp - No Opp"
COL_BOX_DO_NOT_DISTURB  = "Do Not Disturb"
# Both B2B grids carry this one, and it is NOT a talk-to: the lead was wrong,
# so there was nobody there to talk to.
COL_B2B_INACCURATE_LEAD = "Inaccurate Lead"
# From Time Tracker (p=510 JSON), merged onto the disposition rows by badge ID.
COL_GAPS                = "Gaps"               # count of gaps
COL_TOTAL_GAPS          = "Total Gaps (min)"   # total gap minutes (int)
# Extra Time Tracker fields, carried ONLY on the standalone gaps-only rows
# (NDS/wireless offices) — the TeleMapper Knocks board mirrors the p=510
# table (Raf's reference screen, 2026-08-22). Not in SHEET_COLUMNS: the
# production Sheet and every fiber board are untouched.
COL_TT_BREAKS           = "Breaks (min)"
COL_TT_SALES_TIME       = "Sales Time (min)"
COL_TT_SALES            = "Sales"

# Left→right order the Sheet expects (A→P).
SHEET_COLUMNS = [
    COL_ID, COL_REP, COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS,
    COL_TOTAL_TALK_TO, COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_NO_ANSWER,
    COL_TALK_TO_NI, COL_PRES_NI, COL_COME_BACK, COL_SALE,
    COL_INACCESSIBLE, COL_DO_NOT_KNOCK, COL_GAPS, COL_TOTAL_GAPS,
]

# Time Tracker columns: blank when a rep has NO Time Tracker row (per Eve) —
# so they are NOT in COUNT_COLUMNS (which would force a 0).
TIME_TRACKER_COLUMNS = [COL_GAPS, COL_TOTAL_GAPS]

# 'Total Talk to' = sum of these five disposition counts (per Eve):
# Talk To-Not Interested + Presentation-Not Interested + Come Back + Sale
# + Do Not Knock. Excludes 'No answer' and 'Inaccessible' (no one talked to).
TALK_TO_PARTS = [
    COL_TALK_TO_NI, COL_PRES_NI, COL_COME_BACK, COL_SALE, COL_DO_NOT_KNOCK,
]

# Count columns parsed as ints (blank → 0). First/Last Knock stay as the
# source time strings; ID + Rep stay as-is.
COUNT_COLUMNS = {
    COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS, COL_NO_ANSWER, COL_TALK_TO_NI,
    COL_PRES_NI, COL_COME_BACK, COL_SALE, COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
}

DISP_TABLE = "table#table-dispositions"


class KnocksPullFailed(RuntimeError):
    """The scrape did not complete — as distinct from an office that genuinely
    logged no knocks that day.

    Why this exists (2026-08-24): every read path used to return [] for BOTH
    cases, so a stalled grid or a dead Time Tracker endpoint posted the same
    "No data available" line a real empty day posts, exited 0, kept the Hub
    card green, and never fired the runner's retry. Callers now post the
    no-data line ONLY for a verified-empty pull and let this exception fail
    the run loudly.
    """


def _norm(s: str) -> str:
    """Normalize a header for matching: lowercase, drop every non-alphanumeric
    (so an en-dash, the mojibake '�', or extra spaces all collapse), then
    squeeze whitespace. 'Presentation – Not Interested', 'Presentation �
    Not Interested', and 'presentation  not  interested' all map to the same key.
    """
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _to_int(s: str) -> int:
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


def _yesterday() -> dt.date:
    return central_today() - dt.timedelta(days=1)


def _capture_rqst(page) -> Optional[str]:
    """Read the master rqst token. The post-login URL is sometimes the v1
    ownerville.com landing (no rqst); navigating to the v2 root reliably
    hands back a master Welcome URL carrying ?rqst=… (same trick the focus
    report uses)."""
    m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url)
    if m:
        return m.group(1)
    page.goto("https://v2.ownerville.com/", wait_until="networkidle", timeout=25000)
    m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url)
    return m.group(1) if m else None


def _navigate(page, rqst: str, target_mdy: str, *, attempts: int = 3) -> None:
    """Disposition by Rep filters via URL ?startDate=&endDate= (server-side);
    the on-page picker only sets local JS vars. Single-day = same start/end.

    Waits for the grid's HEADER row before returning. DataTables builds the
    grid from an AJAX call that fires AFTER networkidle, so a header read can
    land on an empty <thead>. Reproduced 1-in-2 on 2026-08-05 probing the same
    office/date, so re-navigate instead of letting it raise. When the retries
    are exhausted anyway, _resolve_columns turns the empty header row into
    KnocksPullFailed ("grid never rendered a header row") — it used to fall
    through and report every canonical column as missing, which read as a
    table-shape problem and sent people looking for one (2026-08-31).

    A day with NO knocks still renders the headers (empty <tbody>), so the
    header row is a safe "grid is built" signal and does NOT confuse an empty
    day with a stalled one — the distinction that matters when an office
    legitimately logs nothing."""
    url = (f"https://v2.ownerville.com/index.cfm?p=89&rqst={rqst}"
           f"&startDate={target_mdy}&endDate={target_mdy}")
    for attempt in range(1, attempts + 1):
        page.goto(url, wait_until="networkidle", timeout=25000)
        try:
            page.wait_for_selector("#table-dispositions thead th", timeout=15000)
            break
        except Exception:  # noqa: BLE001 — stalled grid, not a fatal state
            if attempt == attempts:
                # Out of retries: fall through and let _scrape_rows raise with
                # the live-headers diagnostic, same as before this guard.
                print(f"[knocks] grid never built after {attempts} navigations "
                      f"({target_mdy}) — letting the scrape report it",
                      flush=True)
                break
            print(f"[knocks] disposition grid not built yet "
                  f"(try {attempt}/{attempts}) — re-navigating", flush=True)
    try:  # show all rows on one page where possible
        page.locator("select[name='table-dispositions_length']").select_option("100")
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def _header_index(page) -> dict:
    """Map normalized source-header text → 0-based column index, read live.

    WAITS for the header row first. It used to read the instant the navigation
    returned, so a grid that had not finished building yielded {} — and an
    empty index makes EVERY expected column "missing", which the callers raise
    on. That is an intermittent failure that looks exactly like a permanent
    one: Chan Park's comparison line vanished from Raf's board on some ticks
    and came back on the next ("chan's numbers are gone again" … "now it's
    back??", 2026-08-31).

    Best-effort: a stub page in tests has no wait_for_function, and a genuinely
    absent table should still fall through to the caller's own error rather
    than a timeout here.
    """
    try:
        page.wait_for_function(
            "() => document.querySelectorAll("
            "  '#table-dispositions thead th, #table-dispositions thead td'"
            ").length > 0", timeout=15000)
    except Exception:  # noqa: BLE001 — the read below reports what it finds
        pass
    headers = page.evaluate(
        """() => {
            const t = document.querySelector('#table-dispositions');
            if (!t) return [];
            return Array.from(t.querySelectorAll('thead th, thead td'))
                .map(th => (th.innerText||'').trim());
        }"""
    )
    return {_norm(h): i for i, h in enumerate(headers)}


# Columns the board CANNOT be built without — an absent one is a real failure.
# Everything else in SHEET_COLUMNS is OPTIONAL, because the disposition
# vocabulary is per-office: TeleMapper only renders the buckets that office
# actually uses. Proven 2026-08-31 (Stergios Kasapidis): his table carries the
# full house set EXCEPT 'Inaccessible', plus office-only buckets ('bill payer
# not home', 'credit check', 'already has AT&T', 'battery', 'coverage',
# 'device'…). The old all-or-nothing check failed that whole office over one
# bucket nobody there uses. An absent COUNT bucket means zero doors were
# dispositioned that way → 0; an absent text column stays blank.
REQUIRED_COLUMNS = {COL_ID, COL_REP, COL_TOTAL_KNOCKS}


def _resolve_columns(idx: dict, columns, *, label: str = "Disposition",
                     verbose: bool = True) -> tuple[dict, list]:
    """Map each wanted canonical column → live source index.

    Returns (resolved, absent). `resolved` holds ONLY the columns actually on
    the page; `absent` is everything else, which the caller fills with 0 / "".

    Raises KnocksPullFailed when the grid handed back NO headers at all (the
    stalled-grid case — see _navigate), and RuntimeError when the headers are
    real but a REQUIRED column isn't among them.
    """
    if not idx:
        # Zero headers is a grid that never built, NOT a table with a
        # different shape. This used to fall through and report every single
        # column as "missing" — the cryptic wall of text Francisco Castillo's
        # request answered with on 2026-08-31. Typed as KnocksPullFailed so it
        # is retried like the other stalled-grid failures instead of being
        # filed as a data problem.
        raise KnocksPullFailed(
            f"{label} grid never rendered a header row (0 headers) — the "
            "scrape stalled, so nothing was read. This is a failed pull, not "
            "an office with a different table shape.")

    resolved, absent = {}, []
    for col in columns:
        i = idx.get(_norm(col))
        if i is None:
            absent.append(col)
        else:
            resolved[col] = i

    missing_required = [c for c in absent if c in REQUIRED_COLUMNS]
    if missing_required:
        raise RuntimeError(
            f"{label} table is missing required column(s): "
            + ", ".join(missing_required)
            + ". Live headers were: " + ", ".join(sorted(idx)) + ".")

    if absent and verbose:
        # Never silent: an office whose board shows 0 in a bucket has to be
        # traceable to "that bucket isn't on their page", not to a bad scrape.
        print(f"  · {label}: no {', '.join(absent)} column on this office's "
              "page — those read 0/blank", flush=True)
    return resolved, absent


# ---- Short-read guard ------------------------------------------------------
# The Time Tracker is a JSON fetch of everyone who clocked in that day, so it
# is the one number that knows how many reps the Disposition grid OUGHT to
# hold. A rep can legitimately clock in and disposition nothing (a walk-on, a
# rep who logged in and left), so TT >= Disposition is normal and small gaps
# mean nothing. What is NOT normal is a grid holding a fraction of the reps who
# were out: 2 of 22 (Christian Esposito, 2026-09-07), 8 of 27 (2026-09-04).
#
# Two thresholds so neither reading alone can fire this: an ABSOLUTE gap (a
# five-rep office is not judged by percentages) and a RATIO (a big office
# missing five of forty is a normal day, not a broken read).
SHORT_READ_MIN_GAP = 5
SHORT_READ_RATIO = 0.5


def disposition_read_is_short(n_rows: int, n_tt: int) -> bool:
    """Worth READING AGAIN: the Disposition grid came back with fewer reps
    than clocked in. Any shortfall qualifies — the re-read costs one
    navigation, and this is the cheap half of the guard. Pure."""
    return bool(n_rows) and bool(n_tt) and n_tt > n_rows


def short_read_error(n_rows: int, n_tt: int) -> "str | None":
    """The message to REFUSE on when a re-read is still drastically short of
    the Time Tracker, else None — see SHORT_READ_MIN_GAP / SHORT_READ_RATIO.

    Returns a reason rather than raising so both callers phrase the failure
    the same way. Pure — offline-testable."""
    if not n_rows or not n_tt:
        return None
    if (n_tt - n_rows) < SHORT_READ_MIN_GAP:
        return None
    if n_rows >= n_tt * SHORT_READ_RATIO:
        return None
    return ("Disposition grid returned %d rep(s) but %d clocked in on the Time "
            "Tracker that day — it was read twice and stayed short, so this is "
            "a partial grid, not a quiet day. Refusing to publish a board that "
            "leaves reps off with no sign anything is missing."
            % (n_rows, n_tt))


def _wait_rows_settled(page, *, quiet_ms: int = 400, timeout_ms: int = 12000
                       ) -> int:
    """Wait until the Disposition grid STOPS growing, and return the row count.

    DataTables fills #table-dispositions from an AJAX call, and _navigate then
    asks for 100 rows per page, which fires a SECOND one. Between those the
    tbody legitimately holds a partial set — and on the captainship capture,
    which reuses one page for ~44 owners, it can still hold the PREVIOUS
    office's rows. Reading at that moment is how a board publishes 2 reps of
    22 with nothing raising (Christian Esposito, 2026-09-07).

    Two conditions, both cheap: DataTables' own 'processing' overlay is gone,
    and the row count has been unchanged for `quiet_ms`. Best-effort by
    design — on timeout we return what is there and let the Time Tracker
    cross-check in the callers catch a still-short read, because a wait that
    RAISES would turn a slow grid into a missing board."""
    import time as _time
    deadline = _time.monotonic() + timeout_ms / 1000.0
    last, stable_since = -1, _time.monotonic()
    while _time.monotonic() < deadline:
        try:
            n = page.evaluate(
                "() => {"
                " const p = document.querySelector('#table-dispositions_processing');"
                " const busy = p && p.offsetParent !== null;"
                " const rows = document.querySelectorAll("
                "   '#table-dispositions tbody tr').length;"
                " return busy ? -1 : rows;"
                "}")
        except Exception:  # noqa: BLE001 — a wait must never be the failure
            return max(last, 0)
        if n != last:
            last, stable_since = n, _time.monotonic()
        elif n >= 0 and (_time.monotonic() - stable_since) * 1000 >= quiet_ms:
            return n
        try:
            page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001
            break
    return max(last, 0)


def _scrape_rows(page, idx: dict) -> list[dict]:
    """Walk every DataTables page, return one canonical-keyed dict per rep."""
    # Resolve the source column index for each Sheet column we scrape from
    # Disposition. 'Total Talk to' is calculated; Gaps / Total Gaps come from
    # Time Tracker — none of those live in this table.
    _skip = {COL_TOTAL_TALK_TO, *TIME_TRACKER_COLUMNS}
    want, absent = _resolve_columns(
        idx, [c for c in SHEET_COLUMNS if c not in _skip],
        label="Disposition")

    table = page.locator(DISP_TABLE)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#table-dispositions tbody tr').length >= 1",
            timeout=10000,
        )
    except Exception as e:  # noqa: BLE001 — turned into a typed failure below
        # A day with NO knocks still renders ONE tbody row: DataTables' own
        # 'No data available in table' placeholder — the row the walk below
        # skips by name. So ZERO tbody rows does NOT mean an empty day, it
        # means the grid never finished building. Raising is what separates
        # the two; before this both came back [] and posted "No data
        # available" (Isaiah, 2026-08-23 — see KnocksPullFailed).
        raise KnocksPullFailed(
            "Disposition grid rendered no rows at all — not even DataTables' "
            "'No data available' placeholder — so the scrape failed rather "
            "than the day being empty.") from e
    # ONE ROW IS NOT THE GRID. The wait above is satisfied by the FIRST row
    # DataTables paints (or by the previous office's rows, still in the DOM of
    # a session that walks ~44 owners on one page), and the walk below then
    # reads whatever happens to be there — a short board with no error
    # anywhere. Christian Esposito's 2026-09-07 board went out with 2 reps of
    # the 22 ownerville had, and 2026-09-04 with 8 of 27; the same scrape,
    # re-run by hand, returned all of them. So: let the row count SETTLE
    # before reading it.
    _wait_rows_settled(page)

    out: list[dict] = []
    seen_ids: set[str] = set()
    for _ in range(20):  # safety cap on pagination
        for tr in table.locator("tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if not cells:
                continue
            if cells[0].lower().startswith("no data"):
                continue
            # Need every resolved index to be present in this row.
            if max(want.values()) >= len(cells):
                continue
            rec: dict = {}
            for col, i in want.items():
                raw = cells[i]
                rec[col] = _to_int(raw) if col in COUNT_COLUMNS else raw
            # A bucket this office's page doesn't carry: zero doors went into
            # it (blank for the text columns), so the board still renders.
            for col in absent:
                rec[col] = 0 if col in COUNT_COLUMNS else ""
            rec[COL_TOTAL_TALK_TO] = sum(int(rec[p] or 0) for p in TALK_TO_PARTS)
            # De-dupe by badge ID (a rep shouldn't appear twice in one day).
            rid = str(rec.get(COL_ID, "")).strip()
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            out.append(rec)

        nxt = page.locator("#table-dispositions_next").first
        if nxt.count() == 0 or "disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
    return out


def _gaps_count(s) -> int:
    """'3 gaps (24, 32, 23 min)' -> 3 ; '1 gap (...)' -> 1 ; '' / 'No gaps' -> 0."""
    m = re.match(r"\s*(\d+)", str(s or ""))
    return int(m.group(1)) if m else 0


def _blank_zero(v) -> str:
    """'0' / 0 / '' / None -> '' (the p=510 table leaves zero cells empty);
    anything else -> its trimmed string ('273.0' -> '273')."""
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    try:
        n = float(s)
        return "" if n == 0 else str(int(n))
    except ValueError:
        return s


def _fetch_time_tracker(page, rqst: str, mdy: str, *, required: bool,
                        verbose: bool = True) -> list:
    """Raw Time Tracker (p=510) JSON rows for `mdy`, with the status checked.

    `required=True` — this endpoint is the ONLY source for the board being
    built (an NDS/wireless office has no Disposition rows to fall back on), so
    anything other than a clean 200 raises KnocksPullFailed. `required=False`
    — the gaps merely decorate disposition rows we already have, so a failed
    fetch warns and leaves Gaps blank, the documented pre-existing behaviour.

    A 200 carrying zero rows is a VERIFIED empty day, never a failure: that is
    exactly what Isaiah's office returned for Sunday 2026-08-23.
    """
    result = page.evaluate(
        """async ({rqst, mdy}) => {
            const url = `https://v2.ownerville.com/components/telemapper/`
                + `report_timeTracker.cfc?method=getTimeTrackingData&rqst=${rqst}`
                + `&dateToSearch=${encodeURIComponent(mdy)}&returnFormat=json`;
            try {
                const r = await fetch(url, {credentials: 'include'});
                const text = await r.text();
                try { return {status: r.status, data: (JSON.parse(text).data) || []}; }
                catch (e) { return {status: r.status, data: [], raw: text.slice(0, 160)}; }
            } catch (e) { return {status: 0, data: [], raw: String(e).slice(0, 160)}; }
        }""",
        {"rqst": rqst, "mdy": mdy})
    rows = result.get("data", []) or []
    status = result.get("status")
    if status != 200:
        msg = (f"Time Tracker fetch failed for {mdy}: status={status} "
               f"{result.get('raw', '')}").strip()
        if required:
            raise KnocksPullFailed(msg)
        if verbose:
            print(f"  ⚠ {msg} — Gaps / Total Gaps left blank", flush=True)
    elif verbose and not rows:
        # 200 + no rows is a real quiet day, NOT a problem — say so plainly.
        # The old code warned here too, which cried wolf every empty Sunday.
        print(f"  · Time Tracker: 200 OK, no rows for {mdy} "
              "(nobody clocked knocks)", flush=True)
    return rows


def _scrape_time_tracker(page, rqst: str, mdy: str, verbose: bool = True,
                         required: bool = False) -> dict:
    """Fetch Time Tracker (p=510) data for `mdy` from its JSON endpoint and
    return {id_str: {Gaps, Total Gaps (min)}}. The page's own same-origin
    fetch carries the ownerville session cookies — far more robust than
    driving the jQuery datepicker (jQuery isn't on `window` here).

    `required` — see _fetch_time_tracker. Defaults False here because this is
    the gap-MERGE path: callers pass required=True only when the disposition
    came back empty and this is the last source standing."""
    rows = _fetch_time_tracker(page, rqst, mdy, required=required,
                               verbose=verbose)
    out = {}
    for row in rows:
        rid = str(row.get("id", "")).strip()
        if not rid or rid == "0":
            continue
        out[rid] = {
            COL_GAPS: _gaps_count(row.get("gaps")),
            COL_TOTAL_GAPS: int(row.get("totalGapMinutes") or 0),
        }
    return out


def _scrape_time_tracker_rows(page, rqst: str, mdy: str,
                              verbose: bool = True) -> list[dict]:
    """Time Tracker (p=510) as STANDALONE Time-Gaps rows — rep name + knock times
    + gaps — for an office whose Disposition (p=89) is empty (a wireless/NDS owner
    with no door-knock campaign, so p=89 has no rows to hang the gaps on). Same
    JSON as _scrape_time_tracker, but keeps the identity columns the disposition
    normally supplies (name/first/last knock) so render_time_gaps can draw the
    table on its own. Fields from the live endpoint: name, firstKnockDate,
    lastKnockDate, gaps, totalGapMinutes, id.

    required=True always: by the time we get here the Disposition came back
    empty, so this endpoint IS the board. A non-200 here is a failed pull, not
    a quiet day."""
    raw = _fetch_time_tracker(page, rqst, mdy, required=True, verbose=verbose)
    out = []
    for row in raw:
        rid = str(row.get("id", "")).strip()
        if not rid or rid == "0":
            continue
        out.append({
            COL_ID: rid,
            COL_REP: (row.get("name") or "").strip(),
            COL_FIRST_KNOCK: row.get("firstKnockDate") or "",
            COL_LAST_KNOCK: row.get("lastKnockDate") or "",
            COL_GAPS: _gaps_count(row.get("gaps")),
            COL_TOTAL_GAPS: int(row.get("totalGapMinutes") or 0),
            # Blank zeros like the live p=510 table does, so the rendered
            # board reads the same as Raf's reference screen.
            COL_TT_BREAKS: _blank_zero(row.get("breaks")),
            COL_TT_SALES_TIME: _blank_zero(row.get("salesTimeTotal")),
            COL_TT_SALES: _blank_zero(row.get("sales")),
        })
    if verbose:
        print(f"-> Time Tracker standalone gap rows: {len(out)} rep(s)", flush=True)
    return out


def pull_disposition_day(target: Optional[dt.date] = None,
                         verbose: bool = True) -> tuple[dt.date, list[dict]]:
    """Scrape Disposition by Rep + Time Tracker gaps for `target` (default:
    yesterday) in one ownerville session, merged by badge ID. Returns
    (date, [rep_record, ...]) with each record keyed by SHEET_COLUMNS.
    Reps with no Time Tracker row keep Gaps / Total Gaps blank (per Eve)."""
    target = target or _yesterday()
    mdy = target.strftime("%m/%d/%Y")
    with ownerville_session(verbose=verbose) as page:
        rqst = _capture_rqst(page)
        if not rqst:
            raise RuntimeError("Couldn't capture ownerville rqst token from "
                               f"{page.url!r} after login.")
        if verbose:
            print(f"-> Disposition by Rep for {mdy} (rqst {rqst[:12]}…)", flush=True)
        _navigate(page, rqst, mdy)
        idx = _header_index(page)
        rows = _scrape_rows(page, idx)
        # Gaps are supplementary while we HAVE disposition rows; they are the
        # last source standing when we don't — so only then is a failed fetch
        # fatal (see _fetch_time_tracker).
        tt = _scrape_time_tracker(page, rqst, mdy, verbose=verbose,
                                  required=not rows)
        if verbose:
            print(f"-> Time Tracker: gap data for {len(tt)} rep(s)", flush=True)
        # SHORT READ? Read it again before publishing it. Same guard the
        # captainship path runs (rashad_metrics.knocks_pull._scrape_day_on_page)
        # — this is the master office's copy of the sequence, and a fix that
        # lived in only one of them would leave Raf's own board unguarded.
        if disposition_read_is_short(len(rows), len(tt)):
            if verbose:
                print(f"-> Disposition {len(rows)} rep(s) < Time Tracker "
                      f"{len(tt)} — re-reading the grid", flush=True)
            _navigate(page, rqst, mdy)
            again = _scrape_rows(page, _header_index(page))
            if len(again) > len(rows):
                rows = again
            if verbose:
                print(f"-> re-read: {len(rows)} rep(s)", flush=True)
        why = short_read_error(len(rows), len(tt))
        if why:
            raise KnocksPullFailed(why)

    # Merge gaps onto the disposition rows by badge ID. Unmatched reps keep
    # Gaps / Total Gaps unset, so fill writes them blank.
    matched = 0
    for rec in rows:
        rid = str(rec.get(COL_ID, "")).strip()
        if rid in tt:
            rec.update(tt[rid])
            matched += 1
    if verbose:
        print(f"-> Merged gaps onto {matched}/{len(rows)} disposition rep(s)",
              flush=True)
    return target, rows


def _print_preview(target: dt.date, rows: list[dict]) -> None:
    print(f"\n=== Disposition by Rep — {target.isoformat()} "
          f"({len(rows)} rep(s)) ===")
    show = [COL_ID, COL_REP, COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
            COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_SALE, COL_GAPS, COL_TOTAL_GAPS]
    print("  " + " | ".join(f"{c}" for c in show))
    for r in rows[:25]:
        print("  " + " | ".join(str(r.get(c, "")) for c in show))
    if len(rows) > 25:
        print(f"  … +{len(rows) - 25} more")


def main() -> int:
    target = None
    if len(sys.argv) > 1:
        target = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    target, rows = pull_disposition_day(target)
    _print_preview(target, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
