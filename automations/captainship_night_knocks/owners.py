"""Who each office's night mail goes to: its OWNER, and Eve.

Raf 2026-09-15: "For 9:00 pm local time knocks. Can we make it where it only
gets emailed to the specific individual of the knocks?" — Eve, same day: "por
ahora dejemoslo en el owner de la oficina y eve". Until then the night went to
the whole captainship distro as one thread, so every owner saw every other
office's close.

WHY A PINNED TABLE and not a lookup in Contacts at send time. The captainship
distros are lists of ADDRESSES; nothing there says which address is which
office's owner, and matching a board name against a contact name by hand at 9
PM is how one owner's numbers land in another owner's inbox. So the pairs were
read ONCE (2026-09-15, People API, read-only, alphaletereporting@gmail.com) off
the members of the eight night-knocks captainship groups, and pinned here.
Where a person has two addresses in Contacts (Chris Williams, Sam Park, Sahil
Multani) the one in HIS CAPTAINSHIP GROUP wins — it is the one that already
receives his reports.

KEYED BY THE ORG SALES BOARD'S SPELLING, the same names zones.ICD_TIMEZONES
uses, because that is what the roster hands the tick. An office with no line
here is NOT mailed to anybody: it is recorded as an office failure and Eve is
told right away (run.alert_now). An owner email change goes here AND in
Contacts (see captainship_drafts/config.RECIPIENTS for the same rule).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Eve gets a copy of every office's mail (Eve 2026-09-15).
ALWAYS_CC = "eve@alphaletemarketing.com"

OWNER_EMAILS: Dict[str, str] = {
    # rafael
    "Rafael Hidalgo":      "raffi127@gmail.com",
    "Aya Al-Khafaji":      "Ayakhafaji02@gmail.com",
    "Cody Cannon":         "codycannon1993@gmail.com",
    "Cyrus Wade":          "cywadeambient@gmail.com",
    "Haytham Nagi":        "haythamnagi1@gmail.com",
    "Jacob Dover":         "doverjacob94@gmail.com",
    "Joseph Logan":        "Loganjoseph81@yahoo.com",
    "Kash Rai":            "Palace.kash@gmail.com",
    "Muhammad Haque":      "m.hammad.malikk@gmail.com",   # Contacts: "Hammad Malik"
    "Nii Tagoe":           "niitagoe4@gmail.com",         # Contacts: "Nii Teiko - Tagoe"
    "Nuri Burgos":         "nuri@22select.com",
    "Rashad Reed":         "rashadreed715@gmail.com",
    "Salik Mallick":       "salikmallick6@gmail.com",
    "Trang Canavan":       "trang.lecanavan@gmail.com",
    # chan
    "Carissa Ng":          "carissang46@gmail.com",
    "Chan Park":           "parkwchan19@gmail.com",
    "Coel Reif":           "coel.g.reif@gmail.com",
    "Ja Mosley":           "jamosleybiz@gmail.com",
    "Marcial Rodriguez":   "marcial.enrique@yahoo.com",
    "Nicholas Weldon":     "nweldon0130@gmail.com",
    "Sam Park":            "samjpark1497@gmail.com",
    # starr
    "Blue Mendoza":        "adreyb15@gmail.com",
    "JC Pascual":          "jpascual@elevaremanagementinc.com",
    "Juan Botero Berrio":  "juanbotero0120@gmail.com",
    "Milly Villagrana":    "milly.vinceremarketing@gmail.com",
    "Natalia Gwarda":      "nataliagwarda@gmail.com",
    "Oren Shezaf":         "omniamanagementinc@gmail.com",
    "Starr Rodenhurst":    "starr.novamanagement@gmail.com",
    # tony
    "Chris Williams":      "kingslegacyconsultants@gmail.com",
    "German Lopez":        "orbitc2025@gmail.com",
    "Jay Turnage":         "clearviewc.inc@gmail.com",
    "Kobe Cireus":         "kcireus@gmail.com",
    "Tony Chavez":         "tonycv1920@gmail.com",
    # sahil
    "Andre Burton":        "andre082702@gmail.com",
    "Brian Tran":          "ttran.brian@gmail.com",
    "Marcellus Butler":    "marcellusbutlerjr@gmail.com",
    "Sahil Multani":       "multani.business@gmail.com",
    # jess
    "Jennifer Figueroa":   "jenniferfigueroa55@gmail.com",
    "Mercy Ohiokhai":      "mercel.management@gmail.com",
    "Sebastian Gutierrez": "sebbogutierrez@gmail.com",
    # pat
    "Eric Zech":           "ericzech23@gmail.com",
    "Francisco Castillo":  "f.castillo0021@gmail.com",
    "Gabe Perez":          "gperez3rd@yahoo.com",
    "Hasani Lynch":        "hasanilynch17@gmail.com",
    "John Richard Young":  "youngjohnrichard@gmail.com",
    "Stergios Kasapidis":  "kasapidisstergios@gmail.com",
    "Tre Mitchell":        "tre.mitchell60@gmail.com",
    # wayne
    "Christian Esposito":  "resoundinc@gmail.com",
    "Michael Murphy":      "alistacquisition@gmail.com",
}


def _key(name: str) -> str:
    return " ".join((name or "").lower().split())


_BY_KEY = {_key(k): v for k, v in OWNER_EMAILS.items()}


def owner_email(*names: str) -> Optional[str]:
    """The owner's address for the first of `names` that is on file — pass the
    board spelling first, then the alias-canonical one."""
    for n in names:
        hit = _BY_KEY.get(_key(n))
        if hit:
            return hit
    return None


def recipients(*names: str) -> List[str]:
    """[owner, Eve] for one office, or [] when the owner has no address."""
    owner = owner_email(*names)
    if not owner:
        return []
    return [owner] + ([ALWAYS_CC] if owner.lower() != ALWAYS_CC else [])
