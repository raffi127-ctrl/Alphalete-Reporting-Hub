"""NDS Metrics — Carlos's crew on HIS OWN code (RES AT&T OOF, office
11580), the B2B Metrics thread's replacement.

Carlos 2026-10-21: "we should have basically recreated the fib metrics
thread and turned into an NDS metrics thread." Since 2026-10-19 the crew
sells under CARLOS's own Ownerville office / RES AT&T OOF campaign
("NDS"); Raf's login is retired for them (callouts README). This module
is nds_metrics retargeted (that one — Raf's data — is retired):

  * Tableau leg: the NDS-SN (RES-ATT-OOF) ORDERLOG (the view Khalil's
    activation board pulls), Owner & Office = CARLOS HIDALGO, long-format
    measure rows collapsed, then the crew roster as a safety filter.
  * SaraPlus leg: CARLOS'S OWN login on Lucy 2 (sp_order_log.pull_csv,
    Customer Type Both) — the crew's orders live there since 10/19
    (probed 2026-10-21: 27+ crew orders; before 10/19 they sold under
    Raf, so crew-filtered rows HERE are NDS by construction). The old
    Lucy 1 relay (fiber sara_pull) is retired.
  * Pricing: the ATT-D2D-OOF SOW (signed to Carlos's entity) at BASE
    COMP (Tier 3-3) — sow_rates.json beside this file.

Thread: "NDS Metrics — {Month D, YYYY}" in #alphalete-gp-sales, next to
the NDS Knocks/Gaps threads, campaign-first names throughout.

  lucy rerun nds_metrics -- --dm U046G04P5LG        # previews
  lucy rerun nds_metrics -- --post                  # the live thread
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "nds_metrics"
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")
CARLOS = "U046G04P5LG"
LOOKBACK_DAYS = 60
# The crew's NDS SaraPlus logins began Monday 2026-10-20 (Carlos: "we got
# nds logins this monday" — the dealers also carry their migrated pre-NDS
# history back to 9/22, which is not NDS production). Every SaraPlus board
# floors at this date; the Tableau rate/churn boards keep their lookback
# (banding needs it).
NDS_SINCE = dt.date(2026, 10, 19)   # 10/20 until 2026-11-06: Jose Guevara's 10/19 order was paid as NDS Wireless on WE 11.1 and is Smedra's 4th order of that tier week
# SaraPlus only drives boards once it holds this many NDS-era crew orders.
# 2026-10-26: the FIRST call-center entry landed and the Order Log flipped to
# SaraPlus showing that one order while Tableau had the crew's full 17 lines.
# Below this floor every board stays on Tableau (or skips, for the overviews).
SOH_MIN_ORDERS = 5
BUCKETS = ("0-30 Day", "31-60 Day")
_BAND_KEY = {"0-30 Day": "0-30", "31-60 Day": "31-60"}
POSTED = ("posted",)
DEAD = ("canceled", "cancelled", "disconnected")

# ------------------------------------------------------------ sources ----
# Carlos 2026-11-08: "whenever you post the NDS metrics thread ... so I can
# quickly remember and know where the info is coming from"; 2026-11-09: "I
# only want it on the activation reports. You can make it as simple as
# 'Source: Sara' or 'Source: Tableau'." So: the four activation reports carry
# one word, every other section posts bare. Activation Revenue prices
# SaraPlus's per-line statuses (the Tableau log only flags in-footprint), so
# it is Sara; Activation Rate by Rep is the 60-day Tableau order log.
SOURCES: Dict[str, str] = {
    "activation_overview": "Sara",
    "activation_revenue": "Sara",
    "activation_by_rep": "Tableau",
    "activation_by_week": "Sara",
    "activation_by_week_tableau": "Tableau",
    # Carlos 2026-11-14 (screenshot of the churn boards: "These two should
    # have the source listed"): both compute off the 60-day Tableau D2D
    # order log — churn needs the lookback SaraPlus lacks.
    "churn_rates": "Tableau",
    "churn_by_rep": "Tableau",
}


def source_for(sid: str) -> Optional[str]:
    return SOURCES.get(sid)


def caption(sid: str, emoji: str, title: str, suffix: str = "") -> str:
    """The Slack comment over a section's picture; an activation report adds
    'Source: Sara' / 'Source: Tableau' on the line under the title."""
    head = f"{emoji} *{title}*{suffix}"
    src = source_for(sid)
    return f"{head}\nSource: {src}" if src else head


# ---------------------------------------------------------------- load ----

def _parse_date(v) -> Optional[dt.date]:
    """Date, tolerating an attached TIME — the alphaletegp dealer's export
    writes 'M/D/YYYY H:MM AM' where the b2b/Raf ones wrote bare dates, and
    the strict parse silently dropped nearly every sale out of the Revenue
    Board's week window (Carlos 2026-10-23: 'only showing one sale on
    monday')."""
    s = str(v or "").strip()
    if not s:
        return None
    head = s.split()[0].split("T")[0]
    for cand in (s, head):
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                return dt.datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    return None


def pull(today: dt.date, log=print) -> Path:
    """The NDS-SN (RES-ATT-OOF) ORDERLOG .csv with OUR 60-day window (its
    saved window pins stale — same gotcha as every one of these views)."""
    from automations.office_metrics import nds_orderlog as NO
    from automations.shared.tableau_patchright import tableau_session
    start = today - dt.timedelta(days=LOOKBACK_DAYS)
    out = OUT_DIR / f"nds_orderlog_{today.isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    def _looks_like_csv(b: bytes) -> bool:
        """2026-10-22, the first scheduled morning: Tableau returned an
        HTML page that PASSED the old status+size check, got cached, and
        read_crosstab died on it ('field larger than field limit') on every
        retry. A real export's head has no '<html' and carries a Rep
        column."""
        head = b[:4000].decode("utf-8-sig", errors="replace")
        low = head.lower()
        first = head.splitlines()[0] if head else ""
        # 'rep in head' was useless — every Tableau HTML page says 'report'.
        # A real export's FIRST LINE is a comma-separated header.
        return ("<html" not in low and "<!doctype" not in low
                and first.count(",") >= 5)
    if out.exists() and out.stat().st_size > 500 \
            and _looks_like_csv(out.read_bytes()):
        log(f"[nds] reusing today's pull ({out.stat().st_size:,} bytes)")
        return out
    if out.exists():
        out.unlink()                      # a cached bad download must die
    url = NO._orderlog_url(start, today)
    last = ""
    for attempt in (1, 2, 3):
        with tableau_session(verbose=False) as page:
            r = page.context.request.get(url, timeout=300_000)
            body = r.body() or b""
            ok = r.status == 200 and len(body) >= 500 \
                and _looks_like_csv(body)
            log(f"[nds] OL csv status={r.status} bytes={len(body):,} "
                f"valid={ok} (try {attempt}/3)")
            if ok:
                out.write_bytes(body)
                return out
            last = (f"status={r.status} bytes={len(body)} "
                    f"csv-like={_looks_like_csv(body)}")
            log("[nds] body head: "
                + body[:150].decode("utf-8-sig", "replace")
                      .replace("\n", " ")[:150])
    raise RuntimeError(f"NDS ORDERLOG export failed after 3 tries: {last}")


class Cols:
    """Tolerant column lookup — the crosstab reshapes; names, not indices."""

    def __init__(self, header: List[str]):
        self.header = [str(h or "").strip() for h in header]
        self._norm = [" ".join(h.lower().split()) for h in self.header]

    def find(self, *cands) -> Optional[int]:
        for c in cands:
            c = " ".join(c.lower().split())
            if c in self._norm:
                return self._norm.index(c)
        for c in cands:
            c = " ".join(c.lower().split())
            for i, h in enumerate(self._norm):
                if c in h:
                    return i
        return None

    def need(self, label, *cands) -> int:
        i = self.find(*cands)
        if i is None:
            raise RuntimeError(f"ndser log: no {label} column in "
                               f"{self.header}")
        return i


def crew_names(log=print) -> list:
    """Who counts as Carlos's crew on every NDS board: the hand-kept
    GUEST_REPS roster (the fiber-era list), Carlos himself, AND every rep
    on the Vantura 'NDS Sales Board'. Carlos 2026-11-03: "its only showing
    two people on the board that makes no sense" -- the Revenue Board (and
    every other crew-filtered section) had silently dropped each rep who
    joined after the roster was written on 9/25 (Annett, Elisa, Nathaly,
    Brianna, Esmeralda, Cinthya, Yahir, Eric, Valerie, Jorge Hernandez,
    Ruby ...). The board is the roster Carlos actually keeps; when it
    cannot be read the static list stands alone and the log says so."""
    from automations.total_knocks import guests
    names = list(guests.roster("Rafael Hidalgo", "Carlos Hidalgo")) + ["Carlos Hidalgo"]
    try:
        from automations.vantura_slack_sales.run import (NAME_COL, _cell,
                                                         board_grid,
                                                         campaign_rows)
        _ws, g = board_grid("B2B")
        board = [_cell(g, r, NAME_COL).strip()
                 for r in campaign_rows(g, "B2B").values()]
        board = [n for n in board if n]
        log(f"[nds] crew = {len(names)} roster name(s) + {len(board)} rep(s) "
            f"on the NDS Sales Board")
        names += board
    except Exception as e:  # noqa: BLE001 -- a board read never sinks the run
        log(f"[nds] NDS Sales Board roster unreadable ({type(e).__name__}: "
            f"{str(e)[:80]}) -- static roster only")
    seen, out = set(), []
    for n in names:
        k = " ".join(guests._tokens(n))
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def load_crew(path: Path, log=print):
    """-> (Cols, crew rows). Owner & Office = CARLOS HIDALGO, the export's
    long-format measure rows collapsed to one per line (every count doubled
    on the NDS-SN export — probed on Khalil's board 2026-10-05), then the
    crew roster as a safety filter against stragglers on his owner."""
    import csv as _csvmod
    _csvmod.field_size_limit(10_000_000)   # a giant Notes-ish cell must not
    # kill the parse (2026-10-22). Parse with nds_orderlog's own comma
    # reader — the commission crosstab reader SNIFFS the delimiter and a
    # tab inside that giant cell flipped it to tab, turning every row into
    # one cell ('Rep' header unfindable, StopIteration).
    from automations.office_metrics import nds_orderlog as NO
    from automations.total_knocks import guests
    rows = NO._read_csv(path)
    hdr_i = next(i for i, r in enumerate(rows)
                 if any(str(c).strip().lower() == "rep" for c in r))
    cols = Cols(rows[hdr_i])
    data = rows[hdr_i + 1:]
    i_owner = cols.need("owner", "owner name", "owner & office", "owner")
    i_rep = cols.need("rep", "rep")
    i_mn = cols.find("measure names")
    if i_mn is not None:
        measures = sorted({str(r[i_mn]).strip() for r in data
                           if len(r) > i_mn})
        keep = next((m for m in measures if "unit count" in m.lower()),
                    measures[0] if measures else "")
        before = len(data)
        data = [r for r in data
                if len(r) > i_mn and str(r[i_mn]).strip() == keep]
        log(f"[nds] long-format export: kept measure {keep!r} "
            f"({before} -> {len(data)})")
    mine = [r for r in data if len(r) > i_owner
            and "CARLOS" in str(r[i_owner]).upper()
            and "HIDALGO" in str(r[i_owner]).upper()]
    # Carlos sells too (2026-10-26: "i dont see my sale in the order log" —
    # the guest roster is the reps UNDER him and leaves him out, so his own
    # lines were filtered off every board).
    crew_toks = [guests._tokens(n) for n in crew_names(log)]

    def _is_crew(name: str) -> bool:
        t = guests._tokens(name)
        return any(guests._subseq(ct, t) or guests._subseq(t, ct)
                   for ct in crew_toks)

    crew = [r for r in mine
            if len(r) > i_rep and _is_crew(str(r[i_rep]).strip())]
    dropped = len(mine) - len(crew)
    log(f"[nds] {len(data)} line(s) -> carlos {len(mine)} -> crew "
        f"{len(crew)}" + (f" ({dropped} non-crew on his owner)" if dropped
                          else ""))
    if dropped:
        import collections as _coll2
        gone = _coll2.Counter(str(r[i_rep]).strip() for r in mine
                              if len(r) > i_rep
                              and not _is_crew(str(r[i_rep]).strip()))
        log("[nds] non-crew on his owner (dropped): "
            + ", ".join(f"{k}={v}" for k, v in gone.most_common(15)))
    # Every line on his owner, unfiltered -- the Revenue Board prices these
    # (Carlos 2026-11-03: "if you ever see a sale from someone not on the
    # list you still want to add it for the revenue board").
    cols.owner_lines = list(mine)
    if not crew and mine:
        log(f"[nds] crew filter matched NOBODY -- using all {len(mine)} "
            f"line(s) on his owner")
        crew = list(mine)
    if not crew:
        raise RuntimeError("nds log: ZERO crew lines — check the window / "
                           "owner spelling before posting anything")
    return cols, crew


