"""Per-captain configuration for the 12 Captainship Report drafts.

12 drafts in 4 flavors (roster + brand colors confirmed by Eve 2026-07-17):
  rafael  (1) — Raf's Captainship: NI churn + Wireless churn
  fiber   (5) — Wayne / Starr / Chan / Tony / Sahil: 10 sections (see below)
  b2b     (3) — Carlos / Eveliz / Luis: NI churn (5 buckets, incl 120)
  nds     (3) — Khalil / Colten / Jairo: NI churn

Section layout is declared TWICE, index-aligned: _INTRO holds the wording the
reader sees (Eve's list, emoji and all) and SECTION_KINDS says what each of
those lines renders. Adding a section means adding one line to BOTH.

Where each kind comes from:
  product_summary / units      sales_board.py + sheet_shot.py (Sales Board)
  fiber_activation             fiber_png.py (the daily Fiber Activations PNG)
  cancel_tableau / teamstats_  tableau_shot.py (rafael / b2b / nds only)
  churn_ni / churn_wireless    churn_images.py over the churn render engines
  box:<slot>                   box_images.py + daily_box_render.py — the
                               one-column-per-day boxes the cancel-rate,
                               activation-rate and ABP/6-days runs fill
  knock_dispo                  knock_dispo_images.py — one Weekly Knock
                               Dispositions board per OWNER in the captainship
                               (weekly_knock_dispositions reused as a library;
                               rafael-only for now — add the kind + intro line
                               to another flavor and it joins, nothing else).
                               SUN+MON only — see SECTION_DAYS.
  daily_knocks                 knock_dispo_images.py too — YESTERDAY's combined
                               Total Knocks board per owner, with a captainship
                               summary (Chan comparison row) first. Every day.

Churn sources reference the EXISTING open_ws_* helpers + tab constants so
tab names are never hardcoded (and we don't trip on the en-dash/hyphen
mismatch in the spec — the real tabs use a hyphen).
"""
from __future__ import annotations

import datetime as dt
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Tuple

from automations.captainship_churn import fill as _cap
from automations.owners_metrics_churn import fill as _own
from automations.new_internet_churn import render as _ni_render
from automations.wireless_churn import render as _wl_render

# Bucket render order. B2B tabs carry a 5th (120); the others stop at 90.
# render_all_sections only emits sections it actually finds, so listing
# 120 here is harmless for the 4-bucket captains.
BUCKET_ORDER = ("0-30", "30", "60", "90", "120")

# Body intros, verbatim per the spec. rafael/fiber greet "Hello, team!";
# b2b/nds greet "Hi, team!". Rendered as an ordered list in the email.
_INTRO = {
    # Rafael went from 4 sections to 9 on 2026-07-30 (Eve's list, verbatim
    # including the emoji). Like the fiber drafts, the Tableau Cancel-Rates shot
    # is replaced by the two cancel-rate BOXES we now fill daily, and four more
    # boxes join: ABP % (his 'Captainship - ABP' tab, NOT the local-office one),
    # activation 0-30 / 30-60 and
    # 6+ days out. His order differs from fiber's — churn sits between the
    # cancel rates and the ABP block — so the two lists are kept separate
    # rather than shared.
    "rafael": ("Hello, team! Below you'll find:", [
        "Product Summaries Of Sales 💰",
        "New Int 0-30 Day Cancel Rate ⚠️",
        "New Int 30-60 Day Cancel Rate 🚨",
        "New Internet Ongoing Churn Metrics 🌐",
        "Wireless Ongoing Churn Metrics 🛜",
        "ABP % Ongoing Report 💳",
        "0-30 Day Ongoing Activation Rate ▶️",
        "30-60 Day Ongoing Activation Rate 🚀",
        "Ongoing 6+ Days Sales Rate 🤝🏻",
        # 2026-08-23 evening (Raf's Slack: "add the daily knocks to everyones
        # captainship emails … and have Chan's comparison in there"): the
        # daily combined knocks board, once per owner, EVERY day — a daily
        # overall summary first (teal Chan comparison row), then each ICD
        # broken out below it (Megan). Index-aligned with "daily_knocks" in
        # SECTION_KINDS["rafael"] below.
        "Daily Knocks (per owner) 🚪",
        # 2026-08-23 (Raf's Loom): the Sunday per-rep knock board, once per
        # owner in his captainship. Stays index-aligned with the
        # "knock_dispo" kind appended to SECTION_KINDS["rafael"] below.
        # SUN+MON ONLY (SECTION_DAYS): Tue–Sat this line AND its section
        # disappear from the email entirely.
        "Weekly Knock Dispositions (per owner) 🚪",
    ]),
    # Fiber went from 4 sections to 10 on 2026-07-29 (Eve's list, verbatim
    # including the emoji): the Tableau Cancel-Rates shot is replaced by the
    # two cancel-rate BOXES we now fill daily, Wireless churn joins, and the
    # four new metric boxes (ABP, activation 0-30 / 30-60, 6+ days) close it.
    "fiber": ("Hello, team! Below you'll find:", [
        "Product Summaries Of Sales 💰",
        "Captainship Fiber Activations ✅",
        "New Int 0-30 Day Cancel Rate ⚠️",
        "New Int 30-60 Day Cancel Rate 🚨",
        "New Internet Ongoing Churn Metrics 🌐",
        "Wireless Ongoing Churn Metrics 🛜",
        "ABP % Ongoing Report 💳",
        "0-30 Day Ongoing Activation Rate ▶️",
        "30-60 Day Ongoing Activation Rate 🚀",
        "Ongoing 6+ Days Sales Rate 🤝🏻",
        # LOS DOS BLOQUES DE KNOCKS VOLVIERON AL FLAVOR FIBER (Eve 2026-08-25),
        # ahora con COBERTURA PARCIAL explícita. Historia corta: entraron el
        # 23/8, salieron el 24/8 porque 16 de los 35 ICDs de estas cinco
        # capitanías no estaban en el Office Access de la cuenta del reporte
        # (rhidalgo) y cada uno pintaba una caja AMARILLA que frena el envío
        # del reporte entero (run.py, guard 2). El 25/8 Eve pidió el acceso
        # para esos 16 y decidió no esperar a tenerlos todos: "construí los
        # reportes con las oficinas que ya tenemos y andá agregando a medida
        # que nos otorgan acceso".
        # Lo que hace viable el parcial son dos cosas, las dos ya en el
        # código y ninguna con lista de oficinas que mantener:
        #   * un ICD sin acceso NO va al correo (Eve 2026-08-25: "esas 12
        #     oficinas no las vamos a incluir por ahora aunque hayamos pedido
        #     los accesos"). knock_dispo_images.is_access_gap lo detecta y lo
        #     saca de la lista; queda en el LOG y en el rótulo de los totales.
        #     Si NINGUNA oficina de la capitanía es alcanzable, la sección sale
        #     como una nota GRIS que lo dice — nunca la amarilla, que llevaría
        #     PENDING_MARK y retendría el correo entero de ese capitán;
        #   * los boards se arman sobre el roster del Org Sales Board, así que
        #     el día que ownerville otorga una oficina la impersonación deja de
        #     fallar y ese ICD aparece solo — no hay allowlist que tocar. El
        #     rótulo "(N of M ICDs)" de la fila de totales es lo que impide
        #     leer un total parcial como si fuera el de la capitanía entera.
        # Quién sigue el goteo de accesos: automations/knocks_access_watch.
        "Daily Knocks (per owner) 🚪",
        # SUN+MON ONLY, igual que en el de Rafael (SECTION_DAYS): de martes a
        # sábado esta línea Y su sección desaparecen del correo.
        "Weekly Knock Dispositions (per owner) 🚪",
    ]),
    # B2B churn switched to WIRELESS 2026-08-19 (Eve) — the four B2B tabs are
    # filled from the wireless slice of CHURNRATES now, so the section title and
    # the churn blocks below say Wireless. NDS still reports New Internet.
    "b2b": ("Hi, team! Below you'll find:", [
        "Product Summary Of Sales",
        "⚠️Captain Team Stats Breakout ⚠️",
        "💰Wireless Ongoing Churn Metrics 💰",
    ]),
    "nds": ("Hi, team! Below you'll find:", [
        "Product Summary Of Sales",
        "⚠️Captain Team Stats Breakout ⚠️",
        "💰New Internet Ongoing Churn Metrics 💰",
    ]),
}


