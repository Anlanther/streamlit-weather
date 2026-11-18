"""Data cleaning and reshaping for the HK Weather Dashboard.

The HKO API is loosely typed and occasionally sparse: values are nested under
``{"value": .., "unit": ..}``, keys are inconsistently capitalised (``PSR``),
and individual fields can be missing or null. Everything in this module is
defensive and never raises on a malformed day — it degrades to ``None`` instead.
"""

import datetime as dt
import json
from typing import Any

import pandas as pd

# Ordered rain-probability levels, lowest to highest, mapped to a numeric score
# for charting. The HKO codes are "Low", "Medium Low", "Medium", "Medium High"
# and "High"; variants are normalised (case/whitespace) before lookup.
PSR_SCORES: dict[str, int] = {
    "low": 1,
    "medium low": 2,
    "medium": 3,
    "medium high": 4,
    "high": 5,
}

# Human-friendly labels retained for display, keyed by normalised value.
PSR_LABELS: dict[str, str] = {
    "low": "Low",
    "medium low": "Medium Low",
    "medium": "Medium",
    "medium high": "Medium High",
    "high": "High",
}

PSR_COLORS = ["#3b82f6", "#22c55e", "#eab308", "#f97316", "#ef4444"]

FORECAST_DAYS = 7

WARNING_NAMES: dict[str, str] = {
    "WRAIN": "Rainstorm Warning",
    "WTCSGNL": "Tropical Cyclone Warning Signal",
    "WHOT": "Very Hot Weather Warning",
    "WCOLD": "Cold Weather Warning",
    "WFROST": "Frost Warning",
    "WFIRE": "Fire Danger Warning",
    "WTS": "Thunderstorm Warning",
    "WL": "Landslip Warning",
    "WMSGNL": "Strong Monsoon Signal",
    "WTMW": "Tsunami Warning",
    "WSS": "Special Announcement on Flooding in the northern New Territories",
}

# Codes where an active warning warrants a red (severe) banner rather than amber.
_SEVERE_CODES = {"WRAIN", "WTCSGNL", "WL", "WTMW"}

# Rainstorm / fire danger subtypes need the colour in the human-readable name.
_SUBTYPE_LABELS: dict[str, str] = {
    "WRAINR": "Red",
    "WRAINB": "Black",
    "WRAINW": "Amber",
    "WFIREY": "Yellow",
    "WFIRER": "Red",
    "WTCSGNL1": "No. 1",
    "WTCSGNL3": "No. 3",
    "WTCSGNL8NE": "No. 8 Northeast",
    "WTCSGNL8SE": "No. 8 Southeast",
    "WTCSGNL8SW": "No. 8 Southwest",
    "WTCSGNL8NW": "No. 8 Northwest",
    "WTCSGNL9": "No. 9",
    "WTCSGNL10": "No. 10",
}


def _nested_value(container: Any) -> Any:
    """Extract a number from ``{"value": 21, "unit": "C"}``, a bare number, or None."""
    if isinstance(container, dict):
        return container.get("value")
    if isinstance(container, (int, float)):
        return container
    return None


def _as_int(value: Any) -> int | None:
    """Best-effort int conversion; returns None for missing/garbage input."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except TypeError, ValueError:
        return None


def parse_forecast_date(raw: Any) -> dt.date | None:
    """Parse HKO's ``YYYYMMDD`` (or ``YYYY-MM-DD``) date strings."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    cleaned = raw.strip().replace("-", "")
    try:
        return dt.datetime.strptime(cleaned, "%Y%m%d").date()
    except ValueError:
        return None


def normalize_psr(raw: Any) -> str | None:
    """Normalise a ``PSR`` string into a canonical label, or None if unknown."""
    if not isinstance(raw, str):
        return None
    return PSR_LABELS.get(raw.strip().lower())


def psr_score(label: Any) -> int | None:
    """Convert a PSR label (or raw API string) to its 1–5 numeric score."""
    normalised = normalize_psr(label)
    return PSR_SCORES.get(normalised.lower()) if normalised else None


