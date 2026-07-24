"""Reward Center redemption runner."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .browser import ensure_parent_dir
from .config import AppConfig
from .errors import LoginRequiredError, SelectorChangedError
from .models import TaskResult, TaskStatus, TaskSummary
from .selectors import DEFAULT_SELECTORS, SelectorSet

LOGGER = logging.getLogger(__name__)

CARD_PROGRESS_PATTERN = re.compile(r"^(\d+)\s*/\s*(\d+)$")
COST_PATTERN = re.compile(r"^\d[\d,]*$")
PERIOD_LABELS = {"daily", "weekly", "monthly"}


@dataclass(frozen=True, slots=True)
class RewardItem:
    """One reward card parsed from the current Reward Center catalog."""

    name: str
    cost: int
    card_index: int
    redeemed: bool = False

    @property
    def tier_id(self) -> str:
        normalized = " ".join(self.name.casefold().split())
        return f"{self.cost}:{normalized}"


class RedemptionRecordStore:
    """Persists monthly redemption records to avoid repeated attempts."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, month: str) -> dict[str, str]:
        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("兑换记录无法读取，将按空记录处理：%s", self.path)
            return {}

        if not isinstance(data, dict) or data.get("month") != month:
            return {}
        purchases = data.get("purchases", {})
        if not isinstance(purchases, dict):
            return {}
        return {str(key): str(value) for key, value in purchases.items()}

    def mark_purchased(self, month: str, tier_id: str, purchased_at: datetime) -> None:
        purchases = self.load(month)
        purchases[tier_id] = purchased_at.isoformat(timespec="seconds")
        ensure_parent_dir(self.path)
        self.path.write_text(
            json.dumps(
                {
                    "month": month,
                    "purchases": purchases,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def parse_reward_card(text: str, card_index: int) -> RewardItem | None:
    """Parse the visible text of one monthly reward card."""

    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    progress: tuple[int, int] | None = None
    cost: int | None = None
    title_candidates: list[str] = []

    for line in lines:
        progress_match = CARD_PROGRESS_PATTERN.fullmatch(line)
        if progress_match is not None:
            progress = tuple(int(part) for part in progress_match.groups())
            continue
        if line.casefold() in PERIOD_LABELS:
            continue
        if COST_PATTERN.fullmatch(line):
            cost = int(line.replace(",", ""))
            continue
        title_candidates.append(line)

    if progress is None or cost is None or not title_candidates:
        return None

    current, limit = progress
    return RewardItem(
        name=title_candidates[-1],
        cost=cost,
        card_index=card_index,
        redeemed=current >= limit,
    )


def plan_redemptions(
    balance: int,
    rewards: list[RewardItem],
    purchased: dict[str, str],
    *,
    force: bool = False,
) -> list[RewardItem]:
    """Choose affordable cards by cost, preserving page order for ties."""

    remaining = balance
    planned: list[RewardItem] = []
    ordered = sorted(rewards, key=lambda item: (-item.cost, item.card_index))
    for item in ordered:
        if item.redeemed:
            continue
        if not force and item.tier_id in purchased:
            continue
        if remaining < item.cost:
            continue
        planned.append(item)
        remaining -= item.cost
    return planned


class RewardRedemptionRunner:
    """Redeems monthly rewards from the BlablaLink Reward Center."""

    def __init__(
        self,
        page: Page,
        config: AppConfig,
        selectors: SelectorSet = DEFAULT_SELECTORS,
        *,
        force: bool = False,
        dry_run: bool = False,
        now: datetime | None = None,
        record_store: RedemptionRecordStore | None = None,
    ) -> None:
        self.page = page
        self.config = config
        self.selectors = selectors
        self.force = force
        self.dry_run = dry_run
        self.now = now or datetime.now()
        self.record_store = record_store or RedemptionRecordStore(config.redemption_record_path)

    async def redeem_all(self) -> TaskSummary:
        await self._open_points()
        await self._wait_for_rewards_loaded()
        balance = await self._read_token_balance()
        rewards = await self._read_reward_catalog()
        if not rewards:
            raise SelectorChangedError("奖励卡片已加载，但无法解析任何奖励名称、库存和价格")
        month = self.now.strftime("%Y-%m")
        purchased = self.record_store.load(month)
        planned = plan_redemptions(balance, rewards, purchased, force=self.force)

        if not planned:
            return TaskSummary(
                login_ok=True,
                results=[
                    TaskResult(
                        "奖励兑换",
                        TaskStatus.ALREADY_DONE,
                        f"本月可兑换档位均已处理或代币不足，当前代币 {balance}",
                    )
                ],
            )

        if self.dry_run:
            return TaskSummary(
                login_ok=True,
                results=[
                    TaskResult(
                        item.name,
                        TaskStatus.SKIPPED,
                        f"dry-run：计划消耗 {item.cost} 代币",
                        attempted=1,
                    )
                    for item in planned
                ],
            )

        results: list[TaskResult] = []
        for item in planned:
            result = await self._redeem_item(item, month)
            results.append(result)
            if not result.ok:
                break

        return TaskSummary(login_ok=True, results=results)

    async def _redeem_item(self, item: RewardItem, month: str) -> TaskResult:
        await self._open_points()
        await self._wait_for_rewards_loaded()
        balance_before = await self._read_token_balance()
        reward_index = await self._find_reward_index(item)
        if reward_index is None:
            return TaskResult(
                item.name,
                TaskStatus.FAILED,
                f"未找到可兑换卡片：{item.name} / {item.cost}",
                attempted=1,
            )

        LOGGER.info("兑换奖励：%s（消耗 %s）", item.name, item.cost)
        try:
            card = self.page.locator(self.selectors.reward_card).nth(reward_index)
            target = card.locator(self.selectors.reward_title).first
            await target.scroll_into_view_if_needed()
            await target.click()
            await self.page.locator(self.selectors.reward_modal_title).first.wait_for(
                state="visible",
                timeout=self.config.timeout_ms,
            )

            loading = self.page.locator(self.selectors.reward_loading_text).first
            try:
                if await loading.is_visible():
                    await loading.wait_for(state="hidden", timeout=self.config.timeout_ms)
            except PlaywrightTimeoutError:
                return TaskResult(
                    item.name,
                    TaskStatus.FAILED,
                    "兑换详情中的角色信息未加载完成",
                    attempted=1,
                )

            await self.page.locator(self.selectors.reward_redeem_button).first.click()
            await self._settle(0.5)

            if await self._is_visible(self.selectors.reward_confirm_button, timeout=1200):
                await self.page.locator(self.selectors.reward_confirm_button).first.click()
                await self._settle(0.5)
        except PlaywrightTimeoutError as exc:
            return TaskResult(
                item.name,
                TaskStatus.FAILED,
                f"兑换按钮或奖励卡片不可用：{item.name} / {item.cost}",
                attempted=1,
            )
        except Exception as exc:
            raise SelectorChangedError(f"兑换奖励失败：{item.name} / {item.cost}") from exc

        if not await self._verify_redemption(item, balance_before):
            return TaskResult(
                item.name,
                TaskStatus.FAILED,
                "点击兑换后余额和月度库存均未变化，未写入本地记录",
                attempted=1,
            )

        self.record_store.mark_purchased(month, item.tier_id, self.now)
        return TaskResult(item.name, TaskStatus.COMPLETED, "兑换结果已确认", attempted=1, completed=1)

    async def _find_reward_index(self, expected: RewardItem) -> int | None:
        for item in await self._read_reward_catalog():
            if item.tier_id == expected.tier_id and not item.redeemed:
                return item.card_index
        return None

    async def _read_reward_catalog(self) -> list[RewardItem]:
        locator = self.page.locator(self.selectors.reward_card)
        total = await locator.count()
        rewards: list[RewardItem] = []
        for index in range(total):
            card = locator.nth(index)
            try:
                if not await card.is_visible():
                    continue
                card_text = await card.inner_text()
                parsed = parse_reward_card(card_text, index)
            except PlaywrightTimeoutError:
                continue
            if parsed is not None:
                rewards.append(parsed)
            else:
                LOGGER.warning("无法解析奖励卡片 %s：%r", index, " ".join(card_text.split())[:160])
        return rewards

    async def _verify_redemption(self, expected: RewardItem, balance_before: int) -> bool:
        for attempt in range(3):
            await self._open_points()
            await self._wait_for_rewards_loaded()
            balance_after = await self._read_token_balance()
            current = next(
                (
                    item
                    for item in await self._read_reward_catalog()
                    if item.tier_id == expected.tier_id
                ),
                None,
            )
            stock_updated = current is not None and current.redeemed
            balance_updated = balance_after <= balance_before - expected.cost
            if stock_updated or balance_updated:
                return True
            if attempt < 2:
                await self._settle(0.8)
        return False

    async def _open_points(self) -> None:
        await self.page.goto(self._points_url(), wait_until="domcontentloaded")
        await self._settle(0.3)

    def _points_url(self) -> str:
        return self.config.base_url.rstrip("/") + "/points"

    async def _wait_for_rewards_loaded(self) -> None:
        try:
            await self.page.locator(self.selectors.reward_card).first.wait_for(
                state="visible",
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            if await self._is_visible(self.selectors.session_expired_message, timeout=500):
                raise LoginRequiredError("奖励中心提示会话已过期，请重新运行 setup。") from exc
            if await self._is_visible(self.selectors.game_binding_link, timeout=500):
                raise LoginRequiredError("当前账号未绑定游戏角色，无法读取奖励中心。") from exc
            raise SelectorChangedError("奖励中心奖励列表未加载完成") from exc

        await self._read_token_balance_value(allow_zero=True)

    async def _read_token_balance(self) -> int:
        return await self._read_token_balance_value(allow_zero=True)

    async def _read_token_balance_value(self, *, allow_zero: bool = False) -> int:
        locator = self.page.locator(self.selectors.reward_token_amount)
        try:
            await locator.first.wait_for(state="visible", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise SelectorChangedError("未找到奖励中心代币数量") from exc

        total = await locator.count()
        for index in range(total):
            target = locator.nth(index)
            try:
                if not await target.is_visible():
                    continue
                text = await target.inner_text()
            except PlaywrightTimeoutError:
                continue
            match = re.search(r"\d[\d,]*", text)
            if match:
                balance = int(match.group(0).replace(",", ""))
                if allow_zero or balance > 0:
                    return balance

        raise SelectorChangedError("奖励中心代币数量不是有效数字")

    async def _is_visible(self, selector: str, *, timeout: int) -> bool:
        try:
            await self.page.locator(selector).first.wait_for(state="visible", timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _settle(self, seconds: float = 1.0) -> None:
        await asyncio.sleep(max(seconds, 0))
