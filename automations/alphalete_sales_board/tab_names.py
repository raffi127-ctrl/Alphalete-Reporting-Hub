"""Finding a week's tab whatever way its date was typed.

Tabs are named by the week's Sunday, 'Sales Board WE 11.1' / 'Line Up WE 11.1',
and a person may name one 'Sales Board WE 11.01' (Eve 2026-11-01: that one zero
stopped the sweep, which asked for the exact name). Same week, same tab. Only
the date's leading zeros are ignored, so 'SANDBOX — Sales Board WE 11.1' stays a
different tab.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

_LEADING_ZERO = re.compile(r"(?<![\d.])0+(?=\d)|(?<=\.)0+(?=\d)")


def key(title: str) -> str:
    """'Sales Board WE 11.01 ' -> 'sales board we 11.1'."""
    return _LEADING_ZERO.sub("", " ".join(str(title).split()).lower())


def find(titles: Iterable[str], want: str) -> Optional[str]:
    """The real title of tab `want`, or None. The exact name wins if both exist."""
    titles = list(titles)
    if want in titles:
        return want
    return next((t for t in titles if key(t) == key(want)), None)