# Ordered content-kind per section, index-aligned to each flavor's _INTRO
# item list. email_build renders each kind from the image bundle:
#   product_summary   -> §1: PS screenshot + "CAPTAINSHIP UNITS:" + unit charts
#   fiber_activation   -> the daily Fiber Activations PNG for this captain
#   cancel_tableau     -> Tableau Cancel-Rates shot (filtered to this team)
#   teamstats_tableau  -> Tableau Captain Team Stats Breakout shot (this person)
#   churn_ni / churn_wireless -> the rendered churn bucket images
#   box:<slot>         -> a one-column-per-day metrics box (see BOX_SOURCES),
#                         rendered by box_images/daily_box_render
#   knock_dispo        -> per-owner Weekly Knock Dispositions boards
#                         (knock_dispo_images.py) — sub-heading + board PNG per
#                         owner in the captainship. Scope another flavor in by
#                         adding this kind (+ its intro line) to that flavor.
#   daily_knocks       -> per-owner DAILY combined knocks boards + captainship
#                         summary (knock_dispo_images.py again) — same
#                         sub-heading + PNG shape as knock_dispo.
# Where every section's images land, shared by the capture step and the build
# so a build can REUSE what the capture already pulled (knock_dispo_images'
# manifest). Stable across runs on a machine and swept by the OS, never by us:
# an image is a rebuildable artifact, and the manifest refuses any entry whose
# file is gone.
RENDER_DIR = Path(tempfile.gettempdir()) / "captainship_drafts_render"


SECTION_KINDS = {
    "rafael": ["product_summary",
               "box:cancel-0-30", "box:cancel-30-60",
               "churn_ni", "churn_wireless",
               "box:abp", "box:activation-0-30", "box:activation-30-60",
               "box:six-days",
               "daily_knocks", "knock_dispo"],
    # daily_knocks + knock_dispo joined fiber 2026-08-23 (Megan: Raf's
    # captains ARE the fiber flavor). NOT b2b/nds: their offices knock other
    # campaigns / wireless-shaped disposition tables, so the fiber knock
    # scrape doesn't fit them yet — scope them in here (+ intro lines) once
    # their shapes are handled.
    # daily_knocks + knock_dispo VOLVIERON 2026-08-25 con cobertura parcial —
    # ver el comentario largo en _INTRO["fiber"]. Índice-alineados con las dos
    # últimas líneas de ese intro, en el mismo orden que en "rafael".
    "fiber":  ["product_summary", "fiber_activation",
               "box:cancel-0-30", "box:cancel-30-60",
               "churn_ni", "churn_wireless",
               "box:abp", "box:activation-0-30", "box:activation-30-60",
               "box:six-days",
               "daily_knocks", "knock_dispo"],
    # churn_WIRELESS since 2026-08-19: the four B2B tabs are filled from the
    # wireless slice now, so render_captain labels their buckets "Wireless
    # Churn" and run.py sorts them into churn_wireless. Leaving this at
    # churn_ni asked for a list that is now always empty, and the section
    # fell back to the "could not be captured" note in all four B2B drafts
    # while the images sat rendered on disk (Eve 2026-08-19).
    "b2b":    ["product_summary", "teamstats_tableau", "churn_wireless"],
    "nds":    ["product_summary", "teamstats_tableau", "churn_ni"],
}


