"""Daily 6am friendly weather alert for the Frisco, TX team → #alphalete-sales.

Pulls today's forecast from Open-Meteo (free, NO API key), writes a short,
friendly "prep for the day" message (via Claude, with a plain-template
fallback so it never hard-fails), and posts it to #alphalete-sales. Runs
unattended on the always-on Mac mini at 6am Central.

    python -m automations.weather_alert.run            # post to Slack
    python -m automations.weather_alert.run --dry-run  # print only, no post

Deps already in the venv: requests (Open-Meteo), anthropic (wording),
slack_sdk (posting, via automations.shared.slack_metrics_post).
Needs on the machine: the Slack user token
(~/.config/recruiting-report/slack-user-token) to post, and the Anthropic key
(~/.config/brand-audit/keys.json) for the nicer wording (falls back to a
template without it).
"""
from __future__ import annotations

import argparse
import sys

import requests

# DFW metro (coordinates: Frisco, TX)
LAT, LON = 33.1507, -96.8236
LOCATION = "DFW"
TZ = "America/Chicago"

# WMO weather codes → plain description (Open-Meteo's daily weather_code).
_WMO = {
    0: "clear and sunny", 1: "mostly sunny", 2: "partly cloudy", 3: "cloudy",
    45: "foggy", 48: "foggy", 51: "drizzly", 53: "drizzly", 55: "drizzly",
    61: "rainy", 63: "rainy", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "snowy", 73: "snowy", 75: "heavy snow",
    77: "snow grains", 80: "rain showers", 81: "rain showers",
    82: "heavy showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "severe thunderstorms",
}


def _fetch_forecast() -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
        "wind_speed_10m_max,weather_code"
        "&hourly=precipitation_probability,temperature_2m"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&timezone={TZ}&forecast_days=1"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fmt_hour(h: int) -> str:
    """24h int → '3pm' / '12pm' / '7am'."""
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}"


def _summarize(fc: dict) -> dict:
    daily = fc["daily"]
    hourly = fc.get("hourly", {})
    hi = round(daily["temperature_2m_max"][0])
    lo = round(daily["temperature_2m_min"][0])
    wind = round(daily["wind_speed_10m_max"][0])
    rain_prob = int(daily["precipitation_probability_max"][0] or 0)
    code = daily["weather_code"][0]
    conditions = _WMO.get(code, "mixed conditions")

    # Peak rain window (only call it out if it's a real chance).
    rain_time = None
    probs = hourly.get("precipitation_probability") or []
    times = hourly.get("time") or []
    if probs and times:
        peak_i = max(range(len(probs)), key=lambda i: probs[i] or 0)
        if (probs[peak_i] or 0) >= 30:
            try:
                rain_time = _fmt_hour(int(times[peak_i][11:13]))
            except Exception:
                rain_time = None
    return {
        "hi": hi, "lo": lo, "wind": wind, "rain_prob": rain_prob,
        "rain_time": rain_time, "conditions": conditions,
    }


def _facts_line(s: dict) -> str:
    parts = [f"{LOCATION} today: {s['conditions']}, high {s['hi']}°F / low {s['lo']}°F",
             f"wind up to {s['wind']} mph"]
    if s["rain_prob"] >= 30:
        when = f" around {s['rain_time']}" if s["rain_time"] else ""
        parts.append(f"{s['rain_prob']}% chance of rain{when}")
    return "; ".join(parts) + "."


# Fixed-layout message (Megan 2026-06-24):
#   <short funny Lucy greeting>
#   Temp: <hi> degrees
#   <condition line>
#
#   What to prepare:
#   <weather-driven prep items>
#   Water — always! 💧
#   <Lucy crush-it close>
# The structure is built in Python (always correct); Claude only writes the two
# VOICED lines (greeting + close), with a template fallback so it never hard-fails.

_WET_WORDS = ("storm", "thunder", "rain", "shower", "drizzle", "snow", "sleet")


def _is_wet(s: dict) -> bool:
    """Wet day if a meaningful rain chance OR the forecast condition itself is a
    precip type (the daily rain % can read low even when the weather code is
    thunderstorms — trust either signal)."""
    c = (s.get("conditions") or "").lower()
    return s["rain_prob"] >= 30 or any(w in c for w in _WET_WORDS)


def _condition_line(s: dict) -> str:
    c = s["conditions"]
    cap = c[0].upper() + c[1:] if c else "Mixed conditions"
    if _is_wet(s):
        return f"{cap} expected"
    return cap


