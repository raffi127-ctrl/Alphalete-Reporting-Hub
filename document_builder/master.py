"""Editable "master content" for the orientation packet.

The base content lives in automations/orientation_packet/content.py. This
module exposes a set of BLOCKS an admin can edit; edits are stored as one JSON
blob on the "Document Builder Content" sheet tab and applied onto a copy of the
PAGES list at build time (via build_pdf(pages=...)).

Each block: id, label, kind, columns (for tables), get(pages)->value,
apply(pages, value). Values are always JSON-serializable (lists of strings,
lists of rows, etc.) so they round-trip through the sheet and the editor.
"""
from __future__ import annotations

import copy

from automations.orientation_packet import content as C

CONTENT_TAB = "Document Builder Content"


def _find(pages, **kw):
    for p in pages:
        if all(p.get(k) == v for k, v in kw.items()):
            return p
    raise KeyError(kw)


# --- bullet <-> line helpers (packet lines are {"t":"bullet","x":..}) -------
def _lines_to_x(lines):
    out = []
    for ln in lines:
        if ln.get("lead"):
            out.append(f'{ln["lead"]} {ln["x"]}')
        else:
            out.append(ln["x"])
    return out


def _x_to_bullets(values):
    out = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        out.append({"t": "bullet", "x": v})
    return out


# --- core steps <-> flat text ----------------------------------------------
def _steps_get(pages):
    """Each step -> {'title':..., 'text': multiline bullets ('  ' = sub)}."""
    steps = _find(pages, type="framework")["steps"]
    out = []
    for title, bullets in steps:
        lines = []
        for b in bullets:
            if isinstance(b, dict):
                lines.append(b["b"])
                for s in b.get("sub", []):
                    lines.append("  " + s)
            else:
                lines.append(b)
        out.append([title, "\n".join(lines)])
    return out


def _steps_apply(pages, value):
    steps = []
    for row in value:
        if not row or not (row[0] or "").strip():
            continue
        title = row[0].strip()
        bullets = []
        for raw in (row[1] or "").splitlines():
            if not raw.strip():
                continue
            if raw.startswith("  ") and bullets:      # sub-bullet
                prev = bullets[-1]
                if isinstance(prev, str):
                    bullets[-1] = {"b": prev, "sub": [raw.strip()]}
                else:
                    prev.setdefault("sub", []).append(raw.strip())
            else:
                bullets.append(raw.strip())
        steps.append((title, bullets))
    _find(pages, type="framework")["steps"] = steps


# --- generic paytable-table access (handles the 5 commission charts) --------
def _tbl(pages, subtitle, heading, tindex=0):
    """The table dict for a given commission page/section (by label, not
    index — templates move)."""
    page = _find(pages, type="paytable", subtitle=subtitle)
    for blk in page["blocks"]:
        if blk.get("kind") == "tables" and blk.get("heading") == heading:
            return blk["tables"][tindex]
    raise KeyError((subtitle, heading, tindex))


def _tbl_get(pages, subtitle, heading, cols, tindex=0):
    """Rows padded to the column count so they fit an editable grid."""
    n = len(cols)
    t = _tbl(pages, subtitle, heading, tindex)
    return [(list(r) + [""] * n)[:n] for r in t["rows"]]


def _tbl_apply(pages, subtitle, heading, value, tindex=0):
    """Write rows back; trailing blank cells are dropped so a short row still
    renders as a single value spanning the remaining columns (matches the
    original layout, e.g. '1 GIG + Auto Bill Pay … $150')."""
    t = _tbl(pages, subtitle, heading, tindex)
    rows = []
    for r in value:
        if not r or not str(r[0]).strip():
            continue
        cells = ["" if v is None else str(v) for v in r]
        while len(cells) > 1 and cells[-1] == "":
            cells.pop()
        rows.append(cells)
    t["rows"] = rows


def _tbl_block(bid, label, subtitle, heading, cols, tindex=0):
    """A commission-table BLOCK entry (also flagged group='commission' so the
    per-office Advanced options on the builder can surface it). `tindex` picks
    which table when a section holds two side-by-side (page 9)."""
    return {"id": bid, "label": label, "kind": "table", "group": "commission",
            "columns": cols,
            "get": (lambda p, s=subtitle, h=heading, c=cols, ti=tindex:
                    _tbl_get(p, s, h, c, ti)),
            "apply": (lambda p, v, s=subtitle, h=heading, ti=tindex:
                      _tbl_apply(p, s, h, v, ti))}


_TRAIN = "1st Two Weeks · Training Pay"      # page 9 paytable subtitle
_RATE = "Rate Card"                          # page 10 paytable subtitle
_WK3 = "WEEK 3+ — FULL BONUSES + COMMISSIONS"

