"""Hong Kong Weather Dashboard — Streamlit navigation shell.

Declares the sidebar navigation and the pages it can open:

  * ``pages/dashboard.py`` — warnings banner, charts, and forecast table
  * ``pages/chat.py``      — grounded chat constrained to the fetched data

Each page is a standalone script that pulls data via ``data.load()``, so the
chat page never pays the cost of redrawing charts and vice versa.
"""

import streamlit as st

from streamlit_weather.helpers import page_icon

st.set_page_config(
    page_title="Hong Kong Weather Dashboard",
    page_icon=page_icon(),
    layout="wide",
)

pages = [
    st.Page("pages/dashboard.py", title="Forecast", icon="📅", default=True),
    st.Page("pages/chat.py", title="Ask About the Forecast", icon="💬", url_path="ask"),
]

st.navigation(pages).run()