def get_psr(raw: dict) -> Any:
    """Read the rain probability from a forecast object.

    The live API uses ``PSR``; the documented/spec name is ``psr``. Accept both
    (plus casing variants) so the parser is resilient to either.
    """
    for key in ("PSR", "psr", "Psr"):
        if key in raw:
            return raw[key]
    for key, value in raw.items():
        if isinstance(key, str) and key.strip().lower() == "psr":
            return value
    return None


def build_forecast_frame(forecast_payload: dict, days: int = FORECAST_DAYS) -> pd.DataFrame:
    """Shape the raw forecast payload into a tidy, chart-ready DataFrame.

    Drops entries with unparseable dates, sorts chronologically, and keeps only
    the next ``days`` days. Missing values become ``NaN`` (represented as None
    downstream) instead of crashing the chart.

    Columns: ``date``, ``week``, ``condition``, ``max_temp``, ``min_temp``,
    ``max_rh``, ``min_rh``, ``psr``, ``psr_score``.
    """
    raw_days = (
        forecast_payload.get("weatherForecast") if isinstance(forecast_payload, dict) else None
    )
    if not isinstance(raw_days, list):
        raw_days = []

    rows: list[dict] = []
    for raw in raw_days:
        if not isinstance(raw, dict):
            continue
        date = parse_forecast_date(raw.get("forecastDate"))
        if date is None:
            continue

        psr_label = normalize_psr(get_psr(raw))
        condition = raw.get("forecastWeather")
        rows.append(
            {
                "date": date,
                "week": raw.get("week") or date.strftime("%a"),
                "condition": condition.strip() if isinstance(condition, str) else None,
                "max_temp": _as_int(_nested_value(raw.get("forecastMaxtemp"))),
                "min_temp": _as_int(_nested_value(raw.get("forecastMintemp"))),
                "max_rh": _as_int(_nested_value(raw.get("forecastMaxrh"))),
                "min_rh": _as_int(_nested_value(raw.get("forecastMinrh"))),
                "psr": psr_label,
                "psr_score": PSR_SCORES.get(psr_label.lower()) if psr_label else None,
            }
        )

    columns = [
        "date",
        "week",
        "condition",
        "max_temp",
        "min_temp",
        "max_rh",
        "min_rh",
        "psr",
        "psr_score",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)

    frame = pd.DataFrame(rows).sort_values("date").head(days).reset_index(drop=True)

    # Use real datetimes so Altair renders a proper, evenly spaced time axis.
    frame["date"] = pd.to_datetime(frame["date"])
    for col in ("max_temp", "min_temp", "max_rh", "min_rh", "psr_score"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    return frame[columns]


def build_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename/format the forecast frame for the compact ``st.dataframe`` table."""
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "Date",
                "Max Temp",
                "Min Temp",
                "Max Humidity",
                "Min Humidity",
                "Rain Probability",
            ]
        )

    display = pd.DataFrame(
        {
            "Date": frame["date"].dt.strftime("%Y-%m-%d (%a)"),
            "Max Temp": frame["max_temp"],
            "Min Temp": frame["min_temp"],
            "Max Humidity": frame["max_rh"],
            "Min Humidity": frame["min_rh"],
            "Rain Probability": frame["psr"].fillna("N/A"),
        }
    )
    return display


def build_chart_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Melt the forecast frame into long format for multi-series line charts."""
    if frame.empty:
        return pd.DataFrame(columns=["date", "series", "value"])

    melted = frame.melt(
        id_vars=["date"],
        value_vars=["max_temp", "min_temp", "max_rh", "min_rh"],
        var_name="series",
        value_name="value",
    ).dropna(subset=["value"])
    return melted


def _first_sentence(text: Any) -> str:
    """Return the first sentence of ``text`` (falls back to the whole string)."""
    if not isinstance(text, str):
        return ""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    for terminator in (". ", "! ", "? "):
        head, sep, _ = cleaned.partition(terminator)
        if sep:
            return head.strip() + terminator.strip()
    return cleaned


def warning_title(detail: dict) -> str:
    """Build a human-readable warning name from its code and subtype."""
    if not isinstance(detail, dict):
        return "Weather Warning"

    code = str(detail.get("warningStatementCode") or "").strip().upper()
    subtype = str(detail.get("subtype") or "").strip().upper()

    base = WARNING_NAMES.get(code, code or "Weather Warning")
    subtype_label = _SUBTYPE_LABELS.get(subtype)
    if subtype_label:
        return f"{base} — {subtype_label}"
    return base


def is_severe(detail: dict) -> bool:
    """True when a warning should be rendered as an ``st.error`` (vs ``st.warning``)."""
    if not isinstance(detail, dict):
        return False
    code = str(detail.get("warningStatementCode") or "").strip().upper()
    subtype = str(detail.get("subtype") or "").strip().upper()
    return code in _SEVERE_CODES or subtype in {
        "WRAINB",
        "WRAINR",
        "WTCSGNL9",
        "WTCSGNL10",
    }


def summarize_warnings(warning_payload: dict) -> list[dict]:
    """Turn the raw warning payload into display-ready records.

    Each record has ``title``, ``summary`` (first sentence), ``update_time``,
    ``severe``, and ``code``. Entries with no usable text are still shown with
    their title so a warning is never silently hidden.
    """
    details = warning_payload.get("details") if isinstance(warning_payload, dict) else None
    if not isinstance(details, list):
        return []

    summaries: list[dict] = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        contents = detail.get("contents")
        if isinstance(contents, str):
            text = contents
        elif isinstance(contents, list):
            text = " ".join(part for part in contents if isinstance(part, str))
        else:
            text = ""

        update_time = detail.get("updateTime")
        summaries.append(
            {
                "title": warning_title(detail),
                "summary": _first_sentence(text) or "No further details provided.",
                "update_time": (update_time.strip() if isinstance(update_time, str) else None),
                "severe": is_severe(detail),
                "code": str(detail.get("warningStatementCode") or "").strip().upper(),
            }
        )
    return summaries


def warning_update_time(summaries: list[dict]) -> str | None:
    """Return the most recent ``updateTime`` across all active warnings."""
    times = [s["update_time"] for s in summaries if s.get("update_time")]
    return max(times) if times else None


def warning_text_for_prompt(summaries: list[dict]) -> str:
    """Flatten active warnings into plain text for the LLM system prompt."""
    if not summaries:
        return "No active weather warnings."
    lines = []
    for item in summaries:
        line = f"- {item['title']}: {item['summary']}"
        if item.get("update_time"):
            line += f" (updated {item['update_time']})"
        lines.append(line)
    return "\n".join(lines)


def forecast_context_json(frame: pd.DataFrame) -> str:
    """Serialise the 7-day forecast as pretty JSON for grounding and display."""
    records = []
    if not frame.empty:
        for _, row in frame.iterrows():
            records.append(
                {
                    "forecastDate": row["date"].strftime("%Y-%m-%d"),
                    "week": row["week"],
                    "condition": row["condition"],
                    "forecastMaxtemp": _nullable_int(row["max_temp"]),
                    "forecastMintemp": _nullable_int(row["min_temp"]),
                    "forecastMaxrh": _nullable_int(row["max_rh"]),
                    "forecastMinrh": _nullable_int(row["min_rh"]),
                    "PSR": row["psr"] or None,
                }
            )
    return json.dumps(records, indent=2, ensure_ascii=False)


def _nullable_int(value: Any) -> int | None:
    """Convert a pandas numeric cell (possibly NaN) to ``int`` or ``None``."""
    if pd.isna(value):
        return None
    return int(value)


def build_context(frame: pd.DataFrame, summaries: list[dict]) -> str:
    """Assemble the exact grounding snapshot shown to the user and the LLM.

    Identical in both places on purpose: what the model sees is exactly what the
    user can inspect in the "Show retrieved context" expander.
    """
    return (
        "FORECAST (next 7 days):\n"
        f"{forecast_context_json(frame)}\n\n"
        "ACTIVE WARNINGS:\n"
        f"{warning_text_for_prompt(summaries)}"
    )