# Which WEEKDAYS a section kind builds on (date.weekday(): Mon=0 … Sun=6).
# A kind absent here runs every day — every pre-existing section is absent, so
# every other flavor and day is untouched by this table existing.
#
# knock_dispo is SUN+MON only (Raf 2026-08-23: "Monday should re duplicate
# sundays post so I can see it again in the email and use it one on ones").
# Both days resolve to the SAME completed Mon–Sat week — knock_dispo_images
# .week_window anchors on yesterday's completed week — so Monday's boards are
# a true re-show of Sunday's, never the new week's empty one. On the other
# five days the section vanishes from the draft entirely: no heading, no
# pending note, no intro bullet (Captain.sections_on drops the pair before
# either the capture or the email builder ever sees it).
SECTION_DAYS = {
    "knock_dispo": (6, 0),     # Sunday + Monday
}


def kind_runs_on(kind: str, today: "dt.date") -> bool:
    """Does section `kind` build on `today`? True unless SECTION_DAYS says
    that weekday is off."""
    days = SECTION_DAYS.get(kind)
    return days is None or today.weekday() in days


@dataclass(frozen=True)
class ChurnSource:
    """One block of churn images: a worksheet + which render module draws
    it + a label prefix shown above each bucket image in the email."""
    open_ws: Callable          # () -> gspread Worksheet
    render_mod: object         # new_internet_churn.render or wireless_churn.render
    label: str                 # e.g. "New Internet Churn" / "Wireless Churn"
    brand_title: bool = True   # paint the title bar in the captain's brand
                               # color; False keeps the render's own default
                               # (e.g. Rafael's Wireless stays the std blue)
    title_prefix: str = ""     # override the words in the title bar, e.g.
                               # "WIRELESS CHURN" -> "WIRELESS CHURN - 30 DAY".
                               # Use when the DATA changed product but the block
                               # keeps its renderer: the B2B tabs went wireless
                               # 2026-08-19 and must keep the owner-colored
                               # New Internet look (Eve). Empty = the render
                               # module's own title.


@dataclass(frozen=True)
class BoxSource:
    """One ONE-COLUMN-PER-DAY metrics box, rendered by box_images.

    These are the boxes the daily cancel-rate / activation-rate / ABP+6-days
    runs fill. All three fill modules return the same section dict shape
    (header_row / office_avg_row / rep_header_row / rep_rows), which is why one
    renderer covers all six sections."""
    open_ws: Callable          # () -> gspread Worksheet
    find: Callable             # ws -> {box key: section dict}
    box: str                   # which box on that tab
    title: str                 # title-bar text inside the image
    slot: str                  # matches the 'box:<slot>' kind + the cid slot
    cache_key: str             # boxes sharing a tab share this, so the
                               # worksheet is opened once per captain
    col_step: int = 1          # sheet columns per DAY: 1 on the fiber tabs
                               # (% only), 2 on Rafael's and the ABP tab, whose
                               # day is a %+units pair with the date merged
                               # across it
    avg_label: str = "Captainship Avg"   # the roll-up row's name in the image;
                               # the local-office ABP tab says 'Office Avg'


def _fiber_boxes(slug: str) -> List[BoxSource]:
    """The six metric boxes on a fiber captain's three tabs.

    Imported lazily inside the function so `config` stays importable even if
    one of the newer report modules is mid-refactor — a broken import here
    would take all 12 drafts down, not just six sections."""
    from functools import partial
    from automations.captainship_cancel_rate import fill as _cx, captains as _cxc
    from automations.captainship_activation_rate import fill as _ax
    from automations.captainship_abp_6days import fill as _bx

    cancel_tab = _cxc.BY_SLUG[slug].tab
    return [
        BoxSource(partial(_cx.open_ws, cancel_tab), _cx.find_sections, "0-30",
                  "NEW INT 0-30 DAY CANCEL RATE", "cancel-0-30", "cancel"),
        BoxSource(partial(_cx.open_ws, cancel_tab), _cx.find_sections, "30-60",
                  "NEW INT 30-60 DAY CANCEL RATE", "cancel-30-60", "cancel"),
        BoxSource(partial(_ax.open_ws, slug), _ax.find_boxes, "0-30",
                  "0-30 DAY ONGOING ACTIVATION RATE", "activation-0-30", "activation"),
        BoxSource(partial(_ax.open_ws, slug), _ax.find_boxes, "30-60",
                  "30-60 DAY ONGOING ACTIVATION RATE", "activation-30-60", "activation"),
        BoxSource(partial(_bx.open_ws, slug), _bx.find_boxes, "abp",
                  "ABP % ONGOING REPORT", "abp", "abp"),
        BoxSource(partial(_bx.open_ws, slug), _bx.find_boxes, "6days",
                  "ONGOING 6+ DAYS SALES RATE", "six-days", "abp"),
    ]


