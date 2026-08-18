"""Capture functions for the B2B Metrics runner — one per item KIND.

Each returns a Path to the artifact (PNG, or the .xlsx for the order log), or
raises (the runner's continue-on-failure logs + skips). These are thin adapters
over modules that already exist, so the runner is orchestration only:

  tableau_image     -> owner-sliced Download->Image of a shared TEAM view (Lucy 2)
  order_log_workbook-> att_order_log.run pull + xlsx.build  (Tableau; Lucy 2)
  payout_image      -> att_order_log.payout + box_order_log.png  (Lucy 2 for data)

Sheet-order-log data (order_log + payout) is pulled ONCE and cached on the
office for the run, so the 120MB ORDERLOG export isn't fetched twice.

ALL Tableau items (#1/#2/#3-5/#8) go through the SAME path: load the shared team
view with ?Owner Name=<owner> appended, then apply the per-view sort/crop from
offices.VIEW_META. The sort click + crop-to-last-data-row are reused from
b2b_quality (the module that proved them); this runner no longer routes through
b2b_quality's Carlos-hardcoded SPECS, so the owner slice actually takes effect.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from automations.b2b_metrics.offices import B2BOffice, OWNER_FIELD, VIEW_META

REPO_ROOT = Path(__file__).resolve().parents[2]


class BlankRender(Exception):
    """A section rendered with no content — refuse it and let it alert.

    WHY (Megan 2026-08-17, on the blank Out of Bounds): "I also should have been
    alerted." A section that comes back empty used to be indistinguishable from
    one that came back fine — the image posted, the run exited 0, the Hub card
    went green. For a CONFIDENTIAL report an empty post is worse than a gap: it
    reads as "nothing to report this week" when the truth was "we asked the wrong
    question". Raising puts the section in the run's `missed` list, which
    write_manifest already turns into a loud 🚨 in
    #claudecorrections-and-requests via shared.section_drop_alert.

    This OVERRIDES the old post_when_blank behaviour (Carlos's Loom: "if it shows
    nothing, we still want the screenshot"). His ask was for a week we had
    verified as genuinely empty; it was never for a blank nobody had checked.
    A verified-empty week still posts — see tableau_image."""


class WeekFilterNotApplied(Exception):
    """A week-pinned view rendered a week OTHER than the one we asked for.

    Tableau drops an unmatched URL filter in SILENCE and serves its own default
    window, so a wrong-week image looks exactly like a right-week one — except
    on the day the default week has no sales yet, when it looks like a clean
    'nothing to report'. That is precisely how Out of Bounds posted an empty
    confidential report on 2026-08-17. Raising here makes the runner SKIP the
    section and record it as missed (which alerts), instead of posting a blank
    whose week nobody can vouch for."""


# --- week pinning -----------------------------------------------------------
# The week rule lives in automations/shared/report_week.py so every week-scoped
# report answers "which week?" the same way — the Monday rollover is what put a
# blank confidential Out of Bounds in Carlos's thread on 2026-08-17. Re-exported
# here because this module's callers already import them from it.
from automations.shared.report_week import (          # noqa: E402
    completed_week_ending as report_week_ending,
    week_ending, week_value, week_value_variants,
)

# Order-date column in the raw ORDERLOG crosstab — the same one the freshness
# probe (att_order_log.freshness.DATE_COL) and sheet.py key on. Used by the
# --require-fresh gate below to read how far the extract reaches.
_ORDER_DATE_COL = "sp.Order Date (copy)"


class OrderLogNotFresh(Exception):
    """The ORDERLOG extract hasn't reached the prior completed day, so the two
    order-log sections (#8 Order Log, #9 Activation Report Overview) DEFER —
    posted later once it lands — instead of shipping a stale log. Mirrors
    box_order_log's 7:00 --require-fresh gate. Raised ONLY when B2B_REQUIRE_FRESH
    is set (the early/scheduled passes); the floor pass leaves it unset and posts
    whatever the extract has, so the sections are never permanently absent."""

    def __init__(self, maxd, need):
        self.maxd, self.need = maxd, need
        super().__init__(
            "ORDERLOG only through {} (need >= {})".format(maxd, need))


def _require_fresh_gate(lines, log=print) -> None:
    """DEFER the order-log sections unless the ORDERLOG data reaches yesterday.

    Reuses the lines the batch already pulled — NO extra Tableau call. A no-op
    unless B2B_REQUIRE_FRESH is set, so the default path (and the fail-open floor
    pass) is unchanged. 'need' is the prior completed day: same-day B2B orders
    don't finalize until business hours, so gating on today would defer all
    morning; the floor pass is the backstop for a genuine no-prior-day-data day."""
    if not os.environ.get("B2B_REQUIRE_FRESH"):
        return
    from automations.att_order_log.sheet import _parse_date
    dates = [d for d in (_parse_date(l.get(_ORDER_DATE_COL)) for l in lines) if d]
    maxd = max(dates) if dates else None
    need = dt.date.today() - dt.timedelta(days=1)
    if maxd is None or maxd < need:
        log("  [order-log] DEFER — ORDERLOG only through {} (need >= {}); "
            "waiting for a fresher extract".format(maxd, need))
        raise OrderLogNotFresh(maxd, need)
    log("  [order-log] fresh — ORDERLOG through {}".format(maxd))


# --- #6 / #7 : screenshots of the LUCY CHURN tab ---------------------------
def _assert_rolloff_has_data(ws, o: B2BOffice) -> None:
    """#6's blank-guard — the twin of #7's 'no rep rows' check.

    A board whose churn tab has never been written renders the FULL template —
    title, tier legend, column headers — with an empty rolloff list and a lone
    '#N/A' under 'Days Left'. That posts as a confident-looking screenshot of
    nothing (Jamis's board, 2026-08-01), which is worse than a gap: it reads as
    'no churn this week'. #7 already refuses to post blank; #6 didn't.

    Row positions are read from the tab's OWN 'Days Left' header rather than
    hardcoded — these boards are hand-duplicated and drift.
    """
    col_a = ws.get("A1:A200")
    # EXACT match on the header cell, not 'contains': row 2's help text reads
    # "Days left = (Posted+30) - Today...", so a substring match anchors on the
    # caption and waves every blank board through.
    hdr = next((i for i, r in enumerate(col_a, 1)
                if r and str(r[0]).strip().lower() == "days left"), None)
    if hdr is None:
        return          # unknown layout — don't invent a reason to skip
    for r in col_a[hdr:]:
        v = str(r[0]).strip() if r else ""
        # '#N/A' / '#REF!' are the unwritten-board signature, not data.
        if v and not v.startswith("#"):
            return
    raise ValueError(
        "customer_churn: no rolloff rows on {!r} (churn board not written yet "
        "— vantura_churn hasn't run for this office) — skip rather than post "
        "an empty template".format(ws.title))


def churn_tab_image(o: B2BOffice, which: str, out_dir: Path, log=print) -> Path:
    """#6 customer_churn = the tab's main block (0-30 Day Rolloff List); #7
    activation_by_rep = the rep chart at AE:AF. Both via the Sheets export
    endpoint (vantura_churn.shot)."""
    from automations.recruiting_report.fill import open_by_key, worksheet_ci
    from automations.vantura_churn import shot

    # worksheet_ci, not .worksheet(): office boards are hand-duplicated and the
    # churn tab's casing drifts ('Lucy Churn' vs 'LUCY CHURN' — Jamis's board,
    # 2026-08-01). Match tolerantly so a new office doesn't fail at 4am.
    ws = worksheet_ci(open_by_key(o.sheet_id), o.churn_tab)
    if which == "customer_churn":
        _assert_rolloff_has_data(ws, o)
        rng = shot.visible_range(ws)
        out = out_dir / "customer_churn.png"
    elif which == "activation_by_rep":
        col = ws.get("AE1:AE200")
        last = max((i for i, r in enumerate(col, 1) if r and r[0].strip()),
                   default=0)
        # Rep rows sit BELOW the "Rep Name" header (row 15). If there's nothing
        # there, the churn board hasn't been written yet — DON'T post a 2-row
        # blank (2026-07-22: that "posted" empty and read as missing). Raise so
        # the runner skips + flags it for a rerun instead.
        if last <= 15:
            raise ValueError(
                "activation_by_rep: no rep rows on {!r} (churn board not "
                "written yet) — skip rather than post blank".format(o.churn_tab))
        rng = "AE14:AF{}".format(last)
        out = out_dir / "activation_by_rep.png"
    else:
        raise ValueError("unknown churn image {!r}".format(which))
    shot.render(ws, out, rng=rng)
    return out


# --- shared order data (pulled once) ---------------------------------------
_LINE_CACHE: dict = {}


_CSV_ONCE: dict = {}   # date -> shared ORDERLOG csv (pulled ONCE for the batch)


def _order_lines(o: B2BOffice, out_dir: Path, log=print):
    """The un-pivoted AT&T sales lines for this owner. The ORDERLOG export is the
    SAME all-reps pull for EVERY office (~120MB), so in an --all batch we download
    it ONCE and slice each office out of it (mirrors office_metrics' pull-once) —
    the pull costs the same whether it's 2 offices or 20. order_log + payout share
    the per-office sliced result."""
    if o.key in _LINE_CACHE:
        return _LINE_CACHE[o.key]
    from automations.att_order_log import clean, run as al_run
    today = dt.date.today()
    dkey = today.isoformat()
    csv = _CSV_ONCE.get(dkey)
    if csv is None:
        shared = REPO_ROOT / "output" / "b2b_metrics" / "_shared"
        shared.mkdir(parents=True, exist_ok=True)
        csv = shared / "orderlog_{}.csv".format(dkey)
        al_run._pull(today, csv, log=log)
        _CSV_ONCE[dkey] = csv
    else:
        log("  [order-log] reusing this batch's export (pulled once)")
    lines = clean.load_rows(csv, owner_prefix=o.owner)   # slice per office
    # DEFER (raise) if --require-fresh and the extract is behind. Runs BEFORE the
    # cache write so payout's re-call re-checks (it reuses the cached CSV, so no
    # re-pull) and both order-log sections defer together.
    _require_fresh_gate(lines, log=log)
    _LINE_CACHE[o.key] = lines
    return lines


# --- #6 : the order-log workbook -------------------------------------------
def order_log_workbook(o: B2BOffice, out_dir: Path, log=print) -> Path:
    from automations.att_order_log import xlsx
    lines = _order_lines(o, out_dir, log=log)
    # Pending-by-Rep tab is derived from the order-log lines themselves (in-flight
    # DTR status), NOT payroll (Carlos 2026-07-23). xlsx.build builds it in-book.
    out = out_dir / "ATT Order Log {}.xlsx".format(
        dt.date.today().strftime("%m-%d-%Y"))
    xlsx.build(lines, out, today=dt.date.today())
    return out


# --- #7 : the Activation-report-overview image -----------------------------
def payout_image(o: B2BOffice, out_dir: Path, log=print) -> Path:
    """Two-week Activated/Cancelled/Still-Open per rep, rendered like BOX's
    payout image. Reuses box_order_log.png with the AT&T rows remapped to the
    keys that renderer expects."""
    from automations.att_order_log import payout as ap
    from automations.box_order_log import png as bpng

    lines = _order_lines(o, out_dir, log=log)
    tables = ap.build_week_tables(lines, dt.date.today())
    # box png's rows use keys: rep / posted / canceled / pending. Map ours.
    for wk in ("last", "this"):
        for r in tables[wk]["rows"]:
            r["posted"] = r.pop("activated")
            r["pending"] = r.pop("open")
    out = out_dir / "activation_overview.png"
    # Swap the box renderer's column HEADERS to AT&T's for this render — the
    # count key stays "posted" but the header reads "Posted" (Carlos 2026-07-20),
    # not BOX's "Accepted by Supplier". Restored after, so BOX's own report is
    # untouched.
    saved_cols = list(bpng.COLS)
    bpng.COLS[:] = [
        ("Rep Name", "rep", "left"),
        ("Posted", "posted", "center"),
        ("Cancelled", "canceled", "center"),
        ("Still Open", "pending", "center"),
    ]
    try:
        bpng.render(tables, out,
                    subtitle="Posted & Cancelled are for that posted week — pay "
                             "follows. Still Open = not yet posted, any week.")
    finally:
        bpng.COLS[:] = saved_cols
    return out


# --- #1 / #2 / #3-5 / #8 : Tableau Download->Image, owner-sliced ------------
def _sliced_url(o: B2BOffice, view_key: str, today: dt.date = None) -> str:
    """The URL to capture. A per-office OVERRIDE view is a saved view already
    filtered to the owner — captured as-is, no slice appended. Otherwise it's the
    shared team view with ?<field>=<value> appended (drops :iid, a tab index),
    where the field is the view's own filter_field ("Owner Name" for Sales/OOB,
    "Owner & Office" for churn/activation) and the value is the office's matching
    slice value.

    EXCEPTION — slice_overrides: an override view listed there is a whole-workbook
    saved view (a different layout/expand state, NOT a pre-filtered slice), so it
    still needs the owner slice appended. Used for Carlos's Sales Metrics: his
    CarlosEXP view carries the per-rep EXPANDED layout, but both panels still scope
    to his office via ?Owner Name=<owner> exactly like the shared team view did.
    Re-slicing a view that already bakes the same owner filter is harmless (same
    value), so this is safe whether or not the saved view carries the filter.

    WEEK PIN: a view that names a `week_filter` in VIEW_META (Out of Bounds) also
    gets `&<week field>=<M/D/YYYY>` for the week holding the last completed sales
    day. Without it the view opens on ITS default week, which on a Monday is a
    week with no sales in it yet."""
    meta = VIEW_META.get(view_key, {})
    week_field = meta.get("week_filter")
    if o.is_override(view_key) and view_key not in o.slice_overrides:
        url = o.view_url(view_key)
        # An override view is captured as-is — but the week pin is about WHICH
        # week, not which owner, so a saved view still needs it (its saved week
        # is whatever was on screen the day it was saved).
        if week_field:
            url = _with_week(url, week_field, today,
                             meta.get("week_format", "mdy"))
        return url
    from urllib.parse import quote
    field = meta.get("filter_field", OWNER_FIELD)
    value = _tableau_filter_value(o.slice_value(field))
    base = o.view_url(view_key).split("?")[0]
    url = "{}?{}={}".format(base, quote(field), quote(value, safe="\\"))
    if week_field:
        url = _with_week(url, week_field, today,
                         meta.get("week_format", "mdy"))
    return url


def _with_week(url: str, week_field: str, today: dt.date = None,
               fmt: str = "mdy") -> str:
    """Append the week pin to `url`.

    `fmt` because the two ATT week filters disagree: OutofBoundsReport takes ISO
    and ignores M/D/YYYY, while PRODUCTSALESSUMMARY4WK (rep_sales_fill) is the
    other way round and renders nothing at all on ISO. Each view names its own in
    VIEW_META["week_format"] rather than one of them being "the" house format.

    safe="" because quote() leaves '/' alone by default, and a raw-slashed
    '8/16/2026' in a query string is not the same parameter."""
    from urllib.parse import quote
    we = report_week_ending(today)
    wv = we.isoformat() if fmt == "iso" else week_value(we)
    sep = "&" if "?" in url else "?"
    return "{}{}{}={}".format(url, sep, quote(week_field), quote(wv, safe=""))


def _tableau_filter_value(value: str) -> str:
    """Make a dimension member safe to pass as a Tableau URL filter value.

    "Owner & Office" CAN be URL-sliced — the long-standing note that it can't
    (workflows/add-b2b-office.md) was wrong, and cost this project two hand-built
    saved views per office plus a run of blank captures. It needs TWO escapes,
    and it silently returns an EMPTY view when either is missing:

      1. the member carries an embedded CARRIAGE RETURN before the office suffix
         ("JAMIS GARAY\\r [atomic marketing, inc.]"), which must survive as %0D.
         Values recorded through the onboarding form lose it, so restore it.
      2. a COMMA inside the value is Tableau's multi-value SEPARATOR — an office
         like "[atomic marketing, inc.]" is otherwise read as two members, and
         neither matches. Escape it as "\\,".

    Proven live on ATTTRACKER-B2B/CHURNRATES/ALLTEAMSEXP, 2026-08-01: with only
    one of the two, every filter reads "(None)" and the table is empty; with both,
    the view scopes to that office's reps. Carlos's own office has no comma in
    its name, which is why this never surfaced until an office that did.
    """
    v = str(value or "")
    if not v:
        return v
    # Restore the CR the form drops: "NAME [office]" -> "NAME\r [office]".
    if "\r" not in v and " [" in v:
        v = v.replace(" [", "\r [", 1)
    return v.replace(",", "\\,")


# Which views need the sort/crop rep-table handling (Activation + the 3 Churn
# products). All views capture the same way (cdp_pull Download→Image — the path
# that reliably auths via Carlos's warm Chrome on Lucy 2); these just get the
# extra sort (Activation) + crop-to-last-rep afterward.
_REP_TABLE_VIEWS = ("activation_rate", "churn_wireless", "churn_int", "churn_air")

# DIAGNOSTIC 2026-07-21: churn came back as National-Average-only. Download→Image
# exports the WHOLE dashboard, so the rep table should be in the PNG — meaning the
# crop is trimming it off. `runner --no-crop` sets B2B_SKIP_CROP=1 (read at call
# time) to capture uncropped and confirm.
import os as _os


def _crop_to_last_colored_row(png: Path, leading: bool = False,
                              verbose: bool = False) -> bool:
    """Trim the image to END on the last rep row with data, cutting the empty gap
    + the uncoloured table below the rep list. Two modes (reports differ):

      leading=False (CHURN): last rep with a coloured cell in ANY period. Sparse
        products like INT have reps whose only activity is a later column — a
        leading-only rule would drop them (Megan 2026-07-21, Kendrick McClain).
      leading=True (ACTIVATION): last rep with data in the LEADING (0-7 Day)
        column only. The view is sorted 0-7 desc, so reps with no 0-7 activity
        sort to the bottom and should be trimmed (Megan 2026-07-21, end at Aylin).

    Best-effort: any doubt -> keep full."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(png).convert("RGB")
        W, H = im.size
        px = im.load()

        def sat(p):
            return max(p) - min(p) > 45 and max(p) > 90

        if leading:
            # For each row, the x of its LEFTMOST coloured cell. Reps WITH
            # leading-column (0-7) data start their colour in that column; reps
            # without it (sorted to the bottom) start further right. The leading
            # column's x is the MODE of those leftmost-x values (most reps have
            # data there) — robust to the misaligned National-Average band (one
            # row, never the mode). Trim to the last row that starts at that x.
            from collections import Counter
            row_left = {}
            for y in range(0, H, 2):
                for x in range(0, W, 3):
                    if sat(px[x, y]):
                        row_left[y] = x
                        break
            if not row_left:
                return False
            buckets = Counter(round(x / 8) * 8 for x in row_left.values())
            x0 = buckets.most_common(1)[0][0]
            last = 0
            for y, lx in row_left.items():
                if abs(lx - x0) <= 12 and y > last:
                    last = y
        else:
            # Last row with a real RUN of coloured pixels (any column).
            last = 0
            for y in range(H):
                if sum(1 for x in range(0, W, 3) if sat(px[x, y])) > 8:
                    last = y
        if last <= 0:
            return False
        cut = min(H, last + 10)            # +10 keeps the cell's bottom border
        if cut >= H - 4:
            return False                    # nothing meaningful to trim
        im.crop((0, 0, W, cut)).save(png)
        if verbose:
            print("   ✂ cropped to last {} row ({} -> {}px)".format(
                "leading-col" if leading else "coloured", H, cut), flush=True)
        return True
    except Exception as e:  # noqa: BLE001 — a bad crop must never lose the image
        if verbose:
            print("   ⚠ crop failed ({}) — full length kept".format(
                type(e).__name__), flush=True)
        return False


def _select_week(page, want: dt.date, log=print) -> bool:
    """Drive the dashboard's week dropdown to `want`. Returns True if it moved.

    WHY NOT THE URL. On OutofBoundsReport the `?Sale Date Week Ending
    (mon-sun)=` parameter is inert — proved 2026-08-17 against the live view
    with seven variants (plain, :revert=all, :refresh=yes, ISO, the caption
    without its suffix, week-only, and the .csv endpoint): every one still drew
    8/23/2026. The Owner Name slice on the SAME url applies fine, so it is this
    one field, whose datasource name evidently differs from the caption the
    dashboard prints. The dropdown itself is right there on the dashboard —
    Tableau renders it as a .tabComboBox — so we click it the way the person who
    files this report by hand does.

    Found positionally by CONTENT, not index: the box whose current value looks
    like a date. The dashboard has four quick filters ((All), the owner, the
    week, (All)) and their order is a layout detail that can change.
    """
    import re

    from automations.b2b_quality.run import _IFRAME
    fr = page.frame_locator(_IFRAME)
    targets = week_value_variants(want)

    boxes = fr.locator(".tabComboBox")
    idx, cur = None, ""
    for i in range(min(boxes.count(), 12)):
        try:
            t = " ".join((boxes.nth(i).inner_text(timeout=8_000) or "").split())
        except Exception:  # noqa: BLE001
            continue
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t):
            idx, cur = i, t
            break
    if idx is None:
        log("   ⚠ week dropdown not found on the dashboard")
        return False
    if cur in targets:
        log("   week dropdown already on {}".format(cur))
        return True
    log("   week dropdown is on {} — selecting {}".format(cur, targets[0]))
    # OPEN. A .tabComboBox is a composite: the value label, a name container and
    # the arrow button. Which of them actually opens the menu differs by Tableau
    # build, so try each, and stop as soon as menu items appear.
    openers = [(".tabComboBox", idx), (".tabComboBoxButton", idx),
               (".tabComboBoxName", idx)]
    item_sels = (".tabMenuItemName", ".tabComboBoxMenuItem", "[role='option']",
                 "[role='menuitem']", ".tabMenuItem", ".QFCheckbox",
                 "[role='checkbox']")

    # The week filter's own DOM token, so the checkbox list we toggle is THIS
    # dropdown's and not another quick filter's.
    #
    # WHY (2026-08-17): a frame-wide [role='checkbox'] search found a 117-item
    # date list, focus+Space flipped it, 8/23 genuinely unchecked — and the week
    # dropdown still read '8/23/2026' on every attempt. The dashboard carries
    # four quick filters and the list being toggled belonged to one of the
    # others. Tableau embeds the field name in each checkbox's id (the same
    # property box_order_log.window._all_item keys on), so scope by that.
    token = ""
    try:
        raw = boxes.nth(idx).get_attribute("id") or ""
        log("   [week] dropdown id={!r}".format(raw[:120]))
        # ids look like FI_federated.0brn…,none:<field>:nk98096…_<value>
        bits = [b for b in raw.split(":") if b and not b.startswith("FI_")]
        if bits:
            token = bits[0].strip().lstrip("﻿")
            log("   [week] scoping menu to id token {!r}".format(token))
    except Exception:  # noqa: BLE001
        pass

    def _menu_items():
        """(selector, texts) for whichever selector has the open menu's items."""
        sels = ([('[role="checkbox"][id*="{}"]'.format(token))] if token
                else []) + list(item_sels)
        for sel in sels:
            try:
                loc = fr.locator(sel)
                n = min(loc.count(), 300)
            except Exception:  # noqa: BLE001
                continue
            if not n:
                continue
            if sel is not sels[0]:
                log("   [week] falling back to {} (token scope empty)".format(sel))
            texts = []
            for j in range(n):
                try:
                    texts.append(" ".join(
                        (loc.nth(j).inner_text(timeout=3_000) or "").split()
                    ).lstrip("✓").strip())
                except Exception:  # noqa: BLE001
                    texts.append("")
            if any(t for t in texts):
                return sel, loc, texts
        return None, None, []

    for osel, oidx in openers:
        try:
            fr.locator(osel).nth(oidx).click(timeout=15_000)
        except Exception:  # noqa: BLE001
            try:
                fr.locator(osel).nth(oidx).focus()
                page.keyboard.press("Enter")
            except Exception:  # noqa: BLE001
                continue
        page.wait_for_timeout(3_000)
        sel, loc, texts = _menu_items()
        if not sel:
            log("   [week] {} -> no menu items appeared".format(osel))
            continue
        log("   [week] {} opened {} ({} items): {}".format(
            osel, sel, len(texts), " | ".join(t for t in texts[:20] if t)))
        # Ground truth for the next run if this one still misses: the ids the
        # items actually carry.
        for j in range(min(3, len(texts))):
            try:
                log("   [week] item[{}] {!r} id={!r}".format(
                    j, texts[j], (loc.nth(j).get_attribute("id") or "")[:120]))
            except Exception:  # noqa: BLE001
                pass
        pick = next((j for j, t in enumerate(texts) if t in targets), None)
        if pick is None:
            continue
        # This is a MULTI-SELECT checkbox list (it carries an "(All)" item), so
        # picking a week is two moves: check the one we want, then uncheck the
        # week it was on. Check FIRST — Tableau re-selects everything if the
        # last checked value is cleared.
        #
        # And the toggle is KEYBOARD ONLY. .click() (force or not) is swallowed
        # by Tableau's click-capture overlay and leaves aria-checked untouched —
        # which is why the previous pass reported "picked" and still rendered
        # 8/23. Same finding, same fix as box_order_log.window
        # .release_pinned_filters. [[reference_tableau_pinned_id_filters]]
        def _set(j: int, want: bool) -> bool:
            el = loc.nth(j)
            try:
                if (el.get_attribute("aria-checked") == "true") == want:
                    return True
                el.focus()
                page.keyboard.press(" ")
                page.wait_for_timeout(6_000)
                return (el.get_attribute("aria-checked") == "true") == want
            except Exception:  # noqa: BLE001
                return False

        if not _set(pick, True):
            log("   ⚠ {} would not check".format(targets[0]))
            continue
        import re as _re
        for j, t in enumerate(texts):
            if j == pick or not _re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t):
                continue
            try:
                if loc.nth(j).get_attribute("aria-checked") == "true":
                    _set(j, False)
                    log("   [week] unchecked {}".format(t))
            except Exception:  # noqa: BLE001
                pass
        # APPLY. A multi-value quick filter can be set to "Apply" mode, where
        # toggling a checkbox stages the change and nothing requeries until the
        # apply control is pressed — which is exactly what the first keyboard
        # pass looked like: 8/23 unchecked in the DOM, the view still drawing
        # 8/23. Press it if it's there; harmless when it isn't.
        for asel in (".tabApplyButton", ".ApplyButton",
                     "[role='button'][aria-label*='Apply']"):
            try:
                btn = fr.locator(asel).first
                if btn.count():
                    btn.focus()
                    page.keyboard.press("Enter")
                    log("   [week] pressed apply ({})".format(asel))
                    page.wait_for_timeout(8_000)
                    break
            except Exception:  # noqa: BLE001
                continue
        # Close by clicking the dashboard itself, NOT Escape: on a staged filter
        # Escape can discard the pending selection instead of committing it.
        try:
            page.mouse.click(8, 8)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(20_000)           # let the viz requery
        # The control's OWN value is the honest read of whether it moved —
        # independent of the caption the dashboard prints.
        try:
            now = " ".join((boxes.nth(idx).inner_text(timeout=10_000)
                            or "").split())
        except Exception:  # noqa: BLE001
            now = "?"
        log("   ✓ picked {} from {} — dropdown now reads {!r}".format(
            targets[0], sel, now))
        return True
    log("   ⚠ {} not offered by the week dropdown".format(targets[0]))
    return False


def _read_viz_text(page, log=print) -> str:
    """The rendered viz's own text (iframe body), or "" if it can't be read.

    Used to VERIFY a week-pinned view actually moved to the week we asked for —
    the header the image draws ("Sale Date Week Ending (mon-sun) 8/16/2026") is
    real DOM, so this reads the same string the screenshot shows. Best-effort by
    design: a read failure must not sink a capture that is otherwise fine, so the
    caller treats "" as 'could not verify' and says so out loud."""
    from automations.b2b_quality.run import _IFRAME
    try:
        return page.frame_locator(_IFRAME).locator("body").inner_text(
            timeout=30_000) or ""
    except Exception as e:  # noqa: BLE001
        log("   ⚠ could not read the viz text ({})".format(type(e).__name__))
        return ""


def _verify_week(view_key: str, text: str, want: dt.date, log=print) -> None:
    """Refuse a week-pinned capture whose rendered header names another week.

    An unreadable viz ("" text) is NOT treated as a failure — the image itself
    may well be right, and failing every capture on a flaky inner_text would
    trade a rare wrong post for a daily missing one. It IS logged, so a run that
    never verifies is visible rather than assumed good."""
    if not text:
        log("   ⚠ [{}] week pin UNVERIFIED (viz text unreadable) — posting the "
            "image; check the week in the header".format(view_key))
        return
    if any(v in text for v in week_value_variants(want)):
        log("   ✓ [{}] week pin verified — showing week ending {}".format(
            view_key, week_value(want)))
        return
    # Name the week it DID render, so the log says what happened rather than
    # just that something did.
    import re
    shown = re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", text)
    raise WeekFilterNotApplied(
        "{}: asked for week ending {} but the view rendered {} — the URL week "
        "filter did not apply (Tableau drops an unmatched field caption in "
        "silence). Skipping rather than posting a report of an unknown week."
        .format(view_key, week_value(want),
                ", ".join(sorted(set(shown))[:4]) or "no dated header"))


# The viz's own furniture. inner_text on the iframe body starts with the Tableau
# toolbar and the workbook's sheet-tab strip, so an EMPTY board still reads back
# a dozen "lines" — which would tell a row-counting blank check that a report
# with nothing in it is full. Everything here is chrome, never data.
_VIZ_CHROME = {
    "undo", "redo", "revert", "refresh", "pause", "replay animation",
    "replay speed options", "accelerate", "view: original", "save custom view",
    "data guide", "watch", "download", "full screen", "share", "comment",
    "alert", "subscribe", "edit", "loading...", "(all)",
}


def viz_reports_no_data(page, log=print) -> bool:
    """True when TABLEAU ITSELF says the sheet is empty.

    The accessibility label on an empty text table ends with "No data to
    visualize with current filters." — which is the ground truth we spent a day
    inferring from pixels and row counts on 2026-08-17. Read it directly: it is
    unambiguous, it costs nothing, and it can't be fooled by the toolbar the way
    counting text lines can.

    Best-effort: an unreadable frame returns False so a flaky read never drops a
    section that was fine."""
    from automations.b2b_quality.run import _IFRAME
    try:
        return page.frame_locator(_IFRAME).locator(
            '[aria-label*="No data to visualize"]').count() > 0
    except Exception:  # noqa: BLE001
        return False


def _row_summary(text: str, owner: str = "", limit: int = 12) -> list:
    """The viz's non-chrome text lines — what the section actually SHOWS. Used
    only for logging, so a human reading the run log can tell an empty week from
    a full one without opening the PNG.

    The header chrome (captions, the owner the view is sliced to, the week, the
    server-update stamp) is dropped: on a BLANK render those lines are ALL that
    is left, and counting them as content would report an empty week as two
    rows of data."""
    import re
    skip = ("sale date week ending", "owner name", "last server update",
            "data source sales date range", "out of bounds", "view:")
    own = " ".join((owner or "").split()).lower()
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or any(s.lower().startswith(k) for k in skip):
            continue
        if own and " ".join(s.split()).lower() == own:
            continue                       # the slice value, not a row
        if " ".join(s.split()).lower() in _VIZ_CHROME:
            continue                       # toolbar button, not a row
        if re.fullmatch(r"[\d/\-. ]+", s):
            continue                       # a bare date/number echo of a filter
        out.append(s)
        if len(out) >= limit:
            break
    return out


def image_is_blank(png: Path, max_extent: float = 0.15) -> bool:
    """True when the PNG is a HEADER AND NOTHING ELSE.

    Measured by VERTICAL EXTENT — how far down the export the last row of
    content reaches — not by how much ink there is. A blank Tableau board is not
    an empty file: it still draws the title, the filter captions and the
    'Data Source Sales Date Range' footer across the top, so an ink-quantity
    test can't tell it from a small table. Where the content STOPS separates
    them cleanly (measured on the 2026-08-17 shapes):

        header only          last content at  11% of the height
        6-row Out of Bounds  last content at  80%
        25-row churn table   last content at  97%

    Conservative on purpose. 15% is well below any real table, because wrongly
    calling a good board blank would DROP a section that was fine — the more
    expensive mistake of the two. Where a caller has the rendered DOM text (the
    week-pinned views do), that is the authoritative emptiness signal and this is
    only the backstop.

    Best-effort: any doubt returns False."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(png).convert("RGB")
        W, H = im.size
        if W < 20 or H < 20:
            return True
        px = im.load()
        # Background = the corner colour (Tableau exports on white/near-white).
        bg = px[2, 2]

        def differs(p):
            return (abs(p[0] - bg[0]) + abs(p[1] - bg[1])
                    + abs(p[2] - bg[2])) > 40

        last = 0
        for y in range(0, H, 2):
            run = sum(1 for x in range(0, W, 4) if differs(px[x, y]))
            if run > max(3, W // 200):
                last = y
        if not last:
            return True                      # nothing on the page at all
        return (last / float(H)) < max_extent
    except Exception:  # noqa: BLE001 — a guard must never lose the image
        return False


def tableau_image(o: B2BOffice, view_key: str, out_dir: Path, log=print,
                  today: dt.date = None) -> Path:
    """Capture one Tableau view for this office (owner-sliced, or a per-office
    override view captured as-is). LUCY 2 — Carlos's login carries the views.

    Own Chrome per view (NOT a shared batch session): the ORDERLOG pull + other
    captures each run cdp_pull._kill_ours()/_launch() and their own
    sync_playwright, which killed a shared page and can't nest two playwrights in
    one thread (proven 2026-07-22). Sharing one Chrome needs every Chrome user in
    the batch to accept a passed page — a bigger refactor, deferred.

    Each view is captured under the shared CDP-9246 lock, so "own Chrome per
    view" never means "own Chrome AT THE SAME TIME as somebody else's"."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.tableau_screenshots.capture import capture_page
    from automations.vantura_churn import cdp_pull
    from automations.b2b_quality.run import apply_sort, _IFRAME

    meta = VIEW_META.get(view_key, {})
    url = _sliced_url(o, view_key, today)
    out = out_dir / "{}.png".format(view_key)
    spec = {"id": view_key, "title": view_key, "url": url}
    # Filled by after_load on the attempt that produced the saved image, so the
    # week check below reads the SAME render the PNG came from.
    probe = {"text": "", "nodata": False}

    def after_load(page):
        # Week-pinned views: drive the dashboard's week dropdown, THEN read what
        # it drew. The URL carries the pin too (harmless, and it is the right
        # thing to send if the field is ever renamed to match its caption), but
        # the dropdown is what actually moves this view.
        # Tableau's OWN emptiness verdict, for every view — the blank guard's
        # primary signal (see viz_reports_no_data).
        probe["nodata"] = viz_reports_no_data(page, log=log)
        if meta.get("week_filter"):
            want = report_week_ending(today)
            probe["text"] = _read_viz_text(page, log=log)
            # The URL pin is the fast path and now names the field Tableau
            # actually knows. Only if it didn't land do we fall back to driving
            # the dashboard's dropdown — which costs a couple of minutes and is
            # the brittle path, so it stays a backstop, not the plan.
            if probe["text"] and not any(v in probe["text"]
                                         for v in week_value_variants(want)):
                log("   week pin didn't land from the URL — trying the dropdown")
                if _select_week(page, want, log=log):
                    probe["text"] = _read_viz_text(page, log=log)
        # Activation carries no saved sort; click its measure sort glyph high->low
        # before the shot. Churn's saved view sorts itself. Offices whose saved
        # view is ALREADY sorted (o.baked_sort_views, e.g. Atef's AtefEXP) must
        # NOT be clicked — a click toggles the baked sort back off.
        hdr = meta.get("sort_header")
        if not hdr or view_key in o.baked_sort_views:
            return
        # Wait for the rep table's sort column to RENDER before clicking — on a
        # cold load after_load fires before the viz hydrates, so the click misses
        # the header and the table shoots in default (alphabetical) order.
        try:
            page.frame_locator(_IFRAME).locator(
                'div.tab-vizHeader >> text="{}"'.format(hdr)).first.wait_for(
                state="visible", timeout=45_000)
            page.wait_for_timeout(1_500)   # let it settle before the click
        except Exception:  # noqa: BLE001 — apply_sort is still best-effort below
            pass
        apply_sort(page, hdr, clicks=meta.get("sort_clicks", 1), verbose=True)

    # SERIALISE on the shared CDP-9246 lock — the same one activation_board_image
    # below and EVERY att_order_log / vantura_churn entry point already take.
    # Without it the _kill_ours() on the next line is a bare
    # `pkill -f vantura_cdp_profile`: it murders another report's Chrome mid-pull,
    # and that report's own _kill_ours() murders ours right back. Both sides then
    # die with patchright TargetClosedError, which reads like a broken Tableau
    # view but is only two jobs fighting over one Chrome.
    #
    # This was the LAST unlocked user of port 9246, and it was the aggressor on
    # both sides of 2026-08-14: it dropped `carlos: order_tiered_bonus` from the
    # 4am thread (04:57-05:06) and it killed the 07:00 vantura-churn ORDERLOG
    # pull when the 07:45 backstop pass fired. tableau_image feeds 6 of the 11
    # sections (sales_metrics, the 3 churns, order_tiered_bonus, out_of_bounds),
    # so the exposure was most of the thread, not one card.
    with cdp_pull._cdp_lock(label="b2b {} {}".format(o.key, view_key), log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        try:
            with sync_playwright() as p:
                browser = None
                for attempt in range(10):
                    time.sleep(5)
                    try:
                        browser = p.chromium.connect_over_cdp(
                            "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                        break
                    except Exception:  # noqa: BLE001 — retry a not-yet-up port
                        if attempt == 9:
                            raise
                        log("  [cdp] port not up yet (try {}/10)".format(
                            attempt + 1))
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                capture_page(page, spec, out_dir, after_load=after_load,
                             verbose=False)
            if meta.get("data_cols") and not _os.environ.get("B2B_SKIP_CROP"):
                _crop_to_last_colored_row(
                    out, leading=(meta.get("crop_mode") == "leading"),
                    verbose=True)
            verified_week, dom_rows = False, None
            if meta.get("week_filter"):
                # Raises WeekFilterNotApplied -> the runner skips + flags the
                # section, so a blank of an unknown week never reaches Slack.
                _verify_week(view_key, probe["text"],
                             report_week_ending(today), log=log)
                verified_week = True
                rows = _row_summary(probe["text"], owner=o.owner)
                if probe["text"]:
                    dom_rows = len(rows)     # authoritative emptiness signal
                if rows:
                    log("   [{}] shows {} line(s): {}".format(
                        view_key, len(rows), " | ".join(rows[:6])))
                elif probe["text"]:
                    log("   [{}] EMPTY for week ending {} — no rows in the "
                        "verified week (a clean week, not a failed pull)".format(
                            view_key, week_value(report_week_ending(today))))
            # BLANK GUARD — every Tableau section, not just the week-pinned one.
            # An empty render is now heard about (write_manifest -> the 🚨 in
            # #claudecorrections-and-requests) instead of posting as a
            # confident-looking screenshot of nothing.
            # Blank if Tableau says so, if the rendered rows are gone, or if
            # the exported image is a header and nothing else. Any one of the
            # three is enough — the cost of missing a blank (a confidential
            # report of nothing, posted) is worse than the cost of a false one
            # (a section skipped and flagged, which someone then re-runs).
            blank = (probe["nodata"] or image_is_blank(out)
                     or (dom_rows == 0 if dom_rows is not None else False))
            if blank:
                if verified_week:
                    # We KNOW which week this is and it is genuinely empty. Post
                    # it — that is Carlos's ask — but still say so out loud.
                    log("   ⚠ [{}] renders BLANK for the verified week ending "
                        "{} — posting (genuinely empty), flagged".format(
                            view_key, week_value(report_week_ending(today))))
                else:
                    raise BlankRender(
                        "{}: rendered BLANK (no content in the exported image) "
                        "— not posting an empty report. Check the view's own "
                        "filters; on a Monday the usual cause is a week that "
                        "hasn't started selling yet.".format(view_key))
            return out
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            cdp_pull._kill_ours()


# --- week-pin probe ---------------------------------------------------------
# The pin did NOT take on the first live run (2026-08-17): the view still drew
# week ending 8/23 with the filter in the URL. Guessing one candidate per run
# costs ~6 minutes of queue each time, so this tries every candidate in ONE
# Chrome session and prints which one moves the week — the same reasoning
# rep_sales_fill.probe_filters was written on.
def _week_variants(o: B2BOffice, view_key: str, today: dt.date = None) -> list:
    from urllib.parse import quote
    from automations.b2b_metrics.offices import WEEK_FIELD
    meta = VIEW_META.get(view_key, {})
    base = o.view_url(view_key).split("?")[0]
    owner = "{}={}".format(
        quote(meta.get("filter_field", OWNER_FIELD)),
        quote(_tableau_filter_value(o.slice_value(
            meta.get("filter_field", OWNER_FIELD))), safe="\\"))
    we = report_week_ending(today)
    mdy = quote(week_value(we), safe="")
    iso = quote(we.isoformat(), safe="")
    wf = quote(WEEK_FIELD)
    wf_short = quote("Sale Date Week Ending")
    # The names the live filter DOM actually reports (probe-filters, 2026-08-17):
    #   owner -> 'Account.OwnerName'
    #   week  -> 'Sale Date Week Ending (copy)_1603000001376837642'
    # The bare '(copy)' and the printed '(mon-sun)' caption are both already
    # proven inert, so what is left to test is the SUFFIXED field name, and
    # whether this workbook wants field NAMES rather than captions at all (which
    # is what the owner filter answers).
    wf_full = quote("Sale Date Week Ending (copy)_1603000001376837642")
    owner_field_name = "{}={}".format(
        quote("Account.OwnerName"),
        quote(_tableau_filter_value(o.slice_value(OWNER_FIELD)), safe="\\"))
    return [
        ("control (owner only)", "{}?{}".format(base, owner)),
        ("suffixed field name", "{}?{}&{}={}".format(base, owner, wf_full, mdy)),
        ("suffixed + :revert=all", "{}?:revert=all&{}&{}={}".format(
            base, owner, wf_full, mdy)),
        ("suffixed, no owner", "{}?{}={}".format(base, wf_full, mdy)),
        ("field-name owner + suffixed week", "{}?{}&{}={}".format(
            base, owner_field_name, wf_full, mdy)),
        ("mdy bare (copy)", "{}?{}&{}={}".format(base, owner, wf, mdy)),
        ("iso suffixed", "{}?{}&{}={}".format(base, owner, wf_full, iso)),
    ]


def _dump_filters(page, url: str, log=print) -> None:
    """Map each quick filter on the dashboard to the checkbox list it owns.

    WHY (2026-08-17): toggling a frame-wide [role='checkbox'] date list flips
    aria-checked and changes nothing on screen, while the dropdown reading
    '8/23/2026' never moves. The dashboard has FOUR filters and two of them read
    '(All)' — so the 117-item list whose ids say 'Sale Date Week Ending (copy)'
    is very likely one of those (All) ones, and the week dropdown is a DIFFERENT
    field whose list we have never touched. This prints, per dropdown, the ids
    its options carry — which names the field to filter on and the list to
    drive. Tagged FLT| for logtail.
    """
    from automations.b2b_quality.run import _IFRAME
    page.goto("about:blank", wait_until="domcontentloaded", timeout=60_000)
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(35_000)
    fr = page.frame_locator(_IFRAME)
    boxes = fr.locator(".tabComboBox")
    n = min(boxes.count(), 8)
    log("FLT| {} combo box(es)".format(boxes.count()))
    for i in range(n):
        try:
            val = " ".join((boxes.nth(i).inner_text(timeout=8_000) or "").split())
        except Exception:  # noqa: BLE001
            val = "?"
        log("FLT| --- box[{}] reads {!r} ---".format(i, val))
        try:
            boxes.nth(i).click(timeout=15_000)
            page.wait_for_timeout(4_000)
        except Exception as e:  # noqa: BLE001
            log("FLT|   could not open ({})".format(type(e).__name__))
            continue
        try:
            cbs = fr.locator("[role='checkbox']")
            m = min(cbs.count(), 300)
        except Exception:  # noqa: BLE001
            continue
        groups = {}
        for j in range(m):
            try:
                cid = cbs.nth(j).get_attribute("id") or ""
                txt = " ".join((cbs.nth(j).inner_text(timeout=2_500)
                                or "").split()).lstrip("✓")
                chk = cbs.nth(j).get_attribute("aria-checked")
            except Exception:  # noqa: BLE001
                continue
            # The field name is the middle ':'-segment of the id.
            key = next((b for b in cid.split(":")
                        if b and not b.startswith("FI_")), cid[:40])
            g = groups.setdefault(key, {"n": 0, "checked": 0, "first": []})
            g["n"] += 1
            if chk == "true":
                g["checked"] += 1
            if len(g["first"]) < 4 and txt:
                g["first"].append(txt)
        for key, g in groups.items():
            log("FLT|   field={!r} items={} checked={} first={}".format(
                key[:70], g["n"], g["checked"], g["first"]))
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1_500)


def _dump_view(page, url: str, log=print) -> None:
    """Print the loaded view's text + every labelled control, so the week
    control can be DRIVEN when it can't be URL-filtered.

    Every line is prefixed with a grep tag (TXT| LBL| SEL|) because the remote
    queue only shows a log's tail — the laptop pulls these back by tag with
    `lucy logtail <log> TXT|`."""
    from automations.b2b_quality.run import _IFRAME
    page.goto("about:blank", wait_until="domcontentloaded", timeout=60_000)
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(35_000)
    fr = page.frame_locator(_IFRAME)
    try:
        txt = fr.locator("body").inner_text(timeout=45_000) or ""
    except Exception as e:  # noqa: BLE001
        txt = ""
        log("TXT| read failed {}".format(type(e).__name__))
    for ln in txt.splitlines()[:120]:
        s = ln.strip()
        if s:
            log("TXT| " + s[:160])
    # Labelled controls — the quick filters live here when they exist.
    for scope_name, scope in (("viz", fr), ("page", page)):
        try:
            els = scope.locator("[aria-label]")
            n = min(els.count(), 250)
        except Exception as e:  # noqa: BLE001
            log("LBL| [{}] scope failed {}".format(scope_name, type(e).__name__))
            continue
        seen = set()
        for i in range(n):
            try:
                lab = els.nth(i).get_attribute("aria-label") or ""
            except Exception:  # noqa: BLE001
                continue
            if lab and lab not in seen:
                seen.add(lab)
                log("LBL| [{}] {}".format(scope_name, lab[:150]))
    # Tableau's own filter/parameter widget classes, plus anything carrying the
    # week text — one of these is the control to drive.
    for sel in (".tabComboBoxNameContainer", ".tabComboBox", ".QuickFilterBox",
                "[data-tb-test-id]", "[role='button']", "[role='combobox']"):
        try:
            loc = fr.locator(sel)
            n = loc.count()
            log("SEL| {} -> {}".format(sel, n))
            for i in range(min(n, 40)):
                try:
                    t = (loc.nth(i).inner_text(timeout=5_000) or "").strip()
                    tid = loc.nth(i).get_attribute("data-tb-test-id") or ""
                except Exception:  # noqa: BLE001
                    continue
                if t or tid:
                    log("SEL|   [{}] {!r} tid={!r}".format(
                        i, t.replace("\n", " ")[:70], tid[:50]))
        except Exception as e:  # noqa: BLE001
            log("SEL| {} failed {}".format(sel, type(e).__name__))


def _csv_view_url(view_key: str, owner: str, we: dt.date = None,
                  refresh: bool = True) -> str:
    """The DIRECT .csv endpoint for a view, owner-sliced and optionally
    week-pinned.

    This is the path att_order_log._csv_url already uses for ORDERLOG, and it is
    a different animal from the `#/site/…` viewer URL: it renders server-side
    from the query string, so it can't inherit the signed-in user's remembered
    view state — which is exactly what makes it the honest test of whether a
    filter applies at all."""
    from urllib.parse import quote
    from automations.b2b_metrics.offices import WEEK_FIELD
    base = ("https://us-east-1.online.tableau.com/t/sci/views/"
            "ATTTRACKER-B2B/{}.csv").format(view_key_to_view(view_key))
    parts = []
    if refresh:
        parts.append(":refresh=yes")
    if owner:
        parts.append("{}={}".format(quote(OWNER_FIELD),
                                    quote(_tableau_filter_value(owner), safe="\\")))
    if we is not None:
        parts.append("{}={}".format(quote(WEEK_FIELD),
                                    quote(week_value(we), safe="")))
    return base + ("?" + "&".join(parts) if parts else "")


def view_key_to_view(view_key: str) -> str:
    """The Tableau view NAME behind a registry key (the last path segment of the
    team URL, minus any saved-view GUID)."""
    from automations.b2b_metrics.offices import TEAM
    return TEAM[view_key].split("?")[0].rstrip("/").split("/")[-1]


def probe_csv(o: B2BOffice, view_key: str = "out_of_bounds",
              today: dt.date = None, log=print) -> int:
    """Fetch the view's .csv for the target week, the week the viewer insists on,
    and no week at all — then diff them.

    THE CHEAP REGRESSION TEST this codebase already trusts (rep_sales_fill): ask
    for two far-apart periods and compare. Identical output means the filter is
    inert; different output means it applies and we can build the section from
    the data instead of fighting the viewer's remembered week."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    want = report_week_ending(today)
    cases = [("no week", None), ("want {}".format(week_value(want)), want),
             ("next {}".format(week_value(want + dt.timedelta(days=7))),
              want + dt.timedelta(days=7)),
             ("prior {}".format(week_value(want - dt.timedelta(days=7))),
              want - dt.timedelta(days=7))]
    with cdp_pull._cdp_lock(label="b2b probe-csv {}".format(o.key), log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        time.sleep(20)
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(
                    "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                summary = []
                for label, we in cases:
                    url = _csv_view_url(view_key, o.owner, we)
                    log("CSV| --- {} ---".format(label))
                    log("CSV| {}".format(url))
                    try:
                        r = page.context.request.get(url, timeout=300_000)
                        body = (r.body() or b"").decode("utf-8-sig",
                                                        errors="replace")
                        status = r.status
                    except Exception as e:  # noqa: BLE001
                        log("CSV| ERROR {}".format(type(e).__name__))
                        summary.append("{}=error".format(label))
                        continue
                    lines = [l for l in body.splitlines() if l.strip()]
                    log("CSV| status={} bytes={} lines={}".format(
                        status, len(body), len(lines)))
                    for l in lines[:12]:
                        log("CSV|   " + l[:200])
                    summary.append("{}={} row(s)".format(
                        label, max(0, len(lines) - 1)))
                log("PROBECSV " + " | ".join(summary))
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            cdp_pull._kill_ours()
    return 0


def probe_week(o: B2BOffice, view_key: str = "out_of_bounds",
               today: dt.date = None, dump: bool = False, log=print) -> int:
    """Load `view_key` once per URL variant and report the week each one draws.

    Prints a one-line verdict LAST — the remote-control queue keeps only the
    tail of a log in its result cell, so a long listing is invisible from the
    laptop."""
    import re
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull
    from automations.b2b_quality.run import _IFRAME

    want = report_week_ending(today)
    variants = _week_variants(o, view_key, today)
    results = []
    with cdp_pull._cdp_lock(label="b2b probe-week {}".format(o.key), log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        try:
            with sync_playwright() as p:
                browser = None
                for attempt in range(10):
                    time.sleep(5)
                    try:
                        browser = p.chromium.connect_over_cdp(
                            "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                        break
                    except Exception:  # noqa: BLE001
                        if attempt == 9:
                            raise
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                if dump == "filters":
                    _dump_filters(page, variants[0][1], log=log)
                    variants = []
                elif dump:
                    _dump_view(page, variants[0][1], log=log)
                    variants = []
                for label, url in variants:
                    try:
                        # about:blank between variants: these are hash URLs, so
                        # the SPA can treat a query-only change as no navigation
                        # at all and quietly re-show the previous render.
                        page.goto("about:blank", wait_until="domcontentloaded",
                                  timeout=60_000)
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=120_000)
                        page.wait_for_timeout(30_000)
                        txt = page.frame_locator(_IFRAME).locator(
                            "body").inner_text(timeout=45_000) or ""
                    except Exception as e:  # noqa: BLE001
                        log("  [{}] ERROR {}".format(label, type(e).__name__))
                        results.append((label, "error"))
                        continue
                    dates = sorted(set(re.findall(
                        r"\b\d{1,2}/\d{1,2}/\d{4}\b", txt)))
                    hit = any(v in txt for v in week_value_variants(want))
                    rows = _row_summary(txt, owner=o.owner, limit=4)
                    log("  [{}] week(s) drawn: {}  -> {}  rows={}".format(
                        label, ", ".join(dates[:4]) or "none",
                        "MATCH" if hit else "no", rows))
                    results.append((label, "MATCH" if hit else
                                    (dates[0] if dates else "blank")))
                # The real captions, so a wrong guess is named rather than
                # guessed again next run.
                try:
                    fr = page.frame_locator(_IFRAME)
                    els = fr.locator("[aria-label]")
                    labs = []
                    for i in range(min(els.count(), 200)):
                        lab = els.nth(i).get_attribute("aria-label") or ""
                        if "week" in lab.lower() and lab not in labs:
                            labs.append(lab[:90])
                    log("  captions with 'week': {}".format(
                        " | ".join(labs) or "none found"))
                except Exception as e:  # noqa: BLE001
                    log("  caption read failed ({})".format(type(e).__name__))
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            cdp_pull._kill_ours()
    log("PROBE want={} -> {}".format(
        week_value(want),
        " | ".join("{}={}".format(a, b) for a, b in results)))
    return 0


def activation_board_image(o: B2BOffice, out_dir: Path, log=print) -> Path:
    """#2 Activation Rate — RECREATED full-height board (every rep), not Tableau's
    scroll-clipped Download→Image.

    Tableau renders the 'Activation Rates Owner (+/-) Rep' table in a fixed-height
    scroll zone, so the image export cuts it at the fold (Carlos: 45 reps, ~21
    shown). The zone can't be resized in the published view, so we DOWNLOAD the
    'Activation Office' crosstab (the same per-rep source vantura_churn pulls) and
    rebuild the board ourselves — every row, with Tableau's own Activation Color
    per cell so the green/yellow/red matches exactly.

    Office-parameterised: each office's per-office ACTIVATIONRATES view + owner
    prefix come from vantura_churn's _activation_cfg (carlos/atef/jamis…). An
    office with no cfg, or any pull/parse failure, FALLS BACK to the old
    Download→Image so the section still posts — logged loudly, since the fallback
    can be clipped."""
    out = out_dir / "activation_rate.png"
    try:
        import datetime as _dt
        import csv as _csv
        from automations.vantura_churn import cdp_pull as _cdp, compute as _compute
        from automations.vantura_churn import activation_rates as _ar
        from automations.vantura_churn.run import _activation_cfg
        from automations.b2b_metrics import activation_board as _ab

        cfg = _activation_cfg().get(o.key)
        if not cfg:
            raise RuntimeError("no activation cfg for office {!r}".format(o.key))
        view_url, _cv, owner_prefix = cfg
        grid_path = out_dir / "activation_office_{}.csv".format(o.key)
        totals_path = out_dir / "activation_totals_{}.csv".format(o.key)
        with _cdp._cdp_lock(label="b2b activation board {}".format(o.key), log=log):
            _cdp.download_views([(view_url, _ar.REP_SHEET, grid_path)],
                                today=_dt.date.today(), verbose=False, log=log,
                                csv_fetches=[(_ar.CSV_URL, totals_path)])
        board = _ab.parse_grid(_compute._load_grid(grid_path), owner_prefix)
        with open(totals_path, encoding="utf-8-sig", errors="replace") as fh:
            totals = list(_csv.reader(fh))
        _ab.apply_office_colors(board, totals, owner_prefix)
        _ab.set_national(board, _ab.compute_national(totals))
        _ab.render_png(board, out)
        log("   ✓ activation board [{}]: {} reps (recreated, all rows)".format(
            o.key, len(board.reps)))
        return out
    except Exception as e:  # noqa: BLE001 — must still post SOMETHING
        log("   ⚠ activation board [{}] failed ({}: {}) — falling back to "
            "Download→Image (MAY BE CLIPPED)".format(
                o.key, type(e).__name__, str(e).splitlines()[0][:120]))
        return tableau_image(o, "activation_rate", out_dir, log=log)
