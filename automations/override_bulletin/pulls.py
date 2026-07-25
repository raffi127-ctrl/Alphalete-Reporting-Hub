"""Number pulls for the override-bulletin fill (phases 2-4).

Each function fetches ONE piece of the weekly override for a given week and
returns a plain {normalized_owner_name: amount} dict (or a scalar for the
Raf-only pieces), so fill.py can assemble section-1/section-2 and report anyone
it can't match. See FILL_SOURCES.md for the full spec.

WEEK KEYS. The override sheet labels weeks m.d.yy ("7.12.26"). Sources use their
own conventions (Raf PNL "WE 7/12"; DD Detail runs a day behind). Each pull maps
the sheet's week to its source internally; callers pass the sheet label.

The Tableau pulls MUST run on Lucy 1 (Raf's login — only Raf's org views see the
whole downline) and are built on download_crosstab_patchright. The Raf-PNL pull
below is a plain Google-Sheets read and runs anywhere.
"""
from __future__ import annotations

import datetime as dt
import re


def _norm_name(s: str) -> str:
    """Fold a person name for matching across sources: drop any '[office]' /
    '(office)' suffix, lowercase, collapse whitespace. 'CARLOS HIDALGO [alphalete
    specialized marketing, inc.]' and ' Carlos Hidalgo ' both -> 'carlos hidalgo'."""
    s = (s or "").split("[")[0].split("(")[0]
    return " ".join(s.lower().split())


def _we_key(week_mdy: str) -> str:
    """'7.12.26' -> 'WE 7/12' (the Raf PNL header form)."""
    m, d, _y = week_mdy.split(".")
    return f"WE {int(m)}/{int(d)}"


# --------------------------------------------------------------------------
# Raf Captain Override — Google Sheet (Raf PNL 2026, row 335)
# --------------------------------------------------------------------------
RAF_PNL_WORKBOOK = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
RAF_PNL_TAB = "Raf PNL 2026"
RAF_CAPTAIN_ROW = 335        # "Captain Override" row


def _money(raw):
    if raw is None:
        return None
    s = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def raf_captain_override(week_mdy: str, ws=None):
    """Raf's Captain Override for the given sheet week (e.g. '7.12.26').

    Reads Raf PNL 2026 row 335 at the target week's WE block — the value sits in
    the block's Profit/Loss column, i.e. the WE-header column + 2 (the label
    'Captain Override' is one cell left, under 'Got Paid'). Returns the amount or
    None if the week/value isn't present."""
    if ws is None:
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(RAF_PNL_WORKBOOK).worksheet(RAF_PNL_TAB)
    vals = ws.get_all_values()
    header = vals[0]
    want = _we_key(week_mdy)
    base = next((i for i, h in enumerate(header) if (h or "").strip() == want), None)
    if base is None:
        return None
    row = vals[RAF_CAPTAIN_ROW - 1] if RAF_CAPTAIN_ROW - 1 < len(vals) else []
    vcol = base + 2                                  # Profit/Loss col of the block
    return _money(row[vcol]) if vcol < len(row) else None


# --------------------------------------------------------------------------
# Regular override — Tableau ORG OVERRIDE SUMMARY crosstab
# --------------------------------------------------------------------------
OVERRIDE_SUMMARY_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "OverridesICDView/ORGOVERRIDESUMMARY")


def _num_locale(s: str):
    """Parse a money string in either US ('72,253.17') or EU ('72.253,17')
    format, tolerating '$', parens-negatives and spaces. None if not a number."""
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if "," in t and "." in t:
        # last separator is the decimal
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") \
            else t.replace(",", "")
    elif "," in t:
        # comma-only: decimal if it looks like ",dd" at the end, else thousands
        t = t.replace(",", ".") if re.search(r",\d{1,2}$", t) else t.replace(",", "")
    try:
        v = float(t)
        return -v if neg else v
    except ValueError:
        return None


