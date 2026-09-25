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
import time

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


# Open-Meteo is free/best-effort and occasionally throws a transient 503 or
# connection blip (2026-07-05: one 503 killed the whole 6am post). Retry a few
# times with backoff so a single upstream hiccup never eats the daily forecast.
_FETCH_RETRIES = 4
_FETCH_BACKOFF = (2, 5, 10)  # seconds between attempts 1→2, 2→3, 3→4


# EVERY ECO OFFICE GETS ITS OWN, in its own city, in the channel its
# SaraPlus alerts already land in (Megan 2026-09-25: "roll it out to all
# offices"). Cities were read off the zip codes in each office's knocks
# relay; DFW is fetched ONCE and shared by every DFW office (one pull, many
# channels). Add an office here when it enrolls; an office not listed, or
# with no approved alert channel, is skipped and named in the log.
CITIES = {
    "dfw": ("DFW", 33.1507, -96.8236, "America/Chicago"),
    "houston": ("Houston, TX", 29.7604, -95.3698, "America/Chicago"),
    "indianapolis": ("Indianapolis, IN", 39.7684, -86.1581, "America/New_York"),
    "miami": ("Hollywood / Miami, FL", 26.0112, -80.1495, "America/New_York"),
}
OFFICE_CITY = {
    "kash": "dfw", "cyrus": "dfw", "carlos": "dfw", "carlos-b2batt": "dfw",
    "ryan": "dfw", "khalil": "dfw", "khalil-nds": "dfw",
    "roshan": "houston", "aya": "indianapolis", "colten": "miami",
}


def _fetch_forecast(lat: float = LAT, lon: float = LON, tz: str = TZ) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
        "wind_speed_10m_max,weather_code"
        "&hourly=precipitation_probability,temperature_2m"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
        f"&timezone={tz}&forecast_days=1"
    )
    last_err: Exception | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            if attempt < _FETCH_RETRIES - 1:
                wait = _FETCH_BACKOFF[attempt]
                print(f"[weather] fetch attempt {attempt + 1} failed "
                      f"({type(e).__name__}: {e}); retrying in {wait}s", flush=True)
                time.sleep(wait)
    raise last_err  # exhausted retries — surface the last error to main()


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


def _condition_emoji(s: dict) -> str:
    """Header icon reflecting the actual sky."""
    c = (s.get("conditions") or "").lower()
    if "thunder" in c:
        return "⛈️"
    if "freezing" in c:
        return "🧊"
    if "snow" in c or "sleet" in c:
        return "❄️"
    if "rain" in c or "shower" in c or "drizzl" in c:
        return "🌧️"
    if "fog" in c:
        return "🌫️"
    if "partly" in c:
        return "⛅"
    if "cloud" in c:
        return "☁️"
    if "sunny" in c or "clear" in c:
        return "☀️"
    return "🌤️"


def _build_message(s: dict, city: str = LOCATION) -> str:
    """The plain daily forecast — no greeting, hype, nicknames, or sign-off.
    The city is in the header (Megan 2026-09-25) now that ten rooms get one."""
    return "\n".join([
        f"{_condition_emoji(s)} Today's Weather Forecast — {city}",
        f"🌡️ Temp: high {s['hi']}°F / low {s['lo']}°F",
        f"🌧️ Precipitation: {_precipitation(s)}",
        f"👕 Recommended dressing: {_recommended_dressing(s)}",
        f"🎒 Recommended to bring: {_recommended_bring(s)}",
    ])


def office_posts() -> list:
    """[(office_key, city_key, [channel_id, ...])] for every ECO office that
    has a city here AND an approved alert channel. Read-only."""
    from automations.icd_alerts import post as P
    approved = P.approved_channels()
    out = []
    for key, city in OFFICE_CITY.items():
        chans = [c.id for c in (approved.get(key) or [])]
        if chans:
            out.append((key, city, chans))
    return out


def post_offices(client, *, dry_run: bool, dfw_summary: dict | None = None) -> int:
    """One forecast per city, one post per office channel. Never raises: a
    room that fails is logged and the rest still get theirs. Returns how
    many posts went out (or would have)."""
    summaries = {"dfw": dfw_summary} if dfw_summary else {}
    sent, seen = 0, set()
    for key, city, chans in office_posts():
        label, lat, lon, tz = CITIES[city]
        if city not in summaries:
            try:
                summaries[city] = _summarize(_fetch_forecast(lat, lon, tz))
            except Exception as e:  # noqa: BLE001
                print(f"[weather] {label}: forecast fetch failed: {type(e).__name__}: {e}", flush=True)
                summaries[city] = None
        if not summaries[city]:
            continue
        msg = _build_message(summaries[city], label)
        for ch in chans:
            if ch in seen:            # two office keys, one room (Carlos, Khalil)
                continue
            seen.add(ch)
            if dry_run:
                print(f"----- would post to {ch} ({key}, {label}) -----\n{msg}", flush=True)
                sent += 1
                continue
            try:
                client.chat_postMessage(channel=ch, text=msg)
                print(f"[weather] posted {label} to {ch} ({key}) ✓", flush=True)
                sent += 1
            except Exception as e:  # noqa: BLE001
                print(f"[weather] {key} -> {ch} failed: {type(e).__name__}: {e}", flush=True)
    return sent


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
        post_offices(None, dry_run=True, dfw_summary=s)
        return 0

    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        client.chat_postMessage(channel=smp.CHANNEL_ID, text=msg)
        # Raf 8/23: the forecast also lands in #alphalete-lvl1-chat (best-effort —
        # a broken mirror never fails the primary post).
        for _dst in smp.mirror_channels(smp.CHANNEL_ID):
            try:
                client.chat_postMessage(channel=_dst, text=msg)
            except Exception as e:      # noqa: BLE001
                print(f"[weather] mirror to {_dst} failed: "
                      f"{type(e).__name__}: {e}", flush=True)
    except Exception as e:
        print(f"[weather] Slack post failed: {type(e).__name__}: {e}", flush=True)
        return 1
    print("[weather] posted to #alphalete-sales ✓", flush=True)
    # THE ECO OFFICES, after Raf's room and never instead of it: a failure
    # here is logged per room and does not touch the post above.
    try:
        post_offices(client, dry_run=False, dfw_summary=s)
    except Exception as e:  # noqa: BLE001
        print(f"[weather] office fan-out failed: {type(e).__name__}: {e}", flush=True)
    # Mark the "Lucy Weather Forecast" Hub card green when the 6am job (or a manual
    # run) posts — it runs on its own job, not the 4am batch, so nothing else marks
    # it. Best-effort: never fail the post over a Hub write.
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("weather_alert", "Lucy Weather Forecast",
                                 status="success")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
