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
from .errors import SelectorChangedError
from .models import TaskResult, TaskStatus, TaskSummary
from .selectors import DEFAULT_SELECTORS, SelectorSet

LOGGER = logging.getLogger(__name__)

WELCOME_TIER_ID = "welcome_gift"
GEM_COSTS_ASC = (499, 999, 1999, 4999)
GEM_COSTS_DESC = tuple(reversed(GEM_COSTS_ASC))
GEM_AMOUNTS_BY_COST = {
    499: 30,
    999: 60,
    1999: 120,
    4999: 320,
}


@dataclass(frozen=True, slots=True)
class RewardTier:
    """One monthly reward tier that can be redeemed with tokens."""

    tier_id: str
    name: str
    keyword: str
    cost: int


REWARD_TIERS: tuple[RewardTier, ...] = (
    *(
        RewardTier(f"gem_{cost}", f"珠宝×{GEM_AMOUNTS_BY_COST[cost]}", "Gem", cost)
        for cost in GEM_COSTS_DESC
    ),
    RewardTier(WELCOME_TIER_ID, "欢迎礼物（芯尘×30）", "Welcome Gift", 1),
)


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


def plan_redemptions(balance: int, purchased: dict[str, str], *, force: bool = False) -> list[RewardTier]:
    """Choose reward tiers using current balance and monthly purchase records."""

    remaining = balance
    planned: list[RewardTier] = []
    for tier in REWARD_TIERS:
        if not force and tier.tier_id in purchased:
            continue
        if remaining < tier.cost:
            continue
        planned.append(tier)
        remaining -= tier.cost
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
        now: datetime | None = None,
        record_store: RedemptionRecordStore | None = None,
    ) -> None:
        self.page = page
        self.config = config
        self.selectors = selectors
        self.force = force
        self.now = now or datetime.now()
        self.record_store = record_store or RedemptionRecordStore(config.redemption_record_path)

    async def redeem_all(self) -> TaskSummary:
        await self._open_points()
        await self._wait_for_rewards_loaded()
        balance = await self._read_token_balance()
        month = self.now.strftime("%Y-%m")
        purchased = self.record_store.load(month)
        tiers = plan_redemptions(balance, purchased, force=self.force)

        if not tiers:
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

        results: list[TaskResult] = []
        for tier in tiers:
            result = await self._redeem_tier(tier, month)
            results.append(result)
            if not result.ok:
                break

        return TaskSummary(login_ok=True, results=results)

    async def _redeem_tier(self, tier: RewardTier, month: str) -> TaskResult:
        await self._open_points()
        await self._wait_for_rewards_loaded()
        reward_index = await self._find_reward_index(tier)
        if reward_index is None:
            return TaskResult(
                tier.name,
                TaskStatus.FAILED,
                f"未找到可兑换卡片：{tier.keyword} / {tier.cost}",
                attempted=1,
            )

        LOGGER.info("兑换奖励：%s（消耗 %s）", tier.name, tier.cost)
        try:
            target = self.page.locator(self.selectors.reward_title).nth(reward_index)
            await target.scroll_into_view_if_needed()
            await target.click()
            await self._settle(1.0)
            await self.page.locator(self.selectors.reward_redeem_button).first.click()
            await self._settle(1.0)
        except PlaywrightTimeoutError as exc:
            return TaskResult(
                tier.name,
                TaskStatus.FAILED,
                f"兑换按钮或奖励卡片不可用：{tier.keyword} / {tier.cost}",
                attempted=1,
            )
        except Exception as exc:
            raise SelectorChangedError(f"兑换奖励失败：{tier.keyword} / {tier.cost}") from exc

        self.record_store.mark_purchased(month, tier.tier_id, self.now)
        return TaskResult(tier.name, TaskStatus.COMPLETED, "已点击兑换", attempted=1, completed=1)

    async def _find_reward_index(self, tier: RewardTier) -> int | None:
        locator = self.page.locator(self.selectors.reward_title)
        total = await locator.count()
        matches: list[int] = []
        for index in range(total):
            item = locator.nth(index)
            try:
                if not await item.is_visible():
                    continue
                text = " ".join((await item.inner_text()).split())
            except PlaywrightTimeoutError:
                continue
            if tier.keyword.casefold() in text.casefold():
                matches.append(index)

        if tier.keyword == "Welcome Gift":
            return matches[0] if matches else None

        gem_cost_to_index = dict(zip(GEM_COSTS_ASC, matches))
        return gem_cost_to_index.get(tier.cost)

    async def _open_points(self) -> None:
        await self.page.goto(self._points_url(), wait_until="domcontentloaded")
        await self._settle()

    def _points_url(self) -> str:
        return self.config.base_url.rstrip("/") + "/points"

    async def _wait_for_rewards_loaded(self) -> None:
        try:
            await self.page.locator(self.selectors.reward_title).first.wait_for(
                state="visible",
                timeout=self.config.timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise SelectorChangedError("奖励中心奖励列表未加载完成") from exc

        deadline = asyncio.get_running_loop().time() + (self.config.timeout_ms / 1000)
        last_balance: int | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                last_balance = await self._read_token_balance_value(allow_zero=True)
            except SelectorChangedError:
                await self._settle(0.3)
                continue
            if last_balance > 0:
                return
            await self._settle(0.5)

        if last_balance == 0:
            LOGGER.warning("奖励中心代币数量仍为 0，可能是真的没有代币，也可能页面未完全刷新")
            return
        raise SelectorChangedError("奖励中心代币数量未加载完成")

    async def _read_token_balance(self) -> int:
        return await self._read_token_balance_value(allow_zero=False)

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

    async def _settle(self, seconds: float = 1.0) -> None:
        await asyncio.sleep(max(seconds, 0))
