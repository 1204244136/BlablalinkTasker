import pytest

from blablalink_tasker.config import AppConfig
from blablalink_tasker.models import TaskStatus
from blablalink_tasker.tasks import BlablaTaskRunner


class FakeCookieContext:
    async def cookies(self):
        return [{"name": "game_token", "value": "secret"}]


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
        return self.page.visible_counts.get(self.selector, 0)


class FakeLocator:
    def __init__(self, page, selector, index):
        self.page = page
        self.selector = selector
        self.index = index

    @property
    def first(self):
        return self

    async def wait_for(self, *, state, timeout):
        assert state == "visible"
        if self.page.visible_counts.get(self.selector, 0) <= self.index:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            raise PlaywrightTimeoutError("not visible")

    async def is_visible(self):
        hidden = self.page.hidden_indexes.get(self.selector, set())
        return self.page.visible_counts.get(self.selector, 0) > self.index and self.index not in hidden

    async def scroll_into_view_if_needed(self):
        self.page.scrolled.append((self.selector, self.index))

    async def click(self):
        self.page.clicks.append((self.selector, self.index))


class FakePage:
    def __init__(self, visible_counts=None, hidden_indexes=None):
        self.visible_counts = dict(visible_counts or {})
        self.hidden_indexes = {key: set(value) for key, value in (hidden_indexes or {}).items()}
        self.clicks = []
        self.scrolled = []
        self.url = "https://www.blablalink.com/"
        self.context = FakeCookieContext()

    def locator(self, selector):
        return FakeLocatorCollection(self, selector)

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
async def test_likes_use_different_elements_until_max():
    config = AppConfig(max_likes=3)
    selector = runner_selector("like_target")
    page = FakePage({selector: 5})
    runner = BlablaTaskRunner(page, config)

    result = await runner.do_likes()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 3
    assert result.completed == 3
    assert page.clicks == [
        (selector, 0),
        (selector, 0),
        (selector, 1),
        (selector, 1),
        (selector, 2),
        (selector, 2),
    ]


@pytest.mark.asyncio
async def test_likes_stop_at_visible_count():
    config = AppConfig(max_likes=5)
    selector = runner_selector("like_target")
    page = FakePage({selector: 2})
    runner = BlablaTaskRunner(page, config)

    result = await runner.do_likes()

    assert result.attempted == 2
    assert page.clicks == [(selector, 0), (selector, 0), (selector, 1), (selector, 1)]


@pytest.mark.asyncio
async def test_browses_use_different_elements_until_max():
    config = AppConfig(max_browses=2, browse_seconds=0)
    browse_selector = runner_selector("browse_target")
    close_selector = runner_selector("post_close")
    page = FakePage({browse_selector: 4, close_selector: 10})
    runner = BlablaTaskRunner(page, config)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2
    assert page.clicks == [
        (browse_selector, 0),
        (close_selector, 0),
        (browse_selector, 1),
        (close_selector, 0),
    ]


@pytest.mark.asyncio
async def test_browses_skip_hidden_matching_elements():
    config = AppConfig(max_browses=3, browse_seconds=0)
    browse_selector = runner_selector("browse_target")
    close_selector = runner_selector("post_close")
    page = FakePage(
        {browse_selector: 5, close_selector: 10},
        hidden_indexes={browse_selector: {1, 3}},
    )
    runner = BlablaTaskRunner(page, config)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 3
    assert result.completed == 3
    assert page.clicks == [
        (browse_selector, 0),
        (close_selector, 0),
        (browse_selector, 2),
        (close_selector, 0),
        (browse_selector, 4),
        (close_selector, 0),
    ]


def runner_selector(name):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    return getattr(DEFAULT_SELECTORS, name)
