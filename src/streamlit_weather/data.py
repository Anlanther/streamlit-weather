"""Streamlit-side data helpers shared by every page.

Kept separate from ``fetch`` so the network layer stays Streamlit-cache-only
and free of layout concerns, and separate from ``app`` so pages can import it
without running the dashboard.
"""

import pandas as pd
import streamlit as st

from streamlit_weather import fetch
from streamlit_weather import transform as tf

FALLBACK_NOTICE = "Showing cached sample data due to API unavailability."


def load() -> dict:
    """Fetch once, cache the derived frames, and return everything pages need.

    Streamlit's ``@st.cache_data`` is keyed per function, so pages that call
    this on every rerun still only parse the payload once per TTL window.
    """
    forecast_payload, forecast_is_fallback = fetch.fetch_forecast()
    warning_payload, warning_is_fallback = fetch.fetch_warnings()
    forecast_df, warning_summaries = _build_frames(forecast_payload, warning_payload)
    return {
        "forecast_payload": forecast_payload,
        "forecast_df": forecast_df,
        "warning_summaries": warning_summaries,
        "is_fallback": forecast_is_fallback or warning_is_fallback,
    }


@st.cache_data(ttl=fetch.CACHE_TTL_SECONDS, show_spinner=False)
def _build_frames(forecast_payload: dict, warning_payload: dict) -> tuple[pd.DataFrame, list[dict]]:
    forecast_df = tf.build_forecast_frame(forecast_payload, days=tf.FORECAST_DAYS)
    return forecast_df, tf.summarize_warnings(warning_payload)
