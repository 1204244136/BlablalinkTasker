import pytest

from blablalink_tasker.config import AppConfig
from blablalink_tasker.models import TaskResult, TaskStatus
from blablalink_tasker.tasks import BlablaTaskRunner


class FakeCookieContext:
    async def cookies(self):
        return [{"name": "game_token", "value": "secret"}]


class FakeMouse:
    def __init__(self, page):
        self.page = page

    async def click(self, x, y):
        self.page.mouse_clicks.append((x, y))
        self.page.dialog_visible = False


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
        self.page.count_calls.append(self.selector)
        return self.page.visible_counts.get(self.selector, 0)

    def _matching_indexes(self):
        total = self.page.visible_counts.get(self.selector, 0)
        return [
            index
            for index in range(total)
            if self.page.is_visible(self.selector, index)
            and self.page.text_matches(self.selector, index, self.text_pattern)
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
        assert state in {"hidden", "visible"}
        self.page.waits.append((self.selector, self.index, state))
        visible = await self.is_visible()
        if (state == "visible" and not visible) or (state == "hidden" and visible):
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            raise PlaywrightTimeoutError(f"not {state}")

    async def is_visible(self):
        return self.page.is_visible(self.selector, self.index) and self.page.text_matches(
            self.selector, self.index, self.text_pattern
        )

    async def scroll_into_view_if_needed(self):
        self.page.scrolled.append((self.selector, self.index))

    async def click(self):
        self.page.handle_click(self.selector, self.index)

    async def inner_text(self):
        values = self.page.texts.get(self.selector, [])
        if len(values) <= self.index:
            return ""
        return values[self.index]

    async def get_attribute(self, name):
        values = self.page.attributes.get(self.selector, [])
        if len(values) <= self.index:
            return None
        return values[self.index].get(name)

    def locator(self, selector):
        return FakeLocatorCollection(self.page, f"{self.selector} >> {selector}")

    async def bounding_box(self):
        return self.page.bounding_boxes.get(self.selector)


class FakePage:
    def __init__(
        self,
        visible_counts=None,
        hidden_indexes=None,
        texts=None,
        detail_selector=None,
        expand_selector=None,
        expand_reveals=None,
        click_hides_selector=None,
        attributes=None,
        detail_urls=None,
        dialog_selector=None,
        dialog_close_selector=None,
        dialog_blocks_clicks=0,
        click_handlers=None,
        bounding_boxes=None,
    ):
        self.visible_counts = dict(visible_counts or {})
        self.hidden_indexes = {key: set(value) for key, value in (hidden_indexes or {}).items()}
        self.texts = {key: list(value) for key, value in (texts or {}).items()}
        self.detail_selector = detail_selector
        self.expand_selector = expand_selector
        self.expand_reveals = expand_reveals
        self.click_hides_selector = click_hides_selector
        self.attributes = {key: list(value) for key, value in (attributes or {}).items()}
        self.detail_urls = list(detail_urls or [])
        self.dialog_selector = dialog_selector
        self.dialog_close_selector = dialog_close_selector or dialog_selector
        self.dialog_blocks_clicks = dialog_blocks_clicks
        self.dialog_visible = dialog_selector is not None and self.visible_counts.get(dialog_selector, 0) > 0
        self.click_handlers = dict(click_handlers or {})
        self.bounding_boxes = dict(bounding_boxes or {})
        self.in_detail = False
        self.clicks = []
        self.scrolled = []
        self.waits = []
        self.locator_calls = []
        self.count_calls = []
        self.settles = []
        self.url_history = []
        self.detail_visits = []
        self.mouse_clicks = []
        self.go_back_calls = 0
        self.url = "https://www.blablalink.com/"
        self.context = FakeCookieContext()
        self.viewport_size = {"width": 1366, "height": 900}
        self.mouse = FakeMouse(self)

    def locator(self, selector):
        self.locator_calls.append(selector)
        return FakeLocatorCollection(self, selector)

    def is_visible(self, selector, index):
        if selector == self.dialog_selector:
            return self.dialog_visible and self.visible_counts.get(selector, 0) > index
        if self.in_detail and selector == self.detail_selector:
            return False
        hidden = self.hidden_indexes.get(selector, set())
        return self.visible_counts.get(selector, 0) > index and index not in hidden

    def text_matches(self, selector, index, pattern):
        if pattern is None:
            return True
        values = self.texts.get(selector, [])
        if len(values) <= index:
            return False
        return bool(pattern.search(values[index]))

    def handle_click(self, selector, index):
        if (
            self.dialog_visible
            and selector != self.dialog_close_selector
            and self.dialog_blocks_clicks > 0
        ):
            self.dialog_blocks_clicks -= 1
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            raise PlaywrightTimeoutError("home dialog blocks click")

        self.clicks.append((selector, index))
        if selector == self.dialog_close_selector and self.dialog_visible:
            self.dialog_visible = False
            self.hidden_indexes.setdefault(selector, set()).add(index)
        if selector == self.expand_selector and self.expand_reveals is not None:
            self.hidden_indexes.get(self.expand_reveals, set()).clear()
        if selector == self.click_hides_selector:
            self.hidden_indexes.setdefault(selector, set()).add(index)
        if selector == self.detail_selector:
            self.in_detail = True
            if len(self.detail_urls) > index:
                self.url = self.detail_urls[index]
            else:
                self.url = "https://www.blablalink.com/post/detail/mock"
            self.detail_visits.append(self.url)

        handler = self.click_handlers.get(selector)
        if handler is not None:
            handler(self, index)

    async def goto(self, url, wait_until=None):
        self.url = url
        self.url_history.append(url)

    async def title(self):
        return "BlablaLink"

    async def go_back(self, **kwargs):
        self.go_back_calls += 1
        self.in_detail = False
        self.url = "https://www.blablalink.com/"
        self.url_history.append(self.url)

    async def wait_for_url(self, pattern, **kwargs):
        if hasattr(pattern, "search"):
            matched = pattern.search(self.url) is not None
        else:
            matched = self.url == pattern
        if not matched:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError

            raise PlaywrightTimeoutError(f"URL did not match: {self.url}")


class ReflowLikePage(FakePage):
    """A like list whose DOM indexes shrink after every successful click."""

    def __init__(self, like_selector, count):
        super().__init__({like_selector: count}, click_hides_selector=like_selector)
        self.like_selector = like_selector

    def handle_click(self, selector, index):
        super().handle_click(selector, index)
        if selector == self.like_selector:
            self.visible_counts[selector] = max(self.visible_counts.get(selector, 0) - 1, 0)
            self.hidden_indexes[selector] = set()


class ReflowBrowsePage(FakePage):
    """A recommendation list that is re-enumerated and reordered after return."""

    def __init__(self, browse_selector, states):
        self.browse_selector = browse_selector
        self.states = list(states)
        self.state_index = 0
        super().__init__({browse_selector: 0}, detail_selector=browse_selector)
        self._apply_state()

    def _apply_state(self):
        state = self.states[min(self.state_index, len(self.states) - 1)]
        self.visible_counts[self.browse_selector] = len(state)
        self.texts[self.browse_selector] = [title for title, _ in state]
        self.detail_urls = [url for _, url in state]
        self.hidden_indexes[self.browse_selector] = set()

    async def go_back(self, **kwargs):
        await super().go_back(**kwargs)
        if self.state_index < len(self.states) - 1:
            self.state_index += 1
            self._apply_state()


class BlockingDialogPage(FakePage):
    """Shows a home dialog only when the first target click is attempted."""

    def __init__(self, browse_selector, dialog_selector):
        super().__init__(
            {browse_selector: 1, dialog_selector: 1},
            detail_selector=browse_selector,
            dialog_selector=dialog_selector,
            dialog_close_selector=dialog_selector,
            dialog_blocks_clicks=1,
            detail_urls=["https://www.blablalink.com/post/detail?source=dialog"],
        )
        self.browse_selector = browse_selector
        self.dialog_visible = False
        self._dialog_triggered = False

    def handle_click(self, selector, index):
        if selector == self.browse_selector and not self._dialog_triggered:
            self._dialog_triggered = True
            self.dialog_visible = True
        super().handle_click(selector, index)


def record_settle(runner, page):
    async def settle(seconds=1.0):
        page.settles.append(seconds)

    runner._settle = settle


@pytest.mark.asyncio
async def test_check_login_uses_game_cookie():
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig())

    assert await runner.check_login() is True


