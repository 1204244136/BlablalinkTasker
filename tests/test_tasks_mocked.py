import pytest

from blablalink_tasker.config import AppConfig
from blablalink_tasker.models import TaskResult, TaskStatus
from blablalink_tasker.tasks import BlablaTaskRunner


class FakeCookieContext:
    async def cookies(self):
        return [{"name": "game_token", "value": "secret"}]


class FakeLocatorCollection:
    def __init__(self, page, selector, text_pattern=None):
        self.page = page
        self.selector = selector
        self.text_pattern = text_pattern

    @property
    def first(self):
        indexes = self._matching_indexes()
        index = indexes[0] if indexes else 0
        return FakeLocator(self.page, self.selector, index, self.text_pattern)

    def nth(self, index):
        return FakeLocator(self.page, self.selector, index, self.text_pattern)

    def filter(self, *, has_text):
        return FakeLocatorCollection(self.page, self.selector, has_text)

    async def count(self):
        return self.page.visible_counts.get(self.selector, 0)

    def _matching_indexes(self):
        total = self.page.visible_counts.get(self.selector, 0)
        return [
            index
            for index in range(total)
            if self.page.is_visible(self.selector, index) and self.page.text_matches(self.selector, index, self.text_pattern)
        ]


class FakeLocator:
    def __init__(self, page, selector, index, text_pattern=None):
        self.page = page
        self.selector = selector
        self.index = index
        self.text_pattern = text_pattern

    @property
    def first(self):
        return self

    async def wait_for(self, *, state, timeout):
        assert state == "visible"
        if not await self.is_visible():
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            raise PlaywrightTimeoutError("not visible")

    async def is_visible(self):
        return self.page.is_visible(self.selector, self.index) and self.page.text_matches(
            self.selector, self.index, self.text_pattern
        )

    async def scroll_into_view_if_needed(self):
        self.page.scrolled.append((self.selector, self.index))

    async def click(self):
        self.page.clicks.append((self.selector, self.index))

    async def inner_text(self):
        values = self.page.texts.get(self.selector, [])
        if len(values) <= self.index:
            return ""
        return values[self.index]


class FakePage:
    def __init__(self, visible_counts=None, hidden_indexes=None, texts=None):
        self.visible_counts = dict(visible_counts or {})
        self.hidden_indexes = {key: set(value) for key, value in (hidden_indexes or {}).items()}
        self.texts = {key: list(value) for key, value in (texts or {}).items()}
        self.clicks = []
        self.scrolled = []
        self.url = "https://www.blablalink.com/"
        self.context = FakeCookieContext()

    def locator(self, selector):
        return FakeLocatorCollection(self, selector)

    def is_visible(self, selector, index):
        hidden = self.hidden_indexes.get(selector, set())
        return self.visible_counts.get(selector, 0) > index and index not in hidden

    def text_matches(self, selector, index, pattern):
        if pattern is None:
            return True
        values = self.texts.get(selector, [])
        if len(values) <= index:
            return False
        return bool(pattern.search(values[index]))

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