# Rafael's reports do NOT share the fiber captains' workbooks — his whole report
# is its own Sheet (Eve, 2026-07-30), and the same six boxes are spread over
# FOUR separate tabs instead of the fiber layout's three shared ones. So he gets
# his own builder rather than a slug passed to _fiber_boxes.
RAFAEL_SHEET_ID = "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8"

RAFAEL_TABS = {
    "cancel":     "Captainship - Cancel Rate",      # both 0-30 and 30-60 boxes
    "activation": "Captainship - Activation Rate",  # both 0-30 and 30-60 boxes
    # ABP is his CAPTAINSHIP's, not his local office's (Eve, 2026-07-30). The
    # office tab was the wrong 145-person population for a captainship email —
    # right metric, wrong people. Eve split ABP and 6-days-out onto one tab
    # each so neither report has to live with the other's merged cells.
    "abp":        "Captainship - ABP",
    "six_days":   "Captainship - 6 days out",
}


def _raf_ws(tab: str):
    """Open one tab of Rafael's own workbook. Lazy for the same reason
    _fiber_boxes is lazy."""
    from automations.new_internet_churn import fill as _shared
    return _shared.open_by_key(RAFAEL_SHEET_ID).worksheet(tab)


def _rafael_boxes() -> List[BoxSource]:
    """Rafael's six metric boxes, across the four tabs of his own Sheet.

    The FINDERS are the fiber ones unchanged: his tabs carry the identical box
    shape, verified live 2026-07-30 (cancel and activation each return 0-30 and
    30-60; the ABP and 6-days tabs one box each). So this is a different address
    for the same structure, not a second renderer.

    ABP is his CAPTAINSHIP's, off 'Captainship - ABP' (Eve, 2026-07-30) — NOT
    'Local Office - New Internet ABP%' in the same workbook, which is a
    different report (automations.new_internet_abp, ~96 office reps against ~15
    ICD owners here) and must not be what this draft shows.

    Cancel / activation / 6-days-out use captainship_raf_metrics' finder rather
    than the fiber one: it reports the tab's LAYOUT (a %-only column or a
    %+units pair) alongside the rows, and these tabs have flipped between the
    two. ABP keeps the fiber finder, because captainship_abp_6days is what
    fills that tab."""
    from functools import partial
    from automations.captainship_abp_6days import fill as _bx
    from automations.captainship_raf_metrics import fill as _rx

    # cache_key is per TAB: unlike the fiber layout, only the two cancel boxes
    # and the two activation boxes share a worksheet here.
    return [
        BoxSource(partial(_raf_ws, RAFAEL_TABS["cancel"]), _rx.find_boxes,
                  "0-30", "NEW INT 0-30 DAY CANCEL RATE", "cancel-0-30",
                  "raf-cancel"),
        BoxSource(partial(_raf_ws, RAFAEL_TABS["cancel"]), _rx.find_boxes,
                  "30-60", "NEW INT 30-60 DAY CANCEL RATE", "cancel-30-60",
                  "raf-cancel"),
        BoxSource(partial(_raf_ws, RAFAEL_TABS["activation"]), _rx.find_boxes,
                  "0-30", "0-30 DAY ONGOING ACTIVATION RATE", "activation-0-30",
                  "raf-activation"),
        BoxSource(partial(_raf_ws, RAFAEL_TABS["activation"]), _rx.find_boxes,
                  "30-60", "30-60 DAY ONGOING ACTIVATION RATE",
                  "activation-30-60", "raf-activation"),
        BoxSource(partial(_raf_ws, RAFAEL_TABS["abp"]), _bx.find_boxes, "abp",
                  "ABP % ONGOING REPORT", "abp", "raf-abp"),
        BoxSource(partial(_raf_ws, RAFAEL_TABS["six_days"]), _rx.find_boxes,
                  "6days", "ONGOING 6+ DAYS SALES RATE", "six-days",
                  "raf-six-days"),
    ]


@dataclass(frozen=True)
class Captain:
    key: str                   # slug for --only + filenames
    display_name: str          # used in subject "<name>'s Captainship Report"
    flavor: str                # rafael | fiber | b2b | nds
    title_bg: str = "#EA903C"  # per-captain brand color (title-bar bg).
                               # Confirmed by Megan 2026-06-03 (verbal map;
                               # Sales Board banners were inconsistent).
    to: str = ""               # FALLBACK recipient(s), comma-separated. The
                               # live list is the 'Captainship - <Name>'
                               # contact group (see .recipients() / distro.py);
                               # this is what gets used if that group is
                               # missing or unreadable. Blank = --send skips
                               # this captain.
                               #
                               # This exists because a human must NOT open
                               # these drafts in Gmail to send them. Proven
                               # 2026-07-27: opening a draft makes Gmail's
                               # compose rewrite pull the inline images out of
                               # the message, and what then goes out has no
                               # image parts at all — the recipient gets body
                               # text and broken icons. The SAME message sent
                               # straight through the API arrives intact.
                               # So the address lives here, not in Gmail's
                               # "To" box.
    churn: List[ChurnSource] = field(default_factory=list)
    boxes: List[BoxSource] = field(default_factory=list)

    def recipients(self, *, logfn=print) -> str:
        """The LIVE To header: this captain's Gmail contact group, expanded at
        send time, so Eve manages the list from Contacts instead of from code.
        Falls back to `to` (the hardcoded list below) with a loud warning when
        the group is missing or unreadable — see distro.py for the why."""
        from automations.captainship_drafts import distro
        return distro.to_header(self.key, logfn=logfn)

    @property
    def intro(self) -> Tuple[str, List[str]]:
        return _INTRO[self.flavor]

    @property
    def sections(self) -> List[Tuple[str, str]]:
        """[(heading, kind), ...] in body order — the intro item text as the
        section heading, zipped with SECTION_KINDS for this flavor. EVERY
        declared section, day-agnostic — the capture/build paths go through
        sections_on(today) instead, so day-gated sections drop cleanly."""
        _, items = _INTRO[self.flavor]
        return list(zip(items, SECTION_KINDS[self.flavor]))

    def sections_on(self, today: dt.date) -> List[Tuple[str, str]]:
        """The sections that actually RUN on `today` — `sections` minus any
        kind SECTION_DAYS gates off this weekday. Both run.py (capture) and
        email_build (numbered headings + intro bullets) resolve through this,
        so on an off day a gated section leaves no trace at all: no heading,
        no pending note, no intro line — and the numbering closes the gap."""
        return [(h, k) for h, k in self.sections if kind_runs_on(k, today)]


