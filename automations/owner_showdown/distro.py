"""Who gets the daily August Owner Showdown flyer.

Raf 2026-08-03 ("can we get this auto sent to everyone in this chat starting
tomorrow. I can't keep up with sending it out"): the flyer goes to the whole
COMPETITION FOR THE MONTH OF AUGUST!! email thread, not just Raf.

The list lives in a Gmail CONTACT GROUP — "Aug Owner Showdown" on
alphaletereporting@gmail.com — and is expanded at SEND time, so Megan can add or
drop someone in Contacts without a code change (same pattern as the Org Sales
Board's three groups, automations/shared/contacts_auth.py). The table below is
the SEED for that group and the dormant fallback if the People API is down.

Addresses were taken from the thread itself via the Gmail API (thread
19fb093436c2a200, Raf's 2026-07-30 message) — NOT retyped from a screenshot,
because one wrong character mails a competitor's numbers to a stranger.

Names are the roster spellings (see roster.py) so this cross-checks cleanly;
several differ from how the thread addresses them — Ozzy/Osvaldo Centeno,
Blue/Audrey Mendoza, Francisco/Frank Castillo, Michael/Mike Murphy, Gabe/Gabriel
Perez, Nii/Nii-Teiko Tagoe, JC Gerard/JC Pascual, Juan Botero-Berrio/Juan Botero,
Hammad Haque/Muhammad Hammad. Name-spelling fixes belong in the ICD Aliases
sheet, not here.

Aya Al-Khafaji competes in Rep Count Growth but was NOT on Raf's thread — she
would have been the one competitor ranked on the board who never saw it. Megan
supplied her address 2026-08-03 and she is in the list below.
"""
from __future__ import annotations

from typing import List, Tuple

GROUP_NAME = "Aug Owner Showdown"
ACCOUNT = "alphaletereporting@gmail.com"

# Competitors — the 38 rostered owners who are on the thread. (name, email)
COMPETITORS: List[Tuple[str, str]] = [   # (email, name)
    ("osvaldocenteno101@gmail.com", "Ozzy Centeno"),
    ("gperez3rd@yahoo.com", "Gabe Perez"),
    ("kasapidisstergios@gmail.com", "Stergios Kasapidis"),
    ("sebbogutierrez@gmail.com", "Sebastian Gutierrez"),
    ("haythamnagi1@gmail.com", "Haytham Nagi"),
    ("m.hammad.malikk@gmail.com", "Hammad Haque"),
    ("tre.mitchell60@gmail.com", "Tre Mitchell"),
    ("orbitc2025@gmail.com", "German Lopez"),
    ("alistacquisition@gmail.com", "Michael Murphy"),
    ("adreyb15@gmail.com", "Blue Mendoza"),
    ("ericdmartinez222@gmail.com", "Eric Martinez"),
    ("salikmallick6@gmail.com", "Salik Mallick"),
    ("npgilbert00@gmail.com", "Nigel Gilbert"),
    ("clearviewc.inc@gmail.com", "Jay Turnage"),
    ("angel.l.arias4069@gmail.com", "Angel Arias"),
    ("bill@zenithmgmtinc.com", "Bill Fischer"),
    ("carissang46@gmail.com", "Carissa Ng"),
    ("aeldredge90@gmail.com", "Austin Eldredge"),
    ("kimberlyatt458@gmail.com", "Kimberly Rodriguez"),
    ("nataliagwarda@gmail.com", "Natalia Gwarda"),
    ("oren.gspromotions@gmail.com", "Oren Shezaf"),
    ("resoundinc@gmail.com", "Christian Esposito"),
    ("sheree0795@gmail.com", "Sheree Rodriguez"),
    ("codycannon1993@gmail.com", "Cody Cannon"),
    ("palace.kash@gmail.com", "Kash Rai"),
    ("ascottburris@gmail.com", "Andrew Burris"),
    ("niitagoe4@gmail.com", "Nii Tagoe"),
    ("turzynskialex@yahoo.com", "Alex Turzynski"),
    ("f.castillo0021@gmail.com", "Francisco Castillo"),
    ("ericzech23@gmail.com", "Eric Zech"),
    ("jpascual@elevaremanagementinc.com", "JC Gerard Pascual"),
    ("Juanbotero0120@gmail.com", "Juan Botero-Berrio"),
    ("doverjacob94@gmail.com", "Jacob Dover"),
    ("joseph@loganlegacygroup.com", "Joseph Logan"),
    ("marcellusbutlerjr@gmail.com", "Marcellus Butler"),
    ("rashadreed715@gmail.com", "Rashad Reed"),
    ("ttran.brian@gmail.com", "Brian Tran"),
    ("jarredhill1906@gmail.com", "Jarred Hill"),
    # Not on Raf's thread — address from Megan 2026-08-03.
    ("ayakhafaji02@gmail.com", "Aya Al-Khafaji"),
]

# On the thread but NOT competing — leadership watching the board.
OBSERVERS: List[Tuple[str, str]] = [     # (email, name)
    ("pthomp2133@gmail.com", "Patrick Thompson"),
    ("tonycv1920@gmail.com", "Tony Chavez"),
    ("multani.business@gmail.com", "Sahil Multani"),
    ("parkwchan19@gmail.com", "Chan Park"),
    ("kweinraub@gmail.com", "Kenneth Weinraub"),
    ("jlieberman5m@gmail.com", "Jess Lieberman"),
    ("elitestrategicsolutions@gmail.com", "Wayne Rude"),
    ("starr.novamanagement@gmail.com", "Starr Rodenhurst"),
]

# Deliberately NOT in the group: alphaletereporting@ (it is the SENDER), and Raf
# + Megan (they stay on To/Cc, so the group is purely the audience).
SEED: List[Tuple[str, str]] = COMPETITORS + OBSERVERS


def seed_emails() -> List[str]:
    return [e for e, _ in SEED]


def missing_from_thread() -> List[str]:
    """Rostered competitors with no address here — they get no flyer."""
    from automations.owner_showdown import roster
    have = {n.strip().lower() for _, n in SEED}
    everyone = set(roster.SALES_ROSTER) | set(roster.REPCOUNT_ROSTER)
    return sorted(n for n in everyone if n.strip().lower() not in have)