def parse_override_summary(rows, week_header, *, name_col=0):
    """Sum each ICD owner's campaign rows for one week column.

    `rows` is the downloaded crosstab as a list of row-lists. The owner name sits
    in `name_col`; continuation rows for the owner's other campaigns have a blank
    name (Megan 2026-07-22: "add up the sum of everything listed with that ICD").
    `week_header` is the target week's column header (e.g. '07/12/2026'); we find
    that column in the header rows. Returns {normalized_owner: total}. Skips the
    grand-total row ('Total general' / 'Grand Total')."""
    # locate the week column (and the header row) by matching its header. The ORG
    # summary zero-pads ('07/12/2026') and puts the real header under two banner
    # rows, so match dates normalized rather than as literal strings.
    want = _wk_norm(week_header)
    wk_col = hdr_row = None
    for ri, r in enumerate(rows[:6]):
        for ci, cell in enumerate(r):
            if _wk_norm(cell) == want:
                wk_col, hdr_row = ci, ri
                break
        if wk_col is not None:
            break
    if wk_col is None:
        seen = [c for r in rows[:6] for c in r if _WK_HDR.match(str(c).strip())]
        raise ValueError(f"week column {week_header!r} not found; weeks present: {seen}")

    out, cur = {}, None
    for r in rows[hdr_row + 1:]:               # skip the header rows
        name = (r[name_col] if name_col < len(r) else "").strip()
        low = name.lower()
        if low in ("total general", "grand total", "total"):
            cur = None
            continue
        if name:
            cur = _norm_name(name)
            out.setdefault(cur, 0.0)
        if cur is None:
            continue
        val = _num_locale(r[wk_col]) if wk_col < len(r) else None
        if val is not None:
            out[cur] += val
    return {k: round(v, 2) for k, v in out.items()}


# --------------------------------------------------------------------------
# Shared crosstab helpers + the other-source parsers (column names set once
# discovery confirms the real headers; the parse LOGIC below is unit-tested).
# --------------------------------------------------------------------------
_WK_HDR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")


def _wk_norm(s):
    """Normalize a week header so '07/12/2026' == '7/12/2026'. Non-dates fall
    back to lowercased text (so the compare is still safe)."""
    m = _WK_HDR.match(str(s).strip())
    if not m:
        return " ".join(str(s).lower().split())
    return f"{int(m.group(1))}/{int(m.group(2))}/{m.group(3)[-2:]}"


def read_crosstab(path):
    """Read a Tableau crosstab file to a list of row-lists. Tableau exports
    UTF-16 tab-separated; some are UTF-8/comma. Tries encodings in order and
    auto-detects the delimiter (mirrors int_wow_penetration.pull)."""
    import csv
    import io
    raw = open(path, "rb").read()
    txt = None
    for enc in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if txt is None:
        txt = raw.decode("latin-1", "replace")
    first = txt.splitlines()[0] if txt else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    return list(csv.reader(io.StringIO(txt), delimiter=delim))


def _hdr_col(header, name):
    """Index of the header cell matching `name` (case/space-insensitive), or None."""
    want = " ".join(str(name).lower().split())
    for i, h in enumerate(header):
        if " ".join(str(h).lower().split()) == want:
            return i
    return None


_CAP_RE = re.compile(r"captain'?s?\s+bonus", re.I)
_WK_IN_DESC = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def parse_dd_captain(rows, owners):
    """{owner_norm: {week_key: amount}} of Captain's-Bonus overrides from the
    ORG DD Detail crosstab.

    The crosstab is HIERARCHICAL — empty dimensions collapse per row, so columns
    do NOT align to the header (the amount lands wherever the row happens to end).
    So we match by CONTENT, not column index:
      * the row has a 'Captain('s) Bonus M.D.YY' cell (the description),
      * its owner (any cell) is in `owners` (normalized captain names),
      * the amount is the max money cell (Total $ to ICD == the non-zero one).
    week_key is 'M.D.YY' parsed from the description (rows with no date — e.g. the
    $0 NDS wireless 'Captain Bonus' — are skipped). The fill maps week_key to the
    sheet column positionally, so the DD-vs-sheet day offset doesn't matter."""
    out = {}
    for r in rows:
        cap = next((str(c) for c in r if _CAP_RE.search(str(c))), None)
        if not cap:
            continue
        m = _WK_IN_DESC.search(cap)
        if not m:
            continue
        wk = f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)[-2:]}"
        owner = next((_norm_name(c) for c in r if _norm_name(c) in owners), None)
        if not owner:
            continue
        amt = max((_num_locale(c) or 0) for c in r)
        if amt:
            d = out.setdefault(owner, {})
            d[wk] = round(d.get(wk, 0) + amt, 2)
    return out