@pytest.mark.asyncio
async def test_points_progress_expands_and_passes_when_two_values_complete():
    expand_selector = runner_selector("points_expand_button")
    progress_selector = runner_selector("points_progress_text")
    page = FakePage(
        {expand_selector: 1, progress_selector: 2},
        texts={progress_selector: ["5 / 5", "5 / 5"]},
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert page.url == "https://www.blablalink.com/points"
    assert page.clicks == [(expand_selector, 0)]
    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2


@pytest.mark.asyncio
async def test_points_progress_fallback_passes_when_primary_selector_is_missing():
    expand_selector = runner_selector("points_expand_button")
    progress_selector = runner_selector("points_progress_text")
    fallback_selector = runner_selector("points_progress_fallback_texts")[0]
    page = FakePage(
        {expand_selector: 1, progress_selector: 0, fallback_selector: 2},
        texts={fallback_selector: ["5 / 5", "5 / 5"]},
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert result.completed == 2


@pytest.mark.asyncio
async def test_points_progress_fallback_extracts_values_from_longer_text():
    expand_selector = runner_selector("points_expand_button")
    progress_selector = runner_selector("points_progress_text")
    fallback_selector = runner_selector("points_progress_fallback_texts")[0]
    page = FakePage(
        {expand_selector: 1, progress_selector: 0, fallback_selector: 2},
        texts={fallback_selector: ["Browse mission 5 / 5", "Like mission 5 / 5"]},
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert result.completed == 2


@pytest.mark.asyncio
async def test_points_progress_fails_when_one_value_is_incomplete():
    expand_selector = runner_selector("points_expand_button")
    progress_selector = runner_selector("points_progress_text")
    page = FakePage(
        {expand_selector: 1, progress_selector: 2},
        texts={progress_selector: ["5 / 5", "4 / 5"]},
    )
    runner = BlablaTaskRunner(page, AppConfig(points_repair_rounds=0))

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 2
    assert result.completed == 1
    assert "4 / 5" in result.message


@pytest.mark.asyncio
async def test_points_progress_repairs_missing_browse_then_passes(monkeypatch):
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig(points_repair_rounds=2))
    readings = [["4 / 5", "5 / 5"], ["5 / 5", "5 / 5"]]
    calls = []

    async def settle(seconds=1.0):
        return None

    async def open_home():
        calls.append("home")

    async def do_browses():
        calls.append("browse")
        return TaskResult("浏览", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def do_likes():
        calls.append("like")
        return TaskResult("点赞 / 重新点赞", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def points_progress_values():
        return readings.pop(0)

    monkeypatch.setattr(runner, "_settle", settle)
    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "do_browses", do_browses)
    monkeypatch.setattr(runner, "do_likes", do_likes)
    monkeypatch.setattr(runner, "_points_progress_values", points_progress_values)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert result.completed == 2
    assert "补做 1 轮" in result.message
    assert calls == ["home", "browse"]


@pytest.mark.asyncio
async def test_points_progress_repairs_in_browse_then_like_order(monkeypatch):
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig(points_repair_rounds=2))
    readings = [["4 / 5", "3 / 5"], ["5 / 5", "5 / 5"]]
    calls = []

    async def settle(seconds=1.0):
        return None

    async def open_home():
        calls.append("home")

    async def do_browses():
        calls.append("browse")
        return TaskResult("浏览", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def do_likes():
        calls.append("like")
        return TaskResult("点赞 / 重新点赞", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def points_progress_values():
        return readings.pop(0)

    monkeypatch.setattr(runner, "_settle", settle)
    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "do_browses", do_browses)
    monkeypatch.setattr(runner, "do_likes", do_likes)
    monkeypatch.setattr(runner, "_points_progress_values", points_progress_values)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert calls == ["home", "browse", "like"]


@pytest.mark.asyncio
async def test_points_progress_stops_after_repair_round_limit(monkeypatch):
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig(points_repair_rounds=2))
    calls = []

    async def settle(seconds=1.0):
        return None

    async def open_home():
        calls.append("home")

    async def do_browses():
        calls.append("browse")
        return TaskResult("浏览", TaskStatus.ALREADY_DONE)

    async def points_progress_values():
        return ["4 / 5", "5 / 5"]

    monkeypatch.setattr(runner, "_settle", settle)
    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "do_browses", do_browses)
    monkeypatch.setattr(runner, "_points_progress_values", points_progress_values)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.FAILED
    assert result.completed == 1
    assert "已补做 2 轮" in result.message
    assert calls == ["home", "browse", "home", "browse"]


@pytest.mark.asyncio
async def test_points_progress_fails_when_less_than_two_values_are_found():
    expand_selector = runner_selector("points_expand_button")
    progress_selector = runner_selector("points_progress_text")
    page = FakePage(
        {expand_selector: 1, progress_selector: 1},
        texts={progress_selector: ["5 / 5"]},
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 2
    assert result.completed == 1
    assert "期望 2 个" in result.message


@pytest.mark.asyncio
async def test_points_progress_dry_run_skips_expand_click():
    expand_selector = runner_selector("points_expand_button")
    progress_selector = runner_selector("points_progress_text")
    page = FakePage(
        {expand_selector: 1, progress_selector: 2},
        texts={progress_selector: ["5 / 5", "5 / 5"]},
    )
    runner = BlablaTaskRunner(page, AppConfig(), dry_run=True)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.SKIPPED
    assert result.attempted == 2
    assert page.clicks == []


@pytest.mark.asyncio
async def test_run_all_includes_points_progress_failure(monkeypatch):
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig())

    async def open_home():
        return None

    async def check_login():
        return True

    async def completed_task():
        return TaskResult("任务", TaskStatus.COMPLETED)

    async def failed_points_task():
        return TaskResult("奖励中心复核", TaskStatus.FAILED, "未完成", attempted=2, completed=1)

    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "check_login", check_login)
    monkeypatch.setattr(runner, "do_check_in", completed_task)
    monkeypatch.setattr(runner, "do_likes", completed_task)
    monkeypatch.setattr(runner, "do_browses", completed_task)
    monkeypatch.setattr(runner, "verify_points_progress", failed_points_task)

    summary = await runner.run_all()

    assert summary.ok is False
    assert summary.results[-1].name == "奖励中心复核"
    assert summary.results[-1].status == TaskStatus.FAILED


def runner_selector(name):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    return getattr(DEFAULT_SELECTORS, name)
