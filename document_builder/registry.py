"""Registry of documents the builder can generate.

Each Generator declares the inputs it needs (so the web form renders itself)
and a build() that writes a PDF to a path. To add a new document later, write
its generator module, then append one Generator entry here.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Make the repo root importable so generators can pull in the report modules
# (e.g. automations.orientation_packet.build) when this runs on Streamlit Cloud.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass
class Field:
    """One input on the form (or a display-only section / example image)."""
    key: str
    label: str
    kind: str                 # text|color|logo|select|section
    default: str = ""
    required: bool = True
    help: str = ""
    options: tuple = ()       # for kind="select"
    image: str = ""           # example image path (for kind="section")


@dataclass
class Generator:
    key: str
    label: str
    description: str
    fields: list
    build: Callable           # (inputs: dict, out_path: str) -> str
    filename: Callable        # (inputs: dict) -> str
    accent_note: str = ""


# --------------------------------------------------------------------------
# Orientation Packet
# --------------------------------------------------------------------------
def _orientation_build(inputs: dict, out_path: str) -> str:
    from automations.orientation_packet.build import build_pdf, Brand
    brand = Brand.from_args(
        primary=inputs.get("primary") or None,
        accent=inputs.get("accent") or None,
        dark=None,
    )
    schedule = {k: v for k, v in inputs.items()
                if k.startswith(("office_", "field_"))}
    build_pdf(
        out_path,
        company=inputs.get("company") or None,
        owner=inputs.get("owner") or None,
        location=inputs.get("location") or None,
        brand=brand,
        logo_path=inputs.get("logo_path"),
        use_default_logo=False,      # never fall back to the Alphalete mark
        upline=inputs.get("upline") or None,
        backend=inputs.get("backend") or None,
        schedule=schedule,
    )
    return out_path


_SCHED_IMG = str(REPO_ROOT / "resources" / "schedule-example.png")
_UPLINE_IMG = str(REPO_ROOT / "resources" / "upline-example.png")
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

# default schedule template shown pre-filled in the per-day grid
SCHED_DEFAULTS = {
    "office": {"MON": "11:00 – 12:30 PM", "TUE": "11:00 – 12:30 PM",
               "WED": "11:00 – 12:30 PM", "THU": "11:00 – 12:30 PM",
               "FRI": "11:00 – 12:30 PM", "SAT": "9:00 – 10:00 AM",
               "SUN": "OFF"},
    "field": {"MON": "1:30 – 8:30 PM", "TUE": "1:30 – 8:30 PM",
              "WED": "1:30 – 8:30 PM", "THU": "1:30 – 8:30 PM",
              "FRI": "1:30 – 8:30 PM", "SAT": "9:45 AM – 5:00 PM",
              "SUN": "OFF"},
}


def _safe(name: str) -> str:
    return "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip()


ORIENTATION = Generator(
    key="orientation_packet",
    label="Orientation Packet",
    description="Your company's branded new-hire orientation manual "
                "(23 pages) — welcome letter, schedule, comp, 9 core steps, "
                "sales system, dress code, and more.",
    fields=[
        Field("company", "Company name", "text",
              help="e.g. Alphalete Marketing"),
        Field("owner", "ICD Name", "text",
              help="The ICD / office owner's name — appears in the packet."),
        Field("location", "Office location (City, ST)", "text",
              help="e.g. Irving, TX"),
        Field("logo", "Company logo (PNG, JPG, or WebP)", "logo",
              required=True,
              help="Don't have the file? Go to your company website, "
                   "right-click your logo, and choose “Save image "
                   "as…” to your Downloads, then attach it here. A "
                   "transparent PNG looks best; WebP is auto-converted."),
        Field("primary", "Primary brand color", "color", default="#9E1B2E",
              help="Auto-picked from your logo — change it if you like."),
        Field("accent", "Accent color", "color", default="#B8965A",
              required=False,
              help="Auto-picked from your logo — change it if you like."),

        Field("schedule", "Your office schedule", "schedule", image=_SCHED_IMG,
              help="Set the Office and Field hours for each day. Type the "
                   "hours (e.g. 11:00 – 12:30 PM) or “OFF” to mark a "
                   "day off."),

        Field("_upline", "Upline & backend support", "section",
              image=_UPLINE_IMG,
              help="The two circled names are what you're replacing: the "
                   "left circle is your office's upline leadership, the right "
                   "is backend support. If it's just you, fill in only the "
                   "upline name and leave backend support blank."),
        Field("upline", "Your upline leadership (often ICD of office)", "text",
              default="",
              help="The leader(s) the new hire reports up to. e.g. Raf"),
        Field("backend", "Backend support", "text", default="", required=False,
              help="Who provides backend support — one or more names. Leave "
                   "blank if it's just you. e.g. JD"),
    ],
    build=_orientation_build,
    filename=lambda i: f"{_safe(i.get('company') or 'Company')} "
                       f"Orientation Packet.pdf",
)


# Every document the builder offers. Append here to add more.
GENERATORS = [ORIENTATION]


def by_label() -> dict:
    return {g.label: g for g in GENERATORS}
