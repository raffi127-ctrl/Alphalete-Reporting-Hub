"""The welcome-text copy.

Two placeholders:
  {name}    → the new hire's chosen first name (per recipient)
  {manager} → the manager sending it (set once per batch in preflight)

Kept as a single editable template so preflight can show/tweak the copy before
a batch goes out. Megan's approved direction (2026-07-13): fix the placeholder,
frame the attached photo as a sneak peek, add energy, end on a soft reply hook
(confirms the number + cuts Monday no-shows).
"""

from __future__ import annotations

DEFAULT_TEMPLATE = (
    "Hey {name}! This is {manager}, one of the managers at Alphalete "
    "Marketing 🐺 I was prepping for your orientation Monday and just wrapped "
    "up your welcome package! 👀 We're excited to have you starting with the "
    "team! If any questions come up before Monday, just let me know!"
)

# Same copy, with a "See you Monday at {time}!" line appended. {time} is filled
# per-recipient from the roster's Start Time column.
DEFAULT_TEMPLATE_WITH_TIME = DEFAULT_TEMPLATE + " See you at {time}!"


def render(name: str, template: str | None = None, manager: str = "",
           time: str = "") -> str:
    tmpl = template or DEFAULT_TEMPLATE
    # Fill whatever placeholders the template uses; extras are ignored, and a
    # template missing one of these just renders without it.
    try:
        return tmpl.format(name=name, manager=manager, time=time)
    except (KeyError, IndexError):
        return tmpl.replace("{name}", name)