def parse_ledger(rows, *, owner_col, expl_col, amt_col, needle):
    """{owner: Transaction Amount} for ledger rows whose NS_Explanation contains
    `needle` (e.g. 'P6-2026 Special Override' or 'January 2026 ... Credico')."""
    hdr = rows[0]
    oc, ec, ac = (_hdr_col(hdr, c) for c in (owner_col, expl_col, amt_col))
    out, cur = {}, None
    for r in rows[1:]:
        nm = (r[oc] or "").strip() if oc is not None and oc < len(r) else ""
        if nm:
            cur = _norm_name(nm)
        expl = (r[ec] or "") if ec is not None and ec < len(r) else ""
        if needle.lower() in expl.lower() and cur is not None:
            v = _num_locale(r[ac]) if ac is not None and ac < len(r) else None
            if v is not None:
                out[cur] = out.get(cur, 0) + v
    return {k: round(v, 2) for k, v in out.items()}


def parse_raf_payout(rows, *, label, week_header):
    """Scalar 'Raf Payout Total' for a Processed-Week column."""
    wk = None
    for r in rows[:8]:
        for i, c in enumerate(r):
            if str(c).strip() == str(week_header).strip():
                wk = i
                break
        if wk is not None:
            break
    if wk is None:
        return None
    for r in rows:
        if any(label.lower() in str(c).lower() for c in r[:2]):
            return _num_locale(r[wk]) if wk < len(r) else None
    return None


# --------------------------------------------------------------------------
# Fetch wrappers — download the confirmed crosstab sheets (Lucy 1) and parse.
# DD + NETSUITE carry ALL weeks/transactions, so no period-select is needed —
# we download the whole sheet once and filter in the parse.
# --------------------------------------------------------------------------
DD_DETAIL_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "DirectDepositICDVIEWVersion2_0/DDDETAILORG")
DD_DETAIL_SHEET = "ORG DD Detail"

LEDGER_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "OverridesICDView/NETSUITESECURITYLEDGERSFDC")
LEDGER_SHEET = "Transaction Details"


def dd_week_combobox_label(sheet_week):
    """The `cl.DD Week` filter's dropdown label for a sheet week.

    The DD Detail view's ONLY dated filter is `cl.DD Week`, and it labels a week
    by its MONDAY: sheet Sunday 7.19 shows as '07/20/2026' (confirmed on Lucy 1
    2026-07-24 — the pinned default was 07/20 while the sheet's newest week was
    7.19). So the label is the sheet Sunday + 1 day, zero-padded M/D/YYYY. Note
    this is a DIFFERENT convention from the Captain's-Bonus DESCRIPTION text,
    which runs a day BEHIND the sheet (7.18) — the two are unrelated date fields."""
    m, d, y = (int(x) for x in sheet_week.split("."))
    nxt = dt.date(2000 + y if y < 100 else y, m, d) + dt.timedelta(days=1)
    return "{:02d}/{:02d}/{}".format(nxt.month, nxt.day, nxt.year)