@pytest.mark.asyncio
async def test_check_login_prefers_authenticated_balance_over_daily_check_in_title():
    balance_selector = runner_selector("authenticated_points_balance")
    logged_out_selector = runner_selector("logged_out_marker")
    page = FakePage({balance_selector: 1, logged_out_selector: 1})
    runner = BlablaTaskRunner(page, AppConfig())

    assert await runner.check_login() is True


@pytest.mark.asyncio
async def test_check_login_rejects_logged_out_marker_even_with_stale_cookie():
    logged_out_selector = runner_selector("logged_out_marker")
    page = FakePage({logged_out_selector: 1})
    runner = BlablaTaskRunner(page, AppConfig())

    assert await runner.check_login() is False


@pytest.mark.asyncio
async def test_check_in_returns_already_done_when_done_is_visible():
    done_selector = runner_selector("check_in_done")
    page = FakePage({done_selector: 1})
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.do_check_in()

    assert result.status == TaskStatus.ALREADY_DONE
    assert result.attempted == 0
    assert page.clicks == []


@pytest.mark.asyncio
async def test_check_in_dry_run_skips_click():
    button_selector = runner_selector("check_in_button")
    page = FakePage({button_selector: 1})
    runner = BlablaTaskRunner(page, AppConfig(), dry_run=True)

    result = await runner.do_check_in()

    assert result.status == TaskStatus.SKIPPED
    assert result.attempted == 1
    assert page.clicks == []


