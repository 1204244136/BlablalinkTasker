"""Playwright browser/session helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .config import AppConfig


class BrowserManager:
    """Owns Playwright lifecycle and browser context creation."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def new_context(self, *, use_session: bool) -> BrowserContext:
        if self._browser is None:
            raise RuntimeError("BrowserManager 尚未启动")

        kwargs: dict[str, object] = {
            "viewport": {"width": 1366, "height": 900},
        }
        if use_session:
            kwargs["storage_state"] = str(self.config.session_path)

        context = await self._browser.new_context(**kwargs)
        context.set_default_timeout(self.config.timeout_ms)
        return context

    async def new_page(self, *, use_session: bool) -> tuple[BrowserContext, Page]:
        context = await self.new_context(use_session=use_session)
        page = await context.new_page()
        page.set_default_timeout(self.config.timeout_ms)
        return context, page


@asynccontextmanager
async def browser_page(config: AppConfig, *, use_session: bool) -> AsyncIterator[tuple[BrowserContext, Page]]:
    """Open a page and close its browser resources automatically."""

    async with BrowserManager(config) as manager:
        context, page = await manager.new_page(use_session=use_session)
        try:
            yield context, page
        finally:
            await context.close()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