def _c(cols: Cols, r, i: Optional[int]) -> str:
    return (str(r[i]).strip() if i is not None and len(r) > i and r[i]
            else "")


# ---------------------------------------------------------------- boards --

NDS_SARA_CREDS = (Path.home() / ".config" / "recruiting-report"
                  / "saraplus-creds-nds.json")
NDS_SARA_PROFILE = (REPO_ROOT / "automations" / "uploaded"
                    / ".saraplus_nds_profile")


def _pull_nds_soh(start: dt.date, end: dt.date, log=print) -> bytes:
    """Sales Order History off the NDS DEALER's SaraPlus (alphaletegp —
    Carlos 2026-10-22: 'you should have the new saraplus info'; the crew's
    orders re-homed there and the b2batt export went to zero overnight).
    Own creds file + own Chrome profile under automations/uploaded so
    chrome_guard protects it; the b2b and Raf dealers' profiles are never
    touched. Panel found by TEXT (fiber sara_pull's dealer-agnostic
    opener), not the b2b dealer's captured tab index."""
    import json as _json
    from patchright.sync_api import sync_playwright
    from automations.fiber_metrics.sara_pull import _open_soh_panel
    from automations.rc_contact_sync import config as RC
    from automations.rc_contact_sync import sara
    from automations.rc_contact_sync.status_probe import _export_csv
    cr = _json.loads(NDS_SARA_CREDS.read_text())
    NDS_SARA_PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # rc sara.login, not login_healing: it CLEARS the emailed-passcode
        # wall (first login hit SaraPasscodeWall 2026-10-22) by reading the
        # code from the reporting inbox — which works once alphaletegp
        # auto-forwards security.info@saraplus.com there, the same forward
        # the B2B account has (verify_code's own documented path).
        ctx = p.chromium.launch_persistent_context(
            str(NDS_SARA_PROFILE), headless=True, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # 2026-10-24: SaraPlus mails this login's passcode to alphaletegp's
        # OWN inbox (picker: 'alph...@gmail.com'), and no forward to the
        # reporting inbox exists -- every pull since 10/22 died here
        # (CodeNotFound). vantura_nds_sara.config.code_inbox() is that
        # inbox once its app password is on this box
        # (gmail-app-password-alphaletegp); None keeps the default.
        from automations.vantura_nds_sara import config as _NDS_CFG
        _inbox = _NDS_CFG.code_inbox()
        log("[nds] " + _NDS_CFG.code_inbox_status())
        base = sara.login(page, cr["email"], cr["password"], log=log,
                          code_inbox=_inbox)
        try:
            log(f"[nds] saraplus (nds dealer): logged in as {cr['email']}")
            page.goto(base + RC.HUB_PATH, wait_until="networkidle",
                      timeout=RC.NAV_TIMEOUT_MS)
            _open_soh_panel(page, log=log)
            sara._set_telerik_date(page, RC.FIELD_START, start)
            sara._set_telerik_date(page, RC.FIELD_END, end)
            try:
                sara._set_customer_type(page, RC.CUSTOMER_TYPE_BOTH, log=log)
                sara._set_telerik_date(page, RC.FIELD_START, start)
                sara._set_telerik_date(page, RC.FIELD_END, end)
            except Exception as e:  # noqa: BLE001 — dealer may lack it
                log(f"[nds] no Customer Type control ({e}) — dealer default")
            sara._submit(page, log=log)
            data = _export_csv(page, log)
            if not data or len(data) < 200:
                raise RuntimeError("NDS SOH export came back empty")
            try:
                _grid_protect(page, end, log=log)
            except Exception as e:  # noqa: BLE001 -- the sidecar never sinks the export
                log(f"[nds] protect grid read failed ({type(e).__name__}: "
                    f"{str(e)[:120]}) -- no protection sidecar today")
            return data
        finally:
            ctx.close()


def _grid_protect(page, today: dt.date, log=print) -> Path:
    """The Protection columns the on-screen Sales Order History grid carries
    and the CSV export leaves out: 'Protection Plans Sold', 'Protection Plan',
    'Plan Status' per order (Carlos 2026-11-06: "protect add ons should be on
    sara plus somewhere look again" -- the T&C probe's header dump showed them
    at [107] / [133] / [134]; the export has 97 of the grid's 142 columns).
    Pages through the grid that is already on screen after the export and
    writes OUT_DIR/nds_protect_<date>.json for line_revenue."""
    import json as _json
    from automations.nds_tnc_check.run import _next_page, _read_grid_raw
    want = {"order id": "order_id", "customer name": "customer",
            "protection plans sold": "sold", "protection plan": "plan",
            "plan status": "status", "wireless status": "wireless_status",
            "wireless active date": "active", "user name": "rep"}
    orders: dict = {}
    pages = 0
    while pages < 40:
        hdr, rows = _read_grid_raw(page)
        low = [" ".join(str(h).lower().split()) for h in hdr]
        ix = {k: low.index(h) for h, k in want.items() if h in low}
        if "order_id" not in ix:
            raise RuntimeError("grid has no Order ID column: "
                               + ", ".join(h for h in hdr if h)[:300])
        if pages == 0:
            missing = [h for h in ("protection plans sold", "protection plan", "plan status")
                       if h not in low]
            if missing:
                log(f"[nds] protect grid: columns missing on this dealer: {missing}")
        for r in rows:
            oid = r[ix["order_id"]].strip() if len(r) > ix["order_id"] else ""
            if not oid:
                continue
            orders[oid] = {k: (r[i].strip() if len(r) > i else "")
                           for k, i in ix.items() if k != "order_id"}
        pages += 1
        if not _next_page(page):
            break
    out = OUT_DIR / f"nds_protect_{today.isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with_plans = sum(1 for o in orders.values()
                     if (o.get("sold") or "0").strip() not in ("", "0", "0.0"))
    out.write_text(_json.dumps({"pulled": dt.datetime.now().isoformat(timespec="seconds"),
                                "pages": pages, "orders": orders}))
    log(f"[nds] protect grid: {len(orders)} order(s) over {pages} page(s), "
        f"{with_plans} with a protection plan -> {out.name}")
    return out


_SOH_MEMO: list = []


def load_soh(log=print):
    """The NDS DEALER's SaraPlus Sales Order History (_pull_nds_soh),
    crew-filtered. The crew's
    rows here ARE the NDS orders: before 10/19 they sold under Raf, so his
    own SOH carries only their NDS work. One pull a day, cached. -> (ix,
    crew_orders, pulled_at) or None (a failed pull skips the SaraPlus
    boards honestly rather than faking them from Tableau)."""
    if _SOH_MEMO:
        return _SOH_MEMO[0]
    import csv as _csv
    import io
    from automations.total_knocks import guests
    today = dt.date.today()
    cache = OUT_DIR / f"nds_soh_{today.isoformat()}.csv"
    try:
        if not (cache.exists() and cache.stat().st_size > 500):
            # BOTH dealers, merged (Carlos 2026-10-23: the new alphaletegp
            # dealer held only September crew orders + one current one — the
            # transition is mid-flight and current orders still land on the
            # b2batt account the callouts' credit checks read). Dedupe by
            # Order ID; either pull failing alone never empties the board.
            import csv as _mcsv
            import io as _mio
            start = today - dt.timedelta(days=31)
            parts = []
            # Carlos 2026-10-27: "carhi1816 is my b2b logins. we don't
            # need to use it for anything anymore" — the b2batt leg is
            # RETIRED. alphaletegp is the only NDS dealer (probe that day:
            # its one recent crew order was 10/19, pre-NDS).
            try:
                parts.append(("nds", _pull_nds_soh(start, today, log=log)))
            except Exception as e:  # noqa: BLE001
                log(f"[nds] nds-dealer pull blocked ({type(e).__name__})")
            if not parts:
                raise RuntimeError("the NDS dealer SOH pull failed")
            # The dealers' SOH grids are configured differently: the
            # alphaletegp export has no Customer Name / Wireless Order # /
            # Wireless Acct # columns at all (seen 2026-10-27, 100 cols),
            # while b2batt's carries them. The merge projects onto the
            # RICHEST header — the one with Customer Name — so the wrap-up
            # pipeline's fields survive; rows from the thinner export just
            # leave those cells blank.
            def _rows_of(blob):
                return list(_mcsv.reader(_mio.StringIO(
                    blob.decode("utf-8-sig", errors="replace"))))
            parts = sorted(
                parts,
                key=lambda nb: ("Customer Name" not in
                                [str(c).strip() for c in
                                 (_rows_of(nb[1])[:1] or [[]])[0]]))
            merged, seen, hdr_row = [], set(), None
            for name, blob in parts:
                rws = _rows_of(blob)
                if not rws:
                    continue
                h = [str(c).strip() for c in rws[0]]
                if hdr_row is None:
                    hdr_row = h
                    merged.append(h)
                hmap = {c: i for i, c in enumerate(h)}
                i_oid = hmap.get("Order ID")
                n_new = 0
                for r in rws[1:]:
                    oid = (str(r[i_oid]).strip()
                           if i_oid is not None and len(r) > i_oid else "")
                    if oid and oid in seen:
                        continue
                    if oid:
                        seen.add(oid)
                    # re-project onto the first header's column order
                    merged.append([r[hmap[c]] if c in hmap
                                   and len(r) > hmap[c] else ""
                                   for c in hdr_row])
                    n_new += 1
                log(f"[nds] SOH merge: {name} contributed {n_new} order(s)")
            out_txt = _mio.StringIO()
            _mcsv.writer(out_txt).writerows(merged)
            data = out_txt.getvalue().encode("utf-8")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        pulled_at = dt.datetime.fromtimestamp(cache.stat().st_mtime)
        rows = list(_csv.reader(io.StringIO(
            cache.read_bytes().decode("utf-8-sig", errors="replace"))))
    except Exception as e:  # noqa: BLE001
        log(f"[nds] SaraPlus pull unavailable ({type(e).__name__}: {e})")
        _SOH_MEMO.append(None)
        return None
    hdr = [str(h).strip() for h in rows[0]]
    ix = {h: i for i, h in enumerate(hdr)}
    for need in ("User Name", "Order Date", "Wireless Status",
                 "Wireless Active Date", "Wireless Line Count"):
        if need not in ix:
            log(f"[nds] SOH missing column {need!r}")
            _SOH_MEMO.append(None)
            return None
    # Customer Name is DISPLAY-only here (the aggregate boards don't need
    # it) and the alphaletegp grid doesn't export it yet (2026-10-28) —
    # warn, don't refuse. The wrap-up texter still requires it and stays
    # held until the column is added in the SaraPlus portal.
    if "Customer Name" not in ix:
        log("[nds] SOH has no Customer Name column — order log shows "
            "blank customers until the alphaletegp grid gains it")
    # Carlos sells too (2026-10-26: "i dont see my sale in the order log" —
    # the guest roster is the reps UNDER him and leaves him out, so his own
    # lines were filtered off every board).
    toks = [guests._tokens(n) for n in crew_names(log)]

    def _is_crew(n):
        t = guests._tokens(n)
        return any(guests._subseq(ct, t) or guests._subseq(t, ct)
                   for ct in toks)

    crew = [r for r in rows[1:] if len(r) > ix["User Name"]
            and _is_crew(r[ix["User Name"]].strip())]
    pre = len(crew)
    crew = [r for r in crew
            if (lambda d: d is not None and d >= NDS_SINCE)(
                _parse_date(r[ix["Order Date"]])
                if len(r) > ix["Order Date"] else None)]
    if pre != len(crew):
        log(f"[nds] SOH: floored at NDS start {NDS_SINCE} "
            f"({pre} -> {len(crew)} crew order(s))")
    # Who entered the RECENT orders — when this week's sales exist but the
    # crew filter misses them, the names here say why (2026-10-23: the
    # revenue board stuck at one rep while Tableau showed 36 crew lines).
    import collections as _coll
    _recent = _coll.Counter()
    for r in rows[1:]:
        d = (_parse_date(r[ix["Order Date"]])
             if len(r) > ix["Order Date"] else None)
        if d and (dt.date.today() - d).days <= 6 \
                and len(r) > ix["User Name"]:
            _recent[r[ix["User Name"]].strip() or "(blank)"] += 1
    log("[nds] SOH last-7d orders by entry name: "
        + (", ".join(f"{k}={v}" for k, v in _recent.most_common(10))
           or "NONE"))
    log(f"[nds] SOH: {len(rows) - 1} orders, crew {len(crew)}, pulled "
        f"{pulled_at:%m/%d %H:%M}")
    if crew:
        _ds = sorted(d for d in (_parse_date(r[ix["Order Date"]])
                                 for r in crew if len(r) > ix["Order Date"])
                     if d)
        if _ds:
            _wk = sum(1 for d in _ds
                      if (dt.date.today() - d).days <= 6)
            log(f"[nds] SOH crew dates: {_ds[0]}..{_ds[-1]}, "
                f"{_wk} in the last 7 days")
    if not crew:
        # 2026-10-22: the b2batt export came back with ZERO orders and the
        # Order Log + Revenue Board posted EMPTY into the thread. An empty
        # SaraPlus read is never boardable — skip (Tableau fallback where
        # one exists, honest skip where not). Kill the cache ONLY when the
        # export itself was empty (bad pull); when the NDS_SINCE floor is
        # what emptied it, the pull was fine — keep the cache or every
        # section re-pulls both dealers (2026-10-23: 30-min timeout).
        if len(rows) <= 1:
            try:
                cache.unlink()
            except OSError:
                pass
        _SOH_MEMO.append(None)
        return None
    if len(crew) < SOH_MIN_ORDERS:
        log(f"[nds] SOH has {len(crew)} NDS-era order(s) — below the trust "
            f"floor of {SOH_MIN_ORDERS}; boards stay on Tableau")
        _SOH_MEMO.append(None)
        return None
    res = (ix, crew, pulled_at)
    _SOH_MEMO.append(res)
    return res