@pytest.mark.asyncio
async def test_check_in_fails_when_button_and_done_are_missing():
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.do_check_in()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 0
    assert "签到按钮或完成状态" in result.message


def test_current_like_and_points_expand_selectors_are_used():
    assert 'svg[viewBox="0 0 48 48"]' in runner_selector("like_target")
    assert runner_selector("points_expand_button") == ".btn-mask.cursor-pointer"


@pytest.mark.asyncio
async def test_likes_click_each_unliked_target_once_until_max(monkeypatch):
    config = AppConfig(max_likes=3)
    like_selector = runner_selector("like_target")
    page = FakePage({like_selector: 5}, click_hides_selector=like_selector)
    runner = BlablaTaskRunner(page, config)

    record_settle(runner, page)

    result = await runner.do_likes()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 3
    assert result.completed == 3
    assert page.clicks == [
        (like_selector, 4),
        (like_selector, 3),
        (like_selector, 2),
    ]
    assert page.settles == [1.0, 1.0, 1.0]


@pytest.mark.asyncio
async def test_likes_skip_hidden_targets(monkeypatch):
    config = AppConfig(max_likes=3)
    like_selector = runner_selector("like_target")
    page = FakePage(
        {like_selector: 5},
        hidden_indexes={like_selector: {1, 3}},
        click_hides_selector=like_selector,
    )
    runner = BlablaTaskRunner(page, config)

    record_settle(runner, page)

    result = await runner.do_likes()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 3
    assert result.completed == 3
    assert page.clicks == [
        (like_selector, 4),
        (like_selector, 2),
        (like_selector, 0),
    ]
    assert page.settles == [1.0, 1.0, 1.0]


@pytest.mark.asyncio
async def test_likes_refresh_reflowing_svg_collection_between_clicks():
    like_selector = runner_selector("like_target")
    page = ReflowLikePage(like_selector, count=3)
    runner = BlablaTaskRunner(page, AppConfig(max_likes=3, timeout_ms=100))
    record_settle(runner, page)

    result = await runner.do_likes()

    assert result.status == TaskStatus.COMPLETED
    assert result.completed == 3
    assert page.clicks == [
        (like_selector, 2),
        (like_selector, 1),
        (like_selector, 0),
    ]
    assert page.locator_calls.count(like_selector) >= result.completed + 1
    assert page.settles == [1.0, 1.0, 1.0]


@pytest.mark.asyncio
async def test_likes_fail_when_no_unliked_target_is_found():
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.do_likes()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 0
    assert result.completed == 0
    assert "未点赞" in result.message
    assert page.clicks == []