# Who each captain's report goes to (Eve, 2026-07-27 — copied from the
# distribution list she used to pick by hand in Gmail). These are real people:
# `run.py --send` mails every address here, so treat an edit as a real change
# to who receives the report. Kept as lists (one address per line) purely so a
# diff shows exactly who was added or removed.
RECIPIENTS: dict = {
    "rafael": [
        "andrew.sanborn07@gmail.com", "Ayakhafaji02@gmail.com",
        # OUT 2026-08-19, two-week zero rule: Benjamin Burden
        # (Benjaminburden02@gmail.com — the group carried his gmail, not the
        # bgsu.edu this list used to have) and Edgar Muniz II
        # (edgarmuniz2020@icloud.com, "Edgar Munoz II" in Contacts). Both came
        # off the Org Sales Board the same day. NOTE this group is SHARED with
        # the Org Sales Board email (GROUPS docstring), so the removal takes
        # them off that mail too — correct here, since neither has a board row
        # left anywhere.
        "codycannon1993@gmail.com",
        "cywadeambient@gmail.com", "dylanjtwaddle@gmail.com",
        "m.hammad.malikk@gmail.com",
        "haythamnagi1@gmail.com", "doverjacob94@gmail.com",
        "Loganjoseph81@yahoo.com", "Palace.kash@gmail.com",
        "maudmiller4@gmail.com", "Zenithzenith2099@gmail.com",
        "niitagoe4@gmail.com", "raffi127@gmail.com",
        "rashadreed715@gmail.com", "salikmallick6@gmail.com",
        # OUT 2026-08-20 (Eve): Steve McElwee (mcelwee.steve95@gmail.com) is not
        # in Rafael's captainship. Off the board, off his six metrics tabs and
        # off the live "Raf's Captain Team" group the same day — and since that
        # group is SHARED with the Org Sales Board email, off that mail too. He
        # keeps "ATT Fiber Owners": still an ATT fiber ICD, just not Raf's.
        "trang.lecanavan@gmail.com",
        "kesslerzadrian@gmail.com",
    ],
    "wayne": [
        "iraffi127@icloud.com",
        "Turzynskialex@yahoo.com", "ascottburris@gmail.com",
        "resoundinc@gmail.com", "dylanjtwaddle@gmail.com",
        "maudmiller4@gmail.com",
        "alistacquisition@gmail.com", "raffi127@gmail.com",
        "sykes.meridian@gmail.com", "elitestrategicsolutions@gmail.com",
    ],
    "starr": [
        "iraffi127@icloud.com",
        "adreyb15@gmail.com", "dylanjtwaddle@gmail.com",
        "jpascual@elevaremanagementinc.com",
        "maudmiller4@gmail.com", "milly.vinceremarketing@gmail.com",
        "nataliagwarda@gmail.com", "omniamanagementinc@gmail.com",
        "raffi127@gmail.com", "starr.novamanagement@gmail.com",
        # OUT 2026-08-25, two-week zero rule: William Sassenberg
        # (William@optimabusinessmgmt.com) — 0 in both of Starr's boxes
        # for WE 08.23 and WE 08.16.
    ],
    "chan": [
        "carissang46@gmail.com", "parkwchan19@gmail.com",
        "coel.g.reif@gmail.com", "dylanjtwaddle@gmail.com",
        "ericdmartinez222@gmail.com", "kimberlyatt458@gmail.com",
        "marcial.enrique@yahoo.com", "maudmiller4@gmail.com",
        "nweldon0130@gmail.com", "raffi127@gmail.com",
        "samjpark1497@gmail.com",
    ],
    "tony": [
        "kingslegacyconsultants@gmail.com",
        "dmarilongmire7@gmail.com", "dylanjtwaddle@gmail.com",
        "orbitc2025@gmail.com", "clearviewc.inc@gmail.com",
        "kcireus@gmail.com", "maudmiller4@gmail.com",
        "raffi127@gmail.com",
        "tonycv1920@gmail.com",
    ],
    "sahil": [
        # Jeremiah Minor removed 2026-07-30 — Eve took him out of the
        # "Sahil's Captainship" group on purpose; the fallback must not
        # put him back.
        #
        # andre082702@ added 2026-08-18: it was already in the group and had been
        # receiving the report; only this backup was behind. Synced FROM the
        # group, which is the safe direction — it can't revive anyone removed on
        # purpose (see Jeremiah above).
        "andre082702@gmail.com",
        "ttran.brian@gmail.com", "dylanjtwaddle@gmail.com",
        "marcellusbutlerjr@gmail.com",
        "maudmiller4@gmail.com", "raffi127@gmail.com",
        "multani.business@gmail.com",
    ],
    "carlos": [
        # Ethan McKendree removed 2026-08-10 — Eve took him out of the "Carlos'
        # Captain Team" group by hand and seed_groups.py, which REBUILDS that
        # group from this list, put him straight back. Same story as Jeremiah
        # Minor below. Note this group is SHARED (distro.GROUPS): being on it
        # also mailed him the Org Sales Board email and the Override Bulletin.
        #
        # Re-synced to the group 2026-08-18, when Atef's captainship split off:
        # OUT atefchoudhury349@ and sabrinaalicea2021@ (they went with Atef) and
        # smgroupjoe@ (Joe Eckhart, off the captainship); IN jackieleroyatt@.
        # The group had already been edited — this is the backup catching up, and
        # a stale backup is exactly what hid the Khalil typo.
        "CarlosHidalgo349@gmail.com",
        "wgary.att@gmail.com",
        "georgehipolito2@gmail.com", "jamisgaray18@gmail.com",
        "jackieleroyatt@gmail.com", "jeffcstarr@gmail.com",
        "joeyrmz2002@gmail.com", "justinryanwood.93@gmail.com",
        "kinseyguenther@gmail.com",
        "maudmiller4@gmail.com", "murphjjm@gmail.com",
        "raffi127@gmail.com", "vincentsmith24.att@gmail.com",
    ],
    "eveliz": [
        # OUT 2026-08-24 (Eve): lizetteruiz0510@ — Lizette Ruiz is not on
        # Eveliz's captainship, whatever Tableau's B2B captain filter says
        # (pinned in shared/captainship_pins.NOT_ON_TEAM under "Eveliz"). Taken
        # out of the live "Eveliz's Captainship" group the same day; it has to
        # leave this list too or seed_groups.py puts her straight back. That
        # group is NOT shared with the Org Sales Board mail, and she stays on
        # "Alphalete Org Owners" — she is still an ICD of the org.
        "themillenders@gmail.com", "evelizroca.ssm@gmail.com",
        "gregoryahalstead@gmail.com",
        "maudmiller4@gmail.com", "raffi127@gmail.com",
        "shalonda@dime-llc.com", "valeriatristan.amg@gmail.com",
    ],
    "luis": [
        "albert.rubio1228@gmail.com", "CarlosHidalgo349@gmail.com",
        "aventus.marketinginc@gmail.com", "dylanjtwaddle@gmail.com",
        "harman100703@gmail.com", "lusalazar619@gmail.com",
        "maudmiller4@gmail.com", "maxpowell145@gmail.com",
        "mihir.vadlamani@gmail.com", "raffi127@gmail.com",
        "rob.diamondbiz@gmail.com",
    ],
    # FALLBACK ONLY — the live list is the "Atef's Captainship" Contacts group
    # (distro.GROUPS). Snapshot of that group on 2026-08-18, the day his
    # captainship split off Carlos' — Dhey Patel included, added by Eve that
    # same afternoon and picked up with no code change, which is the point.
    "atef": [
        "atefchoudhury349@gmail.com", "CarlosHidalgo349@gmail.com",
        "maudmiller4@gmail.com", "pateldhyeyb@gmail.com",
        "raffi127@gmail.com", "sabrinaalicea2021@gmail.com",
    ],
    "khalil": [
        "CarlosHidalgo349@gmail.com",
        "dylanjtwaddle@gmail.com", "isaiah.revelle@gmail.com",
        # 2026-07-30: was "KhalilImmansour@..." — an extra capital I that made
        # every scheduled send bounce 550 5.1.1 while a hand-resend (Gmail
        # autocompletes the contact) went through. Real address, as it appears
        # on the Org Sales Board / Bulletin distro: Khalilmmansour (two m's).
        "n.lucio326@gmail.com", "Khalilmmansour@gmail.com",
        "maudmiller4@gmail.com", "maxamed.hersi6292@gmail.com",
        "raffi127@gmail.com", "zaid.m.arabiyat@gmail.com",
    ],
    "colten": [
        "coltenwrightsc@gmail.com", "dylanjtwaddle@gmail.com",
        "fernandomunoz710@icloud.com", "georgedelgadod2d@gmail.com",
        "josevelasquezlsm@gmail.com",
        "josephdelgadosc@gmail.com", "coastalcreativeconcepts@yahoo.com",
        "campas.kyle@gmail.com", "lajaviusbrown@yahoo.com",
        "logan.waite24@gmail.com",
        # OUT 2026-08-27 (Eve): Marcos Barbosa (marcosbarbosa.entrepeneur@gmail.com)
        # comes off Colten's captainship — and out from under Colten's org in the
        # bulletins the same day. His three board rows, his four rows on
        # 'Churn - Colten Wright (NDS)' and his 'Lucy Org Tree' / 'Org Tree'
        # entries all went with it, and Tableau is pinned in
        # shared/captainship_pins under "Colten". Same reason as Milan below: he
        # must leave this list AND the live "Colten's Captainship" group, because
        # seed_groups REBUILDS that group from here.
        # OUT 2026-08-21 (Eve): Milan Godbolt (arisesolutions.milan@gmail.com)
        # comes off Colten's captainship. His three board rows went the same
        # day and Tableau is pinned in shared/captainship_pins under "Colten".
        # He must leave this list AND the live "Colten's Captainship" group —
        # seed_groups REBUILDS that group from here, so a name left in code
        # walks back in (the Jeremiah Minor pattern).
        "maudmiller4@gmail.com",
        "nickopereira98@gmail.com", "dubalenoah@gmail.com",
        "raffi127@gmail.com", "taylor.4597@gmail.com",
    ],
    "jairo": [
        "coltenwrightsc@gmail.com", "drewtepp2735@gmail.com",
        "dylanjtwaddle@gmail.com", "fm.peakmanagementinc@gmail.com",
        "frankmatos1128@gmail.com", "amissolutions7@gmail.com",
        # IN 2026-08-28 (Eve): Abdallah Ghousheh entra a la capitania de Jairo.
        # Eve ya lo habia agregado A MANO al grupo vivo "Jairo's Captainship",
        # y sin esta linea el alta no sobrevive: seed_groups REHACE el grupo
        # desde esta lista, asi que lo marcaba para SACAR (verificado con
        # `seed_groups --dry-run --only jairo` el mismo dia). Es la contracara
        # exacta del caso Milan/Marcos en la lista de Colten, y la razon por la
        # que un alta o una baja tienen que estar en los DOS lados.
        "ghoushehbusiness@gmail.com",
        "jairoruizpmg@gmail.com", "ferminjustin71@gmail.com",
        "maudmiller4@gmail.com", "nickopereira98@gmail.com",
        "raffi127@gmail.com",
    ],
}


