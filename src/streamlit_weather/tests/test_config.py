"""Unit tests for the ``.env`` configuration loader (no network, no Streamlit)."""

import pytest

from streamlit_weather import config


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Keep ambient configuration from leaking into loader assertions."""
    for var in ("LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL", "LM_STUDIO_API_KEY", "NEW_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_load_dotenv_reads_values_and_strips_comments(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "export LM_STUDIO_MODEL='my-model'\n"
        'LM_STUDIO_BASE_URL="http://example.test/v1"  # trailing comment\n'
        "NEW_KEY=plain-value  # inline comment\n",
        encoding="utf-8",
    )

    used = config.load_dotenv(env_file)

    assert used == env_file
    assert config.env("LM_STUDIO_MODEL") == "my-model"
    assert config.env("LM_STUDIO_BASE_URL") == "http://example.test/v1"
    assert config.env("NEW_KEY") == "plain-value"


def test_load_dotenv_never_overrides_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NEW_KEY", "from-env")
    env_file = tmp_path / ".env"
    env_file.write_text("NEW_KEY=from-file\n", encoding="utf-8")

    config.load_dotenv(env_file)

    assert config.env("NEW_KEY") == "from-env"


def test_env_treats_empty_string_as_unset(monkeypatch):
    monkeypatch.setenv("NEW_KEY", "")
    assert config.env("NEW_KEY", "fallback") == "fallback"


def test_load_dotenv_returns_none_when_file_is_absent(tmp_path):
    assert config.load_dotenv(tmp_path / "missing.env") is None