def _drive_dd_week(label, verbose=False):
    """pre_export hook that drives the `cl.DD Week` filter to exactly `label`.

    The default download only carries the CURRENT DD week — that is why an
    already-closed week (e.g. 7.12, which the VA has fully filled) returns
    nothing: its rows aren't in the file. The VA reaches an old week by changing
    this same filter. Adapted from org_sales_board.je_pull's proven
    'Sales Week Ending' driver: the filter is a Tableau categorical quick filter,
    each option a `div.FIItem[role=checkbox]` toggled via its `.FICheckRadio`
    glyph; filters apply immediately (no Apply button). We check the target week,
    uncheck every other still-checked week, then collapse the dropdown so it
    can't overlay the Download button."""
    import re as _re

    def _close_dropdown(page, viz):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
        except Exception:  # noqa: BLE001
            pass
        try:
            glass = viz.locator("div.tab-glass").first
            if glass.count():
                glass.click(timeout=3000)
                page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            pass

    def pre_export(page, viz):
        boxes = viz.locator('span.tabComboBox[role="combobox"]')
        # cl.DD Week is the ONLY combobox showing a single date (the rest are
        # '(All)'); find it by its M/D/YYYY text rather than a fixed index.
        tbox = cur = None
        for _ in range(20):
            for i in range(boxes.count()):
                t = (boxes.nth(i).inner_text() or "").strip()
                if _re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", t):
                    tbox, cur = boxes.nth(i), t
                    break
            if tbox is not None:
                break
            page.wait_for_timeout(1000)
        if tbox is None:
            if verbose:
                print("  [dd] ⚠ cl.DD Week dropdown not found — leaving default week")
            return
        if cur == label:
            return

        def _find_visible(loc):
            """First VISIBLE match — the open dropdown's item, not a cached one
            from another of the 10 filter panels (all have their own FIItems)."""
            for i in range(loc.count()):
                try:
                    if loc.nth(i).is_visible():
                        return loc.nth(i)
                except Exception:  # noqa: BLE001
                    continue
            return None

        tbox.click()                              # open the dropdown
        page.wait_for_timeout(1500)
        # '(All)' has its own class; a date is matched by exact text. Scope to the
        # VISIBLE item so we don't grab an identically-named item from a closed
        # panel (which is why earlier clicks silently did nothing).
        if label == "(All)":
            target = _find_visible(viz.locator('div.FIItem.all-item'))
        else:
            target = _find_visible(viz.locator('div.FIItem[role="checkbox"]').filter(
                has_text=_re.compile(r"^{}$".format(_re.escape(label)))))
        if target is None:
            if verbose:
                print("  [dd] option {} not visible in the cl.DD Week list — "
                      "leaving default".format(label))
            _close_dropdown(page, viz)
            return
        def _aria(el):
            try:
                return el.get_attribute("aria-checked")
            except Exception:  # noqa: BLE001
                return "?"
        before = _aria(target)
        # Tableau's item handler fires on the real MOUSE SEQUENCE, which the
        # tab-glass overlay intercepts (so a plain Locator.click no-op'd) — and a
        # bare JS el.click() dispatches no mousedown, so the handler never runs
        # either. So: drop the glass, then fire a full pointer sequence on the
        # item (glyph first, then the row) with real Playwright clicks.
        try:
            viz.locator("div.tab-glass").evaluate_all(
                "els => els.forEach(e => e.remove())")
        except Exception:  # noqa: BLE001
            pass
        glyph = target.locator(".FICheckRadio").first
        for node in (glyph if glyph.count() else target, target):
            try:
                node.scroll_into_view_if_needed(timeout=4000)
                node.click(timeout=6000, force=True)
            except Exception:  # noqa: BLE001
                # last resort: synthesize the full sequence in the DOM
                try:
                    (node if node.count() else target).evaluate(
                        "el => ['pointerdown','mousedown','pointerup','mouseup',"
                        "'click'].forEach(t => el.dispatchEvent("
                        "new MouseEvent(t,{bubbles:true,cancelable:true})))")
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_timeout(1500)
            if _aria(target) == "true" or (tbox.inner_text() or "").strip() == label:
                break
        checked = _aria(target) == "true"
        # The click REGISTERS (aria false->true) but the combobox text lags — it
        # is not the source of truth, the downloaded rows are. Commit the change:
        # an Apply-button filter needs Apply; ESCAPE would CANCEL it. Then collapse
        # by toggling the combobox (not Escape) and proceed to export regardless
        # of the stale box text — the parse confirms whether all weeks came.
        for sel in ('button:has-text("Apply")', 'a:has-text("Apply")',
                    '[data-tb-test-id*="pply"]'):
            try:
                b = viz.locator(sel).first
                if b.count() and b.is_visible():
                    b.click(timeout=4000, force=True)
                    page.wait_for_timeout(1000)
                    break
            except Exception:  # noqa: BLE001
                continue
        try:
            tbox.click(timeout=4000)          # toggle closed — NOT Escape
            page.wait_for_timeout(1500)
        except Exception:  # noqa: BLE001
            pass
        final = (tbox.inner_text() or "").strip()
        if verbose:
            print("  [dd] cl.DD Week: box={!r} all-item {}->{} (checked={})".format(
                final, before, _aria(target), checked))
        # Only a genuine failure — the checkbox never flipped — aborts (so the
        # download_crosstab retry re-navigates and tries again).
        if not checked and final != label:
            raise RuntimeError(
                "DD week select failed: aria never checked; box={!r}".format(final))

    return pre_export


