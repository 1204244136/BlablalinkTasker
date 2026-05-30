"""BlablaLink community daily task runner."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .config import AppConfig
from .errors import LoginRequiredError, SelectorChangedError
from .models import TaskResult, TaskStatus, TaskSummary
from .selectors import DEFAULT_SELECTORS, SelectorSet

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DiagnosticReport:
    """Read-only page diagnostic information."""

    current_url: str
    title: str
    login_ok: bool
    selector_visibility: dict[str, bool]

    def format_lines(self) -> list[str]:
        lines = [
            "BlablaLink 诊断结果",
            f"- 当前 URL: {self.current_url}",
            f"- 页面标题: {self.title}",
            f"- 登录状态: {'可能已登录' if self.login_ok else '可能未登录'}",
        ]
        for name, visible in self.selector_visibility.items():
            lines.append(f"- 选择器 {name}: {'可见' if visible else '未发现'}")
        return lines


class BlablaTaskRunner:
    """Runs BlablaLink daily tasks through a Playwright page."""

    def __init__(
        self,
        page: Page,
        config: AppConfig,
        selectors: SelectorSet = DEFAULT_SELECTORS,
        *,
        dry_run: bool = False,
    ) -> None:
        self.page = page
        self.config = config
        self.selectors = selectors
        self.dry_run = dry_run

    async def open_home(self) -> None:
        LOGGER.info("打开 BlablaLink 首页：%s", self.config.base_url)
        await self.page.goto(self.config.base_url, wait_until="domcontentloaded")
        await self._settle()

    async def run_all(self) -> TaskSummary:
        await self.open_home()
        login_ok = await self.check_login()
        if not login_ok:
            raise LoginRequiredError("当前会话可能未登录或已过期，请运行 `blablalink-tasker setup` 重新登录。")

        results = [
            await self.do_check_in(),
            await self.do_likes(),
            await self.do_browses(),
        ]
        return TaskSummary(login_ok=login_ok, results=results)

    async def diagnose(self) -> DiagnosticReport:
        await self.open_home()
        login_ok = await self.check_login()
        title = await self.page.title()
        visibility = {
            "check_in_button": await self._is_visible(self.selectors.check_in_button, timeout=1200),
            "check_in_close": await self._is_visible(self.selectors.check_in_close, timeout=800),
            "like_target": await self._is_visible(self.selectors.like_target, timeout=1200),
            "browse_target": await self._is_visible(self.selectors.browse_target, timeout=1200),
            "post_close": await self._is_visible(self.selectors.post_close, timeout=800),
        }
        return DiagnosticReport(
            current_url=self.page.url,
            title=title,
            login_ok=login_ok,
            selector_visibility=visibility,
        )

    async def check_login(self) -> bool:
        if "login" in self.page.url.lower():
            return False

        for selector in self.selectors.login_links:
            if await self._is_visible(selector, timeout=600):
                return False

        cookies = await self.page.context.cookies()
        has_game_cookie = any(cookie.get("name", "").startswith("game_") for cookie in cookies)
        has_task_ui = await self._is_visible(self.selectors.check_in_button, timeout=1000)
        return has_game_cookie or has_task_ui

    async def do_check_in(self) -> TaskResult:
        task_name = "签到"
        LOGGER.info("开始执行：%s", task_name)

        if not await self._is_visible(self.selectors.check_in_button, timeout=3000):
            return TaskResult(task_name, TaskStatus.ALREADY_DONE, "未发现签到入口，可能已经完成或页面布局变化")

        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：已发现签到入口但未点击", attempted=1)

        await self.page.locator(self.selectors.check_in_button).first.click()
        await self._settle(1.0)

        if await self._is_visible(self.selectors.check_in_close, timeout=2500):
            await self.page.locator(self.selectors.check_in_close).first.click()
            await self._settle(0.8)

        return TaskResult(task_name, TaskStatus.COMPLETED, "已点击签到入口", attempted=1, completed=1)

    async def do_likes(self) -> TaskResult:
        task_name = "点赞 / 重新点赞"
        LOGGER.info("开始执行：%s", task_name)

        like_indexes = await self._visible_indexes(self.selectors.like_target, timeout=2500)
        target_indexes = like_indexes[: self.config.max_likes]
        attempted = len(target_indexes)
        completed = 0

        for step, element_index in enumerate(target_indexes, start=1):
            LOGGER.info("执行点赞步骤 %s/%s（元素 %s）", step, attempted, element_index)
            if self.dry_run:
                continue

            await self._click_indexed_element(self.selectors.like_target, element_index)
            await self._settle(1.0)
            await self._click_indexed_element(self.selectors.like_target, element_index)
            await self._settle(1.0)
            completed += 1

        if attempted == 0:
            return TaskResult(task_name, TaskStatus.ALREADY_DONE, "未发现点赞任务入口，可能已经完成或页面布局变化")
        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：未点击点赞目标", attempted=attempted)
        return TaskResult(task_name, TaskStatus.COMPLETED, "点赞流程结束", attempted=attempted, completed=completed)

    async def do_browses(self) -> TaskResult:
        task_name = "浏览"
        LOGGER.info("开始执行：%s", task_name)

        browse_indexes = await self._visible_indexes(self.selectors.browse_target, timeout=2500)
        target_indexes = browse_indexes[: self.config.max_browses]
        attempted = len(target_indexes)
        completed = 0

        for step, element_index in enumerate(target_indexes, start=1):
            LOGGER.info("执行浏览步骤 %s/%s（元素 %s）", step, attempted, element_index)
            if self.dry_run:
                continue

            await self._click_indexed_element(self.selectors.browse_target, element_index)
            await self._settle(self.config.browse_seconds)
            await self._close_post_or_go_back()
            completed += 1
            await self._settle(1.0)

        if attempted == 0:
            return TaskResult(task_name, TaskStatus.ALREADY_DONE, "未发现浏览任务入口，可能已经完成或页面布局变化")
        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：未打开浏览目标", attempted=attempted)
        return TaskResult(task_name, TaskStatus.COMPLETED, "浏览流程结束", attempted=attempted, completed=completed)

    async def _close_post_or_go_back(self) -> None:
        if await self._is_visible(self.selectors.post_close, timeout=2500):
            await self.page.locator(self.selectors.post_close).first.click()
            return

        LOGGER.warning("未发现关闭按钮，尝试使用浏览器返回")
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise SelectorChangedError("无法关闭浏览内容，也无法返回列表页") from exc

    async def _is_visible(self, selector: str, *, timeout: int) -> bool:
        try:
            await self.page.locator(selector).first.wait_for(state="visible", timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _visible_indexes(self, selector: str, *, timeout: int) -> list[int]:
        if not await self._is_visible(selector, timeout=timeout):
            return []

        locator = self.page.locator(selector)
        total = await locator.count()
        indexes: list[int] = []
        for index in range(total):
            try:
                if await locator.nth(index).is_visible():
                    indexes.append(index)
            except PlaywrightTimeoutError:
                continue
        return indexes

    async def _click_indexed_element(self, selector: str, index: int) -> None:
        target = self.page.locator(selector).nth(index)
        await target.scroll_into_view_if_needed()
        if not await target.is_visible():
            raise SelectorChangedError(f"元素在点击前变为不可见：{selector} nth({index})")
        await target.click()

    async def _settle(self, seconds: float = 1.0) -> None:
        await asyncio.sleep(max(seconds, 0))