BLOCKS = [
    {"id": "welcome_letter", "label": "Welcome letter (page 1)",
     "kind": "paragraphs",
     "get": lambda p: list(_find(p, type="cover")["letter"]),
     "apply": lambda p, v: _find(p, type="cover").__setitem__(
         "letter", [s.strip() for s in v if s.strip()])},

    {"id": "stats", "label": "30-day boot camp stats (page 2)", "kind": "table",
     "columns": ["Big", "Label"],
     "get": lambda p: [[s["big"], s["label"]]
                       for s in _find(p, type="splash")["stats"]],
     "apply": lambda p, v: _find(p, type="splash").__setitem__(
         "stats", [{"big": r[0], "label": r[1]} for r in v if r and r[0]])},

    {"id": "booklist", "label": "Book list (page 6)", "kind": "table",
     "columns": ["Title", "Author"],
     "get": lambda p: [list(t) for t in _find(p, type="booklist")["books"]],
     "apply": lambda p, v: _find(p, type="booklist").__setitem__(
         "books", [(r[0], r[1]) for r in v if r and r[0]])},

    {"id": "core_steps", "label": "9 Core Steps (page 8)", "kind": "steps",
     "columns": ["Step title", "Bullets (indent 2 spaces = sub-bullet)"],
     "get": _steps_get, "apply": _steps_apply},

    # --- the 5 commission charts (pages 9 + 10) ----------------------------
    _tbl_block("commission_int_only",
               "Commission — Training pay: INT only (page 9)",
               _TRAIN, _WK3, ["Examples", "Per Sale", "Payout"]),
    _tbl_block("commission_int_lines",
               "Commission — Training pay: INT + 5 new lines (page 9)",
               _TRAIN, _WK3, ["Examples", "Breakdown", "Payout"], tindex=1),
    _tbl_block("commission_rate",
               "Commission — AT&T INT Fiber rate card (page 10)",
               _RATE, "AT&T INT FIBER",
               ["ATT INT Fiber", "With ABP", "No ABP", "Owner Pay"]),
    _tbl_block("commission_dtv",
               "Commission — DTV Stream (page 10)",
               _RATE, "DTV STREAM", ["DTV Stream", "Commission"]),
    _tbl_block("commission_new_lines",
               "Commission — New lines (page 10)",
               _RATE, "NEW LINES",
               ["New Lines", "With Next Up", "No Next Up",
                "Bonus · 5 new INTs same week"]),

    {"id": "seasonal_always", "label": "Seasonal — Always bring (page 15)",
     "kind": "lines",
     "get": lambda p: list(_find(p, type="seasonal")["always"]["items"]),
     "apply": lambda p, v: _find(p, type="seasonal")["always"].__setitem__(
         "items", [s.strip() for s in v if s.strip()])},

    {"id": "seasonal_summer", "label": "Seasonal — Summer (page 15)",
     "kind": "lines",
     "get": lambda p: _lines_to_x(_find(p, type="seasonal")["cards"][0]
                                  ["lines"]),
     "apply": lambda p, v: _find(p, type="seasonal")["cards"][0].__setitem__(
         "lines", _x_to_bullets(v))},

    {"id": "seasonal_winter", "label": "Seasonal — Winter (page 15)",
     "kind": "lines",
     "get": lambda p: _lines_to_x(_find(p, type="seasonal")["cards"][1]
                                  ["lines"]),
     "apply": lambda p, v: _find(p, type="seasonal")["cards"][1].__setitem__(
         "lines", _x_to_bullets(v))},

    {"id": "dress_office_men", "label": "Dress code — Men (page 13)",
     "kind": "lines",
     "get": lambda p: _lines_to_x(_find(p, type="dresscode",
                                        subtitle="OFFICE UNIFORM")
                                  ["cards"][0]["lines"]),
     "apply": lambda p, v: _find(p, type="dresscode",
                                 subtitle="OFFICE UNIFORM")["cards"][0]
     .__setitem__("lines", _x_to_bullets(v))},

    {"id": "dress_office_women", "label": "Dress code — Women (page 13)",
     "kind": "lines",
     "get": lambda p: _lines_to_x(_find(p, type="dresscode",
                                        subtitle="OFFICE UNIFORM")
                                  ["cards"][1]["lines"]),
     "apply": lambda p, v: _find(p, type="dresscode",
                                 subtitle="OFFICE UNIFORM")["cards"][1]
     .__setitem__("lines", _x_to_bullets(v))},
]

_BY_ID = {b["id"]: b for b in BLOCKS}


def defaults() -> dict:
    """The base value of every block, read from content.py."""
    return {b["id"]: b["get"](C.PAGES) for b in BLOCKS}


def apply_overrides(pages, overrides):
    """Return a copy of `pages` with the given overrides applied."""
    if not overrides:
        return pages
    pages = copy.deepcopy(pages)
    for k, v in overrides.items():
        b = _BY_ID.get(k)
        if b and v is not None:
            try:
                b["apply"](pages, v)
            except Exception:                        # noqa: BLE001
                pass                                 # bad override → keep base
    return pages