def _drive_dd_week_all(verbose=False):
    """pre_export hook that sets the cl.DD Week filter to '(All)'.

    Reaching a far-down weekly option by click proved flaky (the list is
    virtualized — 07/13 wouldn't register), but '(All)' is the FIRST option and
    always rendered. Selecting it downloads EVERY week in one file; the caller
    then picks the target week from the parsed result. This is the robust way to
    reach any past week (verification) or catch captain bonuses that post after
    the current week's default download (backfill)."""
    return _drive_dd_week("(All)", verbose=verbose)

    return pre_export


def dd_captain_overrides(owners, out_path, *, page=None, verbose=True,
                         period=None, sheet_week=None):
    """{owner_norm: {week_key: amount}} — every Captain's-Bonus override for the
    captains in `owners`, keyed by the description's week (M.D.YY).

    When `sheet_week` is given, the `cl.DD Week` filter is driven to that week so
    the download carries exactly that week's rows — the ONLY way to reach a week
    other than the current default (the VA does the same by hand). Without it,
    the default download (current week) is used, with a period filter as a
    fallback for the empty-viz case."""
    want = {_norm_name(o) for o in owners}

    def _accept(rows):
        return parse_dd_captain(rows, want) or None

    if sheet_week:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        # Drive cl.DD Week to '(All)' so the download carries EVERY week — the
        # only reliable way to reach a week other than the current default. The
        # caller keys per week (_dd_week_for), so getting all weeks is harmless
        # and also picks up captain bonuses that posted after the current week.
        if verbose:
            print("  [dd] driving cl.DD Week to (All) to reach sheet {}".format(sheet_week))
        download_crosstab_patchright(
            DD_DETAIL_VIEW, DD_DETAIL_SHEET, out_path, page=page, verbose=verbose,
            pre_export=_drive_dd_week_all(verbose=verbose))
        return parse_dd_captain(read_crosstab(out_path), want)

    periods = [None] + (period_candidates(period) if period else [])
    val, _used = _download_first_nonempty(
        DD_DETAIL_VIEW, DD_DETAIL_SHEET, out_path, periods,
        page=page, verbose=verbose, accept=_accept)
    return val or {}


def ledger_amounts(needle, out_path, *, page=None, verbose=True):
    """{owner: Transaction Amount} for ledger rows whose NS_Explanation contains
    `needle` (e.g. 'P6-2026 Special Override' or 'January 2026 ... Credico').
    Downloads the Transaction Details sheet once (all owners, all transactions)."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    download_crosstab_patchright(LEDGER_VIEW, LEDGER_SHEET, out_path,
                                 page=page, verbose=verbose)
    rows = read_crosstab(out_path)
    return parse_ledger(rows, owner_col="ICD Owner Name and OFFICE NAME",
                        expl_col="NS_Explanation__c", amt_col="Transaction Amount",
                        needle=needle)


# --------------------------------------------------------------------------
# Period-scoped pulls (RAF special, regular override). The crosstab shows only
# the selected Period's weeks, so we set the Period via a URL filter param
# (avoids driving the dropdown). Field name/value format confirmed on Lucy 1.
# --------------------------------------------------------------------------
RAF_BONUS_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "ResATTSpecialDealOverride-Raf/RafOverrideBonus")
RAF_BONUS_SHEET = "Payout- Raf wow"

ORG_SUMMARY_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                    "OverridesICDView/ORGOVERRIDESUMMARY")
# Crosstab sheet name — confirmed on Lucy 1; only renders under a 'Period 2026-M'
# filter (the bare 'Period M' form returns no sheets).
ORG_SUMMARY_SHEET = "ORG Override Summary"


def _with_filter(base_url, field, value):
    """Append a Tableau URL filter param: ?<field>=<value> (or &…)."""
    from urllib.parse import quote
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{quote(field)}={quote(value)}"


def period_candidates(period):
    """Period-filter values to try, best guess first.

    Tableau's Crosstab dialog reports 'No sheets to select' when the VIZ IS
    EMPTY — a filter value that matches nothing looks EXACTLY like a broken or
    permission-denied view (Megan spotted this 2026-07-24: the working ORG
    summary shows the same empty dialog when opened on its default
    'Period 2024-13' with no week chosen). So never trust a single filter
    string: the period naming differs per view and has changed before
    ('Period 7' vs 'Period 2026-7'), and a stale value silently yields nothing.
    """
    out, seen = [], set()
    cands = [period]
    m = re.match(r"^Period\s+(\d{4})-(\d{1,2})$", str(period or "").strip())
    if m:                                    # year-prefixed -> also try bare
        cands.append("Period {}".format(int(m.group(2))))
    m2 = re.match(r"^Period\s+(\d{1,2})$", str(period or "").strip())
    if m2:                                   # bare -> also try year-prefixed
        n = int(m2.group(1))
        cands += ["Period {}-{}".format(dt.date.today().year, n),
                  "Period {}-{}".format(dt.date.today().year - 1, n)]
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _download_first_nonempty(view, sheet, out_path, periods, *, page=None,
                             verbose=True, accept=None):
    """Try each period filter until one yields a crosstab that actually PARSES.

    Returns (parsed, period_used). `accept` turns the raw rows into the parsed
    result and should return something falsey when the download came back empty
    or without the week we need — that is the signal to try the next candidate
    rather than to report the view as broken."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    last_err = None
    for period in periods:
        url = _with_filter(view, "Period", period) if period else view
        try:
            download_crosstab_patchright(url, sheet, out_path, page=page,
                                         verbose=verbose)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if verbose:
                print("  {} → no crosstab ({}); trying the next period".format(
                    period or "(no filter)", type(e).__name__))
            continue
        rows = read_crosstab(out_path)
        got = accept(rows) if accept else rows
        if got:
            if verbose:
                print("  {} → OK".format(period or "(no filter)"))
            return got, period
        if verbose:
            print("  {} → empty; trying the next period".format(period or "(no filter)"))
    if last_err is not None:
        raise last_err
    return None, None


