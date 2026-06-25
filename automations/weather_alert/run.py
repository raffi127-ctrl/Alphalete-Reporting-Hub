"""Daily 6am weather forecast for the DFW team → #alphalete-sales.

Pulls today's forecast from Open-Meteo (free, NO API key) and posts a plain,
matter-of-fact forecast — temp, precipitation, what to wear, what to bring —
to #alphalete-sales. Runs unattended on the always-on Mac mini at 6am Central.

    python -m automations.weather_alert.run            # post to Slack
    python -m automations.weather_alert.run --dry-run  # print only, no post

Deps already in the venv: requests (Open-Meteo), slack_sdk (posting, via
automations.shared.slack_metrics_post). Needs on the machine: the Slack user
token (~/.config/recruiting-report/slack-user-token) to post.
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


# ---- Plain, matter-of-fact forecast (Megan 2026-06-24: dropped the Lucy hype) ----
# Layout, fully Python-built (no AI, no greeting/sign-off):
#   Today's Weather Forecast
#   Temp: high <hi>°F / low <lo>°F
#   Precipitation: <chance + time + type, or "none expected">
#   Recommended dressing: <weather-driven>
#   Recommended to bring: <water / sunscreen / umbrella / bug spray>

_WET_WORDS = ("storm", "thunder", "rain", "shower", "drizzle", "snow", "sleet")


def _precip_type(s: dict) -> str:
    """The precip word from the forecast conditions, if any (else '')."""
    c = (s.get("conditions") or "").strip().lower()
    return c if any(w in c for w in _WET_WORDS) else ""


def _is_wet(s: dict) -> bool:
    """Bring-rain-gear trigger: a real (>=30%) chance of precip. The condition
    code can read 'thunderstorms' at a 2% chance — we don't push rain gear for
    that; it shows as 'isolated' in the precipitation line instead."""
    return s["rain_prob"] >= 30


def _precipitation(s: dict) -> str:
    kind = _precip_type(s)
    when = f" around {s['rain_time']}" if s.get("rain_time") else ""
    if s["rain_prob"] >= 30:
        return f"{s['rain_prob']}% chance{when}, {kind or 'rain'}"
    if kind:
        return f"{s['rain_prob']}% chance (isolated {kind})"
    return "none expected"


def _recommended_dressing(s: dict) -> str:
    if s["hi"] >= 85:
        base = "light field clothes, hat & sunscreen"
    elif s["hi"] <= 45:
        base = "warm layers"
    else:
        base = "standard field clothes"
    if _is_wet(s):
        base += "; rain jacket / outer layer"
    return base


def _recommended_bring(s: dict) -> str:
    items = ["water"]
    if not _is_wet(s) and s["hi"] >= 75:
        items.append("sunscreen")
    if _is_wet(s):
        items.append("umbrella")
    if s["hi"] >= 75:
        items.append("bug spray")
    return ", ".join(items)


def _build_message(s: dict) -> str:
    """The plain daily forecast — no greeting, hype, nicknames, or sign-off."""
    return "\n".join([
        "Today's Weather Forecast",
        f"Temp: high {s['hi']}°F / low {s['lo']}°F",
        f"Precipitation: {_precipitation(s)}",
        f"Recommended dressing: {_recommended_dressing(s)}",
        f"Recommended to bring: {_recommended_bring(s)}",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description="Post the daily DFW weather forecast "
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
    msg = _build_message(s)

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