def _prep_items(s: dict) -> list:
    items = []
    if _is_wet(s):
        items.append("Rain jacket / outer layer to peel off later")
    if s["hi"] >= 85:
        items.append("Light field clothes + hat & sunscreen to change into")
    elif s["hi"] <= 45:
        items.append("Warm layer to change into")
    items.append("Water — always! 💧")
    return items


def _assemble(greeting: str, s: dict, crush: str) -> str:
    lines = [greeting.strip(),
             f"Temp: {s['hi']} degrees",
             _condition_line(s),
             "",
             "What to prepare:"]
    lines += _prep_items(s)
    lines.append(crush.strip())
    return "\n".join(lines)


_FALLBACK_GREETING = "🐺 Morning, Dawgs — let's GO! ⚡"
_FALLBACK_CRUSH = "Now go turn those doors into SALES today! 🔥 — Lucy 🐾"


def _template_message(s: dict) -> str:
    """Plain fallback layout if Claude is unavailable — never hard-fails."""
    return _assemble(_FALLBACK_GREETING, s, _FALLBACK_CRUSH)


def _voiced_lines(s: dict) -> tuple:
    """Just the two Lucy-voiced lines (greeting, crush) from Claude; falls back
    to the template lines on any error so the post always goes out."""
    try:
        import anthropic
        from automations.brand_audit import credentials

        system = (
            "You ARE 'Lucy' — Alphalete's office dog turned HIGH-ENERGY D2D sales "
            "hype pup. Wolf-PACK energy (🐺⚡🔥🐾), Hormozi/Cardone closer intensity, "
            "for the hungry 20-something sales team. ABSOLUTELY NO PROFANITY — PG, "
            "all hype. Address the crew with ONE of these nicknames (mix it up day "
            "to day): Dawgs, Dogs, killers, killas, snicklepops, snicklepoppers, "
            "cats, catz. NEVER call them 'rep' or 'reps'. The work is knocking DOORS "
            "to make SALES — frame the rally around turning DOORS into SALES "
            "(closing, knocking), NEVER say 'leads'. PLAIN TEXT only: no markdown, "
            "no asterisks, no hashtags; ALL-CAPS for emphasis is fine."
        )
        user = (
            f"Today in {LOCATION}: high {s['hi']}F, {s['conditions']}, "
            f"rain chance {s['rain_prob']}%.\n\n"
            "Give EXACTLY two lines and nothing else:\n"
            "GREETING: one short, FUNNY, high-energy greeting from Lucy the office "
            "dog (8 words max, 1-2 emoji)\n"
            "CRUSH: one short 'go crush it today' rally close (8 words max), ending "
            "with the sign-off '— Lucy 🐾'"
        )
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()

        def _clean(v: str) -> str:
            return v.strip().strip("*").strip()

        greeting = crush = None
        for line in text.splitlines():
            ls = line.strip().lstrip("*-•").strip()
            low = ls.lower()
            if ":" in ls and low.startswith("greeting"):
                greeting = _clean(ls.split(":", 1)[1])
            elif ":" in ls and low.startswith("crush"):
                crush = _clean(ls.split(":", 1)[1])
        # Lenient fallback: model returned just two unlabeled lines.
        if not (greeting and crush):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if len(lines) == 2 and not any(
                    w in l.lower() for l in lines for w in ("greeting", "crush")):
                greeting, crush = _clean(lines[0]), _clean(lines[1])
        if greeting and crush:
            return greeting, crush
        print("[weather] Claude didn't return both lines — using template voice.",
              flush=True)
    except Exception as e:
        print(f"[weather] Claude wording unavailable ({type(e).__name__}: "
              f"{str(e)[:120]}) — using template.", flush=True)
    return _FALLBACK_GREETING, _FALLBACK_CRUSH


def _claude_message(s: dict) -> str:
    """Assemble the fixed-layout message with Lucy's two voiced lines."""
    greeting, crush = _voiced_lines(s)
    return _assemble(greeting, s, crush)


def main() -> int:
    ap = argparse.ArgumentParser(description="Post the daily Frisco weather alert "
                                             "to #alphalete-sales.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the message instead of posting to Slack.")
    args = ap.parse_args()

    try:
        fc = _fetch_forecast()
    except Exception as e:
        print(f"[weather] forecast fetch failed: {type(e).__name__}: {e}", flush=True)
        return 1
    s = _summarize(fc)
    msg = _claude_message(s)

    if args.dry_run:
        print("----- would post to #alphalete-sales -----")
        print(msg)
        print("------------------------------------------")
        return 0

    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        client.chat_postMessage(channel=smp.CHANNEL_ID, text=msg)
    except Exception as e:
        print(f"[weather] Slack post failed: {type(e).__name__}: {e}", flush=True)
        return 1
    print("[weather] posted to #alphalete-sales ✓", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