def raf_special_override(week_header, out_path, *, period, page=None, verbose=True):
    """Raf's special override ('Raf Payout Total' row) for a week.

    `period` is the preferred Period-filter value; sibling formats are tried too
    (see period_candidates) because an unmatched value renders an EMPTY viz,
    which Tableau reports as 'no sheets' — indistinguishable from a dead view."""
    def _accept(rows):
        return parse_raf_payout(rows, label="Raf Payout Total",
                                week_header=week_header)
    val, _used = _download_first_nonempty(
        RAF_BONUS_VIEW, RAF_BONUS_SHEET, out_path, period_candidates(period),
        page=page, verbose=verbose, accept=_accept)
    return val


def regular_overrides(week_header, out_path, *, period, page=None, verbose=True):
    """{owner: regular override} — sum each owner's campaign rows for the week
    column. `period` is the Period-filter value (e.g. 'Period 2026-7')."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    url = _with_filter(ORG_SUMMARY_VIEW, "Period", period)
    download_crosstab_patchright(url, ORG_SUMMARY_SHEET, out_path, page=page, verbose=verbose)
    rows = read_crosstab(out_path)
    return parse_override_summary(rows, week_header)


def period_for(week_mdy, *, style="num"):
    """Period-filter value for a sheet week. 'Period 2026-7' (style='year') or
    'Period 7' (style='num') — the month drives the period number."""
    m = int(week_mdy.split(".")[0])
    return f"Period 2026-{m}" if style == "year" else f"Period {m}"


def summary_weeks(rows):
    """Week labels present in an ORG Override Summary crosstab, NEWEST FIRST, as
    sheet-style 'M.D.YY'. This source lags the others (on Thu 2026-07-23 its
    newest was 07/12 while DD was already at 7.18), so it decides which week can
    actually be filled."""
    out = []
    for r in rows[:6]:
        for c in r:
            m = _WK_HDR.match(str(c).strip())
            if m:
                lbl = f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)[-2:]}"
                if lbl not in out:
                    out.append(lbl)
    return out


# Ledger column names (confirmed on Lucy 1) — used by the marker reconcile pass.
LEDGER_OWNER_COL = "ICD Owner Name and OFFICE NAME"
LEDGER_EXPL_COL = "NS_Explanation__c"
LEDGER_AMT_COL = "Transaction Amount"


def ledger_rows(out_path, *, page=None, verbose=True):
    """Download the NetSuite Transaction Details sheet once and return its rows.
    The marker pass needs the raw rows (it looks up several periods), not one
    pre-parsed needle."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    download_crosstab_patchright(LEDGER_VIEW, LEDGER_SHEET, out_path,
                                 page=page, verbose=verbose)
    return read_crosstab(out_path)
