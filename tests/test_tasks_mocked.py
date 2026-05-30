import pytest

from blablalink_tasker.config import AppConfig
from blablalink_tasker.models import TaskStatus
from blablalink_tasker.tasks import BlablaTaskRunner


class FakeCookieContext:
    async def cookies(self):
        return [{"name": "game_token", "value": "secret"}]


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    async def wait_for(self, *, state, timeout):
        assert state == "visible"
        if self.page.visible_counts.get(self.selector, 0) <= 0:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            raise PlaywrightTimeoutError("not visible")

    async def click(self):
        self.page.clicks.append(self.selector)
        if self.page.consume_on_click:
            self.page.visible_counts[self.selector] = max(self.page.visible_counts.get(self.selector, 0) - 1, 0)


class FakePage:
    def __init__(self, visible_counts=None):
        self.visible_counts = dict(visible_counts or {})
        self.clicks = []
        self.url = "https://www.blablalink.com/"
        self.context = FakeCookieContext()
        self.consume_on_click = False

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def goto(self, url, wait_until=None):
        self.url = url

    async def title(self):
        return "BlablaLink"

    async def go_back(self, **kwargs):
        self.url = "https://www.blablalink.com/"


@pytest.mark.asyncio
async def test_check_login_uses_game_cookie():
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig())

    assert await runner.check_login() is True


@pytest.mark.asyncio
async def test_check_in_dry_run_skips_click():
    config = AppConfig()
    page = FakePage({runner_selector("check_in_button"): 1})
    runner = BlablaTaskRunner(page, config, dry_run=True)

    result = await runner.do_check_in()

    assert result.status == TaskStatus.SKIPPED
    assert page.clicks == []


@pytest.mark.asyncio
async def test_likes_stop_at_max():
    config = AppConfig(max_likes=3)
    page = FakePage({runner_selector("like_target"): 10})
    runner = BlablaTaskRunner(page, config)

    result = await runner.do_likes()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 3
    assert result.completed == 3


@pytest.mark.asyncio
async def test_browses_stop_at_max():
    config = AppConfig(max_browses=2, browse_seconds=0)
    page = FakePage({runner_selector("browse_target"): 10, runner_selector("post_close"): 10})
    runner = BlablaTaskRunner(page, config)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2


def runner_selector(name):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    return getattr(DEFAULT_SELECTORS, name)
