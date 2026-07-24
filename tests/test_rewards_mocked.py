from datetime import datetime

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from blablalink_tasker.config import AppConfig
from blablalink_tasker.errors import SelectorChangedError
from blablalink_tasker.models import TaskResult, TaskStatus
from blablalink_tasker.rewards import (
    RedemptionRecordStore,
    RewardItem,
    RewardRedemptionRunner,
    parse_reward_card,
    plan_redemptions,
)
from blablalink_tasker.selectors import DEFAULT_SELECTORS


class FakeLocatorCollection:
    def __init__(self, page, selector, parent=None):
        self.page = page
        self.selector = selector
        self.parent = parent

    @property
    def first(self):
        return FakeLocator(self.page, self.selector, 0, self.parent)

    def nth(self, index):
        return FakeLocator(self.page, self.selector, index, self.parent)

    async def count(self):
        return len(self.page.locator_texts(self.selector, self.parent))


class FakeLocator:
    def __init__(self, page, selector, index, parent=None):
        self.page = page
        self.selector = selector
        self.index = index
        self.parent = parent

    @property
    def path(self):
        segment = (self.selector, self.index)
        if self.parent is None:
            return (segment,)
        return (*self.parent.path, segment)

    def locator(self, selector):
        return FakeLocatorCollection(self.page, selector, parent=self)

    async def wait_for(self, *, state, timeout):
        assert timeout > 0
        visible = await self.is_visible()
        if state == "visible" and not visible:
            raise PlaywrightTimeoutError(f"{self.path} is not visible")
        if state == "hidden" and visible:
            raise PlaywrightTimeoutError(f"{self.path} is still visible")

    async def is_visible(self):
        return self.index < len(self.page.locator_texts(self.selector, self.parent))

    async def inner_text(self):
        return self.page.locator_texts(self.selector, self.parent)[self.index]

    async def scroll_into_view_if_needed(self):
        self.page.scrolled.append(self.path)

    async def click(self):
        self.page.clicks.append(self.path)


class FakePage:
    def __init__(self, texts):
        self.texts = texts
        self.clicks = []
        self.scrolled = []
        self.urls = []

    def locator_texts(self, selector, parent=None):
        if parent is None:
            key = selector
        else:
            key = (parent.selector, parent.index, selector)
        return self.texts.get(key, [])

    def locator(self, selector):
        return FakeLocatorCollection(self, selector)

    async def goto(self, url, wait_until=None):
        self.urls.append(url)


def card_text(name, cost, *, progress="0 / 1"):
    return f"{progress}\nMonthly\n{name}\n{cost}"


async def no_settle(seconds=1.0):
    return None


def test_parse_reward_card_accepts_current_monthly_card_text():
    item = parse_reward_card(
        "0 / 1\nMonthly\n[Global] Gem x120\n1999",
        card_index=4,
    )

    assert item == RewardItem(
        name="[Global] Gem x120",
        cost=1999,
        card_index=4,
        redeemed=False,
    )

    redeemed = parse_reward_card(
        "1 / 1\nMonthly\n[Global] Gem x120\n1999",
        card_index=4,
    )
    assert redeemed is not None
    assert redeemed.redeemed is True


def test_plan_redemptions_orders_by_cost_and_preserves_page_order_for_ties():
    rewards = [
        RewardItem("small-later", 1000, 8),
        RewardItem("large", 3000, 4),
        RewardItem("small-first", 1000, 2),
        RewardItem("medium", 2000, 1),
    ]

    planned = plan_redemptions(7000, rewards, {})

    assert [(item.cost, item.card_index) for item in planned] == [
        (3000, 4),
        (2000, 1),
        (1000, 2),
        (1000, 8),
    ]


def test_plan_redemptions_uses_remaining_balance_greedily():
    rewards = [
        RewardItem("large", 3000, 0),
        RewardItem("medium", 2000, 1),
        RewardItem("small", 1000, 2),
        RewardItem("tiny", 500, 3),
    ]

    planned = plan_redemptions(4500, rewards, {})

    assert [item.name for item in planned] == ["large", "small", "tiny"]


def test_plan_redemptions_skips_redeemed_stock_and_monthly_records():
    sold_out = RewardItem("sold-out", 4000, 0, redeemed=True)
    recorded = RewardItem("recorded", 3000, 1)
    available = RewardItem("available", 2000, 2)
    rewards = [sold_out, recorded, available]
    purchased = {recorded.tier_id: "2026-05-01T00:00:00"}

    assert plan_redemptions(10000, rewards, purchased) == [available]
    assert plan_redemptions(10000, rewards, purchased, force=True) == [
        recorded,
        available,
    ]


def test_redemption_record_store_resets_by_month(tmp_path):
    store = RedemptionRecordStore(tmp_path / "redemptions.json")

    store.mark_purchased("2026-05", "1999:[global] gem x120", datetime(2026, 5, 31, 12))

    assert store.load("2026-05") == {
        "1999:[global] gem x120": "2026-05-31T12:00:00"
    }
    assert store.load("2026-06") == {}


@pytest.mark.asyncio
async def test_read_reward_catalog_uses_dynamic_masonry_cards(tmp_path):
    assert DEFAULT_SELECTORS.reward_card == ".masonry-item"
    page = FakePage(
        {
            DEFAULT_SELECTORS.reward_card: [
                card_text("[Global] Gem x120", 1999),
                card_text("[Global] Gem x60", 999, progress="1 / 1"),
            ]
        }
    )
    runner = RewardRedemptionRunner(
        page,
        AppConfig(redemption_record_path=tmp_path / "redemptions.json"),
    )

    rewards = await runner._read_reward_catalog()

    assert rewards == [
        RewardItem("[Global] Gem x120", 1999, 0),
        RewardItem("[Global] Gem x60", 999, 1, redeemed=True),
    ]


