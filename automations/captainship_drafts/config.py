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

Churn sources reference the EXISTING open_ws_* helpers + tab constants so
tab names are never hardcoded (and we don't trip on the en-dash/hyphen
mismatch in the spec — the real tabs use a hyphen).
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
    ]),
    "b2b": ("Hi, team! Below you'll find:", [
        "Product Summary Of Sales",
        "⚠️Captain Team Stats Breakout ⚠️",
        "💰New Internet Ongoing Churn Metrics 💰",
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
SECTION_KINDS = {
    "rafael": ["product_summary",
               "box:cancel-0-30", "box:cancel-30-60",
               "churn_ni", "churn_wireless",
               "box:abp", "box:activation-0-30", "box:activation-30-60",
               "box:six-days"],
    "fiber":  ["product_summary", "fiber_activation",
               "box:cancel-0-30", "box:cancel-30-60",
               "churn_ni", "churn_wireless",
               "box:abp", "box:activation-0-30", "box:activation-30-60",
               "box:six-days"],
    "b2b":    ["product_summary", "teamstats_tableau", "churn_ni"],
    "nds":    ["product_summary", "teamstats_tableau", "churn_ni"],
}


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
        section heading, zipped with SECTION_KINDS for this flavor."""
        _, items = _INTRO[self.flavor]
        return list(zip(items, SECTION_KINDS[self.flavor]))


# Who each captain's report goes to (Eve, 2026-07-27 — copied from the
# distribution list she used to pick by hand in Gmail). These are real people:
# `run.py --send` mails every address here, so treat an edit as a real change
# to who receives the report. Kept as lists (one address per line) purely so a
# diff shows exactly who was added or removed.
RECIPIENTS: dict = {
    "rafael": [
        "andrew.sanborn07@gmail.com", "Ayakhafaji02@gmail.com",
        # Benjamin Burden: the group carries his gmail, not the bgsu.edu
        # address this list had. Synced 2026-07-30.
        "Benjaminburden02@gmail.com", "codycannon1993@gmail.com",
        "cywadeambient@gmail.com", "dylanjtwaddle@gmail.com",
        "edgarmuniz2020@icloud.com", "m.hammad.malikk@gmail.com",
        "haythamnagi1@gmail.com", "doverjacob94@gmail.com",
        "Loganjoseph81@yahoo.com", "Palace.kash@gmail.com",
        "maudmiller4@gmail.com", "Zenithzenith2099@gmail.com",
        "niitagoe4@gmail.com", "raffi127@gmail.com",
        "rashadreed715@gmail.com", "salikmallick6@gmail.com",
        "mcelwee.steve95@gmail.com", "trang.lecanavan@gmail.com",
        "kesslerzadrian@gmail.com",
    ],
    "wayne": [
        "iraffi127@icloud.com",
        "Turzynskialex@yahoo.com", "ascottburris@gmail.com",
        "resoundinc@gmail.com", "dylanjtwaddle@gmail.com",
        "mason.d.management@gmail.com", "maudmiller4@gmail.com",
        "alistacquisition@gmail.com", "raffi127@gmail.com",
        "sykes.meridian@gmail.com", "elitestrategicsolutions@gmail.com",
    ],
    "starr": [
        "iraffi127@icloud.com",
        "adreyb15@gmail.com", "dylanjtwaddle@gmail.com",
        "jason.vyzahinc@gmail.com", "jpascual@elevaremanagementinc.com",
        "maudmiller4@gmail.com", "milly.vinceremarketing@gmail.com",
        "nataliagwarda@gmail.com", "omniamanagementinc@gmail.com",
        "raffi127@gmail.com", "starr.novamanagement@gmail.com",
        "William@optimabusinessmgmt.com",
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
        "berhaneaden3@gmail.com", "kingslegacyconsultants@gmail.com",
        "dmarilongmire7@gmail.com", "dylanjtwaddle@gmail.com",
        "orbitc2025@gmail.com", "clearviewc.inc@gmail.com",
        "kcireus@gmail.com", "maudmiller4@gmail.com",
        "melikeljaiez@yahoo.com", "raffi127@gmail.com",
        "tonycv1920@gmail.com",
    ],
    "sahil": [
        # Jeremiah Minor removed 2026-07-30 — Eve took him out of the
        # "Sahil's Captainship" group on purpose; the fallback must not
        # put him back.
        "ttran.brian@gmail.com", "dylanjtwaddle@gmail.com",
        "marcellusbutlerjr@gmail.com",
        "maudmiller4@gmail.com", "raffi127@gmail.com",
        "multani.business@gmail.com",
    ],
    "carlos": [
        "atefchoudhury349@gmail.com", "CarlosHidalgo349@gmail.com",
        "ethanmckendree01@gmail.com", "wgary.att@gmail.com",
        "georgehipolito2@gmail.com", "jamisgaray18@gmail.com",
        "smgroupjoe@yahoo.com", "joeyrmz2002@gmail.com",
        "justinryanwood.93@gmail.com", "kevdriggs25@gmail.com",
        "kinseyguenther@gmail.com", "maudmiller4@gmail.com",
        "raffi127@gmail.com", "ryankabbes@gmail.com",
        "sabrinaalicea2021@gmail.com",
    ],
    "eveliz": [
        "themillenders@gmail.com", "evelizroca.ssm@gmail.com",
        "gregoryahalstead@gmail.com", "lizetteruiz0510@gmail.com",
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
    "khalil": [
        "agonzalezz25@outlook.com", "CarlosHidalgo349@gmail.com",
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
        "javeonterrell@gmail.com", "josevelasquezlsm@gmail.com",
        "josephdelgadosc@gmail.com", "coastalcreativeconcepts@yahoo.com",
        "campas.kyle@gmail.com", "lajaviusbrown@yahoo.com",
        "logan.waite24@gmail.com", "marcosbarbosa.entrepeneur@gmail.com",
        "maudmiller4@gmail.com", "arisesolutions.milan@gmail.com",
        "nickopereira98@gmail.com", "dubalenoah@gmail.com",
        "raffi127@gmail.com", "selena.powersmiami@gmail.com",
        "taylor.4597@gmail.com",
    ],
    "jairo": [
        "coltenwrightsc@gmail.com", "drewtepp2735@gmail.com",
        "dylanjtwaddle@gmail.com", "fm.peakmanagementinc@gmail.com",
        "frankmatos1128@gmail.com", "amissolutions7@gmail.com",
        "jairoruizpmg@gmail.com", "ferminjustin71@gmail.com",
        "maudmiller4@gmail.com", "nickopereira98@gmail.com",
        "raffi127@gmail.com",
    ],
}


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
        ChurnSource(_own.open_ws_b2b_carlos, _ni_render, "New Internet Churn"),
    ]),
    Captain("eveliz", "Eveliz", "b2b", title_bg="#A64D79", to=_to("eveliz"), churn=[
        ChurnSource(_own.open_ws_b2b_eveliz, _ni_render, "New Internet Churn"),
    ]),
    Captain("luis", "Luis", "b2b", title_bg="#B5ADFB", to=_to("luis"), churn=[
        ChurnSource(_own.open_ws_b2b_luis, _ni_render, "New Internet Churn"),
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
