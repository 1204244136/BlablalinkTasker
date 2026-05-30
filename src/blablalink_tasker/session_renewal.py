"""Renew BlablaLink game cookies using the official login refresh endpoint."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any

from playwright.async_api import BrowserContext, Page

from .config import AppConfig
from .errors import LoginRequiredError, TaskRunError

LOGGER = logging.getLogger(__name__)

REQUIRED_GAME_COOKIES = (
    "game_token",
    "game_uid",
    "game_openid",
    "game_gameid",
    "game_channelid",
    "game_user_name",
    "game_adult_status",
)

SENSITIVE_COOKIE_NAMES = {"game_token", "token", "openid", "game_openid"}


@dataclass(slots=True)
class RenewalResult:
    """Result of a cookie renewal attempt."""

    renewed: bool
    message: str
    updated_cookie_names: list[str]
    expire_days: int | None = None


async def renew_session(context: BrowserContext, page: Page, config: AppConfig) -> RenewalResult:
    """Renew the saved BlablaLink session from existing game cookies."""

    cookies = await context.cookies(config.base_url)
    cookie_values = _extract_game_cookie_values(cookies)
    missing = [name for name in REQUIRED_GAME_COOKIES if not cookie_values.get(name)]
    if missing:
        raise LoginRequiredError(f"当前会话缺少必要 Cookie：{', '.join(missing)}。请先重新运行 setup。")

    expire_days = 29
    expire_at = int(time.time()) + expire_days * 24 * 60 * 60
    request_body = {
        "game_openid": cookie_values["game_openid"],
        "game_channelid": _to_int(cookie_values["game_channelid"], default=131),
        "game_token": cookie_values["game_token"],
        "game_id": cookie_values.get("game_gameid") or "29080",
        "game_expire_time": expire_at,
        "game_uid": cookie_values["game_uid"],
        "game_user_name": cookie_values["game_user_name"],
        "game_adult_status": _to_int(cookie_values["game_adult_status"], default=1),
    }

    LOGGER.info("正在请求 BlablaLink 会话续期接口")
    response = await page.request.post(
        "https://api.blablalink.com/api/user/Login",
        headers={
            "Content-Type": "application/json",
            "Origin": "https://www.blablalink.com",
            "Referer": "https://www.blablalink.com/",
            "X-Channel-Type": "2",
            "X-Language": "en",
            "Cookie": _format_cookie_header(cookie_values),
        },
        data=request_body,
    )

    response_text = await response.text()
    if not response.ok:
        raise TaskRunError(f"会话续期请求失败：HTTP {response.status}")

    try:
        payload = await response.json()
    except Exception as exc:  # pragma: no cover - defensive against invalid upstream body
        raise TaskRunError(f"会话续期响应不是有效 JSON：{response_text[:120]}") from exc

    if payload.get("code") != 0:
        raise TaskRunError(f"会话续期失败：code={payload.get('code')} message={payload.get('message') or payload.get('msg')}")

    set_cookie_header = response.headers.get("set-cookie", "")
    updated = _parse_set_cookie_header(set_cookie_header)
    if not updated:
        LOGGER.warning("续期接口未返回 Set-Cookie，将保留当前会话文件")
        return RenewalResult(False, "续期接口未返回新的 Cookie", [])

    merged = {**cookie_values, **updated}
    if not merged.get("game_token"):
        raise TaskRunError("续期响应未包含可用 game_token")

    await _apply_cookies(context, config, merged, expire_at)
    return RenewalResult(True, "会话 Cookie 已续期", sorted(updated), expire_days=expire_days)


def _extract_game_cookie_values(cookies: list[dict[str, Any]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for cookie in cookies:
        name = str(cookie.get("name", ""))
        if name.startswith("game_"):
            values[name] = str(cookie.get("value", ""))
    return values


def _format_cookie_header(cookie_values: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookie_values.items() if name.startswith("game_") and value)


def _parse_set_cookie_header(header: str) -> dict[str, str]:
    if not header:
        return {}

    parsed: dict[str, str] = {}
    for part in _split_combined_set_cookie(header):
        cookie = SimpleCookie()
        try:
            cookie.load(part)
        except Exception:
            continue
        for name, morsel in cookie.items():
            if name.startswith("game_"):
                parsed[name] = morsel.value
    return parsed


def _split_combined_set_cookie(header: str) -> list[str]:
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(header):
        if header[index] == "," and _looks_like_cookie_pair(header[index + 1 :]):
            parts.append(header[start:index].strip())
            start = index + 1
        index += 1
    parts.append(header[start:].strip())
    return [part for part in parts if part]


def _looks_like_cookie_pair(value: str) -> bool:
    stripped = value.lstrip()
    if "=" not in stripped:
        return False
    name = stripped.split("=", 1)[0]
    return bool(name) and all(ch.isalnum() or ch in "_-" for ch in name)


async def _apply_cookies(context: BrowserContext, config: AppConfig, cookie_values: dict[str, str], expire_at: int) -> None:
    cookies = []
    for name, value in cookie_values.items():
        if not name.startswith("game_") or not value:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".blablalink.com",
                "path": "/",
                "expires": expire_at,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
        )

    await context.add_cookies(cookies)
    await context.storage_state(path=str(config.session_path))
    LOGGER.info("已写回续期后的会话文件：%s", config.session_path)


def _to_int(value: str | None, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def safe_cookie_names(names: list[str]) -> str:
    """Format cookie names without exposing values."""

    return ", ".join("<sensitive>" if name in SENSITIVE_COOKIE_NAMES else name for name in names)