@pytest.mark.asyncio
async def test_likes_skip_without_querying_targets_when_budget_is_zero():
    like_selector = runner_selector("like_target")
    page = FakePage({like_selector: 3})
    runner = BlablaTaskRunner(page, AppConfig(max_likes=0))

    result = await runner.do_likes()

    assert result.status in {TaskStatus.SKIPPED, TaskStatus.ALREADY_DONE}
    assert result.attempted == 0
    assert result.completed == 0
    assert like_selector not in page.locator_calls
    assert page.clicks == []


@pytest.mark.asyncio
async def test_browses_open_details_and_return_until_max():
    config = AppConfig(max_browses=2, browse_seconds=0)
    browse_selector = runner_selector("browse_target")
    page = FakePage(
        {browse_selector: 4},
        texts={browse_selector: ["A", "B", "C", "D"]},
        detail_selector=browse_selector,
        detail_urls=[
            "https://www.blablalink.com/post/detail?id=a",
            "https://www.blablalink.com/post/detail?id=b",
            "https://www.blablalink.com/post/detail?id=c",
            "https://www.blablalink.com/post/detail?id=d",
        ],
    )
    runner = BlablaTaskRunner(page, config)
    record_settle(runner, page)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2
    assert page.clicks == [(browse_selector, 0), (browse_selector, 1)]
    assert page.go_back_calls == 2
    assert page.in_detail is False
    assert page.detail_visits == [
        "https://www.blablalink.com/post/detail?id=a",
        "https://www.blablalink.com/post/detail?id=b",
    ]
    assert sum(
        state == "visible"
        for selector, _, state in page.waits
        if selector == browse_selector
    ) >= 3


@pytest.mark.asyncio
async def test_browses_skip_hidden_elements():
    config = AppConfig(max_browses=3, browse_seconds=0)
    browse_selector = runner_selector("browse_target")
    page = FakePage(
        {browse_selector: 5},
        hidden_indexes={browse_selector: {1, 3}},
        texts={browse_selector: ["A", "B", "C", "D", "E"]},
        detail_selector=browse_selector,
        detail_urls=[
            "https://www.blablalink.com/post/detail?id=a",
            "https://www.blablalink.com/post/detail?id=b",
            "https://www.blablalink.com/post/detail?id=c",
            "https://www.blablalink.com/post/detail?id=d",
            "https://www.blablalink.com/post/detail?id=e",
        ],
    )
    runner = BlablaTaskRunner(page, config)
    record_settle(runner, page)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 3
    assert result.completed == 3
    assert page.clicks == [
        (browse_selector, 0),
        (browse_selector, 2),
        (browse_selector, 4),
    ]
    assert page.go_back_calls == 3


@pytest.mark.asyncio
async def test_browses_reenumerate_and_ignore_duplicate_detail_urls():
    browse_selector = runner_selector("browse_target")
    duplicate_url = "https://www.blablalink.com/post/detail?id=duplicate"
    unique_url = "https://www.blablalink.com/post/detail?id=unique"
    page = ReflowBrowsePage(
        browse_selector,
        states=[
            [("First", duplicate_url), ("Second", duplicate_url), ("Third", unique_url)],
            [("Second", duplicate_url), ("Third", unique_url)],
            [("Third", unique_url)],
        ],
    )
    runner = BlablaTaskRunner(
        page,
        AppConfig(max_browses=2, browse_seconds=0, timeout_ms=100),
    )
    record_settle(runner, page)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.completed == 2
    assert page.detail_visits == [duplicate_url, duplicate_url, unique_url]
    assert page.go_back_calls == 3
    assert page.state_index == 2
    assert page.locator_calls.count(browse_selector) >= 3


@pytest.mark.asyncio
async def test_browses_close_blocking_home_dialog_and_retry(monkeypatch):
    browse_selector = runner_selector("browse_target")
    dialog_selector = runner_selector("home_event_dialog")
    page = BlockingDialogPage(browse_selector, dialog_selector)
    page.texts[browse_selector] = ["Dialog blocked post"]
    runner = BlablaTaskRunner(
        page,
        AppConfig(max_browses=1, browse_seconds=0, timeout_ms=100),
    )
    dismiss_calls = []

    async def dismiss_home_event_dialogs():
        dismiss_calls.append(page.dialog_visible)
        if not page.dialog_visible:
            return False
        page.dialog_visible = False
        return True

    monkeypatch.setattr(runner, "_dismiss_home_event_dialogs", dismiss_home_event_dialogs)
    record_settle(runner, page)

    result = await runner.do_browses()

    assert result.status == TaskStatus.COMPLETED
    assert result.completed == 1
    assert page.detail_visits == ["https://www.blablalink.com/post/detail?source=dialog"]
    assert dismiss_calls.count(True) == 1
    assert page.clicks == [(browse_selector, 0)]