def _soh_cell(ix, r, col):
    i = ix.get(col)
    return (str(r[i]).strip() if i is not None and len(r) > i and r[i]
            else "")


def build_order_log_soh(ix, crew, today, pulled_at, log=print) -> Path:
    """The crew's ORDERS off Carlos's SaraPlus — near-live, one row per order."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    cols = ["Rep", "Order Date", "Customer", "Phone", "Lines", "BYOD",
            "Wireless Status", "Active Date", "TPV", "City"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NDS Order Log (SaraPlus)"
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True)
    rows = sorted(crew, key=lambda r: (_soh_cell(ix, r, "User Name"),
                                       _parse_date(_soh_cell(
                                           ix, r, "Order Date"))
                                       or dt.date.min))
    for r in rows:
        st = _soh_cell(ix, r, "Wireless Status")
        ws.append([
            _soh_cell(ix, r, "User Name"),
            _soh_cell(ix, r, "Order Date"),
            _soh_cell(ix, r, "Customer Name"),
            _soh_cell(ix, r, "Phone"),
            _soh_cell(ix, r, "Wireless Line Count"),
            _soh_cell(ix, r, "BYOD Line Count"),
            st, _soh_cell(ix, r, "Wireless Active Date"),
            _soh_cell(ix, r, "TPV Status"),
            _soh_cell(ix, r, "City"),
        ])
        sl = st.lower()
        fill = ("C6EFCE" if sl == "active"
                else "FFC7CE" if "cancel" in sl or "disconnect" in sl
                else "FFF2CC" if sl else None)
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill)
    for col_cells in ws.columns:
        w = max((len(str(c.value or "")) for c in col_cells), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(
            max(w + 2, 9), 34)
    ws.freeze_panes = "A2"
    out = OUT_DIR / "NDS Order Log {}.xlsx".format(
        today.strftime("%m-%d-%Y"))
    wb.save(out)
    log(f"[nds] order log (SARAPLUS, pulled {pulled_at:%H:%M}): "
        f"{len(rows)} order(s)")
    return out


def build_pending_soh(ix, crew, today, pulled_at, log=print):
    """Chase list off Carlos's SaraPlus: no Wireless Active Date, not dead.
    Splits into two images past 20 rows (Carlos's B2B rule) — both returned,
    posted as one message."""
    from automations.box_order_log import pending_png
    from automations.box_order_log import pending as bp
    COLS = ("Customer", "Order Date", "Days Waiting", "Lines", "Status")

    class _Row:
        def __init__(self, cells, status, rep, sale_date, business):
            self.cells, self.status = cells, status
            self.history = ()
            self.rep, self.sale_date = rep, sale_date
            self.fields = {"Rep Name": rep, "Business Name": business}

    rows = []
    for r in crew:
        st = _soh_cell(ix, r, "Wireless Status")
        sl = st.lower()
        if _soh_cell(ix, r, "Wireless Active Date") or sl == "active" \
                or "cancel" in sl or "disconnect" in sl:
            continue
        od = _parse_date(_soh_cell(ix, r, "Order Date"))
        cust = _soh_cell(ix, r, "Customer Name")
        rows.append(_Row((cust,
                          od.strftime("%m/%d/%Y") if od else "",
                          str((today - od).days) if od else "",
                          _soh_cell(ix, r, "Wireless Line Count"),
                          st or "\u2014"),
                         sl, _soh_cell(ix, r, "User Name"), od, cust))
    n = len(rows)
    base = {"today": today,
            "title": "NDS — pending orders, not yet activated",
            "columns": COLS,
            "color_fn": lambda st, _h: "FFF2CC" if st else "",
            }
    sub = ("Crew orders on Carlos's SaraPlus with no activation yet — {} as "
           "of {} (pulled {}). Active and canceled excluded."
           .format("{} order{}".format(n, bp.plural(n)) if n
                   else "none right now",
                   today.strftime("%B %d, %Y"), f"{pulled_at:%H:%M}"))
    reps = bp.by_rep(rows)
    outs = []
    if n <= 20 or len(reps) < 2:
        work = dict(base, count=n, subtitle=sub,
                    sections=[{"key": "p", "title": None, "rows": rows,
                               "reps": reps, "empty_note":
                               "Nothing pending — every crew order is "
                               "activated or closed."}])
        out = OUT_DIR / "nds_pending_orders.png"
        pending_png.render(work, out)
        outs = [out]
    else:
        acc, cut = 0, 1
        for i, (_rep, rr) in enumerate(reps):
            acc += len(rr)
            if acc >= n / 2:
                cut = i + 1
                break
        cut = min(cut, len(reps) - 1)
        for i, part in enumerate((reps[:cut], reps[cut:]), 1):
            prows = [x for _rep, rr in part for x in rr]
            work = dict(base, count=len(prows),
                        title=base["title"] + f" ({i} of 2)",
                        subtitle=sub + f"  Part {i} of 2.",
                        sections=[{"key": "p", "title": None,
                                   "rows": prows, "reps": part,
                                   "empty_note": ""}])
            out = OUT_DIR / f"nds_pending_orders_{i}.png"
            pending_png.render(work, out)
            outs.append(out)
    log(f"[nds] pending (SARAPLUS): {n} order(s), {len(outs)} image(s)")
    return outs if len(outs) > 1 else outs[0]


# Carlos 2026-11-09 ("on this NDS order log report we need to add in the
# phone number for each line, in between the package and status column"):
# the crew's per-rep tabs carry the line's number (spe.TN — the All tab's
# Customer Phone column) between Package and Status, headed Phone Number.
# The house NDS rep tabs drop the number, and Raf's NDS offices keep theirs:
# this layout rides only on the crew's build below.
# 2026-11-10 (Carlos: "can we also add in the zip code on file"): the
# customer's zip (the export's 'Customer Zip Simple') rides along as a crew-
# only extra column -- Zip Code right after Phone Number on the rep tabs,
# Customer Zip at the end of the All tab. The export is Tableau's NDS-SN
# order log, not SaraPlus (whose wireless feed carries no address).
CREW_EXTRA_COLUMNS = [
    ("Customer Zip", "Customer Zip", ("customer zip simple", "customer zip", "zip")),
    # 11/11 (Carlos: "does our order log have a churn bucket column like b2b
    # had so we can see what disconnects are falling into what column?"):
    # the export carries none, so it is computed from the activation date
    # (nds_orderlog.churn_bucket) -- Tableau's 0-30 Day / 30 Day / 60 Day /
    # 90 Day / 120 Day columns. Right after Status on the rep tabs.
    ("Churn Bucket", "Churn Bucket", None),
]
# Carlos 2026-11-11 ("Let's add in: the wireless order number, BAN, the
# line, the type, device, ship date, delivered, port status, last updated"):
# the Vantura NDS Order Log TAB's own columns, on the crew's workbook too.
# The workbook is Tableau and the tab is the SaraPlus wireless feed, so each
# Tableau line is joined to its tab row by the line's phone number
# (order_log_tab.LineIndex over order_log_tab.preview = the rows the tab
# will carry after its own refresh later in the run). (tab header, workbook
# header): the tab's "Type" (Port / New / Upgrade) is "Line Type" on the
# workbook, whose Type already means Phone / Tablet / Wearable.
CREW_TAB_COLUMNS = [
    ("Wireless Order #", "Wireless Order #"), ("BAN", "BAN"), ("Line", "Line"),
    ("Type", "Line Type"), ("Device", "Device"), ("Ship Date", "Ship Date"),
    ("Delivered", "Delivered"), ("Port Status", "Port Status"),
    ("Last Updated", "Last Updated"),
]
CREW_TEXT_COLUMNS = ("Wireless Order #", "BAN")     # kept as text in the workbook
# Rep-tab order mirrors the tab's where the pinned placements allow: Package,
# Phone Number, Zip Code, Status, Churn Bucket stay contiguous (11/9-11/11).
CREW_REP_TAB_COLUMNS = [
    "Order Date", "Activation Date", "Customer Name", "SPM Number",
    "Wireless Order #", "BAN", "Line", "Line Type", "Type", "Device",
    "Next Up", "Package", "Customer Phone", "Customer Zip", "Status",
    "Churn Bucket", "Ship Date", "Delivered", "Port Status", "Last Updated",
    "Install Date", "Ported From", "Tier Bonus $",
]
CREW_REP_TAB_DISPLAY = {"Customer Phone": "Phone Number", "Customer Zip": "Zip Code"}


def crew_extra_columns(index=None):
    """CREW_EXTRA_COLUMNS plus the tab columns, each read off `index`
    (order_log_tab.LineIndex) by the row's phone number + DSI #. None =
    every tab column blank (no usable feed / tab rows today)."""
    def col(tab_header):
        def fn(get):
            if index is None:
                return ""
            return index.value(tab_header, phone=get("sp.Customer Phone"),
                               dsi=get("sp.SPM Number"))
        return fn
    return list(CREW_EXTRA_COLUMNS) + [(wb, wb, col(tab)) for tab, wb in CREW_TAB_COLUMNS]


def build_order_log(cols, crew, today, log=print) -> Path:
    """The crew's lines as a status-colored workbook. SaraPlus relay first
    (Carlos 2026-10-08: "lets make this come from sara plus instead"),
    Tableau when the relay is missing or stale."""
    # The wireless per-line feed first (Carlos 2026-10-29: B2B-style
    # workbook — All Reps / Pending by Rep / Paycheck by Week / tab per
    # rep, with customer first+last names, which only this feed carries).
    # THE house format (Carlos 2026-10-29, after the Activation/Pay Week
    # screenshot): the SAME renderer Raf's #alphalete-sales log and every
    # NDS office's log use — office_metrics.nds_orderlog through
    # uploaded.order_log's column_profile. Pay Period tab first, per-rep
    # tabs with "Week m/d to m/d • Paid Friday m/d" banners, the
    # Pending / Disconnect / Cancel section, and the Activation/Pay Week
    # calendar under every rep tab.
    try:
        from automations.office_metrics import nds_orderlog as NOL
        path = pull(today)
        # NOL.load wants an EXACT normalized owner; Carlos's cell carries
        # the office suffix, so match the way load_crew does.
        _all = NOL._read_csv(path)
        header2 = _all[0] if _all else []
        _oc = next((i for i, h in enumerate(header2)
                    if NOL._norm_h(h).startswith("owner")), 0)
        rows2 = [r for r in _all[1:]
                 if len(r) > _oc and "CARLOS" in str(r[_oc]).upper()
                 and "HIDALGO" in str(r[_oc]).upper()]
        if rows2:
            index = None
            try:
                from automations.nds_metrics import order_log_tab
                tab_rows = order_log_tab.preview(today, log=log)
                if tab_rows:
                    index = order_log_tab.LineIndex(tab_rows)
            except Exception as e:  # noqa: BLE001 -- tab columns blank; the log still ships
                log(f"[nds] house order log: tab columns unavailable "
                    f"({type(e).__name__}: {str(e)[:120]}) -- left blank")
            x, n = NOL._render_order_log("Carlos Hidalgo", header2, rows2,
                                         today, OUT_DIR,
                                         rep_tab_columns=CREW_REP_TAB_COLUMNS,
                                         rep_tab_display=CREW_REP_TAB_DISPLAY,
                                         extra_columns=crew_extra_columns(index),
                                         text_columns=CREW_TEXT_COLUMNS)
            log(f"[nds] house order log: {n} line(s) -> {Path(x).name}")
            if index is not None:
                log(f"[nds] house order log: tab columns matched {len(index.hits)} "
                    f"of {len(index.hits) + len(index.misses)} line(s)")
            else:
                log("[nds] house order log: tab columns blank (no feed/tab rows today)")
            return Path(x)
        log("[nds] house order log: no rows for Carlos — falling back")
    except Exception as e:  # noqa: BLE001
        log(f"[nds] house order log failed ({type(e).__name__}: "
            f"{str(e)[:140]}) — falling back")
    # IDENTICAL-format path (Carlos 2026-10-29): the same shape_lines +
    # att_order_log.xlsx builder his old log used — paycheck-week banners,
    # pay boxes, Pending by Rep, the shared colour map — fed by the NDS
    # SOH + wireless per-line scrape with the activation-day tracker.
    try:
        from automations.sp_order_log.run import build_artifacts_nds
        return build_artifacts_nds(out_dir=OUT_DIR, today=today,
                                   log=log)["xlsx"]
    except Exception as e:  # noqa: BLE001 — fall through to the plainer
        log(f"[nds] identical-format log failed ({type(e).__name__}: "
            f"{str(e)[:140]}) — falling back")
    from automations.nds_metrics import order_xlsx, wireless_pull
    wcache = wireless_pull.cached(today)
    if wcache:
        orders, wlines = wireless_pull.parse(wcache.read_bytes(), log=log)
        if wlines:
            return order_xlsx.build(orders, wlines, today, OUT_DIR, log=log)
    soh = load_soh(log=log)
    if soh:
        return build_order_log_soh(soh[0], soh[1], today, soh[2], log=log)
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    FILL = {"posted": "C6EFCE", "confirmed": "FFF2CC", "shipped": "FFF2CC",
            "disconnected": "FFC7CE", "canceled": "FFC7CE",
            "cancelled": "FFC7CE"}
    want = [
        ("Rep", ("rep",)),
        ("Order Date", ("sp.order date",)),
        ("Customer", ("customer name",)),
        ("SPM", ("sp.spm number",)),
        ("SPE", ("spe.name",)),
        ("Status", ("dtr status", "spe.status")),
        ("Active Date", ("dtr active date", "activatoin date", "dtr first available")),
        ("Product", ("product type (broken out)", "product")),
        ("Provider", ("spe.provider",)),
        ("Churn Bucket", ("churn buckets",)),
        ("Days to Disc", ("days to disconnect",)),
        ("Disc Reason", ("disconnect reason",)),
        ("Bonus Eligible $", ("bonus eligible",)),
    ]
    ix = [(label, cols.find(*cands)) for label, cands in want]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NDS Order Log"
    ws.append([label for label, _ in ix])
    for c in ws[1]:
        c.font = Font(bold=True)
    i_rep = cols.need("rep", "rep")
    i_od = cols.need("order date", "sp.order date")
    i_st = cols.find("dtr status", "spe.status")
    rows = sorted((r for r in crew
                   if (_parse_date(_c(cols, r, i_od)) or dt.date.min)
                   >= NDS_SINCE),
                  key=lambda r: (_c(cols, r, i_rep),
                                 _parse_date(_c(cols, r, i_od))
                                 or dt.date.min))
    for r in rows:
        ws.append([_c(cols, r, i) for _, i in ix])
        st = _c(cols, r, i_st).lower()
        fill = FILL.get(st)
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill)
    for col_cells in ws.columns:
        w = max((len(str(c.value or "")) for c in col_cells), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(
            max(w + 2, 9), 36)
    ws.freeze_panes = "A2"
    out = OUT_DIR / "NDS Order Log {}.xlsx".format(
        today.strftime("%m-%d-%Y"))
    wb.save(out)
    log(f"[nds] order log workbook: {len(rows)} line(s)")
    return out


def _activation_counts(cols, crew, today):
    """Per rep + crew total: sold / activated by sale-date bucket. Tablets,
    wearables and upgrades are not orders (Carlos 2026-11-10: "tablets
    watches and upgrades we should not count towards pending orders or
    activations") -- the rule lives in nds_churn.compute.counts_as_order so
    this board and the NDS CHURN tab's rate agree; the dropped count rides
    under '__EXCLUDED__'."""
    from automations.nds_churn import compute as NCC
    i_od = cols.need("order date", "sp.order date")
    i_st = cols.find("dtr status", "spe.status")
    i_rep = cols.need("rep", "rep")
    i_prod = cols.find("product type (broken out)", "product type")
    i_tn = cols.find("spe.tn type", "tn type")
    i_dev = cols.find("device description")
    i_wt = cols.find("spe.wireless type", "wireless type")
    i_pkg = cols.find("package")
    out: Dict[str, dict] = {}
    excluded = 0

    def slot(key, bucket):
        return out.setdefault(key, {b: {"sold": 0, "act": 0}
                                    for b in BUCKETS})[bucket]

    for r in crew:
        od = _parse_date(_c(cols, r, i_od))
        if od is None:
            continue
        rec = {"prod": NCC.product_of(_c(cols, r, i_prod)),
               "tn_type": _c(cols, r, i_tn), "device": _c(cols, r, i_dev),
               "package": _c(cols, r, i_pkg), "wireless_type": _c(cols, r, i_wt)}
        if not NCC.counts_as_order(rec):
            excluded += 1
            continue
        age = (today - od).days
        bucket = ("0-30 Day" if 0 <= age <= 30
                  else "31-60 Day" if 31 <= age <= 60 else None)
        if bucket is None:
            continue
        st = _c(cols, r, i_st).lower()
        act = st in POSTED or st == "disconnected"   # was active before it fell
        for key in (_c(cols, r, i_rep) or "(no rep)", "__TOTAL__"):
            c = slot(key, bucket)
            c["sold"] += 1
            if act:
                c["act"] += 1
    out["__EXCLUDED__"] = excluded
    return out


def build_activation_png(cols, crew, today, log=print) -> Path:
    from automations.b2b_metrics.rep_boards import render_table_png
    from automations.vantura_churn.fill import BANDS
    counts = _activation_counts(cols, crew, today)
    excluded = counts.pop("__EXCLUDED__", 0)

    def _color(bucket, rate):
        for floor, name in BANDS[_BAND_KEY[bucket]]:
            if rate >= floor:
                return name.capitalize()
        return ""

    def _cells(d):
        cells = {}
        for b in BUCKETS:
            c = d.get(b) or {}
            if not c.get("sold"):
                cells[b] = {}
                continue
            rate = c["act"] / c["sold"]
            cells[b] = {"act": str(c["sold"]), "disc": str(c["act"]),
                        "rate": f"{round(rate * 100, 1)}%",
                        "color": _color(b, rate)}
        return cells

    rows = [("Crew Total (all reps)", "", True, _cells(counts["__TOTAL__"]))]
    for rep in sorted(k for k in counts if k != "__TOTAL__"):
        rows.append((rep, "", False, _cells(counts[rep])))
    for b in BUCKETS:
        t = counts["__TOTAL__"][b]
        log(f"[nds] CREW {b}: {t['act']}/{t['sold']}")
    log(f"[nds] activation by rep: {excluded} tablet/wearable/upgrade line(s) not counted")
    return render_table_png(
        "NDS — ACTIVATION RATES BY REP",
        f"Carlos's crew on his own NDS code — {today.strftime('%B %d, %Y')} "
        "(activated/sold by sale-date age from the D2D order log; phones, Air "
        "and Internet only — tablets, watches and upgrades not counted; cancels "
        "count as sold; Posted = activated; total = whole crew)",
        list(BUCKETS), rows, OUT_DIR / "nds_activation_by_rep.png")


def build_pending_png(cols, crew, today, log=print):
    """Chase list: sold in the last 31 days, not activated, not dead.
    SaraPlus relay first; Tableau fallback."""
    soh = load_soh(log=log)
    if soh:
        return build_pending_soh(soh[0], soh[1], today, soh[2], log=log)
    from automations.box_order_log import pending_png
    from automations.box_order_log import pending as bp
    i_od = cols.need("order date", "sp.order date")
    i_st = cols.find("dtr status", "spe.status")
    i_rep = cols.need("rep", "rep")
    i_cust = cols.find("customer name")
    COLS = ("Customer", "Sale Date", "Days Waiting", "Status")

    class _Row:
        def __init__(self, cells, status, rep, sale_date, business):
            self.cells, self.status = cells, status
            self.history = ()
            self.rep, self.sale_date = rep, sale_date
            self.fields = {"Rep Name": rep, "Business Name": business}

    rows = []
    for r in crew:
        od = _parse_date(_c(cols, r, i_od))
        if od is None or (today - od).days > 31 or od < NDS_SINCE:
            continue
        st = _c(cols, r, i_st)
        sl = st.lower()
        if sl in POSTED or sl in DEAD:
            continue
        cust = _c(cols, r, i_cust)
        rows.append(_Row((cust, od.strftime("%m/%d/%Y"),
                          str((today - od).days), st or "—"),
                         sl, _c(cols, r, i_rep), od, cust))
    n = len(rows)
    work = {"today": today, "count": n,
            "title": "NDS — pending orders, not yet activated",
            "subtitle": ("Crew lines sold in the last 31 days with no "
                         "activation yet — {} as of {}. Confirmed/Shipped/"
                         "blank statuses; Posted and dead lines excluded."
                         .format("{} line{}".format(n, bp.plural(n)) if n
                                 else "none right now",
                                 today.strftime("%B %d, %Y"))),
            "columns": COLS,
            "color_fn": lambda st, _h: {"shipped": "FFF2CC",
                                        "confirmed": "FFF2CC"}.get(st, ""),
            "sections": [{"key": "pending", "title": None, "rows": rows,
                          "reps": bp.by_rep(rows),
                          "empty_note": "Nothing pending — every crew line "
                                        "is activated or closed."}]}
    out = OUT_DIR / "nds_pending_orders.png"
    pending_png.render(work, out)
    log(f"[nds] pending orders: {n} line(s)")
    return out


def build_churn_rolloff_png(cols, crew, today, log=print) -> Path:
    """The 0-30 rolloff list — the log's own churn columns do the dating."""
    from automations.b2b_metrics.rep_boards import render_table_png
    i_od = cols.need("order date", "sp.order date")
    i_st = cols.find("dtr status", "spe.status")
    i_rep = cols.need("rep", "rep")
    i_cust = cols.find("customer name")
    i_fa = cols.find("dtr active date", "activatoin date", "dtr first available")
    i_dtd = cols.find("days to disconnect")
    i_why = cols.find("disconnect reason")
    i_bkt = cols.find("churn buckets")

    rows_out, n_disc = [], 0
    for r in crew:
        if _c(cols, r, i_st).lower() != "disconnected":
            continue
        bucket = _c(cols, r, i_bkt)
        if bucket and "0-30" not in bucket and "0 - 30" not in bucket:
            continue                     # only the 0-30 window chase list
        act = _parse_date(_c(cols, r, i_fa)) or _parse_date(_c(cols, r, i_od))
        dtd = _c(cols, r, i_dtd)
        disc_day = None
        try:
            if act and dtd:
                disc_day = act + dt.timedelta(days=int(float(dtd)))
        except ValueError:
            pass
        ages_off = (act + dt.timedelta(days=30)) if act else None
        days_left = (ages_off - today).days if ages_off else None
        n_disc += 1
        rows_out.append(((days_left if days_left is not None else 99),
                         (_c(cols, r, i_rep), "", False, {
            "Days Left": {"act": "", "disc": "",
                          "rate": str(days_left) if days_left is not None
                          else "?", "color": ""},
            "Customer": {"rate": _c(cols, r, i_cust)},
            "Activated": {"rate": act.strftime("%m/%d") if act else ""},
            "Disconnected": {"rate": disc_day.strftime("%m/%d")
                             if disc_day else ""},
            "Reason": {"rate": (_c(cols, r, i_why) or "")[:28]},
        })))
    rows_out.sort(key=lambda t: t[0])
    cols_list = ["Days Left", "Customer", "Activated", "Disconnected",
                 "Reason"]
    table = [t[1] for t in rows_out] or [
        ("No 0-30 disconnects right now", "", True,
         {c: {} for c in cols_list})]
    log(f"[nds] churn rolloff: {n_disc} disconnected line(s) in 0-30")
    return render_table_png(
        "NDS — 0-30 DAY ROLLOFF LIST",
        f"Carlos's crew on his own NDS code — {today.strftime('%B %d, %Y')} "
        "(disconnected lines still inside the 0-30 window, soonest to age "
        "off first; dates from the log's own churn columns)",
        cols_list, table, OUT_DIR / "nds_customer_churn.png")


def build_churn_rates_png(cols, crew, today, log=print) -> Path:
    """Crew churn per product per bucket — computed, since the D2D CHURN
    views only know offices."""
    from automations.b2b_metrics.rep_boards import render_table_png
    i_od = cols.need("order date", "sp.order date")
    i_st = cols.find("dtr status", "spe.status")
    i_prod = cols.find("product type (broken out)", "product")
    agg: Dict[str, dict] = {}
    for r in crew:
        od = _parse_date(_c(cols, r, i_od))
        if od is None:
            continue
        age = (today - od).days
        bucket = ("0-30 Day" if 0 <= age <= 30
                  else "31-60 Day" if 31 <= age <= 60 else None)
        if bucket is None:
            continue
        st = _c(cols, r, i_st).lower()
        if not (st in POSTED or st == "disconnected"):
            continue                       # churn base = activated lines
        prod = _c(cols, r, i_prod) or "(unknown)"
        for key in (prod, "__ALL__"):
            c = agg.setdefault(key, {b: {"act": 0, "disc": 0}
                                     for b in BUCKETS})[bucket]
            c["act"] += 1
            if st == "disconnected":
                c["disc"] += 1

    def _cells(d):
        cells = {}
        for b in BUCKETS:
            c = d.get(b) or {}
            if not c.get("act"):
                cells[b] = {}
                continue
            rate = c["disc"] / c["act"]
            cells[b] = {"act": str(c["act"]), "disc": str(c["disc"]),
                        "rate": f"{round(rate * 100, 1)}%",
                        "color": ("Green" if rate < 0.04 else
                                  "Yellow" if rate < 0.06 else "Red")}
        return cells

    rows = [("Crew Total (all products)", "", True,
             _cells(agg.get("__ALL__", {})))]
    for prod in sorted(k for k in agg if k != "__ALL__"):
        rows.append((prod, "", False, _cells(agg[prod])))
    return render_table_png(
        "NDS — CHURN RATES",
        f"Carlos's crew on his own NDS code — {today.strftime('%B %d, %Y')} "
        "(disconnects ÷ activated lines, by sale-date age; provisional "
        "bands green<4% yellow<6% until the NDS comp sets real ones)",
        list(BUCKETS), rows, OUT_DIR / "nds_churn_rates.png")


def build_activation_overview(cols, crew, today, log=print) -> Path:
    """#4 Activation Report Overview — the two weekly tables (Posted /
    Pending / Cancelled per rep), UNITS not orders (each order fanned out by
    its Wireless Line Count — Carlos's B2B counting rule), from Raf's
    SaraPlus relay. No Tableau fallback on purpose: a days-stale 'overview'
    reads as fresh and lies; a skipped section is honest."""
    from automations.att_order_log import payout as ap
    from automations.box_order_log import png as bpng
    soh = load_soh(log=log)
    if not soh:
        raise RuntimeError("activation overview needs the SaraPlus relay — "
                           "run nds_sara_pull on Lucy 1 first")
    ix, orders, pulled_at = soh
    lines = []
    for r in orders:
        st = _soh_cell(ix, r, "Wireless Status").lower()
        status = ("active" if st == "active"
                  else "canceled" if ("cancel" in st or "disconnect" in st)
                  else (st or "pending"))
        try:
            n = max(1, int(float(_soh_cell(ix, r, "Wireless Line Count")
                                 or 1)))
        except ValueError:
            n = 1
        base = {"Rep": _soh_cell(ix, r, "User Name"),
                ap.POSTED_DATE_COL: _soh_cell(ix, r, "Wireless Active Date"),
                "DTR Status (enriched)": status}
        lines.extend(dict(base) for _ in range(n))
    # sp_order_log's builder owns the activated->posted/open->pending remap
    # and the COLS override (KeyError:'posted' on the first fiber render) —
    # one builder, both campaigns.
    from automations.sp_order_log.run import build_overview_png
    out = build_overview_png(lines, today, log=log,
                             out_path=OUT_DIR / "nds_activation_overview.png")
    log(f"[nds] activation overview (SARAPLUS, pulled {pulled_at:%H:%M}): "
        f"{len(lines)} unit(s)")
    return out


def build_churn_by_rep_png(cols, crew, today, log=print) -> Path:
    """#11 Churn by Rep — disconnects / activated per rep per bucket, from
    the 60-day D2D log (churn needs the longer lookback SaraPlus lacks)."""
    from automations.b2b_metrics.rep_boards import render_table_png
    i_od = cols.need("order date", "sp.order date")
    i_st = cols.find("dtr status", "spe.status")
    i_rep = cols.need("rep", "rep")
    i_prod = cols.find("product type (broken out)", "product")
    agg: Dict[tuple, dict] = {}
    prods = set()
    for r in crew:
        od = _parse_date(_c(cols, r, i_od))
        if od is None:
            continue
        age = (today - od).days
        bucket = ("0-30 Day" if 0 <= age <= 30
                  else "31-60 Day" if 31 <= age <= 60 else None)
        if bucket is None:
            continue
        st = _c(cols, r, i_st).lower()
        if not (st in POSTED or st == "disconnected"):
            continue
        rep = _c(cols, r, i_rep) or "(no rep)"
        prod = _c(cols, r, i_prod) or "(unknown)"
        prods.add(prod)
        for key in ((rep, prod), ("__TOTAL__", "")):
            c = agg.setdefault(key, {b: {"act": 0, "disc": 0}
                                     for b in BUCKETS})[bucket]
            c["act"] += 1
            if st == "disconnected":
                c["disc"] += 1

    def _cells(d):
        cells = {}
        for b in BUCKETS:
            c = d.get(b) or {}
            if not c.get("act"):
                cells[b] = {}
                continue
            rate = c["disc"] / c["act"]
            cells[b] = {"act": str(c["act"]), "disc": str(c["disc"]),
                        "rate": f"{round(rate * 100, 1)}%",
                        "color": ("Green" if rate < 0.04 else
                                  "Yellow" if rate < 0.06 else "Red")}
        return cells

    multi = len(prods) > 1
    rows = [("Crew Total (all reps)", "All products" if multi else "", True,
             _cells(agg.get(("__TOTAL__", ""), {})))]
    last_rep = None
    for (rep, prod) in sorted(k for k in agg if k[0] != "__TOTAL__"):
        rows.append((rep if rep != last_rep else "",
                     prod if multi else "", False, _cells(agg[(rep, prod)])))
        last_rep = rep
    log(f"[nds] churn by rep: {len(rows) - 1} row(s), "
        f"{len(prods)} product(s)")
    return render_table_png(
        "NDS — CHURN BY REP",
        f"Carlos's crew on his own NDS code — {today.strftime('%B %d, %Y')} "
        "(disconnects ÷ activated by sale-date age, from the D2D order "
        "log; provisional bands green<4% yellow<6%)",
        list(BUCKETS), rows, OUT_DIR / "nds_churn_by_rep.png")


def sow_rates():
    global _SOW
    if _SOW is None:
        import json as _json
        _SOW = _json.loads((Path(__file__).parent
                            / "sow_rates.json").read_text())
    return _SOW


def price_order(ix, r) -> float:
    """One SaraPlus order priced on the ATT-D2D-OOF Schedule A at BASE COMP
    (Tier 3-3 — Carlos 2026-10-09: 'assume base comp for now'). OOF rates
    (this IS the OOF program; the export carries no IF/OOF flag). BYOD lines
    are priced as BYOD PORTS (ports dominate; the export doesn't split BYOD
    new vs port). Add-ons (Next Up / Unlimited / Protect) aren't in the
    export yet — stated on every board that shows these dollars."""
    sw = sow_rates()["wireless"]

    def _n(col):
        try:
            return max(0, int(float(_soh_cell(ix, r, col) or 0)))
        except ValueError:
            return 0

    port = _n("Port Line Count")
    byod = _n("BYOD Line Count")
    new = _n("New Line Count")
    upg = _n("Upgrade Line Count")
    port_nb = max(0, port - byod)
    byod_paid = min(byod, port) if port else byod
    return (port_nb * sw["port_nonbyod"]["OOF"]
            + byod_paid * sw["port_byod"]["OOF"]
            + max(0, byod - byod_paid) * sw["port_byod"]["OOF"]
            + new * sw["new_line"]
            + upg * sw["upgrade_voice"])


def build_activation_revenue(cols, crew, today, log=print) -> Path:
    """#5 Activation Revenue Overview — activated $ per rep by activation
    week, SaraPlus orders priced on the SOW at base comp."""
    from automations.att_order_log import payout as ap
    from automations.box_order_log import png as bpng
    soh = load_soh(log=log)
    if not soh:
        raise RuntimeError("activation revenue needs the SaraPlus relay")
    ix, orders, pulled_at = soh
    ls, le, ts, te = ap.week_bounds(today)
    reps: Dict[str, dict] = {}
    for r in orders:
        rep = _soh_cell(ix, r, "User Name")
        if not rep:
            continue
        a = reps.setdefault(rep, {"posted_last": 0.0, "posted_this": 0.0,
                                  "open": 0.0, "can_last": 0.0,
                                  "can_this": 0.0})
        amt = price_order(ix, r)
        st = _soh_cell(ix, r, "Wireless Status").lower()
        act = _parse_date(_soh_cell(ix, r, "Wireless Active Date"))
        if "cancel" in st or "disconnect" in st:
            which = "can_last" if (act and ls <= act <= le) else "can_this"
            a[which] += amt
        elif act is None:
            a["open"] += amt
        elif ls <= act <= le:
            a["posted_last"] += amt
        elif ts <= act <= te:
            a["posted_this"] += amt

    def _table(start, end, pk, ck):
        rows = [{"rep": rep, "posted": round(a[pk]),
                 "pending": round(a["open"]), "canceled": round(a[ck])}
                for rep, a in reps.items()]
        rows.sort(key=lambda x: (-x["posted"], x["rep"].lower()))
        totals = {k: sum(x[k] for x in rows)
                  for k in ("posted", "pending", "canceled")}
        return {"label": ap.label(start, end), "rows": rows,
                "totals": totals}

    tables = {"last": _table(ls, le, "posted_last", "can_last"),
              "this": _table(ts, te, "posted_this", "can_this")}
    out = OUT_DIR / "nds_activation_revenue.png"
    saved = list(bpng.COLS)
    bpng.COLS[:] = [("Rep Name", "rep", "left"),
                    ("Posted $", "posted", "center"),
                    ("Cancelled $", "canceled", "center"),
                    ("Still Open $", "pending", "center")]
    try:
        bpng.render(tables, out, money=True,
                    subtitle="NDS — activated $ by activation week, "
                             "ATT-D2D-OOF SOW at BASE COMP (Tier 3-3, OOF "
                             "rates; BYOD priced as BYOD port; add-ons not "
                             f"in the export). SaraPlus pulled "
                             f"{pulled_at:%H:%M}.")
    finally:
        bpng.COLS[:] = saved
    log("[nds] activation revenue (SARAPLUS + SOW base comp)")
    return out


def build_override_board(cols, crew, today, log=print) -> Path:
    """NDS Leader Overrides, SECTIONS layout (Carlos 2026-10-29): one
    section per tree leader with first-gen trainees. Each trainee row =
    what the DD actually PAID them for the latest settled week (the
    Scoutly RAW tab, NDS Wireless campaign — SaraPlus statuses lag the
    per-line payouts, so the deposit is the only source that matches
    itself), then the leader's total with the override at 2.5/5/7.5/10%.
    First generation only."""
    import collections
    from PIL import Image, ImageDraw
    from automations.recruiting_report.fill import open_by_key
    from automations.sales_boards.render import _title_font, title_bar
    from automations.team_tree import run as TT
    from automations.total_knocks import guests as gst

    sh = open_by_key("1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY")
    raw = next(w for w in sh.worksheets()
               if w.title.strip().lower() == "raw")
    vals = raw.get_all_values()
    hix = {h: k for k, h in enumerate(vals[0])}
    weeks = [r[0].strip() for r in vals[1:] if r and r[0].strip()]
    week = weeks[-1] if weeks else "?"

    def money(v):
        try:
            return float(str(v).replace("$", "").replace(",", "") or 0)
        except ValueError:
            return 0.0

    paid = collections.defaultdict(float)
    for r in vals[1:]:
        if (r and r[0].strip() == week
                and r[hix["Campaign"]].strip() == "NDS Wireless"):
            paid[r[hix["Rep Name"]].strip()] += money(
                r[hix["Total $ to ICD"]])
    log(f"[nds] overrides: DD week {week!r}, {len(paid)} paid rep(s), "
        f"${sum(paid.values()):,.0f} NDS total")

    _wk, reps, _roots, _sched = TT.build(today)

    def paid_for(name):
        t = gst._tokens(name)
        for rep, amt in paid.items():
            rt = gst._tokens(rep)
            if gst._subseq(t, rt) or gst._subseq(rt, t):
                return amt
        return 0.0

    sections = []
    for leader in reps:
        kids = list(leader.children)
        if not kids:
            continue
        rows = [(k.name, paid_for(k.name)) for k in kids]
        rows.sort(key=lambda x: -x[1])
        total = sum(v for _n, v in rows)
        sections.append((leader.name, rows, total))
    sections.sort(key=lambda s: -s[2])

    # ---------------- render: one table per leader, stacked ----------
    S = 2
    COLW = [230 * S, 95 * S, 80 * S, 80 * S, 80 * S, 80 * S]
    W = sum(COLW)
    ROW = 26 * S
    f_head = _title_font(13 * S)
    f_cell = _title_font(12 * S)
    HEADS = ["First Gen", "Paid $", "2.5%", "5%", "7.5%", "10%"]
    NAVY, LBLUE, GREY = (46, 84, 150), (178, 203, 233), (229, 229, 229)

    def table_height(n_rows):
        return ROW * (1 + n_rows + 1) + 14 * S

    H = 60 * S + sum(table_height(len(rows)) + 16 * S
                     for _l, rows, _t in sections)
    img = Image.new("RGB", (W + 24 * S, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = 8 * S
    d.text((12 * S, y),
           f"NDS Leader Overrides — DD WE {week} (what the deposit paid "
           "each first gen) x 2.5% / 5% / 7.5% / 10%",
           font=f_cell, fill=(90, 90, 90))
    y += 26 * S

    def row_out(cells, y, bg, bold=False):
        x = 12 * S
        for (val, w) in zip(cells, COLW):
            d.rectangle([x, y, x + w, y + ROW], fill=bg,
                        outline=(120, 120, 120))
            d.text((x + 6 * S, y + 5 * S), str(val),
                   font=f_head if bold else f_cell, fill=(20, 20, 20))
            x += w
        return y + ROW

    for leader, rows, total in sections:
        d.rectangle([12 * S, y, 12 * S + W, y + ROW], fill=NAVY)
        d.text((18 * S, y + 5 * S),
               f"{leader}  —  {len(rows)} first gen", font=f_head,
               fill=(255, 255, 255))
        y += ROW
        y = row_out(HEADS, y, LBLUE, bold=True)
        for name, amt in rows:
            y = row_out([name, f"${amt:,.0f}", f"${amt*.025:,.0f}",
                         f"${amt*.05:,.0f}", f"${amt*.075:,.0f}",
                         f"${amt*.10:,.0f}"], y, (255, 255, 255))
        y = row_out([f"{leader.split()[0].upper()} TOTAL",
                     f"${total:,.0f}", f"${total*.025:,.0f}",
                     f"${total*.05:,.0f}", f"${total*.075:,.0f}",
                     f"${total*.10:,.0f}"], y, GREY, bold=True)
        y += 16 * S
    out = OUT_DIR / "nds_override_board.png"
    img.crop((0, 0, img.width, min(img.height, y + 8 * S))).save(out)
    for leader, rows, total in sections:
        log(f"[nds] overrides {leader}: 1st-gen paid ${total:,.0f} -> "
            f"2.5% ${total*.025:,.0f} / 5% ${total*.05:,.0f} / "
            f"7.5% ${total*.075:,.0f} / 10% ${total*.10:,.0f}")
    return out


def build_knocks_final(cols, crew, today, log=print) -> Path:
    """Yesterday's LAST knocks board (Carlos 2026-10-28: "the last nds
    knocks board from the day prior should also be posted every morning
    in the NDS thread"). nds_oof renders all day into
    output/nds_oof/<date>/total_knocks_*.png on this machine — the newest
    one by mtime IS the day's final board. No render of its own: a day
    with no knocks run is an honest skip."""
    from automations.nds_oof.run import OUTPUT_DIR as _NOOF
    yday = today - dt.timedelta(days=1)
    cands = sorted((_NOOF / yday.isoformat()).glob("*knocks*.png"),
                   key=lambda q: q.stat().st_mtime)
    if not cands:
        raise RuntimeError(f"no knocks boards rendered for {yday}")
    log(f"[nds] knocks final: {cands[-1].name} "
        f"({dt.datetime.fromtimestamp(cands[-1].stat().st_mtime):%H:%M})")
    return cands[-1]


def build_revenue_board(cols, crew, today, log=print) -> Path:
    """#1 Revenue Board — styled like the B2B one, base-comp mode, but
    priced from the TABLEAU NDS log, not SaraPlus. 2026-10-23: both
    SaraPlus dealers combined held ONE order from the last 7 days (crew
    data ends 10/19 — the switchover day); OOF orders route through the
    call center and reach SaraPlus days late, while the NDS-SN log carries
    this week's sales. Per line: port when 'Ported From' is set (else new),
    BYOD read from the Package string; SOW base-comp OOF rates."""
    from automations.vantura_revenue_board.run import (build_rows, render,
                                                       week_of)
    sw = sow_rates()["wireless"]
    i_od = cols.need("order date", "sp.order date")
    i_rep = cols.need("rep", "rep")
    i_port = cols.find("ported from", "port")
    i_pkg = cols.find("package")
    i_tn = cols.find("spe.tn type", "tn type")
    monday = week_of(today)
    # Carlos 2026-11-03: "if you ever see a sale from someone not on the
    # list you still want to add it for the revenue board" -- every line on
    # his owner prices here; the crew roster never drops one.
    lines = getattr(cols, "owner_lines", None) or crew
    extra = sorted({_c(cols, r, i_rep) for r in lines}
                   - {_c(cols, r, i_rep) for r in crew} - {""})
    if extra:
        log(f"[nds] revenue board: +{len(extra)} rep(s) off the roster, "
            f"kept: {', '.join(extra)}")
    per_rep: Dict[str, dict] = {}
    for r in lines:
        od = _parse_date(_c(cols, r, i_od))
        rep = _c(cols, r, i_rep)
        if not rep or od is None or not (monday <= od <= today):
            continue
        tn = _c(cols, r, i_tn).lower()
        ported = bool(_c(cols, r, i_port)) or tn == "port"
        byod = "BYOD" in _c(cols, r, i_pkg).upper()
        if ported:
            amt = (sw["port_byod"] if byod else sw["port_nonbyod"])["OOF"]
        else:
            amt = sw["new_line"]
        rec = per_rep.setdefault(rep, {"days": {}, "elig": 0, "payable": 0})
        rec["days"][od] = rec["days"].get(od, 0.0) + amt
    rows, office = build_rows(per_rep, monday, today, tiered=False)
    out = render(rows, office, monday, today,
                 OUT_DIR / "nds_revenue_board.png",
                 board_name="NDS Revenue Board", tiered=False)
    log(f"[nds] revenue board (styled, ALL lines on his owner): {len(rows)} rep(s), "
        f"crew ${sum(r['total'] for r in rows):,.0f}")
    return out


def build_sales_metrics(cols, crew, today, log=print) -> Path:
    """#2 Sales Metrics — the D2D 'Metrics' view shot, scoped to Rafael
    Hidalgo (the office Carlos's crew sells under). A view screenshot can't
    slice to the crew, so this is RAF'S WHOLE OFFICE, said on the caption.
    Reuses office_metrics' per-day shot cache (every office's shot is
    captured in one session each morning); captures fresh only if today's
    isn't there yet."""
    import shutil
    from automations.office_metrics import metrics_shot as MS
    out = OUT_DIR / "nds_sales_metrics.png"
    shot = MS.cached_shot(MS.MAIN_OWNER)
    if shot is None:
        log("[nds] no cached Metrics shot yet today — capturing")
        shot = MS.capture(MS.MAIN_OWNER, out_dir=OUT_DIR,
                          filter_field=MS.DEFAULT_FILTER_FIELD,
                          headless=True)
    shutil.copyfile(shot, out)
    log(f"[nds] sales metrics shot: {Path(shot).name}")
    return out


_SOW = None


def sow_rates():
    global _SOW
    if _SOW is None:
        import json as _json
        _SOW = _json.loads((Path(__file__).parent
                            / "sow_rates.json").read_text())
    return _SOW


def price_order(ix, r) -> float:
    """One SaraPlus order priced on the ATT-D2D-OOF Schedule A at BASE COMP
    (Tier 3-3 — Carlos 2026-10-09: 'assume base comp for now'). OOF rates
    (this IS the OOF program; the export carries no IF/OOF flag). BYOD lines
    are priced as BYOD PORTS (ports dominate; the export doesn't split BYOD
    new vs port). Add-ons (Next Up / Unlimited / Protect) aren't in the
    export yet — stated on every board that shows these dollars."""
    sw = sow_rates()["wireless"]

    def _n(col):
        try:
            return max(0, int(float(_soh_cell(ix, r, col) or 0)))
        except ValueError:
            return 0

    port = _n("Port Line Count")
    byod = _n("BYOD Line Count")
    new = _n("New Line Count")
    upg = _n("Upgrade Line Count")
    port_nb = max(0, port - byod)
    byod_paid = min(byod, port) if port else byod
    return (port_nb * sw["port_nonbyod"]["OOF"]
            + byod_paid * sw["port_byod"]["OOF"]
            + max(0, byod - byod_paid) * sw["port_byod"]["OOF"]
            + new * sw["new_line"]
            + upg * sw["upgrade_voice"])


def build_activation_revenue(cols, crew, today, log=print) -> Path:
    """#5 Activation Revenue Overview -- $ per rep by activation week, priced
    per LINE the way the deposit pays (line_revenue: the SaraPlus wireless
    report's per-line statuses + the activation-day ledger + Internet Air
    off the SOH; Mon-Sun weeks). Carlos 2026-11-06: "price each individual
    line and add internet air". Orders the wireless report does not carry
    fall back to price_order at order level."""
    from automations.nds_metrics import line_revenue
    soh = load_soh(log=log)
    if not soh:
        raise RuntimeError("activation revenue needs the SaraPlus relay")
    return line_revenue.build(soh, today, OUT_DIR / "nds_activation_revenue.png",
                              log=log,
                              tableau=(cols, getattr(cols, "owner_lines", None) or crew))

def build_activation_by_week(cols, crew, today, log=print) -> Path:
    """Activation rate by Mon-Sun week ending, the last 5 weeks since NDS
    started (Carlos 2026-11-06) -- activation_by_week.py."""
    from automations.nds_metrics import activation_by_week as AW
    soh = load_soh(log=log)
    if not soh:
        raise RuntimeError("activation by week needs the SaraPlus relay")
    return AW.build(soh, today, OUT_DIR / "nds_activation_by_week.png", log=log)


def build_activation_by_week_tableau(cols, crew, today, log=print) -> Path:
    """The Tableau twin of #activation_by_week, posted right after it (Carlos
    2026-11-13: "can you make a tableau version and post both always") --
    activation_by_week.build_tableau off this run's order-log pull."""
    from automations.nds_metrics import activation_by_week as AW
    path = OUT_DIR / f"nds_orderlog_{today.isoformat()}.csv"
    pulled_at = (dt.datetime.fromtimestamp(path.stat().st_mtime)
                 if path.exists() else None)
    return AW.build_tableau(cols, crew, today,
                            OUT_DIR / "nds_activation_by_week_tableau.png",
                            pulled_at=pulled_at, log=log)


def build_rep_tiers_shot(cols, crew, today, log=print) -> Path:
    from automations.nds_metrics import tableau_shots as TS
    return TS.capture("rep_tiers", OUT_DIR, log=log)


def build_top_reps_shot(cols, crew, today, log=print) -> Path:
    from automations.nds_metrics import tableau_shots as TS
    return TS.capture("top_reps", OUT_DIR, log=log)


def build_team_tree(cols, crew, today, log=print) -> Path:
    """The 6am NDS team tree rides the 7:30 thread (Carlos 2026-10-28:
    post it "in the NDS metrics thread every morning instead of just on
    the Aplayers" — the A-Players 6am post stays). The team_tree agent
    renders on this same machine; only TODAY's render is ever posted, a
    stale file is an honest skip."""
    # ALWAYS render our own copy into our own file. Sharing the agent's
    # team_tree.png is what posted the VERIZON tree here on 2026-10-28
    # (the agent's second leg overwrote it) — a file nobody else writes
    # can't go stale or get swapped.
    from automations.team_tree import run as TT
    week, reps, roots, scheduled = TT.build(today)
    html = OUT_DIR / "nds_team_tree.html"
    png = OUT_DIR / f"nds_team_tree_{today.isoformat()}.png"
    html.write_text(TT.render_html(week, reps, roots, scheduled),
                    encoding="utf-8")
    TT.render_png(html, png)
    log(f"[nds] team tree rendered fresh: week {week!r}, {len(reps)} reps, "
        f"{png.stat().st_size:,}b")
    return png


def build_pct_on_board(cols, crew, today, log=print) -> Path:
    """The NDS Sales Board tab's "% on the Board" block (Carlos 2026-10-24).
    Ignores the Tableau pull — it shoots the live Sheet. On Monday before the
    ~8:20 week roll the board still shows the week that just closed, so the
    7:30 shot is that week's final read; from Tuesday it is the live week."""
    from automations.sales_boards.pct_block import render_pct_block
    return render_pct_block(
        "NDS Sales Board",
        OUT_DIR / f"nds_pct_on_board_{today.isoformat()}.png", log=log)


def build_day_board(cols, crew, today, log=print) -> Path:
    """Yesterday's board cut (Carlos 2026-10-28) — see board_shots."""
    from automations.nds_metrics import board_shots
    return board_shots.render(today, OUT_DIR, log=log)["day"]


def build_week_board(cols, crew, today, log=print) -> Path:
    """Week-to-date board cut (Carlos 2026-10-28) — see board_shots."""
    from automations.nds_metrics import board_shots
    return board_shots.render(today, OUT_DIR, log=log)["week"]


def build_customer_churn(cols, crew, today, log=print) -> Path:
    """The NDS CHURN tab (automations.nds_churn, written 07:00) as one
    picture -- the B2B thread's #6 Customer Churn remade for NDS (Carlos
    2026-11-09). Shot off the live sheet like pct_on_board; a missing tab
    is an honest skip."""
    from automations.nds_churn import sheet as NCS
    from automations.recruiting_report.fill import open_by_key, worksheet_ci
    from automations.vantura_churn import shot
    ws = worksheet_ci(open_by_key(NCS.SHEET_ID), NCS.TAB)
    out = OUT_DIR / f"nds_customer_churn_{today.isoformat()}.png"
    return shot.render_report(ws, out, log=log)


# Sections that BUILD (so --only/--dm previews work) but never post to the
# thread (Carlos 2026-10-29: "dont send the override tree on the nds thread
# yet") — move a sid out of here when he says go. customer_churn was held
# here 2026-11-09 (preview DM'd) and released 2026-11-10 (Carlos: "you didnt
# post the churn screenshot this morning") — it posts daily now.
HELD_FROM_THREAD = {"override_board"}
# Carlos 2026-11-11 ("I just don't like this order log in general that gets
# sent out. Let's go ahead and just cancel it"): the crew's Order Log
# workbook is neither built nor posted any more. Its builder stays for a
# one-off preview (`--only order_log --dm U...`); never the thread. The
# 'NDS Order Log' TAB on the Vantura board is a different thing and still
# refreshes every morning (order_log_tab.refresh).
RETIRED = {"order_log"}


def thread_sections():
    """The sections the live thread lists and posts."""
    return [sec for sec in SECTIONS if sec[0] not in HELD_FROM_THREAD | RETIRED]

SECTIONS = [
    ("day_board", "\U0001F3C6", "NDS Sales Board — Yesterday",
     build_day_board),
    ("week_board", "\U0001F4C5", "NDS Sales Board — Week to Date",
     build_week_board),
    ("knocks_final", "\U0001F6AA", "NDS Knocks Board — Day Prior",
     build_knocks_final),
    ("revenue_board", "\U0001F4B0", "NDS Revenue Board",
     build_revenue_board),
    # Carlos 2026-10-24: the Sales Board tab's "% on the Board" block, every
    # morning once the board is filled (vantura_slack_sales fills it at 5:00,
    # this thread posts 7:30). Verizon's copy rides the 5:10 sales_boards run.
    ("pct_on_board", "\U0001F4CA", "NDS % On Board",
     build_pct_on_board),
    ("team_tree", "\U0001F333", "NDS Team Tree",
     build_team_tree),
    ("override_board", "\U0001FA9C", "NDS Leader Overrides",
     build_override_board),
    # sales_metrics: REMOVED (Carlos 2026-10-21: "remove the sales metrics")
    # — the old shot was the D2D Metrics view filtered to RAF's office.
    ("order_log", "\U0001F4C4", "NDS Order Log", build_order_log),
    ("activation_overview", "\U0001F4B5", "NDS Activation Report Overview",
     build_activation_overview),
    ("activation_revenue", "\U0001F4B0", "NDS Activation Revenue Overview",
     build_activation_revenue),
    ("activation_by_rep", "\U0001F4C8", "NDS Activation Rate by Rep",
     build_activation_png),
    # Carlos 2026-11-06: activation rate per Mon-Sun WEEK ENDING, the last 5
    # weeks since NDS started, off SaraPlus per-line statuses.
    ("activation_by_week", "\U0001F4C6", "NDS Activation Rate by Week Ending",
     build_activation_by_week),
    ("activation_by_week_tableau", "\U0001F4C6", "NDS Activation Rate by Week Ending (Tableau)",
     build_activation_by_week_tableau),
    # Carlos 2026-11-09: the B2B thread's Customer Churn picture, remade --
    # the NDS CHURN tab (nds_churn, 06:00) as one shot. In the thread daily
    # since 2026-11-10.
    ("customer_churn", "\U0001F43A", "NDS Customer Churn",
     build_customer_churn),
    # Carlos 2026-11-07: the Tableau "Order Tiered Bonus - Rep Ranking" view
    # filtered to his owner (posted on B2B before, never on NDS) and the
    # workbook's "Top 100 Reps View" (top 50), every morning.
    ("rep_tiers", "\U0001F3C5", "NDS Rep Tiered Ranking (this week)",
     build_rep_tiers_shot),
    ("top_reps", "\U0001F3C6", "NDS Top 50 Reps", build_top_reps_shot),
    ("pending_orders", "⏳", "NDS Pending Orders", build_pending_png),
    # customer_churn: DISCONTINUED for Fiber (Carlos 2026-10-08 scope list);
    # build_churn_rolloff_png stays importable for reference only.
    ("churn_rates", "\U0001F4C9", "NDS Churn Rates",
     build_churn_rates_png),
    ("churn_by_rep", "\U0001F4C9", "NDS Churn by Rep",
     build_churn_by_rep_png),
]


# ---------------------------------------------------------------- post ----

def _state_path(today: dt.date) -> Path:
    return OUT_DIR / f"thread_{today.isoformat()}.json"


# Sections that ALSO go out as a text the moment they hit the thread (Carlos
# 2026-11-14, the churn rolloff shot: "texted every single morning in the B2B
# leaders text chain and the A-players text chain right after you get it for
# the NDS metrics thread"). Routing lives in b2b_dispositions.config.TEXT_ROUTES
# under (TEXT_CAMPAIGN, "nds_" + sid); empty that list to stop the text.
# + churn_rates / churn_by_rep (Carlos 2026-11-14: "Every morning after these
# two are created, let's also send these on the same text chains").
TEXT_SECTIONS = {"customer_churn", "churn_rates", "churn_by_rep"}
TEXT_CAMPAIGN = "NDS METRICS"


def _text_section(sid, title, paths, today, log=print) -> bool:
    """Hand the section's picture to the Lucy 2 poller through the
    b2b_dispositions manifest + local text outbox (the identity with the
    Messages grant) -- the same path nds_oof's boards take. Never raises:
    the thread matters more than the text."""
    try:
        from automations.b2b_dispositions import text_post as tp
        from automations.b2b_dispositions import run as bd_run
        from automations.day_orchestrator import text_outbox as tob
        kind = "nds_" + sid
        spec = {"kind": kind,
                "title": f"{title} — {today.strftime('%B')} {today.day}",
                "by_campaign": {TEXT_CAMPAIGN: [str(p) for p in paths]}}
        if not tp.spec_has_routes(spec):
            log(f"[nds] text: no route for {TEXT_CAMPAIGN}/{kind} -- not queued")
            return False
        out_dir = bd_run.OUTPUT_DIR / today.isoformat()
        mp = tp.write_manifest(spec, out_dir, f"{kind}-{dt.datetime.now().strftime('%H%M')}")
        tob.drop(mp, by="nds_metrics", day=today.isoformat())
        log(f"[nds] text: outbox {mp.name} ({sid})")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"[nds] text {sid} FAILED (thread unaffected): {type(e).__name__}: {e}")
        return False


def text_sections(artifacts, today, state, log=print, force: bool = False) -> None:
    """Queue the text for every TEXT_SECTIONS picture built today, once per
    day (state['texted']); --force re-texts."""
    titles = {s: (e, t) for s, e, t, _fn in SECTIONS}
    texted = state.setdefault("texted", [])
    for sid in sorted(TEXT_SECTIONS):
        path = artifacts.get(sid)
        if not path or (sid in texted and not force):
            continue
        paths = list(path) if isinstance(path, (list, tuple)) else [path]
        _emoji, title = titles.get(sid, ("", sid))
        if _text_section(sid, title, paths, today, log=log) and sid not in texted:
            texted.append(sid)


def post_thread(artifacts, today, log=print, force: bool = False) -> None:
    from automations.shared.slack_metrics_post import _client
    client = _client()
    sp = _state_path(today)
    state = json.loads(sp.read_text()) if sp.exists() else {}
    ts = state.get("ts")
    if not ts:
        header = f"NDS Metrics — {today.strftime('%B %d, %Y')}"
        ts = client.chat_postMessage(channel=CHANNEL[1], text=header)["ts"]
        contents = "\n".join(f"{emoji} {title}"
                             for _id, emoji, title, _fn in thread_sections())
        client.chat_postMessage(channel=CHANNEL[1], thread_ts=ts,
                                text="In this thread:\n" + contents)
        state = {"ts": ts, "posted": []}
        log(f"[nds] opened thread {ts} in {CHANNEL[0]}")
        from automations.shared.slack_metrics_post import pin_message
        pin_message(client, CHANNEL[1], ts, log=log)
    for (sid, emoji, title, _fn) in thread_sections():
        path = artifacts.get(sid)
        if not path or (sid in state["posted"] and not force):
            continue
        paths = list(path) if isinstance(path, (list, tuple)) else [path]
        client.files_upload_v2(
            channel=CHANNEL[1], thread_ts=ts,
            initial_comment=caption(sid, emoji, title),
            file_uploads=[{"file": str(pp), "filename": Path(pp).name}
                          for pp in paths])
        if sid not in state["posted"]:
            state["posted"].append(sid)
        sp.write_text(json.dumps(state))
        log(f"[nds] posted {sid}")
    # The texts ride on the same pass: right after the thread, same picture.
    text_sections(artifacts, today, state, log=log, force=force)
    sp.write_text(json.dumps(state))


def delete_today(today, log=print) -> None:
    """Delete today's NDS Metrics thread — the parent and every reply LUCY
    posted in it (Carlos 2026-10-23: 'delete the NDS metrics thread posted
    today and repost everything with the correct info'). Only Lucy's own
    messages; state cleared so the next --post opens a fresh thread."""
    from automations.shared.slack_metrics_post import _client
    client = _client()
    sp = _state_path(today)
    if not sp.exists():
        log("[nds] no thread state for today — nothing to delete")
        return
    ts = json.loads(sp.read_text()).get("ts")
    if ts:
        try:
            replies = client.conversations_replies(channel=CHANNEL[1],
                                                   ts=ts, limit=200)
            msgs = replies.get("messages", [])
        except Exception as e:  # noqa: BLE001
            log(f"[nds] couldn't list the thread ({e}) — deleting parent only")
            msgs = [{"ts": ts}]
        # children first, parent last
        for m in sorted(msgs, key=lambda m: m.get("ts", ""), reverse=True):
            try:
                client.chat_delete(channel=CHANNEL[1], ts=m["ts"])
            except Exception as e:  # noqa: BLE001
                if "message_not_found" not in str(e):
                    log(f"[nds] delete {m.get('ts')} failed: {str(e)[:100]}")
        log(f"[nds] deleted today's thread ({len(msgs)} message(s))")
    sp.unlink()


def reply_is_section(m: dict, sid: str, title: str) -> bool:
    """Does thread reply `m` carry section `sid`? Its caption names the
    title in bold (matched WITHOUT the emoji: Slack may hand the emoji back
    as a shortcode), or -- a files_upload_v2 reply often has EMPTY text, the
    caption lives on the file -- the upload's filename says it: an
    'nds_order_log...png', or the house workbook's 'Order Log 11-09-2026.xlsx'
    (case + spaces folded; that name never matched 'order_log', which is why
    the 2026-11-09 re-post left the morning copy in the thread)."""
    txt = (m.get("text") or "").strip()
    if f"*{title}*" in txt:
        return True
    for f in (m.get("files") or []):
        name = (f.get("name") or "").lower().replace(" ", "_")
        if sid in name:
            return True
    return False


def prune_sections(sids, today, log=print) -> None:
    """Delete ONE section's reply(ies) from today's thread and clear it
    from state, so --post can replace just that board (Carlos 2026-10-28:
    the Verizon tree landed in the NDS thread and only that message
    should go)."""
    from automations.shared.slack_metrics_post import _client
    client = _client()
    sp = _state_path(today)
    if not sp.exists():
        log("[nds] no thread state — nothing to prune")
        return
    state = json.loads(sp.read_text())
    ts = state.get("ts")
    titles = {sid: title for sid, _emoji, title, _fn in SECTIONS if sid in sids}
    if not ts or not titles:
        return
    replies = client.conversations_replies(channel=CHANNEL[1], ts=ts,
                                           limit=200).get("messages", [])
    pruned = 0
    for m in replies:
        if m.get("ts") == ts:
            continue                      # never the thread parent
        for sid, title in titles.items():
            if reply_is_section(m, sid, title):
                try:
                    client.chat_delete(channel=CHANNEL[1], ts=m["ts"])
                    pruned += 1
                    log(f"[nds] pruned {sid} reply {m['ts']}")
                except Exception as e:  # noqa: BLE001
                    log(f"[nds] prune {m['ts']} failed: {str(e)[:120]}")
                break
    if not pruned:
        log(f"[nds] prune: no reply in the thread matched {sorted(titles)}")
    state["posted"] = [x for x in state.get("posted", []) if x not in sids]
    sp.write_text(json.dumps(state))


def dm_previews(artifacts, user, log=print) -> None:
    """`user` = one Slack id (a PREVIEW DM, the original use) or a comma-
    separated list (Carlos 2026-11-06: "send to sebastian and i on slack" --
    one group DM from Lucy with the board, no PREVIEW wording)."""
    from automations.shared import slack_metrics_post as smp
    users = [u.strip() for u in str(user).split(",") if u.strip()]
    stamp = dt.date.today().strftime("%B %d, %Y")
    for sid, emoji, title, _fn in SECTIONS:
        path = artifacts.get(sid)
        if not path:
            continue
        for pp in (path if isinstance(path, (list, tuple)) else [path]):
            if len(users) > 1:
                res = smp.dm_users_with_file(
                    Path(pp), users=users, file_name=Path(pp).name,
                    comment=caption(sid, emoji, title, f" — {stamp}"))
                log(f"[nds] sent {sid} to {len(users)} people ({res.get('mode')})")
            else:
                smp.dm_user_with_file(
                    Path(pp), user=users[0], file_name=Path(pp).name,
                    comment=caption(sid, emoji, title,
                                    " — NDS Metrics PREVIEW (crew only, "
                                    "not posted)."))
                log(f"[nds] DM'd {sid}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_metrics")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--only", default=None,
                    help="comma-separated section ids")
    ap.add_argument("--dm", default=None, metavar="U...",
                    help="DM previews to this user; never touches the channel")
    ap.add_argument("--post", action="store_true",
                    help="post the live NDS Metrics thread")
    ap.add_argument("--delete-today", action="store_true",
                    help="delete today's NDS Metrics thread (Lucy's own "
                         "posts) and clear its state; pair with --repull "
                         "--post to repost fresh")
    ap.add_argument("--prune", default=None,
                    help="comma-separated section ids: delete just their "
                         "replies from today's thread (then usually --only "
                         "<same> --post to replace them)")
    ap.add_argument("--repull", action="store_true",
                    help="delete today's SOH + order-log caches first (test "
                         "a fresh pull, e.g. a new dealer login)")
    ap.add_argument("--force", action="store_true",
                    help="re-post sections already in today's thread state "
                         "(replace a bad one); pair with --only")
    ap.add_argument("--tab", action="store_true",
                    help="refresh the 'NDS Order Log' tab on the Vantura board from "
                         "today's wireless feed; alone = ONLY that, no pull, no post")
    a = ap.parse_args(argv)
    today = (dt.date.fromisoformat(a.today) if a.today else dt.date.today())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if a.tab and not (a.post or a.dm or a.only):
        # The tab by itself (Carlos 2026-10-29): today's cached feed -> tab.
        from automations.nds_metrics import order_log_tab
        order_log_tab.refresh(today)
        print("=== done ===", flush=True)
        return 0

    if a.delete_today:
        delete_today(today)
    if a.prune:
        prune_sections(set(a.prune.split(",")), today)
    if a.repull:
        for f in OUT_DIR.glob(f"*_{today.isoformat()}.csv"):
            f.unlink()
            print(f"[nds] --repull: dropped {f.name}")
    path = pull(today)
    cols, crew = load_crew(path)
    only = set(a.only.split(",")) if a.only else None
    artifacts = {}
    for sid, _e, _t, fn in SECTIONS:
        if only and sid not in only:
            continue
        if sid in RETIRED and not only:
            continue                      # cancelled; built only when named by --only
        try:
            artifacts[sid] = fn(cols, crew, today)
        except Exception as e:  # noqa: BLE001 — one board never sinks the rest
            print(f"[nds] {sid} FAILED: {type(e).__name__}: {e}")
    print(f"[nds] built: {sorted(artifacts)}")
    for sid in sorted(artifacts):
        if source_for(sid):
            print(f"[nds] source {sid}: {source_for(sid)}")
    if a.dm and a.post:
        print("[nds] --dm overrides --post — previews only, nothing posted")
        a.post = False
    if a.dm:
        dm_previews(artifacts, a.dm)
    if a.post:
        post_thread(artifacts, today, force=a.force)
    if a.post or a.tab:
        # Every morning after the thread (Carlos 2026-10-29): the same lines the
        # order-log workbook carries, merged into the "NDS Order Log" tab on the
        # Vantura Master Sales Board. Its own try: a tab problem never sinks
        # the thread.
        try:
            from automations.nds_metrics import order_log_tab
            order_log_tab.refresh(today)
        except Exception as e:  # noqa: BLE001
            print(f"[nds] NDS Order Log tab FAILED (thread unaffected): "
                  f"{type(e).__name__}: {e}")
    if not a.dm and not a.post:
        print("[nds] dry-run — --dm for previews, --post for the thread")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
