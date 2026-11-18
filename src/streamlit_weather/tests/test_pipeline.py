"""Unit tests for the data pipeline and chat plumbing (no network, no Streamlit)."""

import datetime as dt
import json

import pytest

from streamlit_weather import fetch, llm
from streamlit_weather import transform as tf


# --------------------------------------------------------------------------- #
# transform: PSR handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "label", "score"),
    [
        ("High", "High", 5),
        ("Medium High", "Medium High", 4),
        ("Medium", "Medium", 3),
        ("medium low", "Medium Low", 2),  # casing/whitespace normalised
        (" Low ", "Low", 1),
    ],
)
def test_psr_levels_normalised(raw, label, score):
    assert tf.normalize_psr(raw) == label
    assert tf.psr_score(raw) == score


@pytest.mark.parametrize("raw", [None, "", "Torrential", 3])
def test_psr_unknown_is_none(raw):
    assert tf.normalize_psr(raw) is None
    assert tf.psr_score(raw) is None


def test_psr_key_accepted_in_either_case():
    """The live API uses ``PSR``; the brief documents ``psr``."""
    frame = tf.build_forecast_frame(
        {
            "weatherForecast": [
                {"forecastDate": "20261119", "PSR": "High"},
                {"forecastDate": "20261120", "psr": "Low"},
            ]
        }
    )
    assert frame["psr"].tolist() == ["High", "Low"]
    assert frame["psr_score"].tolist() == [5, 1]


# --------------------------------------------------------------------------- #
# transform: dates and slicing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20261119", dt.date(2026, 11, 19)),
        ("2026-11-19", dt.date(2026, 11, 19)),
        ("garbage", None),
        ("", None),
        (None, None),
        (20261119, None),  # not a string
    ],
)
def test_parse_forecast_date(raw, expected):
    assert tf.parse_forecast_date(raw) == expected


def test_forecast_is_sliced_to_seven_sorted_days():
    payload = fetch._build_fallback_forecast()  # 9 days
    frame = tf.build_forecast_frame(payload)

    assert len(frame) == 7
    assert frame["date"].is_monotonic_increasing


# --------------------------------------------------------------------------- #
# transform: malformed input
# --------------------------------------------------------------------------- #
def test_missing_and_null_fields_degrade_to_nan():
    frame = tf.build_forecast_frame(
        {
            "weatherForecast": [
                {"forecastDate": "20261120", "forecastMaxtemp": {"value": None}, "psr": None},
                {"forecastDate": "20261121", "forecastMaxrh": None},
            ]
        }
    )
    assert frame["max_temp"].isna().all()
    assert frame["max_rh"].isna().all()
    assert frame["psr"].isna().all()


def test_non_dict_days_are_skipped():
    frame = tf.build_forecast_frame(
        {"weatherForecast": ["nope", None, {"forecastDate": "20261120"}]}
    )
    assert len(frame) == 1


def test_empty_payload_returns_empty_frames():
    frame = tf.build_forecast_frame({})
    assert frame.empty
    assert tf.build_display_frame(frame).empty
    assert tf.forecast_context_json(frame) == "[]"


# --------------------------------------------------------------------------- #
# transform: warnings
# --------------------------------------------------------------------------- #
def test_warning_title_and_first_sentence():
    payload = {
        "details": [
            {
                "warningStatementCode": "WRAIN",
                "subtype": "WRAINR",
                "updateTime": "2026-11-18T09:00:00+08:00",
                "contents": ["THE RED RAINSTORM WARNING SIGNAL IS STILL IN FORCE.", "More rain."],
            }
        ]
    }
    [summary] = tf.summarize_warnings(payload)

    assert summary["title"] == "Rainstorm Warning — Red"
    assert summary["summary"] == "THE RED RAINSTORM WARNING SIGNAL IS STILL IN FORCE."
    assert summary["severe"] is True


def test_unknown_warning_code_falls_back_to_code():
    [summary] = tf.summarize_warnings({"details": [{"warningStatementCode": "WXYZ"}]})
    assert summary["title"] == "WXYZ"
    assert summary["summary"] == "No further details provided."


def test_no_warnings_prompt_text():
    assert tf.warning_text_for_prompt([]) == "No active weather warnings."
    assert tf.warning_update_time([]) is None


def test_context_contains_forecast_json_and_warnings():
    frame = tf.build_forecast_frame(fetch._build_fallback_forecast())
    context = tf.build_context(frame, tf.summarize_warnings(fetch._build_fallback_warnings()))

    assert "ACTIVE WARNINGS:" in context
    assert "Rainstorm Warning — Red" in context

    # The embedded forecast must itself be valid JSON.
    embedded = context.split("FORECAST (next 7 days):\n", 1)[1].split("\n\nACTIVE WARNINGS:")[0]
    records = json.loads(embedded)
    assert len(records) == 7
    assert {"forecastDate", "PSR"} <= records[0].keys()


# --------------------------------------------------------------------------- #
# fetch: fallback behaviour
# --------------------------------------------------------------------------- #
def test_empty_warning_payload_means_all_clear():
    """HKO returns ``{}`` when nothing is active — not a failure."""
    assert fetch._is_valid_warnings({}) is True
    assert fetch._is_valid_warnings(None) is False
    assert fetch._is_valid_warnings({"details": "oops"}) is False


