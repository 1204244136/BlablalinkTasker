"""Configuration loading for BlablaLinkTasker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError


DEFAULT_BASE_URL = "https://www.blablalink.com/"
DEFAULT_SESSION_PATH = Path(".blablalink/storage_state.json")
DEFAULT_HEADLESS = True
DEFAULT_TIMEOUT_MS = 15_000
DEFAULT_MAX_LIKES = 5
DEFAULT_MAX_BROWSES = 5
DEFAULT_BROWSE_SECONDS = 1.0
DEFAULT_SLOW_MO_MS = 0
DEFAULT_EXIT_WHEN_FAIL = True

TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration for browser automation."""

    base_url: str = DEFAULT_BASE_URL
    session_path: Path = DEFAULT_SESSION_PATH
    headless: bool = DEFAULT_HEADLESS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_likes: int = DEFAULT_MAX_LIKES
    max_browses: int = DEFAULT_MAX_BROWSES
    browse_seconds: float = DEFAULT_BROWSE_SECONDS
    slow_mo_ms: int = DEFAULT_SLOW_MO_MS
    exit_when_fail: bool = DEFAULT_EXIT_WHEN_FAIL

    @property
    def login_url(self) -> str:
        return self.base_url.rstrip("/") + "/login?to=/"

    def ensure_session_exists(self) -> None:
        if not self.session_path.exists():
            raise ConfigError(
                f"找不到会话文件：{self.session_path}。请先运行 `blablalink-tasker setup`。"
            )


def load_config(**overrides: Any) -> AppConfig:
    """Load configuration from environment variables and explicit overrides."""

    config = AppConfig(
        base_url=os.getenv("BLABLA_BASE_URL", DEFAULT_BASE_URL),
        session_path=Path(os.getenv("BLABLA_SESSION_PATH", str(DEFAULT_SESSION_PATH))),
        headless=_env_bool("BLABLA_HEADLESS", DEFAULT_HEADLESS),
        timeout_ms=_env_int("BLABLA_TIMEOUT_MS", DEFAULT_TIMEOUT_MS, minimum=1),
        max_likes=_env_int("BLABLA_MAX_LIKES", DEFAULT_MAX_LIKES, minimum=0),
        max_browses=_env_int("BLABLA_MAX_BROWSES", DEFAULT_MAX_BROWSES, minimum=0),
        browse_seconds=_env_float("BLABLA_BROWSE_SECONDS", DEFAULT_BROWSE_SECONDS, minimum=0),
        slow_mo_ms=_env_int("BLABLA_SLOW_MO_MS", DEFAULT_SLOW_MO_MS, minimum=0),
        exit_when_fail=_env_bool("BLABLA_EXIT_WHEN_FAIL", DEFAULT_EXIT_WHEN_FAIL),
    )

    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, value)

    _validate_config(config)
    return config


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default

    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigError(f"环境变量 {name} 不是有效布尔值：{raw!r}")


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 不是有效整数：{raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"环境变量 {name} 必须大于等于 {minimum}，当前为 {value}")
    return value


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"环境变量 {name} 不是有效数字：{raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"环境变量 {name} 必须大于等于 {minimum}，当前为 {value}")
    return value


def _validate_config(config: AppConfig) -> None:
    if not config.base_url.startswith(("http://", "https://")):
        raise ConfigError(f"BLABLA_BASE_URL 必须以 http:// 或 https:// 开头：{config.base_url}")
    if config.timeout_ms <= 0:
        raise ConfigError("timeout_ms 必须大于 0")
    if config.max_likes < 0 or config.max_browses < 0:
        raise ConfigError("任务次数上限不能为负数")
    if config.browse_seconds < 0:
        raise ConfigError("browse_seconds 不能为负数")
    if config.slow_mo_ms < 0:
        raise ConfigError("slow_mo_ms 不能为负数")
