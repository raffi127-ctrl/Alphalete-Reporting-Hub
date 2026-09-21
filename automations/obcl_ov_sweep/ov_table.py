"""Read OwnerVille's Onboard → View Progress table — every rep, one page.

Megan's screenshot 2026-09-21 (Marqoun Holland): each step column holds a pill
plus a date stamp —
    done        green ✓ pill + "09/21/26 11:00 AM"
    UID         green "Requested" pill + date
    in flight   yellow "Pending", no date
    not done    red ✗ (per the 8/25 walkthrough) or, for Owner Submit, BLANK

So "done" = the cell carries a date stamp and is neither Pending nor red.
The date is the load-bearing part: `_photo_pill` in headshots is the standing
warning that ✓ and ✗ pills can render the same inner_text, and a date only
appears once OwnerVille has recorded the step.
"""
from __future__ import annotations

import re
from typing import Dict, List

from automations.obcl_ov_sweep import config

DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
# Markup that means a red / not-done pill. Checked on the cell's HTML because
# the text alone cannot tell ✓ from ✗.
RED_MARKERS = ("danger", "bg-red", "text-red", "fa-times", "fa-xmark",
               "fa-x ", "badge-error", "btn-danger")

# OBCL column -> the View Progress headers that must ALL be done.
# Headers are matched case/space-insensitively and by prefix, so
# "AT&T Compliance – 2023" survives the dash spelling.
TABLE_COLUMNS = {
    "Digi Docs": ("onboarding documents",),
    "Onboarding Quizzes": ("ftc directv compliance training",
                           "at&t protective advantage course",
                           "at&t broadband facts",
                           "at&t protecting cpni",
                           "at&t compliance",
                           "2024 consent decree"),
    "UID Request": ("at&t uid request",),
    "Owner Submit": ("owner submit",),
}

# Everything OwnerVille needs before an owner can submit (Megan 2026-09-21:
# "for someone to be owner submitted, they must have all the other things
# completed"). The View Progress columns left of Owner Submit. Supplement is
# left out: it was blank on Marqoun Holland's otherwise-finished row, so it is
# not a step every rep gets. Badge / SARA Plus come AFTER the submit.
READY_FOR_OWNER_SUBMIT = (
    "login created", "onboarding documents", "background check", "drug test",
    *TABLE_COLUMNS["Onboarding Quizzes"],
    "upload documents", "at&t uid request", "service",
)