@pytest.mark.asyncio
async def test_home_event_dialog_is_dismissed_by_clicking_outside_its_box():
    dialog_selector = runner_selector("home_event_dialog")
    page = FakePage(
        {dialog_selector: 1},
        dialog_selector=dialog_selector,
        bounding_boxes={
            dialog_selector: {"x": 400, "y": 80, "width": 500, "height": 700},
        },
    )
    runner = BlablaTaskRunner(page, AppConfig())

    dismissed = await runner._dismiss_home_event_dialogs()

    assert dismissed is True
    assert page.dialog_visible is False
    assert page.mouse_clicks == [(388, 88)]
    assert (dialog_selector, 0, "hidden") in page.waits


@pytest.mark.asyncio
async def test_browses_fail_when_no_target_is_found():
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.do_browses()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 0
    assert result.completed == 0
    assert "推荐帖子标题" in result.message
    assert page.go_back_calls == 0


@pytest.mark.asyncio
async def test_browses_skip_without_querying_targets_when_budget_is_zero():
    browse_selector = runner_selector("browse_target")
    page = FakePage(
        {browse_selector: 2},
        texts={browse_selector: ["A", "B"]},
        detail_selector=browse_selector,
    )
    runner = BlablaTaskRunner(page, AppConfig(max_browses=0, browse_seconds=0))

    result = await runner.do_browses()

    assert result.status in {TaskStatus.SKIPPED, TaskStatus.ALREADY_DONE}
    assert result.attempted == 0
    assert result.completed == 0
    assert browse_selector not in page.locator_calls
    assert page.clicks == []