# Eve va en TODAS las listas, sin excepcion (Eve, 2026-08-28). Se aplica en un
# bucle y no pegando la direccion trece veces a mano, porque el modo de falla
# es justamente el olvido: estaba en los TRECE grupos vivos de Contacts y en
# NINGUNA lista de codigo, asi que `seed_groups --dry-run` la marcaba para
# SACAR de todos (verificado ese dia). Un capitan nuevo agregado manana hereda
# esto solo; una linea literal por lista se olvida en el proximo alta.
#
# Ojo con lo que esto NO es: el envio expande el GRUPO VIVO de Contacts
# (distro.recipients_for), asi que esto no cambia quien recibe hoy — arregla
# las dos cosas que dependen del codigo, el fallback cuando el grupo no se
# puede leer y lo que seed_groups escribe de vuelta en el grupo.
ALWAYS = "eve@alphaletemarketing.com"
for _lst in RECIPIENTS.values():
    if ALWAYS.lower() not in {a.lower() for a in _lst}:
        _lst.append(ALWAYS)


def _to(key: str) -> str:
    """The To header for one captain — its RECIPIENTS list, comma-joined."""
    return ", ".join(RECIPIENTS[key])


# Per-captain brand colors (title-bar background). Email brand map
# confirmed by Eve 2026-07-17 (distinct from the Fiber Activations PNG
# colors). Rafael's Wireless block keeps the standard wireless blue
# (brand_title=False) so its orange title bar doesn't clash with the
# blue date band ("ok como está").
CAPTAINS: List[Captain] = [
    Captain("rafael", "Rafael", "rafael", title_bg="#E8612A", to=_to("rafael"), churn=[
        ChurnSource(_cap.open_ws_new_int,  _ni_render, "New Internet Churn"),
        ChurnSource(_cap.open_ws_wireless, _wl_render, "Wireless Churn",
                    brand_title=False),
    ], boxes=_rafael_boxes()),
    # ----- Fiber (Aron retired → Chan; Tony + Sahil added 2026-07-17) -----
    # Wireless churn joined the fiber drafts 2026-07-29. It comes off the
    # per-captain Wireless tabs owners_metrics_churn fills from ONE org-wide
    # pull sliced by Captain's Bonus Teams — there are no per-captain wireless
    # views in Tableau. brand_title=False like Rafael's: wireless_churn.render
    # pins its own blue palette (title bar AND date band) and takes no title_bg
    # at all, so a brand color here is not just off-style, it raises TypeError.
    Captain("wayne", "Wayne", "fiber", title_bg="#E69138", to=_to("wayne"), churn=[
        ChurnSource(_own.open_ws_fiber_wayne, _ni_render, "New Internet Churn"),
        ChurnSource(_own.open_ws_wl_wayne, _wl_render, "Wireless Churn",
                    brand_title=False),
    ], boxes=_fiber_boxes("wayne")),
    Captain("starr", "Starr", "fiber", title_bg="#9900FF", to=_to("starr"), churn=[
        ChurnSource(_own.open_ws_fiber_starr, _ni_render, "New Internet Churn"),
        ChurnSource(_own.open_ws_wl_starr, _wl_render, "Wireless Churn",
                    brand_title=False),
    ], boxes=_fiber_boxes("starr")),
    Captain("chan", "Chan", "fiber", title_bg="#8A7465", to=_to("chan"), churn=[
        ChurnSource(_own.open_ws_fiber_chan, _ni_render, "New Internet Churn"),
        ChurnSource(_own.open_ws_wl_chan, _wl_render, "Wireless Churn",
                    brand_title=False),
    ], boxes=_fiber_boxes("chan")),
    Captain("tony", "Tony", "fiber", title_bg="#001F5B", to=_to("tony"), churn=[
        ChurnSource(_own.open_ws_fiber_tony, _ni_render, "New Internet Churn"),
        ChurnSource(_own.open_ws_wl_tony, _wl_render, "Wireless Churn",
                    brand_title=False),
    ], boxes=_fiber_boxes("tony")),
    Captain("sahil", "Sahil", "fiber", title_bg="#800020", to=_to("sahil"), churn=[
        ChurnSource(_own.open_ws_fiber_sahil, _ni_render, "New Internet Churn"),
        ChurnSource(_own.open_ws_wl_sahil, _wl_render, "Wireless Churn",
                    brand_title=False),
    ], boxes=_fiber_boxes("sahil")),
    # ----- B2B (5 buckets incl 120) -----
    Captain("carlos", "Carlos", "b2b", title_bg="#4CAF4F", to=_to("carlos"), churn=[
        ChurnSource(_own.open_ws_b2b_carlos, _ni_render, "Wireless Churn",
                    title_prefix="WIRELESS CHURN"),
    ]),
    Captain("eveliz", "Eveliz", "b2b", title_bg="#A64D79", to=_to("eveliz"), churn=[
        ChurnSource(_own.open_ws_b2b_eveliz, _ni_render, "Wireless Churn",
                    title_prefix="WIRELESS CHURN"),
    ]),
    Captain("luis", "Luis", "b2b", title_bg="#B5ADFB", to=_to("luis"), churn=[
        ChurnSource(_own.open_ws_b2b_luis, _ni_render, "Wireless Churn",
                    title_prefix="WIRELESS CHURN"),
    ]),
    # Split off Carlos' captainship 2026-08-18 (Atef + Sabrina Alicea + Dhey
    # Patel). His churn tab fills off the ALL-TEAMS view until Tableau adds him
    # to the captain dropdown — see owners_metrics_churn.pull
    # .make_b2b_captainship_parser. Nothing here changes when that happens.
    Captain("atef", "Atef", "b2b", title_bg="#00695C", to=_to("atef"), churn=[
        ChurnSource(_own.open_ws_b2b_atef, _ni_render, "Wireless Churn",
                    title_prefix="WIRELESS CHURN"),
    ]),
    # ----- NDS -----
    Captain("khalil", "Khalil", "nds", title_bg="#EA4335", to=_to("khalil"), churn=[
        ChurnSource(_own.open_ws_nds_khalil, _ni_render, "New Internet Churn"),
    ]),
    Captain("colten", "Colten", "nds", title_bg="#46BDC6", to=_to("colten"), churn=[
        ChurnSource(_own.open_ws_nds_colten, _ni_render, "New Internet Churn"),
    ]),
    Captain("jairo", "Jairo", "nds", title_bg="#FBBC04", to=_to("jairo"), churn=[
        ChurnSource(_own.open_ws_nds_jairo, _ni_render, "New Internet Churn"),
    ]),
]

