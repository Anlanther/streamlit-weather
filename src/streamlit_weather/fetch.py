"""Data access layer for the Hong Kong Observatory (HKO) Open Data API.

Everything network-facing lives here: endpoint URLs, caching, JSON validation,
and fallback data used when the API is unreachable or returns garbage.
"""

import copy
import datetime as dt
import logging

import requests
import streamlit as st

logger = logging.getLogger(__name__)

FORECAST_URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=fnd&lang=en"
WARNING_URL = (
    "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warningInfo&lang=en"
)

# HKO updates the 9-day forecast a few times per day, and warnings are only
# issued/changed when the weather changes. A 10 minute TTL keeps the app fresh
# without hammering the public endpoint on every Streamlit rerun.
CACHE_TTL_SECONDS = 600
REQUEST_TIMEOUT_SECONDS = 10

# Relative dates are computed at read time (not import time) so the sample data
# never goes stale no matter when the app is started.
_FALLBACK_PSR = ["Medium", "Medium High", "High", "Medium", "Medium Low", "Low", "Low"]
_FALLBACK_MAXTEMP = [24, 24, 23, 22, 24, 26, 27]
_FALLBACK_MINTEMP = [19, 19, 18, 18, 20, 21, 22]
_FALLBACK_MAXRH = [85, 88, 90, 80, 75, 70, 72]
_FALLBACK_MINRH = [65, 68, 72, 60, 55, 50, 52]
_FALLBACK_CONDITIONS = [
    "Mainly cloudy with one or two light rain patches.",
    "Cloudy with a few rain patches and isolated thunderstorms.",
    "Overcast with rain, heavy at times.",
    "Cloudy with patches of rain easing off later.",
    "Sunny intervals and a few showers.",
    "Mainly fine and warm.",
    "Fine and dry.",
]

_WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _build_fallback_forecast() -> dict:
    """Return a 9-day sample forecast shaped like the real HKO payload.

    The payload deliberately mirrors the API's structure (including its
    capitalised ``PSR`` key) so downstream code cannot tell the difference.
    """
    today = dt.date.today()
    forecast = []
    for offset in range(9):
        day = today + dt.timedelta(days=offset)
        # Only the first 7 days have realistic numbers; the last 2 exist purely
        # so the "slice to 7 days" logic is exercised in fallback mode too.
        idx = min(offset, len(_FALLBACK_MAXTEMP) - 1)
        forecast.append(
            {
                "forecastDate": day.strftime("%Y%m%d"),
                "week": _WEEKDAYS[day.weekday()],
                "forecastWind": "East to northeast force 3 to 4.",
                "forecastWeather": _FALLBACK_CONDITIONS[idx],
                "forecastMaxtemp": {"value": _FALLBACK_MAXTEMP[idx], "unit": "C"},
                "forecastMintemp": {"value": _FALLBACK_MINTEMP[idx], "unit": "C"},
                "forecastMaxrh": {"value": _FALLBACK_MAXRH[idx], "unit": "percent"},
                "forecastMinrh": {"value": _FALLBACK_MINRH[idx], "unit": "percent"},
                "ForecastIcon": 54,
                "PSR": _FALLBACK_PSR[idx],
            }
        )

    return {
        "generalSituation": (
            "A broad trough of low pressure is bringing cloudy weather and a few "
            "showers to the south China coast. (Sample data.)"
        ),
        "weatherForecast": forecast,
        "updateTime": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _build_fallback_warnings() -> dict:
    """Return a single sample warning shaped like the real HKO payload."""
    return {
        "details": [
            {
                "warningStatementCode": "WRAIN",
                "subtype": "WRAINR",
                "updateTime": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "contents": [
                    "THE RED RAINSTORM WARNING SIGNAL IS STILL IN FORCE. "
                    "(Sample data shown because the HKO API was unavailable.)",
                    "Heavy rain has fallen over the territory and more rain is expected.",
                ],
            }
        ]
    }


def _get_json(url: str) -> dict | None:
    """Fetch ``url`` and return a parsed JSON object, or ``None`` on any failure.

    Handles network errors, non-2xx responses, non-JSON bodies, and JSON that is
    not an object (e.g. ``[]`` or ``"error"``). Errors are logged rather than
    raised so callers can fall back gracefully.
    """
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("Request to %s failed: %s", url, exc)
        return None
    except ValueError as exc:  # includes json.JSONDecodeError
        logger.warning("Invalid JSON from %s: %s", url, exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("Unexpected JSON type from %s: %s", url, type(payload).__name__)
        return None

    return payload


def _is_valid_forecast(payload: dict | None) -> bool:
    """A usable forecast needs a non-empty list of day objects under ``weatherForecast``."""
    if not payload:
        return False
    days = payload.get("weatherForecast")
    return isinstance(days, list) and len(days) > 0 and all(isinstance(d, dict) for d in days)


def _is_valid_warnings(payload: dict | None) -> bool:
    """Check that a warning payload is structurally usable.

    HKO returns a bare ``{}`` (no ``details`` key at all) when no warnings are
    active. That is a *successful* response meaning "all clear", not a failure,
    so a missing ``details`` key is treated as an empty warning list. A present
    ``details`` value must still be a list of objects.
    """
    if payload is None:
        return False
    details = payload.get("details", [])
    return isinstance(details, list) and all(isinstance(d, dict) for d in details)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_forecast() -> tuple[dict, bool]:
    """Return ``(forecast_payload, used_fallback)``.

    The second element lets the UI warn the user when sample data is shown.
    """
    payload = _get_json(FORECAST_URL)
    if _is_valid_forecast(payload):
        return payload, False

    logger.warning("Falling back to sample forecast data.")
    return copy.deepcopy(_build_fallback_forecast()), True


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_warnings() -> tuple[dict, bool]:
    """Return ``(warning_payload, used_fallback)``.

    A successful response with no active warnings returns ``({}, False)`` (or
    ``({"details": []}, False)``) — that is *not* a failure and must not trigger
    the fallback sample warning.
    """
    payload = _get_json(WARNING_URL)
    if _is_valid_warnings(payload):
        return payload, False

    logger.warning("Falling back to sample warning data.")
    return copy.deepcopy(_build_fallback_warnings()), True
