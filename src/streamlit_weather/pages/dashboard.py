"""Forecast page: warnings banner, 7-day charts, and the summary table."""

import altair as alt
import streamlit as st

from streamlit_weather import data
from streamlit_weather import transform as tf
from streamlit_weather.helpers import page_icon

st.set_page_config(
    page_title="Forecast · Hong Kong Weather Dashboard",
    page_icon=page_icon(),
    layout="wide",
)

with st.spinner("Loading the latest HKO data…"):
    weather = data.load()

forecast_payload = weather["forecast_payload"]
forecast_df = weather["forecast_df"]
warning_summaries = weather["warning_summaries"]

if weather["is_fallback"]:
    st.info(data.FALLBACK_NOTICE)

# --------------------------------------------------------------------------- #
# 1. Warnings banner
# --------------------------------------------------------------------------- #
st.title("🌧️ Hong Kong Weather Dashboard")
st.caption("Live data from the Hong Kong Observatory Open Data API")

st.subheader("⚠️ Notable Weather Warnings")


def _render_warning(item: dict) -> None:
    """Render one warning as an error (severe) or warning block."""
    body = f"**{item['title']}**\n\n{item['summary']}"
    if item.get("update_time"):
        body += f"\n\n<small>Updated: {item['update_time']}</small>"
    (st.error if item["severe"] else st.warning)(body)


if warning_summaries:
    if len(warning_summaries) == 1:
        _render_warning(warning_summaries[0])
    else:
        # Side-by-side keeps multiple active signals visible without scrolling.
        columns = st.columns(min(len(warning_summaries), 2))
        for index, item in enumerate(warning_summaries):
            with columns[index % len(columns)]:
                _render_warning(item)

    latest_update = tf.warning_update_time(warning_summaries)
    st.caption(f"Last updated: {latest_update}" if latest_update else "Last updated: unknown")
else:
    st.success("No active weather warnings.")
    update_time = forecast_payload.get("updateTime")
    if isinstance(update_time, str) and update_time:
        st.caption(f"Last updated: {update_time}")

# --------------------------------------------------------------------------- #
# 2. 7-day forecast dashboard
# --------------------------------------------------------------------------- #
st.divider()
st.subheader(f"📅 {tf.FORECAST_DAYS}-Day Forecast")

if forecast_df.empty:
    st.warning("No usable forecast data is available right now.")
else:
    date_range = f"{forecast_df['date'].min():%Y-%m-%d} to {forecast_df['date'].max():%Y-%m-%d}"
    st.caption(f"{len(forecast_df)} days · {date_range}")

    chart_data = tf.build_chart_frame(forecast_df)
    date_axis = alt.Axis(format="%a %d %b", title=None, labelAngle=0)

    base = alt.Chart(chart_data).encode(
        x=alt.X("date:T", axis=date_axis),
        y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", title=None, sort=["max_temp", "min_temp", "max_rh", "min_rh"]),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%Y-%m-%d (%a)"),
            alt.Tooltip("series:N", title="Series"),
            alt.Tooltip("value:Q", title="Value"),
        ],
    )

    temp_tab, humidity_tab, rain_tab = st.tabs(
        ["🌡️ Temperature", "💧 Humidity", "☔ Rain Probability"]
    )

    with temp_tab:
        temp_chart = (
            base.transform_filter(alt.datum.series == "max_temp")
            .mark_line(point=True)
            .properties(title="Max temperature (°C)", height=320)
        )
        min_temp_chart = (
            base.transform_filter(alt.datum.series == "min_temp")
            .mark_line(point=True)
            .properties(title="Min temperature (°C)", height=320)
        )
        st.altair_chart((temp_chart + min_temp_chart).resolve_scale(color="shared"))

    with humidity_tab:
        humidity_chart = (
            base.transform_filter(
                alt.FieldOneOfPredicate(field="series", oneOf=["max_rh", "min_rh"])
            )
            .mark_line(point=True)
            .properties(title="Relative humidity (%)", height=320)
        )
        st.altair_chart(humidity_chart.resolve_scale(color="shared"))

    with rain_tab:
        rain_data = forecast_df.dropna(subset=["psr_score"])
        if rain_data.empty:
            st.info("No rain probability (PSR) data is available for the coming days.")
        else:
            rain_chart = (
                alt.Chart(rain_data)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                .encode(
                    x=alt.X(
                        "date:T",
                        axis=alt.Axis(format="%a %d %b", title=None, labelAngle=0),
                    ),
                    y=alt.Y(
                        "psr_score:Q",
                        title="Rain probability",
                        scale=alt.Scale(domain=[0, 5]),
                        axis=alt.Axis(
                            values=[1, 2, 3, 4, 5],
                            labelExpr=(
                                "datum.value == 1 ? 'Low' : datum.value == 2 ? 'Medium Low' : "
                                "datum.value == 3 ? 'Medium' : datum.value == 4 ? 'Medium High' : "
                                "datum.value == 5 ? 'High' : ''"
                            ),
                        ),
                    ),
                    color=alt.Color(
                        "psr:N",
                        title="Rain probability",
                        scale=alt.Scale(domain=list(tf.PSR_LABELS.values()), range=tf.PSR_COLORS),
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format="%Y-%m-%d (%a)"),
                        alt.Tooltip("psr:N", title="Probability of significant rain"),
                    ],
                )
                .properties(title="Probability of significant rain (PSR)", height=320)
            )
            st.altair_chart(rain_chart)

    st.dataframe(
        tf.build_display_frame(forecast_df),
        width="stretch",
        hide_index=True,
        column_config={
            "Max Temp": st.column_config.NumberColumn("Max Temp (°C)", format="%d"),
            "Min Temp": st.column_config.NumberColumn("Min Temp (°C)", format="%d"),
            "Max Humidity": st.column_config.NumberColumn("Max Humidity (%)", format="%d"),
            "Min Humidity": st.column_config.NumberColumn("Min Humidity (%)", format="%d"),
        },
    )

    general_situation = forecast_payload.get("generalSituation")
    if isinstance(general_situation, str) and general_situation.strip():
        with st.expander("General situation"):
            st.write(general_situation)