BY_KEY = {c.key: c for c in CAPTAINS}


# ---------------------------------------------------------------------------
# BLOCKS — the unit of review (Eve, 2026-08-26)
# ---------------------------------------------------------------------------
# The 12 drafts used to be ONE artefact: one PDF, one link, one checkmark, and
# nothing could be approved until the last of the twelve had finished building
# and printing. Eve's ask: split the build into blocks so a block finishes,
# posts its own link inside the same 'Captainship Reports' thread, and can be
# approved and sent while the rest are still being assembled.
#
# ORDER IS THE SCHEDULE. This list is the order the drafts are built in AND the
# order their links go into the thread: Fiber first (Rafael, then Wayne+Starr,
# then Tony+Chan+Sahil), then B2B, then NDS. Reordering this list reorders both
# — there is no second place that says what comes first.
#
# Rafael sits under Fiber even though his FLAVOR is "rafael": the flavor is
# about which sections his email renders (his own Sheet, 9 sections), the block
# is about who gets reviewed together. Eve grouped him with Fiber.
@dataclass(frozen=True)
class Block:
    key: str                   # slug for --block, filenames and Slack markers
    label: str                 # what the Slack post calls it, e.g. "Fiber 1"
    captains: Tuple[str, ...]  # captain keys, in send order

    @property
    def members(self) -> List[Captain]:
        return [BY_KEY[k] for k in self.captains if k in BY_KEY]

    @property
    def who(self) -> str:
        """"Wayne, Starr" — the names for the Slack post and the log line."""
        return ", ".join(c.display_name for c in self.members)


