import pytest

from blablalink_tasker.config import AppConfig
from blablalink_tasker.errors import LoginRequiredError
from blablalink_tasker.session_renewal import (
    _extract_game_cookie_values,
    _parse_set_cookie_header,
    _split_combined_set_cookie,
    renew_session,
)


class FakeResponse:
    ok = True
    status = 200
    headers = {
        "set-cookie": "game_token=new-token; Path=/; Secure, game_uid=uid-1; Path=/; Secure",
    }

    async def text(self):
        return '{"code":0}'

    async def json(self):
        return {"code": 0}


class FakeRequest:
    def __init__(self):
        self.calls = []

    async def post(self, url, *, headers, data):
        self.calls.append((url, headers, data))
        return FakeResponse()


class FakePage:
    def __init__(self):
        self.request = FakeRequest()


class FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies
        self.added_cookies = []
        self.storage_state_path = None

    async def cookies(self, url=None):
        return self._cookies

    async def add_cookies(self, cookies):
        self.added_cookies.extend(cookies)

    async def storage_state(self, *, path):
        self.storage_state_path = path


def game_cookie(name, value):
    return {"name": name, "value": value}


def required_cookies():
    return [
        game_cookie("game_token", "old-token"),
        game_cookie("game_uid", "uid-1"),
        game_cookie("game_openid", "openid-1"),
        game_cookie("game_gameid", "29080"),
        game_cookie("game_channelid", "131"),
        game_cookie("game_user_name", "tester"),
        game_cookie("game_adult_status", "1"),
    ]


def test_extract_game_cookie_values_ignores_non_game_cookies():
    values = _extract_game_cookie_values([
        game_cookie("game_token", "token"),
        {"name": "other", "value": "value"},
    ])

    assert values == {"game_token": "token"}


def test_split_combined_set_cookie_preserves_expires_commas():
    header = "game_token=a; Expires=Wed, 21 Oct 2030 07:28:00 GMT; Path=/, game_uid=b; Path=/"

    assert _split_combined_set_cookie(header) == [
        "game_token=a; Expires=Wed, 21 Oct 2030 07:28:00 GMT; Path=/",
        "game_uid=b; Path=/",
    ]


def test_parse_set_cookie_header_keeps_game_cookies_only():
    parsed = _parse_set_cookie_header("game_token=a; Path=/, other=x; Path=/, game_uid=b; Path=/")

    assert parsed == {"game_token": "a", "game_uid": "b"}


@pytest.mark.asyncio
async def test_renew_session_updates_context_and_storage(tmp_path):
    context = FakeContext(required_cookies())
    page = FakePage()
    config = AppConfig(session_path=tmp_path / "storage_state.json")

    result = await renew_session(context, page, config)

    assert result.renewed is True
    assert result.updated_cookie_names == ["game_token", "game_uid"]
    assert context.storage_state_path == str(config.session_path)
    added = {cookie["name"]: cookie["value"] for cookie in context.added_cookies}
    assert added["game_token"] == "new-token"
    assert added["game_uid"] == "uid-1"
    url, headers, data = page.request.calls[0]
    assert url == "https://api.blablalink.com/api/user/Login"
    assert "game_token=old-token" in headers["Cookie"]
    assert data["game_openid"] == "openid-1"
    assert data["game_id"] == "29080"


@pytest.mark.asyncio
async def test_renew_session_requires_existing_game_cookies(tmp_path):
    context = FakeContext([game_cookie("game_token", "old-token")])
    page = FakePage()
    config = AppConfig(session_path=tmp_path / "storage_state.json")

    with pytest.raises(LoginRequiredError):
        await renew_session(context, page, config)