def test_forecast_validation_requires_days():
    assert fetch._is_valid_forecast({"weatherForecast": [{"forecastDate": "20261119"}]}) is True
    assert fetch._is_valid_forecast({"weatherForecast": []}) is False
    assert fetch._is_valid_forecast({}) is False


def test_fetch_forecast_falls_back_when_api_fails(monkeypatch):
    monkeypatch.setattr(fetch, "_get_json", lambda url: None)
    fetch.fetch_forecast.clear()

    payload, used_fallback = fetch.fetch_forecast()

    assert used_fallback is True
    assert len(tf.build_forecast_frame(payload)) == 7


def test_fetch_warnings_falls_back_when_api_fails(monkeypatch):
    monkeypatch.setattr(fetch, "_get_json", lambda url: None)
    fetch.fetch_warnings.clear()

    payload, used_fallback = fetch.fetch_warnings()

    assert used_fallback is True
    assert tf.summarize_warnings(payload)


def test_fetch_warnings_all_clear_is_not_fallback(monkeypatch):
    monkeypatch.setattr(fetch, "_get_json", lambda url: {})
    fetch.fetch_warnings.clear()

    payload, used_fallback = fetch.fetch_warnings()

    assert used_fallback is False
    assert tf.summarize_warnings(payload) == []


# --------------------------------------------------------------------------- #
# llm (local LM Studio backend)
# --------------------------------------------------------------------------- #
class _FakeClient:
    """Minimal stand-in for an OpenAI-compatible client talking to LM Studio."""

    def __init__(self, content="Grounded answer", error=None, models=("local-model",)):
        self.calls: list[dict] = []
        self._content = content
        self._error = error
        self._models = models
        # The openai client exposes capabilities as attributes on itself: the
        # real ``client.models.list()`` and ``client.chat.completions.create()``
        # both resolve against this object, so the fake mirrors that shape.
        self.chat = type("Chat", (), {"completions": self})()
        # ``client.models.list()`` is accessed on the client, not on ``chat``.
        self.models = type("ModelsAPI", (), {"list": self.list})()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        message = type("Msg", (), {"content": self._content})()
        return type("Resp", (), {"choices": [type("Choice", (), {"message": message})()]})

    def list(self):
        return type("Models", (), {"data": [type("M", (), {"id": m})() for m in self._models]})()


@pytest.fixture(autouse=True)
def _clean_lm_env(monkeypatch):
    """Keep ambient LM Studio configuration from leaking between tests."""
    for var in ("LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL", "LM_STUDIO_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_build_messages_includes_context_and_drops_errors():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "⚠️ failed", "error": True},
        {"role": "assistant", "content": "ok"},
    ]
    messages = llm.build_messages("now?", "CONTEXT-BLOB", history)

    assert messages[0]["role"] == "system"
    assert "CONTEXT-BLOB" in messages[0]["content"]
    assert "Answer ONLY using the provided forecast and warning data" in messages[0]["content"]
    assert [m["content"] for m in messages[1:]] == ["first", "ok", "now?"]


def test_build_messages_caps_history():
    history = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    messages = llm.build_messages("last", "ctx", history)
    assert len(messages) == 1 + llm.MAX_HISTORY_MESSAGES + 1


def test_base_url_defaults_and_normalises_trailing_slash(monkeypatch):
    assert llm.base_url() == "http://localhost:1234/v1"
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://192.168.1.50:1234/v1/")
    assert llm.base_url() == "http://192.168.1.50:1234/v1"


def test_client_points_at_lm_studio_without_real_key():
    client = llm.get_client()
    assert client is not None
    assert str(client.base_url).startswith("http://localhost:1234/v1")
    assert client.api_key == llm.DEFAULT_API_KEY


def test_api_key_is_overridable_from_the_environment(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_API_KEY", "s3cret")
    assert llm.api_key() == "s3cret"
    assert llm.get_client().api_key == "s3cret"


def test_model_is_auto_detected_from_server(monkeypatch):
    client = _FakeClient(models=("lmstudio-community/qwen2.5-7b-instruct",))
    assert llm.resolve_model(client) == "lmstudio-community/qwen2.5-7b-instruct"


def test_explicit_model_override_skips_discovery(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_MODEL", "my-model")
    client = _FakeClient(models=("other-model",))
    assert llm.resolve_model(client) == "my-model"


def test_resolve_model_none_when_nothing_loaded():
    assert llm.resolve_model(_FakeClient(models=())) is None


def test_answer_sends_grounded_messages_to_local_model():
    client = _FakeClient()
    text, is_error = llm.answer("q", "ctx", [], client=client)

    assert (text, is_error) == ("Grounded answer", False)
    sent = client.calls[0]
    assert sent["model"] == "local-model"
    assert sent["messages"][0]["role"] == "system"
    assert "ctx" in sent["messages"][0]["content"]
    assert sent["temperature"] == 0


def test_answer_reports_server_unreachable():
    client = _FakeClient(error=ConnectionError("Connection refused"))
    text, is_error = llm.answer("q", "ctx", [], client=client)

    assert is_error is True
    assert "LM Studio" in text
    assert "LM_STUDIO_BASE_URL" in text


def test_answer_does_not_call_model_when_none_loaded():
    client = _FakeClient(models=())
    text, is_error = llm.answer("q", "ctx", [], client=client)

    assert is_error is True
    assert "no model is loaded" in text
    assert client.calls == []  # never hit the completions endpoint
