from datetime import datetime

import pytest

from blablalink_tasker.config import AppConfig
from blablalink_tasker.rewards import (
    RedemptionRecordStore,
    RewardRedemptionRunner,
    plan_redemptions,
)


class FakeLocatorCollection:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return FakeLocator(self.page, self.selector, 0)

    def nth(self, index):
        return FakeLocator(self.page, self.selector, index)

    async def count(self):
        return len(self.page.texts.get(self.selector, []))


class FakeLocator:
    def __init__(self, page, selector, index):
        self.page = page
        self.selector = selector
        self.index = index

    async def wait_for(self, *, state, timeout):
        assert state == "visible"

    async def is_visible(self):
        return self.index < len(self.page.texts.get(self.selector, []))

    async def inner_text(self):
        if hasattr(self.page, "next_text"):
            return self.page.next_text(self.selector, self.index)
        return self.page.texts[self.selector][self.index]

    async def scroll_into_view_if_needed(self):
        self.page.scrolled.append((self.selector, self.index))

    async def click(self):
        self.page.clicks.append((self.selector, self.index))


class FakePage:
    def __init__(self, texts):
        self.texts = texts
        self.clicks = []
        self.scrolled = []
        self.urls = []

    def locator(self, selector):
        return FakeLocatorCollection(self, selector)

    async def goto(self, url, wait_until=None):
        self.urls.append(url)


class LoadingFakePage(FakePage):
    def __init__(self, texts, selector, loading_values):
        super().__init__(texts)
        self.selector = selector
        self.loading_values = list(loading_values)

    def next_text(self, selector, index):
        if selector == self.selector and index == 0 and self.loading_values:
            return self.loading_values.pop(0)
        return self.texts[selector][index]


def test_plan_redemptions_buys_gems_large_to_small_before_welcome():
    tiers = plan_redemptions(5000, {})

    assert [tier.tier_id for tier in tiers] == ["gem_4999", "welcome_gift"]


def test_plan_redemptions_skips_monthly_records():
    tiers = plan_redemptions(6000, {"gem_4999": "2026-05-01T00:00:00"})

    assert [tier.tier_id for tier in tiers] == ["gem_1999", "gem_999", "gem_499", "welcome_gift"]


def test_redemption_record_store_resets_by_month(tmp_path):
    store = RedemptionRecordStore(tmp_path / "redemptions.json")

    store.mark_purchased("2026-05", "gem_499", datetime(2026, 5, 31, 12, 0, 0))

    assert store.load("2026-05") == {"gem_499": "2026-05-31T12:00:00"}
    assert store.load("2026-06") == {}


@pytest.mark.asyncio
async def test_redeem_all_clicks_planned_rewards_and_records(tmp_path, monkeypatch):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    title_selector = DEFAULT_SELECTORS.reward_title
    token_selector = DEFAULT_SELECTORS.reward_token_amount
    button_selector = DEFAULT_SELECTORS.reward_redeem_button
    page = FakePage(
        {
            token_selector: ["5000"],
            title_selector: [
                "[Global] Welcome Gift: Core Dust ×30",
                "[Global] Gem ×30",
                "[Global] Gem ×60",
                "[Global] Credit Case (1H) ×9",
                "[Global] Core Dust Case (1H) ×3",
                "[Global] Gem ×120",
                "[Global] Gem ×320",
            ],
            button_selector: ["Redeem"],
        }
    )
    record_path = tmp_path / "redemptions.json"
    config = AppConfig(redemption_record_path=record_path)
    runner = RewardRedemptionRunner(page, config, now=datetime(2026, 5, 31, 12, 0, 0))

    async def settle(seconds=1.0):
        return None

    monkeypatch.setattr(runner, "_settle", settle)

    summary = await runner.redeem_all()

    assert summary.ok is True
    assert [result.name for result in summary.results] == ["珠宝×320", "欢迎礼物（芯尘×30）"]
    assert page.clicks == [
        (title_selector, 6),
        (button_selector, 0),
        (title_selector, 0),
        (button_selector, 0),
    ]
    purchases = RedemptionRecordStore(record_path).load("2026-05")
    assert sorted(purchases) == ["gem_4999", "welcome_gift"]


@pytest.mark.asyncio
async def test_redeem_all_waits_for_nonzero_token_balance(tmp_path, monkeypatch):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    title_selector = DEFAULT_SELECTORS.reward_title
    token_selector = DEFAULT_SELECTORS.reward_token_amount
    button_selector = DEFAULT_SELECTORS.reward_redeem_button
    page = LoadingFakePage(
        {
            token_selector: ["5000"],
            title_selector: [
                "[Global] Welcome Gift: Core Dust ×30",
                "[Global] Gem ×30",
                "[Global] Gem ×60",
                "[Global] Gem ×120",
                "[Global] Gem ×320",
            ],
            button_selector: ["Redeem"],
        },
        token_selector,
        ["0", "0", "5000"],
    )
    config = AppConfig(redemption_record_path=tmp_path / "redemptions.json")
    runner = RewardRedemptionRunner(page, config, now=datetime(2026, 5, 31, 12, 0, 0))

    async def settle(seconds=1.0):
        return None

    monkeypatch.setattr(runner, "_settle", settle)

    summary = await runner.redeem_all()

    assert summary.ok is True
    assert [result.name for result in summary.results] == ["珠宝×320", "欢迎礼物（芯尘×30）"]


@pytest.mark.asyncio
async def test_redeem_all_skips_when_monthly_records_exist(tmp_path, monkeypatch):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    store = RedemptionRecordStore(tmp_path / "redemptions.json")
    now = datetime(2026, 5, 31, 12, 0, 0)
    for tier_id in ["gem_4999", "gem_1999", "gem_999", "gem_499", "welcome_gift"]:
        store.mark_purchased("2026-05", tier_id, now)

    page = FakePage(
        {
            DEFAULT_SELECTORS.reward_token_amount: ["10879"],
            DEFAULT_SELECTORS.reward_title: [],
            DEFAULT_SELECTORS.reward_redeem_button: ["Redeem"],
        }
    )
    config = AppConfig(redemption_record_path=tmp_path / "redemptions.json")
    runner = RewardRedemptionRunner(page, config, now=now)

    async def settle(seconds=1.0):
        return None

    monkeypatch.setattr(runner, "_settle", settle)

    summary = await runner.redeem_all()

    assert summary.ok is True
    assert summary.results[0].status.value == "already_done"
    assert page.clicks == []