@pytest.mark.asyncio
async def test_points_progress_expands_folded_like_row_and_reads_both_tasks():
    browse_selector = runner_selector("points_browse_task_row")
    like_selector = runner_selector("points_like_task_row")
    expand_selector = runner_selector("points_expand_button")
    page = FakePage(
        {browse_selector: 1, like_selector: 1, expand_selector: 1},
        hidden_indexes={like_selector: {0}},
        texts={
            browse_selector: ["Browse 5 posts\n5 / 5"],
            like_selector: ["Like 5 posts\n5 / 5"],
        },
        expand_selector=expand_selector,
        expand_reveals=like_selector,
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert page.url == "https://www.blablalink.com/points"
    assert page.clicks == [(expand_selector, 0)]
    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2


@pytest.mark.asyncio
async def test_points_progress_does_not_collapse_already_visible_like_row():
    browse_selector = runner_selector("points_browse_task_row")
    like_selector = runner_selector("points_like_task_row")
    expand_selector = runner_selector("points_expand_button")
    page = FakePage(
        {browse_selector: 1, like_selector: 1, expand_selector: 1},
        texts={
            browse_selector: ["Browse 5 posts\n5 / 5"],
            like_selector: ["Like 5 posts\n5 / 5"],
        },
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2
    assert page.clicks == []


@pytest.mark.asyncio
async def test_points_progress_fails_when_like_task_is_incomplete():
    browse_selector = runner_selector("points_browse_task_row")
    like_selector = runner_selector("points_like_task_row")
    page = FakePage(
        {browse_selector: 1, like_selector: 1},
        texts={
            browse_selector: ["Browse 5 posts 5 / 5"],
            like_selector: ["Like 5 posts 4 / 5"],
        },
    )
    runner = BlablaTaskRunner(page, AppConfig(points_repair_rounds=0))

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 2
    assert result.completed == 1
    assert "4 / 5" in result.message


@pytest.mark.parametrize(
    ("value", "complete"),
    [
        ("3 / 3", True),
        ("5 / 3", True),
        ("4 / 5", False),
        ("0 / 0", False),
        ("0 / 3", False),
    ],
)
def test_points_progress_completion_uses_reported_positive_target(value, complete):
    assert BlablaTaskRunner._is_complete_points_progress(value) is complete


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

    async def do_browses(*, max_actions=None):
        assert max_actions == 1
        calls.append("browse")
        return TaskResult("浏览", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def points_progress_values():
        return readings.pop(0)

    monkeypatch.setattr(runner, "_settle", settle)
    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "do_browses", do_browses)
    monkeypatch.setattr(runner, "_points_progress_values", points_progress_values)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2
    assert "补做 1 轮" in result.message
    assert calls == ["home", "browse"]


@pytest.mark.asyncio
async def test_points_progress_repairs_browse_then_like_when_both_are_missing(monkeypatch):
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig(points_repair_rounds=2))
    readings = [["4 / 5", "3 / 5"], ["5 / 5", "5 / 5"]]
    calls = []

    async def open_home():
        calls.append("home")

    async def do_browses(*, max_actions=None):
        assert max_actions == 1
        calls.append("browse")
        return TaskResult("浏览", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def do_likes(*, max_actions=None):
        assert max_actions == 2
        calls.append("like")
        return TaskResult("点赞", TaskStatus.COMPLETED, attempted=1, completed=1)

    async def points_progress_values():
        return readings.pop(0)

    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "do_browses", do_browses)
    monkeypatch.setattr(runner, "do_likes", do_likes)
    monkeypatch.setattr(runner, "_points_progress_values", points_progress_values)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.COMPLETED
    assert result.attempted == 2
    assert result.completed == 2
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

    async def do_browses(*, max_actions=None):
        assert max_actions == 1
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
    assert result.attempted == 2
    assert result.completed == 1
    assert "已补做 2 轮" in result.message
    assert calls == ["home", "browse", "home", "browse"]


@pytest.mark.asyncio
async def test_points_progress_fails_when_like_row_remains_missing_after_expand():
    browse_selector = runner_selector("points_browse_task_row")
    like_selector = runner_selector("points_like_task_row")
    expand_selector = runner_selector("points_expand_button")
    page = FakePage(
        {browse_selector: 1, like_selector: 1, expand_selector: 1},
        hidden_indexes={like_selector: {0}},
        texts={
            browse_selector: ["Browse 5 posts\n5 / 5"],
            like_selector: ["Like 5 posts\n5 / 5"],
        },
    )
    runner = BlablaTaskRunner(page, AppConfig())

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.FAILED
    assert result.attempted == 2
    assert result.completed == 1
    assert "期望 2 个" in result.message
    assert page.clicks == [(expand_selector, 0)]


@pytest.mark.asyncio
async def test_points_progress_dry_run_skips_page_load():
    page = FakePage()
    runner = BlablaTaskRunner(page, AppConfig(), dry_run=True)

    result = await runner.verify_points_progress()

    assert result.status == TaskStatus.SKIPPED
    assert result.attempted == 2
    assert result.completed == 0
    assert page.url == "https://www.blablalink.com/"
    assert page.clicks == []


@pytest.mark.asyncio
async def test_run_all_reads_complete_progress_after_check_in_and_performs_no_actions(monkeypatch):
    like_selector = runner_selector("like_target")
    browse_selector = runner_selector("browse_target")
    page = FakePage(
        {like_selector: 3, browse_selector: 3},
        texts={browse_selector: ["A", "B", "C"]},
        detail_selector=browse_selector,
    )
    runner = BlablaTaskRunner(page, AppConfig())
    events = []

    async def open_home():
        events.append("home")

    async def check_login():
        events.append("login")
        return True

    async def check_in_task():
        events.append("check-in")
        return TaskResult("签到", TaskStatus.ALREADY_DONE)

    async def load_points_progress_values():
        events.append("points")
        return ["5 / 5", "5 / 5"]

    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "check_login", check_login)
    monkeypatch.setattr(runner, "do_check_in", check_in_task)
    monkeypatch.setattr(runner, "_load_points_progress_values", load_points_progress_values)

    summary = await runner.run_all()

    assert events[:4] == ["home", "login", "check-in", "points"]
    assert page.clicks == []
    assert [result.name for result in summary.results] == ["签到", "点赞", "浏览", "奖励中心复核"]
    assert summary.ok is True


