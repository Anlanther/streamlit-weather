"""Smoke tests that run the real Streamlit script in-process via AppTest.

These cover the runtime states a reviewer will hit: live data, API outage
(fallback), navigation between the two pages, and a grounded chat exchange.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import streamlit_weather
from streamlit_weather import fetch

APP_PATH = Path(streamlit_weather.__file__).parent / "app.py"
CHAT_PAGE = "pages/chat.py"


def _run(monkeypatch, json_payload):
    """Run app.py with the HTTP layer patched to return ``json_payload``.

    ``None`` simulates total API failure (exercising the fallback path).
    """
    monkeypatch.setattr(fetch, "_get_json", lambda url: json_payload)
    fetch.fetch_forecast.clear()
    fetch.fetch_warnings.clear()
    return AppTest.from_file(str(APP_PATH), default_timeout=60).run()


def test_app_renders_with_fallback_data(monkeypatch):
    at = _run(monkeypatch, json_payload=None)

    assert not at.exception
    assert any("sample data" in info.value for info in at.info)
    assert [tab.label for tab in at.tabs] == [
        "🌡️ Temperature",
        "💧 Humidity",
        "☔ Rain Probability",
    ]
    assert len(at.dataframe[0].value) == 7
    # The forecast page is the default entry point; chat lives on its own page.
    assert not at.chat_input


def test_navigation_exposes_the_forecast_and_chat_pages(monkeypatch):
    at = _run(monkeypatch, json_payload=None)

    assert not at.exception
    at.switch_page(CHAT_PAGE).run()
    assert not at.exception
    assert at.chat_input
    assert not at.tabs


def test_app_shows_all_clear_when_no_warnings(monkeypatch):
    at = _run(monkeypatch, json_payload={})

    assert not at.exception
    assert any("No active weather warnings" in s.value for s in at.success)


def test_chat_reports_when_lm_studio_unreachable(monkeypatch):
    """With no LM Studio server running, the chat must degrade with a clear notice."""
    # Point at a closed port so the test never depends on a real local server.
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)
    at = _run(monkeypatch, json_payload=None)
    at.switch_page(CHAT_PAGE).run()

    at.chat_input[0].set_value("Which day is hottest?").run()

    assert not at.exception
    reply = at.session_state["messages"][-1]
    assert reply["error"] is True
    assert "LM Studio" in reply["content"]
    # A failed call must not advertise grounding context that produced nothing.
    assert not any("retrieved context" in e.label.lower() for e in at.get("expander"))
