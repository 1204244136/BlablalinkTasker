from pathlib import Path

from blablalink_tasker.cli import build_parser, clear_session, main
from blablalink_tasker.config import AppConfig
from blablalink_tasker.errors import EXIT_CONFIG_ERROR, EXIT_OK


def test_parser_accepts_run_options():
    parser = build_parser()
    args = parser.parse_args([
        "run",
        "--headful",
        "--dry-run",
        "--max-likes",
        "3",
        "--browse-seconds",
        "1.5",
    ])

    assert args.command == "run"
    assert args.headful is True
    assert args.dry_run is True
    assert args.max_likes == 3
    assert args.browse_seconds == 1.5


def test_main_rejects_conflicting_head_modes():
    code = main(["diagnose", "--headful", "--headless"])

    assert code == EXIT_CONFIG_ERROR


def test_clear_session_requires_yes(tmp_path):
    config = AppConfig(session_path=tmp_path / "storage_state.json")

    try:
        clear_session(config, yes=False)
    except Exception as exc:
        assert "--yes" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("clear_session should require --yes")


def test_clear_session_deletes_file(tmp_path):
    session_path = tmp_path / "storage_state.json"
    session_path.write_text("{}", encoding="utf-8")
    config = AppConfig(session_path=session_path)

    code = clear_session(config, yes=True)

    assert code == EXIT_OK
    assert not session_path.exists()