@pytest.mark.asyncio
async def test_run_all_uses_only_partial_progress_deficits(monkeypatch):
    runner = BlablaTaskRunner(
        FakePage(),
        AppConfig(max_likes=5, max_browses=5, points_repair_rounds=0),
    )
    readings = iter(
        [
            ["4 / 5", "3 / 5"],
            ["5 / 5", "5 / 5"],
        ]
    )
    events = []
    actions = {"like": 0, "browse": 0}

    async def open_home():
        events.append("home")

    async def check_login():
        return True

    async def check_in_task():
        events.append("check-in")
        return TaskResult("签到", TaskStatus.COMPLETED)

    async def load_points_progress_values():
        events.append("points")
        return next(readings)

    async def like_task(*, max_actions=None):
        events.append("like")
        allowed = runner._like_budget_remaining
        if max_actions is not None:
            allowed = min(allowed, max_actions)
        actions["like"] += allowed
        runner._like_budget_remaining -= allowed
        return TaskResult("点赞", TaskStatus.COMPLETED, attempted=allowed, completed=allowed)

    async def browse_task(*, max_actions=None):
        events.append("browse")
        allowed = runner._browse_budget_remaining
        if max_actions is not None:
            allowed = min(allowed, max_actions)
        actions["browse"] += allowed
        runner._browse_budget_remaining -= allowed
        return TaskResult("浏览", TaskStatus.COMPLETED, attempted=allowed, completed=allowed)

    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "check_login", check_login)
    monkeypatch.setattr(runner, "do_check_in", check_in_task)
    monkeypatch.setattr(runner, "_load_points_progress_values", load_points_progress_values)
    monkeypatch.setattr(runner, "do_likes", like_task)
    monkeypatch.setattr(runner, "do_browses", browse_task)

    summary = await runner.run_all()

    assert events.index("points") < events.index("like")
    assert events.index("points") < events.index("browse")
    assert actions == {"like": 2, "browse": 1}
    assert summary.ok is True


@pytest.mark.asyncio
async def test_run_all_repairs_never_exceed_cumulative_action_budgets(monkeypatch):
    config = AppConfig(
        max_likes=1,
        max_browses=1,
        points_repair_rounds=2,
    )
    runner = BlablaTaskRunner(FakePage(), config)
    actions = {"like": 0, "browse": 0}
    progress_reads = 0

    async def open_home():
        return None

    async def check_login():
        return True

    async def check_in_task():
        return TaskResult("签到", TaskStatus.COMPLETED)

    async def load_points_progress_values():
        nonlocal progress_reads
        progress_reads += 1
        return ["4 / 5", "4 / 5"]

    async def spend_budget(task_name, key, budget_attr, max_actions):
        remaining = getattr(runner, budget_attr)
        allowed = remaining if max_actions is None else min(remaining, max_actions)
        actions[key] += allowed
        setattr(runner, budget_attr, remaining - allowed)
        status = TaskStatus.COMPLETED if allowed else TaskStatus.SKIPPED
        return TaskResult(task_name, status, attempted=allowed, completed=allowed)

    async def like_task(*, max_actions=None):
        return await spend_budget("点赞", "like", "_like_budget_remaining", max_actions)

    async def browse_task(*, max_actions=None):
        return await spend_budget("浏览", "browse", "_browse_budget_remaining", max_actions)

    monkeypatch.setattr(runner, "open_home", open_home)
    monkeypatch.setattr(runner, "check_login", check_login)
    monkeypatch.setattr(runner, "do_check_in", check_in_task)
    monkeypatch.setattr(runner, "_load_points_progress_values", load_points_progress_values)
    monkeypatch.setattr(runner, "do_likes", like_task)
    monkeypatch.setattr(runner, "do_browses", browse_task)

    summary = await runner.run_all()

    assert actions == {"like": config.max_likes, "browse": config.max_browses}
    assert progress_reads == 4
    assert summary.results[-1].status == TaskStatus.FAILED
    assert "已补做 2 轮" in summary.results[-1].message


def runner_selector(name):
    from blablalink_tasker.selectors import DEFAULT_SELECTORS

    return getattr(DEFAULT_SELECTORS, name)
