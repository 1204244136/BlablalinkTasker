"""BlablaLink community daily task runner."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .config import AppConfig
from .errors import LoginRequiredError, SelectorChangedError
from .models import TaskResult, TaskStatus, TaskSummary
from .selectors import DEFAULT_SELECTORS, SelectorSet

LOGGER = logging.getLogger(__name__)
PROGRESS_PATTERN = re.compile(r"^(\d+)\s*/\s*(\d+)$")
PROGRESS_SEARCH_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)")
POINTS_TASK_ORDER = ("浏览", "点赞")
POST_DETAIL_PATTERN = re.compile(r"/post/detail(?:\?.*)?$")
LIKE_SETTLE_SECONDS = 1.0
HOME_SETTLE_SECONDS = 2.0


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
        self._like_budget_remaining = config.max_likes
        self._browse_budget_remaining = config.max_browses
        self._like_progress_complete = False
        self._browse_progress_complete = False
        self._visited_post_urls: set[str] = set()

    async def open_home(self) -> None:
        LOGGER.info("打开 BlablaLink 首页：%s", self.config.base_url)
        await self.page.goto(self.config.base_url, wait_until="domcontentloaded")
        await self._dismiss_cookie_banner()
        await self._dismiss_home_event_dialogs()
        await self._settle(HOME_SETTLE_SECONDS)

    async def run_all(self) -> TaskSummary:
        await self.open_home()
        login_ok = await self.check_login()
        if not login_ok:
            raise LoginRequiredError("当前会话可能未登录或已过期，请运行 `blablalink-tasker setup` 重新登录。")

        results = [await self.do_check_in()]

        if self.dry_run:
            results.extend([await self.do_likes(), await self.do_browses()])
        else:
            initial_values = await self._load_points_progress_values()
            self._configure_action_budgets(initial_values)
            await self.open_home()
            results.append(await self.do_likes())
            results.append(await self.do_browses())

        results.append(await self.verify_points_progress())
        return TaskSummary(login_ok=login_ok, results=results)

    async def diagnose(self) -> DiagnosticReport:
        await self.open_home()
        login_ok = await self.check_login()
        home_url = self.page.url
        title = await self.page.title()
        visibility = {
            "check_in_button": await self._is_visible(self.selectors.check_in_button, timeout=1200),
            "check_in_done": await self._is_visible(self.selectors.check_in_done, timeout=800),
            "authenticated_points_balance": await self._is_visible(
                self.selectors.authenticated_points_balance,
                timeout=800,
            ),
            "like_target": await self._is_visible(self.selectors.like_target, timeout=1200),
            "browse_target": await self._is_visible(self.selectors.browse_target, timeout=1200),
        }

        if login_ok:
            await self.page.goto(self._points_url(), wait_until="domcontentloaded")
            await self._settle(0.3)
            expand_button_visible = await self._is_visible(
                self.selectors.points_expand_button,
                timeout=1200,
            )
            await self._ensure_points_tasks_expanded()
            visibility.update(
                {
                    "points_expand_button": expand_button_visible,
                    "points_browse_task": await self._is_visible(
                        self.selectors.points_browse_task_row,
                        timeout=2500,
                    ),
                    "points_like_task": await self._is_visible(
                        self.selectors.points_like_task_row,
                        timeout=2500,
                    ),
                    "reward_card": await self._is_visible(self.selectors.reward_card, timeout=2500),
                }
            )

        return DiagnosticReport(
            current_url=home_url,
            title=title,
            login_ok=login_ok,
            selector_visibility=visibility,
        )

    async def check_login(self) -> bool:
        if "login" in self.page.url.lower():
            return False

        if await self._is_visible(self.selectors.session_expired_message, timeout=500):
            return False

        if await self._is_visible(self.selectors.check_in_done, timeout=800):
            return True

        if await self._is_visible(self.selectors.authenticated_points_balance, timeout=800):
            return True

        for selector in self.selectors.login_links:
            if await self._is_visible(selector, timeout=600):
                return False

        if await self._is_visible(self.selectors.logged_out_marker, timeout=800):
            return False

        cookies = await self.page.context.cookies()
        has_game_cookie = any(cookie.get("name", "").startswith("game_") for cookie in cookies)
        return has_game_cookie

    async def do_check_in(self) -> TaskResult:
        task_name = "签到"
        LOGGER.info("开始执行：%s", task_name)

        if await self._is_visible(self.selectors.check_in_done, timeout=1200):
            return TaskResult(task_name, TaskStatus.ALREADY_DONE, "今日网页签到已完成")

        if not await self._is_visible(self.selectors.check_in_button, timeout=3000):
            return TaskResult(task_name, TaskStatus.FAILED, "未发现新版网页签到按钮或完成状态")

        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：已发现签到入口但未点击", attempted=1)

        await self.page.locator(self.selectors.check_in_button).first.click()
        try:
            await self.page.locator(self.selectors.check_in_done).first.wait_for(
                state="visible",
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError:
            if await self._is_visible(self.selectors.session_expired_message, timeout=500):
                raise LoginRequiredError("网页签到时登录会话失效，请重新运行 setup。")
            return TaskResult(task_name, TaskStatus.FAILED, "点击签到后未出现 Done 状态", attempted=1)

        if await self._is_visible(self.selectors.check_in_success_message, timeout=500):
            try:
                await self.page.locator(self.selectors.check_in_success_message).first.wait_for(
                    state="hidden",
                    timeout=min(self.config.timeout_ms, 5000),
                )
            except PlaywrightTimeoutError:
                await self._settle(LIKE_SETTLE_SECONDS)

        return TaskResult(task_name, TaskStatus.COMPLETED, "网页签到完成", attempted=1, completed=1)

    async def do_likes(self, *, max_actions: int | None = None) -> TaskResult:
        task_name = "点赞"
        LOGGER.info("开始执行：%s", task_name)

        action_budget = self._like_budget_remaining
        if max_actions is not None:
            action_budget = min(action_budget, max_actions)
        if action_budget <= 0:
            status = TaskStatus.ALREADY_DONE if self._like_progress_complete else TaskStatus.SKIPPED
            message = "奖励中心点赞进度已完成" if self._like_progress_complete else "本次运行的点赞动作预算已用完"
            return TaskResult(task_name, status, message)

        like_indexes = await self._visible_indexes(self.selectors.like_target, timeout=2500)
        attempted = min(len(like_indexes), action_budget)
        completed = 0

        if attempted == 0:
            return TaskResult(task_name, TaskStatus.FAILED, "未发现新版推荐帖子中的未点赞按钮")
        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：未点击点赞目标", attempted=attempted)

        for step in range(1, attempted + 1):
            like_indexes = await self._visible_indexes(
                self.selectors.like_target,
                timeout=self.config.timeout_ms,
            )
            if not like_indexes:
                return TaskResult(
                    task_name,
                    TaskStatus.FAILED,
                    "点赞过程中没有剩余的未点赞目标",
                    attempted=attempted,
                    completed=completed,
                )

            previous_count = len(like_indexes)
            # Click the last matching icon so its index disappears after the state swap;
            # clicking the first item would let a re-indexed locator point at the next card.
            element_index = like_indexes[-1]
            LOGGER.info("执行点赞步骤 %s/%s（元素 %s）", step, attempted, element_index)
            state_changed = False
            for click_attempt in range(2):
                await self._click_home_target(self.selectors.like_target, element_index)
                try:
                    await self.page.locator(self.selectors.like_target).nth(element_index).wait_for(
                        state="hidden",
                        timeout=min(self.config.timeout_ms, 5000),
                    )
                    state_changed = True
                    break
                except PlaywrightTimeoutError:
                    if click_attempt == 0 and await self._dismiss_home_event_dialogs():
                        continue
                    break
            if not state_changed:
                return TaskResult(
                    task_name,
                    TaskStatus.FAILED,
                    "点击后目标点赞图标仍保持未点赞状态",
                    attempted=attempted,
                    completed=completed,
                )
            if not await self._wait_for_visible_count_below(
                self.selectors.like_target,
                previous_count,
            ):
                return TaskResult(
                    task_name,
                    TaskStatus.FAILED,
                    "点击后点赞按钮未切换为已点赞状态",
                    attempted=attempted,
                    completed=completed,
                )
            completed += 1
            self._like_budget_remaining -= 1
            await self._settle(LIKE_SETTLE_SECONDS)

        return TaskResult(
            task_name,
            TaskStatus.COMPLETED,
            "点赞流程结束",
            attempted=attempted,
            completed=completed,
        )

    async def do_browses(self, *, max_actions: int | None = None) -> TaskResult:
        task_name = "浏览"
        LOGGER.info("开始执行：%s", task_name)

        action_budget = self._browse_budget_remaining
        if max_actions is not None:
            action_budget = min(action_budget, max_actions)
        if action_budget <= 0:
            status = (
                TaskStatus.ALREADY_DONE
                if self._browse_progress_complete
                else TaskStatus.SKIPPED
            )
            message = "奖励中心浏览进度已完成" if self._browse_progress_complete else "本次运行的浏览动作预算已用完"
            return TaskResult(task_name, status, message)

        browse_indexes = await self._visible_indexes(self.selectors.browse_target, timeout=2500)
        attempted = min(len(browse_indexes), action_budget)
        completed = 0
        tried_titles: set[str] = set()
        candidate_attempts = 0
        max_candidate_attempts = max(len(browse_indexes) * 2, attempted)

        if attempted == 0:
            return TaskResult(task_name, TaskStatus.FAILED, "未发现新版推荐帖子标题")
        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：未打开浏览目标", attempted=attempted)

        while completed < attempted and candidate_attempts < max_candidate_attempts:
            current_indexes = await self._visible_indexes(
                self.selectors.browse_target,
                timeout=self.config.timeout_ms,
            )
            candidate_index: int | None = None
            candidate_title = ""
            for element_index in current_indexes:
                target = self.page.locator(self.selectors.browse_target).nth(element_index)
                title = " ".join((await target.inner_text()).split())
                if title and title not in tried_titles:
                    candidate_index = element_index
                    candidate_title = title
                    break

            if candidate_index is None:
                break

            tried_titles.add(candidate_title)
            candidate_attempts += 1
            LOGGER.info(
                "执行浏览步骤 %s/%s（元素 %s：%s）",
                completed + 1,
                attempted,
                candidate_index,
                candidate_title,
            )

            detail_url = await self._open_post_detail(candidate_index)
            if detail_url is None:
                continue
            if detail_url in self._visited_post_urls:
                LOGGER.warning("浏览目标返回了重复详情 URL，跳过：%s", detail_url)
                await self._close_post_or_go_back()
                continue

            self._visited_post_urls.add(detail_url)
            await self._settle(self.config.browse_seconds)
            await self._close_post_or_go_back()
            completed += 1
            self._browse_budget_remaining -= 1

        if completed == 0:
            return TaskResult(
                task_name,
                TaskStatus.FAILED,
                "未能打开任何唯一的新版推荐帖子详情",
                attempted=attempted,
                completed=completed,
            )
        if completed < attempted:
            return TaskResult(
                task_name,
                TaskStatus.FAILED,
                f"浏览流程只完成 {completed}/{attempted} 个唯一帖子",
                attempted=attempted,
                completed=completed,
            )
        return TaskResult(
            task_name,
            TaskStatus.COMPLETED,
            "浏览流程结束",
            attempted=attempted,
            completed=completed,
        )

    async def verify_points_progress(self) -> TaskResult:
        task_name = "奖励中心复核"
        LOGGER.info("开始执行：%s", task_name)

        if self.dry_run:
            return TaskResult(task_name, TaskStatus.SKIPPED, "dry-run：未检查奖励中心浏览与点赞进度", attempted=2)

        repair_rounds = 0
        values = await self._load_points_progress_values()

        while (
            len(values) >= len(POINTS_TASK_ORDER)
            and not self._is_complete_points_snapshot(values)
        ):
            missing_indexes = self._incomplete_points_task_indexes(values)
            missing_names = [POINTS_TASK_ORDER[index] for index in missing_indexes]

            if repair_rounds >= self.config.points_repair_rounds:
                completed = sum(1 for value in values if self._is_complete_points_progress(value))
                return TaskResult(
                    task_name,
                    TaskStatus.FAILED,
                    (
                        f"奖励中心进度未完成：已补做 {repair_rounds} 轮，"
                        f"最后缺失 {'、'.join(missing_names)}，实际 {values}"
                    ),
                    attempted=2,
                    completed=completed,
                )

            repair_rounds += 1
            LOGGER.info(
                "奖励中心进度异常：%s；第 %s/%s 轮回首页补做：%s",
                values,
                repair_rounds,
                self.config.points_repair_rounds,
                "、".join(missing_names),
            )
            await self._repair_points_tasks(values, missing_indexes)
            values = await self._load_points_progress_values()

        if len(values) < len(POINTS_TASK_ORDER):
            completed = sum(1 for value in values if self._is_complete_points_progress(value))
            return TaskResult(
                task_name,
                TaskStatus.FAILED,
                (
                    f"奖励中心进度文本不足：期望 2 个，实际 {len(values)} 个，读取到 {values}"
                    f"；已补做 {repair_rounds} 轮"
                ),
                attempted=2,
                completed=completed,
            )

        completed = sum(1 for value in values if self._is_complete_points_progress(value))
        if completed != 2:
            return TaskResult(
                task_name,
                TaskStatus.FAILED,
                (
                    f"奖励中心进度未完成：实际 {values}；已补做 {repair_rounds} 轮"
                ),
                attempted=2,
                completed=completed,
            )

        message = f"奖励中心浏览与点赞进度均已完成：{values[:2]}"
        if repair_rounds:
            message += f"（补做 {repair_rounds} 轮）"
        return TaskResult(
            task_name,
            TaskStatus.COMPLETED,
            message,
            attempted=2,
            completed=2,
        )

    def _points_url(self) -> str:
        return self.config.base_url.rstrip("/") + "/points"

    @staticmethod
    def _is_complete_points_progress(value: str) -> bool:
        match = PROGRESS_PATTERN.match(value)
        if match is None:
            return False
        current, target = (int(part) for part in match.groups())
        return target > 0 and current >= target

    @staticmethod
    def _remaining_points_progress(value: str) -> int | None:
        match = PROGRESS_PATTERN.match(value)
        if match is None:
            return None
        current, target = (int(part) for part in match.groups())
        if target <= 0:
            return None
        return max(target - current, 0)

    @classmethod
    def _is_complete_points_snapshot(cls, values: list[str]) -> bool:
        return len(values) >= len(POINTS_TASK_ORDER) and all(
            cls._is_complete_points_progress(value)
            for value in values[: len(POINTS_TASK_ORDER)]
        )

    @classmethod
    def _incomplete_points_task_indexes(cls, values: list[str]) -> list[int]:
        return [
            index
            for index, value in enumerate(values[: len(POINTS_TASK_ORDER)])
            if not cls._is_complete_points_progress(value)
        ]

    def _configure_action_budgets(self, values: list[str]) -> None:
        if len(values) < len(POINTS_TASK_ORDER):
            return

        browse_remaining = self._remaining_points_progress(values[0])
        like_remaining = self._remaining_points_progress(values[1])
        if browse_remaining is not None:
            self._browse_progress_complete = browse_remaining == 0
            self._browse_budget_remaining = min(self.config.max_browses, browse_remaining)
        if like_remaining is not None:
            self._like_progress_complete = like_remaining == 0
            self._like_budget_remaining = min(self.config.max_likes, like_remaining)

    async def _load_points_progress_values(self) -> list[str]:
        await self.page.goto(self._points_url(), wait_until="domcontentloaded")
        await self._settle(0.3)

        if await self._is_visible(self.selectors.session_expired_message, timeout=800):
            raise LoginRequiredError("奖励中心提示会话已过期，请重新运行 setup。")

        if not await self._ensure_points_tasks_expanded():
            LOGGER.warning("奖励中心点赞任务仍处于隐藏状态或展开控件已变化")

        return await self._points_progress_values()

    async def _ensure_points_tasks_expanded(self) -> bool:
        if await self._is_visible(self.selectors.points_like_task_row, timeout=800):
            return True

        if not await self._is_visible(self.selectors.points_expand_button, timeout=2500):
            return False

        expand_button = self.page.locator(self.selectors.points_expand_button).first
        await expand_button.scroll_into_view_if_needed()
        await expand_button.click()
        try:
            await self.page.locator(self.selectors.points_like_task_row).first.wait_for(
                state="visible",
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError:
            return False
        return True

    async def _repair_points_tasks(self, values: list[str], missing_indexes: list[int]) -> None:
        await self.open_home()
        for index in missing_indexes:
            if index == 0:
                remaining = self._remaining_points_progress(values[0]) if values else None
                await self.do_browses(max_actions=remaining)
            elif index == 1:
                remaining = self._remaining_points_progress(values[1]) if len(values) > 1 else None
                await self.do_likes(max_actions=remaining)

    async def _close_post_or_go_back(self) -> None:
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError:
            LOGGER.warning("浏览器返回超时，改用首页导航恢复推荐列表")
            try:
                await self.page.goto(self.config.base_url, wait_until="domcontentloaded")
            except PlaywrightTimeoutError as goto_exc:
                raise SelectorChangedError("无法从帖子详情返回推荐列表") from goto_exc

        try:
            await self.page.locator(self.selectors.browse_target).first.wait_for(
                state="visible",
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError:
            LOGGER.warning("返回后推荐列表未及时恢复，重新导航首页")
            try:
                await self.page.goto(self.config.base_url, wait_until="domcontentloaded")
                await self.page.locator(self.selectors.browse_target).first.wait_for(
                    state="visible",
                    timeout=self.config.timeout_ms,
                )
            except PlaywrightTimeoutError as goto_exc:
                raise SelectorChangedError("返回后推荐帖子列表未恢复") from goto_exc
        await self._dismiss_home_event_dialogs()
        await self._settle(HOME_SETTLE_SECONDS)

    async def _open_post_detail(self, element_index: int) -> str | None:
        for attempt in range(2):
            try:
                await self._click_home_target(self.selectors.browse_target, element_index)
                await self.page.wait_for_url(
                    POST_DETAIL_PATTERN,
                    wait_until="domcontentloaded",
                    timeout=min(self.config.timeout_ms, 5000),
                )
                return self.page.url
            except PlaywrightTimeoutError as exc:
                if attempt == 0 and await self._dismiss_home_event_dialogs():
                    continue
                raise SelectorChangedError("点击帖子标题后未进入帖子详情") from exc
        return None

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

    async def _wait_for_visible_count_below(self, selector: str, previous_count: int) -> bool:
        deadline = asyncio.get_running_loop().time() + (self.config.timeout_ms / 1000)
        while True:
            locator = self.page.locator(selector)
            visible_count = 0
            for index in range(await locator.count()):
                try:
                    if await locator.nth(index).is_visible():
                        visible_count += 1
                except PlaywrightTimeoutError:
                    continue

            if visible_count < previous_count:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def _click_home_target(self, selector: str, index: int) -> None:
        await self._dismiss_home_event_dialogs()
        try:
            await self._click_indexed_element(selector, index)
        except PlaywrightTimeoutError as exc:
            if not await self._dismiss_home_event_dialogs():
                raise SelectorChangedError(f"元素点击被页面遮罩阻塞：{selector} nth({index})") from exc
            await self._click_indexed_element(selector, index)

    async def _points_progress_values(self) -> list[str]:
        browse_values = await self._points_progress_values_by_selector(
            self.selectors.points_browse_task_row,
            timeout=self.config.timeout_ms,
        )
        like_values = await self._points_progress_values_by_selector(
            self.selectors.points_like_task_row,
            timeout=self.config.timeout_ms,
        )
        return [*browse_values[:1], *like_values[:1]]

    async def _points_progress_values_by_selector(
        self,
        selector: str,
        *,
        timeout: int,
    ) -> list[str]:
        locator = self.page.locator(selector).filter(has_text=PROGRESS_SEARCH_PATTERN)
        try:
            await locator.first.wait_for(
                state="visible",
                timeout=timeout,
            )
        except PlaywrightTimeoutError:
            return []

        total = await locator.count()
        values: list[str] = []
        for index in range(total):
            target = locator.nth(index)
            try:
                if await target.is_visible():
                    progress = self._extract_points_progress_text(await target.inner_text())
                    if progress is not None:
                        values.append(progress)
            except PlaywrightTimeoutError:
                continue
        return values[:1]

    @staticmethod
    def _extract_points_progress_text(value: str) -> str | None:
        match = PROGRESS_SEARCH_PATTERN.search(" ".join(value.split()))
        if match is None:
            return None
        current, target = match.groups()
        return f"{current} / {target}"

    async def _click_indexed_element(self, selector: str, index: int) -> None:
        target = self.page.locator(selector).nth(index)
        await target.scroll_into_view_if_needed()
        if not await target.is_visible():
            raise SelectorChangedError(f"元素在点击前变为不可见：{selector} nth({index})")
        await target.click()

    async def _dismiss_cookie_banner(self) -> None:
        if not await self._is_visible(self.selectors.cookie_close_button, timeout=800):
            return

        await self.page.locator(self.selectors.cookie_close_button).first.click()
        try:
            await self.page.locator(self.selectors.cookie_close_button).first.wait_for(
                state="hidden",
                timeout=1500,
            )
        except PlaywrightTimeoutError:
            LOGGER.debug("Cookie banner close button remains in the DOM")

    async def _dismiss_home_event_dialogs(self) -> bool:
        dialogs = self.page.locator(self.selectors.home_event_dialog)
        total = await dialogs.count()
        if total == 0:
            return False
        dismissed = False
        viewport = getattr(self.page, "viewport_size", None) or {"width": 1920, "height": 1080}

        for index in range(total):
            dialog = dialogs.nth(index)
            try:
                if not await dialog.is_visible():
                    continue
                if await dialog.locator(self.selectors.session_expired_message).count():
                    continue
                box = await dialog.bounding_box()
                if box is None:
                    continue

                y = min(max(box["y"] + 8, 1), viewport["height"] - 1)
                candidates = (
                    (box["x"] - 12, y),
                    (box["x"] + box["width"] + 12, y),
                    (5, 5),
                )
                for x, candidate_y in candidates:
                    if 1 <= x < viewport["width"] and not (
                        box["x"] <= x <= box["x"] + box["width"]
                        and box["y"] <= candidate_y <= box["y"] + box["height"]
                    ):
                        await self.page.mouse.click(x, candidate_y)
                        break
                try:
                    await dialog.wait_for(state="hidden", timeout=1500)
                except PlaywrightTimeoutError:
                    continue
                dismissed = True
            except PlaywrightTimeoutError:
                continue

        return dismissed

    async def _settle(self, seconds: float = 1.0) -> None:
        await asyncio.sleep(max(seconds, 0))