_BLOCKS: List[Block] = [
    Block("fiber-1", "Fiber 1", ("rafael",)),
    Block("fiber-2", "Fiber 2", ("wayne", "starr")),
    Block("fiber-3", "Fiber 3", ("tony", "chan", "sahil")),
    Block("b2b", "B2B", ("carlos", "eveliz", "luis", "atef")),
    Block("nds", "NDS", ("khalil", "colten", "jairo")),
]

# A captain added to CAPTAINS and forgotten here must NOT silently stop being
# built, reviewed and mailed — that is a report that quietly disappears, which
# is the one failure nobody notices. Anyone unclaimed lands in a trailing block
# of their own so they still get a link and a checkmark; the label says loudly
# that they need a home in _BLOCKS above.
_UNBLOCKED = tuple(c.key for c in CAPTAINS
                   if not any(c.key in b.captains for b in _BLOCKS))
BLOCKS: List[Block] = _BLOCKS + (
    [Block("unassigned", "Unassigned (add them to config.BLOCKS)", _UNBLOCKED)]
    if _UNBLOCKED else [])

BLOCK_BY_KEY = {b.key: b for b in BLOCKS}


def block_of(captain_key: str) -> Block:
    """The block a captain belongs to. KeyError if the key isn't a captain."""
    for b in BLOCKS:
        if captain_key in b.captains:
            return b
    raise KeyError(f"{captain_key!r} is not in any block (and not a captain?)")


def captains_in_order() -> List[Captain]:
    """All 12 captains in BLOCK order — the order they build and mail in.

    Use this instead of CAPTAINS anywhere order is visible (the build loop, the
    review PDF, the send list). CAPTAINS keeps its own roster order because
    that is how the recipient lists read in a diff."""
    return [c for b in BLOCKS for c in b.members]