@pytest.mark.asyncio
async def test_redeem_all_rejects_visible_but_unparseable_cards(tmp_path, monkeypatch):
    page = FakePage(
        {
            DEFAULT_SELECTORS.reward_card: ["Loading"],
            DEFAULT_SELECTORS.reward_token_amount: ["1,000"],
        }
    )
    runner = RewardRedemptionRunner(
        page,
        AppConfig(redemption_record_path=tmp_path / "redemptions.json"),
    )
    monkeypatch.setattr(runner, "_settle", no_settle)

    with pytest.raises(SelectorChangedError, match="无法解析任何奖励"):
        await runner.redeem_all()


@pytest.mark.asyncio
async def test_redeem_all_executes_the_dynamic_catalog_plan(tmp_path, monkeypatch):
    page = FakePage(
        {
            DEFAULT_SELECTORS.reward_card: [
                card_text("[Global] Small First", 1000),
                card_text("[Global] Large", 3000),
                card_text("[Global] Small Later", 1000),
            ],
            DEFAULT_SELECTORS.reward_token_amount: ["4,000"],
        }
    )
    runner = RewardRedemptionRunner(
        page,
        AppConfig(redemption_record_path=tmp_path / "redemptions.json"),
        now=datetime(2026, 5, 31, 12),
    )
    redeemed = []

    async def redeem_item(item, month):
        redeemed.append((item, month))
        return TaskResult(item.name, TaskStatus.COMPLETED, completed=1)

    monkeypatch.setattr(runner, "_settle", no_settle)
    monkeypatch.setattr(runner, "_redeem_item", redeem_item)

    summary = await runner.redeem_all()

    assert summary.ok is True
    assert [(item.name, month) for item, month in redeemed] == [
        ("[Global] Large", "2026-05"),
        ("[Global] Small First", "2026-05"),
    ]
    assert page.clicks == []


@pytest.mark.asyncio
async def test_redeem_all_dry_run_skips_clicks_and_records(tmp_path, monkeypatch):
    now = datetime(2026, 5, 31, 12)
    record_path = tmp_path / "redemptions.json"
    store = RedemptionRecordStore(record_path)
    recorded = RewardItem("[Global] Recorded", 2000, 2)
    store.mark_purchased("2026-05", recorded.tier_id, now)
    page = FakePage(
        {
            DEFAULT_SELECTORS.reward_card: [
                card_text("[Global] Sold Out", 5000, progress="1 / 1"),
                card_text("[Global] Available", 3000),
                card_text(recorded.name, recorded.cost),
                card_text("[Global] Remainder", 500),
            ],
            DEFAULT_SELECTORS.reward_token_amount: ["3,500"],
        }
    )
    config = AppConfig(redemption_record_path=record_path)
    runner = RewardRedemptionRunner(page, config, dry_run=True, now=now)
    monkeypatch.setattr(runner, "_settle", no_settle)

    summary = await runner.redeem_all()

    assert [result.name for result in summary.results] == [
        "[Global] Available",
        "[Global] Remainder",
    ]
    assert all(result.status is TaskStatus.SKIPPED for result in summary.results)
    assert page.clicks == []
    assert store.load("2026-05") == {
        recorded.tier_id: "2026-05-31T12:00:00"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verified", "expected_status", "should_record"),
    [
        (False, TaskStatus.FAILED, False),
        (True, TaskStatus.COMPLETED, True),
    ],
)
async def test_redeem_item_records_only_after_verification(
    tmp_path,
    monkeypatch,
    verified,
    expected_status,
    should_record,
):
    item = RewardItem("[Global] Gem x120", 1999, 0)
    card_scope = (
        DEFAULT_SELECTORS.reward_card,
        item.card_index,
        DEFAULT_SELECTORS.reward_title,
    )
    page = FakePage(
        {
            DEFAULT_SELECTORS.reward_card: [card_text(item.name, item.cost)],
            card_scope: [item.name],
            DEFAULT_SELECTORS.reward_modal_title: ["Redeem Detail"],
            DEFAULT_SELECTORS.reward_redeem_button: ["Redeem"],
        }
    )
    record_path = tmp_path / "redemptions.json"
    store = RedemptionRecordStore(record_path)
    runner = RewardRedemptionRunner(
        page,
        AppConfig(redemption_record_path=record_path),
        now=datetime(2026, 5, 31, 12),
        record_store=store,
    )

    async def no_op(*args, **kwargs):
        return None

    async def read_balance():
        return 5000

    async def find_reward_index(expected):
        assert expected == item
        return item.card_index

    async def verify_redemption(expected, balance_before):
        assert expected == item
        assert balance_before == 5000
        return verified

    monkeypatch.setattr(runner, "_open_points", no_op)
    monkeypatch.setattr(runner, "_wait_for_rewards_loaded", no_op)
    monkeypatch.setattr(runner, "_read_token_balance", read_balance)
    monkeypatch.setattr(runner, "_find_reward_index", find_reward_index)
    monkeypatch.setattr(runner, "_verify_redemption", verify_redemption)
    monkeypatch.setattr(runner, "_settle", no_settle)

    result = await runner._redeem_item(item, "2026-05")

    assert result.status is expected_status
    purchases = store.load("2026-05")
    assert (item.tier_id in purchases) is should_record