def _h(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip().lower()


def cell_done(text: str, html: str = "") -> bool:
    t = (text or "").lower()
    if "pending" in t or not DATE_RE.search(t):
        return False
    h = (html or "").lower()
    return not any(m in h for m in RED_MARKERS)


def cell_filled(text: str, html: str = "") -> bool:
    """Looser than cell_done, for the readiness check only: Upload Documents
    shows a green "✓ Photo" pill with NO date, so a date cannot be required.
    Filled, not Pending, not red."""
    t = (text or "").strip().lower()
    if not t or "pending" in t:
        return False
    h = (html or "").lower()
    return not any(m in h for m in RED_MARKERS)


# The only readiness column judged without a date ("✓ Photo" carries none).
# Everything else — BACKGROUND CHECK above all — must be green WITH a date:
# nobody can be owner-submitted without a PASSED background check (Megan
# 2026-09-21), and a Pending / red / undated BG cell is not a pass.
_NO_DATE_OK = ("upload documents",)


def ready_for_owner_submit(headers: List[str], cells: List[dict]):
    """True when every step before Owner Submit is green; None if a header is
    missing (unread — never paint on a guess)."""
    for w in READY_FOR_OWNER_SUBMIT:
        i = header_index(headers, w)
        if i is None or i >= len(cells):
            return None
        judge = cell_filled if w in _NO_DATE_OK else cell_done
        if not judge(cells[i].get("text", ""), cells[i].get("html", "")):
            return False
    return True


def header_index(headers: List[str], want: str):
    hs = [_h(x) for x in headers]
    for i, h in enumerate(hs):
        if h == want:
            return i
    for i, h in enumerate(hs):
        if h.startswith(want):
            return i
    return None


def done_columns(headers: List[str], cells: List[dict]) -> Dict[str, object]:
    """{OBCL column: True/False, or None when a header is missing}.

    `cells` = [{"text":..., "html":...}] in table order."""
    out: Dict[str, object] = {}
    for col, wants in TABLE_COLUMNS.items():
        ok = True
        for w in wants:
            i = header_index(headers, w)
            if i is None or i >= len(cells):
                ok = None
                break
            if not cell_done(cells[i].get("text", ""), cells[i].get("html", "")):
                ok = False
        out[col] = ok
    return out


# One evaluate for the whole table: 100+ rows x 20 cells as locator calls is
# thousands of round trips.
# VISIBLE table only: the page carries hidden copies, and reading those is the
# 2026-09-21 "read 24, table says 144" under-read (digi_docs_roster_probe).
_READ_JS = """() => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  const tables = [...document.querySelectorAll('table')].filter(vis);
  const t = tables.sort((a, b) =>
    b.querySelectorAll('tbody tr').length - a.querySelectorAll('tbody tr').length)[0];
  if (!t) return {heads: [], rows: []};
  const heads = [...t.querySelectorAll('thead th')].map(th => th.innerText);
  const rows = [...t.querySelectorAll('tbody tr')].map(tr =>
    [...tr.querySelectorAll('td')].map(td => ({
      text: td.innerText,
      html: td.innerHTML.slice(0, 600)})));
  const box = t.closest('.dataTables_wrapper');
  const info = box ? (box.querySelector('.dataTables_info') || {}).innerText : '';
  return {heads, rows, info: info || ''};
}"""


def read_table(page, *, verbose: bool = True) -> tuple:
    """(headers, {ov name: cells}, complete). RES-AT&T, Show All, every entry.

    `complete` compares what we read against DataTables' own "of N entries"
    (digi_docs.ownerville.snapshot's lesson: page sizes are not rosters). A
    person missing from an incomplete read is "not read", never "not done".
    """
    from automations.b2b_dispositions.capture import capture_rqst
    from automations.digi_docs import ownerville as dov
    from automations.headshots.ov_upload import (
        VIEW_PROGRESS_P, _campaign_select, _show_all)

    rqst = capture_rqst(page)
    page.set_default_navigation_timeout(90000)
    page.goto(f"https://v2.ownerville.com/index.cfm?p={VIEW_PROGRESS_P}"
              f"&rqst={rqst}", wait_until="domcontentloaded")
    _settle(page)
    _campaign_select(page).select_option(label=config.CAMPAIGN)
    _settle(page)
    _show_all(page)
    _settle(page)
    _largest_page_length(page) or dov._show_all_entries(page)
    _settle(page)

    got = page.evaluate(_READ_JS)
    heads = got.get("heads") or []
    reps: Dict[str, list] = {}
    _collect(got, heads, reps)
    m = re.search(r"of\s+([\d,]+)\s+entries", got.get("info") or "", re.I)
    claimed = int(m.group(1).replace(",", "")) if m else dov._entries_total(page)
    complete = claimed is None or len(reps) >= claimed
    if verbose:
        print(f"  View Progress ({config.CAMPAIGN}, Show All): read "
              f"{len(reps)}, table says {claimed if claimed is not None else '?'}"
              f"{'' if complete else '  ⛔ INCOMPLETE'}", flush=True)
    return heads, reps, complete


def _collect(got: dict, heads: List[str], reps: Dict[str, list]) -> int:
    """Add each table row to reps under its OV name. Returns rows added."""
    name_i = header_index(heads, "name")
    added = 0
    for cells in got.get("rows") or []:
        if name_i is None or name_i >= len(cells):
            continue
        # Name cell reads "Marqoun Holland\n(9502292)\nEdit\nAction".
        first_line = (cells[name_i].get("text") or "").strip().split("\n")[0]
        if first_line and "no data" not in first_line.lower():
            if first_line.strip() not in reps:
                added += 1
            reps.setdefault(first_line.strip(), cells)
    return added


def search_fill(page, heads: List[str], reps: Dict[str, list],
                surnames: List[str], *, verbose: bool = True) -> int:
    """Look up each surname through DataTables' search box and add whatever
    rows it shows. The fallback for when the one-page read comes up short
    (Lucy 3, 2026-09-21: 50 of 58 "not found" — the table never left page 1).
    Search filters client-side, so the person's row is on page 1 by
    construction; this is the same box headshots' find_rep has used daily."""
    box = page.locator("input[type='search']:visible").first
    box.wait_for(state="visible", timeout=20000)
    found = 0
    for term in surnames:
        try:
            box.fill("")
            box.press_sequentially(term, delay=25)
            page.wait_for_timeout(1500)
            got = page.evaluate(_READ_JS)
            if not heads:
                heads[:] = got.get("heads") or []
            found += _collect(got, heads, reps)
        except Exception as e:                              # noqa: BLE001
            if verbose:
                print(f"    search {term!r} failed: {type(e).__name__}")
    try:
        box.fill("")
    except Exception:                                       # noqa: BLE001
        pass
    if verbose:
        print(f"  search fallback: {len(surnames)} surname(s) looked up, "
              f"{found} more row(s) read", flush=True)
    return found


def _largest_page_length(page) -> int:
    """Set the VISIBLE DataTables length menu to its biggest option ("All" is
    -1). digi_docs' _show_all_entries takes `.first` without :visible, which
    can resize a hidden table and leave the real one at 25 rows."""
    sel = page.locator("div.dataTables_length select:visible, "
                       "div[id$='_length'] select:visible, "
                       "select[name$='_length']:visible").first
    try:
        if not sel.count():
            return 0
        vals = sel.evaluate("el => [...el.options].map(o => o.value)")
    except Exception:                                       # noqa: BLE001
        return 0

    def size(v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return 10 ** 9 if n < 0 else n

    best = max(range(len(vals)), key=lambda i: size(vals[i]), default=None)
    if best is None or size(vals[best]) <= 0:
        return 0
    try:
        sel.select_option(index=best)
    except Exception:                                       # noqa: BLE001
        return 0
    page.wait_for_timeout(1500)
    return size(vals[best])


def _settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                                       # noqa: BLE001
        pass
    page.wait_for_timeout(800)
