"""Per-captain configuration for the 12 Captainship Report drafts.

12 drafts in 4 flavors (roster + brand colors confirmed by Eve 2026-07-17):
  rafael  (1) — Raf's Captainship: NI churn + Wireless churn
  fiber   (5) — Wayne / Starr / Chan / Tony / Sahil: NI churn
  b2b     (3) — Carlos / Eveliz / Luis: NI churn (5 buckets, incl 120)
  nds     (3) — Khalil / Colten / Jairo: NI churn

Section layout (per flavor) — the last 1-2 sections are the CHURN blocks,
wired here via ChurnSource over the existing render engine. Section 1
(Product Summary + Captainship Units, Sales Board screenshots) and section
2 (Tableau Cancel-Rates / Team-Stats shots; fiber also pastes the Fiber
Activations PNG) are built in sales_board.py / tableau_shot.py / fiber_png.py
and assembled by email_build.py.

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
    "rafael": ("Hello, team! Below you'll find:", [
        "Product Summaries Of Sales 💰",
        "New Internet Ongoing Cancel Metrics ⚠️",
        "New Internet Ongoing Churn Metrics 🌐",
        "Wireless Ongoing Churn Metrics 🛜",
    ]),
    "fiber": ("Hello, team! Below you'll find:", [
        "Product Summaries Of Sales 💰",
        "Captainship Fiber Activations ✅",
        "New Internet Ongoing Cancel Metrics ⚠️",
        "New Internet Ongoing Churn Metrics 🌐",
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
SECTION_KINDS = {
    "rafael": ["product_summary", "cancel_tableau", "churn_ni",
               "churn_wireless"],
    "fiber":  ["product_summary", "fiber_activation", "cancel_tableau",
               "churn_ni"],
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
class Captain:
    key: str                   # slug for --only + filenames
    display_name: str          # used in subject "<name>'s Captainship Report"
    flavor: str                # rafael | fiber | b2b | nds
    title_bg: str = "#EA903C"  # per-captain brand color (title-bar bg).
                               # Confirmed by Megan 2026-06-03 (verbal map;
                               # Sales Board banners were inconsistent).
    to: str = ""               # recipient(s) for `run.py --send`, comma-
                               # separated. Blank = --send skips this captain.
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
        "burdenb@bgsu.edu", "codycannon1993@gmail.com",
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
        "Turzynskialex@yahoo.com", "ascottburris@gmail.com",
        "resoundinc@gmail.com", "dylanjtwaddle@gmail.com",
        "mason.d.management@gmail.com", "maudmiller4@gmail.com",
        "alistacquisition@gmail.com", "raffi127@gmail.com",
        "sykes.meridian@gmail.com", "elitestrategicsolutions@gmail.com",
    ],
    "starr": [
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
        "ttran.brian@gmail.com", "dylanjtwaddle@gmail.com",
        "Jeremiahminor2@gmail.com", "marcellusbutlerjr@gmail.com",
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
        "n.lucio326@gmail.com", "KhalilImmansour@gmail.com",
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
    ]),
    # ----- Fiber (Aron retired → Chan; Tony + Sahil added 2026-07-17) -----
    Captain("wayne", "Wayne", "fiber", title_bg="#E69138", to=_to("wayne"), churn=[
        ChurnSource(_own.open_ws_fiber_wayne, _ni_render, "New Internet Churn"),
    ]),
    Captain("starr", "Starr", "fiber", title_bg="#9900FF", to=_to("starr"), churn=[
        ChurnSource(_own.open_ws_fiber_starr, _ni_render, "New Internet Churn"),
    ]),
    Captain("chan", "Chan", "fiber", title_bg="#8A7465", to=_to("chan"), churn=[
        ChurnSource(_own.open_ws_fiber_chan, _ni_render, "New Internet Churn"),
    ]),
    Captain("tony", "Tony", "fiber", title_bg="#001F5B", to=_to("tony"), churn=[
        ChurnSource(_own.open_ws_fiber_tony, _ni_render, "New Internet Churn"),
    ]),
    Captain("sahil", "Sahil", "fiber", title_bg="#800020", to=_to("sahil"), churn=[
        ChurnSource(_own.open_ws_fiber_sahil, _ni_render, "New Internet Churn"),
    ]),
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
