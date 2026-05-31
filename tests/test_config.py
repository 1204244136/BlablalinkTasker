from pathlib import Path

import pytest

from blablalink_tasker.config import AppConfig, load_config
from blablalink_tasker.errors import ConfigError


def test_load_config_defaults(monkeypatch):
    for name in [
        "BLABLA_BASE_URL",
        "BLABLA_SESSION_PATH",
        "BLABLA_HEADLESS",
        "BLABLA_TIMEOUT_MS",
        "BLABLA_MAX_LIKES",
        "BLABLA_MAX_BROWSES",
        "BLABLA_BROWSE_SECONDS",
        "BLABLA_SLOW_MO_MS",
        "BLABLA_EXIT_WHEN_FAIL",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = load_config()

    assert config.base_url == "https://www.blablalink.com/"
    assert config.session_path == Path(".blablalink/storage_state.json")
    assert config.headless is True
    assert config.max_likes == 5
    assert config.max_browses == 5


def test_load_config_env_overrides(monkeypatch):
    monkeypatch.setenv("BLABLA_HEADLESS", "off")
    monkeypatch.setenv("BLABLA_TIMEOUT_MS", "3000")
    monkeypatch.setenv("BLABLA_MAX_LIKES", "2")
    monkeypatch.setenv("BLABLA_BROWSE_SECONDS", "2.5")

    config = load_config()

    assert config.headless is False
    assert config.timeout_ms == 3000
    assert config.max_likes == 2
    assert config.browse_seconds == 2.5


def test_load_config_rejects_invalid_bool(monkeypatch):
    monkeypatch.setenv("BLABLA_HEADLESS", "maybe")

    with pytest.raises(ConfigError):
        load_config()


def test_load_config_rejects_negative_limits(monkeypatch):
    monkeypatch.setenv("BLABLA_MAX_BROWSES", "-1")

    with pytest.raises(ConfigError):
        load_config()


def test_session_missing_raises(tmp_path):
    config = AppConfig(session_path=tmp_path / "missing.json")

    with pytest.raises(ConfigError):
        config.ensure_session_exists()
