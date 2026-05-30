"""Command-line interface for BlablaLinkTasker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from .browser import browser_page, ensure_parent_dir
from .config import AppConfig, load_config
from .errors import (
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    BlablaTaskerError,
    ConfigError,
    exit_code_for_error,
)
from .logging_utils import configure_logging
from .tasks import BlablaTaskRunner

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(getattr(args, "verbose", False))

    try:
        return asyncio.run(_dispatch(args))
    except BlablaTaskerError as exc:
        LOGGER.error("%s", exc)
        return exit_code_for_error(exc)
    except PlaywrightError as exc:
        LOGGER.error("Playwright 运行失败：%s", exc)
        return EXIT_CONFIG_ERROR
    except KeyboardInterrupt:
        LOGGER.warning("用户中断")
        return EXIT_CONFIG_ERROR
    except Exception as exc:  # pragma: no cover - defensive boundary
        LOGGER.exception("未预期错误：%s", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blablalink-tasker",
        description="BlablaLink / NIKKE 社区每日任务命令行工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="打开浏览器手动登录并保存会话")
    add_common_options(setup_parser)
    setup_parser.add_argument("--no-wait", action="store_true", help="不等待手动 Enter，主要用于测试")

    run_parser = subparsers.add_parser("run", help="执行社区每日任务")
    add_common_options(run_parser)
    run_parser.add_argument("--dry-run", action="store_true", help="只检查流程，不点击任务按钮")
    run_parser.add_argument("--pause-on-finish", action="store_true", help="任务结束后暂停，按 Enter 后再关闭浏览器")

    diagnose_parser = subparsers.add_parser("diagnose", help="诊断会话和页面选择器")
    add_common_options(diagnose_parser)

    clear_parser = subparsers.add_parser("clear-session", help="删除本地保存的登录会话")
    add_common_options(clear_parser)
    clear_parser.add_argument("--yes", action="store_true", help="确认删除会话文件")

    return parser


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", dest="base_url", help="BlablaLink 首页 URL")
    parser.add_argument("--session-path", type=Path, dest="session_path", help="Playwright storage_state 路径")
    parser.add_argument("--headful", action="store_true", help="显示浏览器窗口运行")
    parser.add_argument("--headless", action="store_true", help="强制无头运行")
    parser.add_argument("--timeout-ms", type=int, dest="timeout_ms", help="页面操作超时时间")
    parser.add_argument("--max-likes", type=int, dest="max_likes", help="点赞 / 重新点赞最大次数")
    parser.add_argument("--max-browses", type=int, dest="max_browses", help="浏览最大次数")
    parser.add_argument("--browse-seconds", type=float, dest="browse_seconds", help="每次浏览停留秒数")
    parser.add_argument("--slow-mo-ms", type=int, dest="slow_mo_ms", help="Playwright slow motion 调试延迟")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")


async def _dispatch(args: argparse.Namespace) -> int:
    config = _config_from_args(args)

    if args.command == "setup":
        return await setup(config, wait_for_enter=not args.no_wait)
    if args.command == "run":
        return await run_tasks(config, dry_run=args.dry_run, pause_on_finish=args.pause_on_finish)
    if args.command == "diagnose":
        return await diagnose(config)
    if args.command == "clear-session":
        return clear_session(config, yes=args.yes)

    raise ConfigError(f"未知命令：{args.command}")


def _config_from_args(args: argparse.Namespace) -> AppConfig:
    overrides = {
        "base_url": args.base_url,
        "session_path": args.session_path,
        "timeout_ms": args.timeout_ms,
        "max_likes": args.max_likes,
        "max_browses": args.max_browses,
        "browse_seconds": args.browse_seconds,
        "slow_mo_ms": args.slow_mo_ms,
    }
    if args.headful and args.headless:
        raise ConfigError("不能同时使用 --headful 和 --headless")
    if args.headful:
        overrides["headless"] = False
    elif args.headless:
        overrides["headless"] = True

    return load_config(**overrides)


async def setup(config: AppConfig, *, wait_for_enter: bool = True) -> int:
    LOGGER.info("启动浏览器，请在打开的页面中手动登录 BlablaLink。")
    setup_config = AppConfig(
        base_url=config.base_url,
        session_path=config.session_path,
        headless=False,
        timeout_ms=config.timeout_ms,
        max_likes=config.max_likes,
        max_browses=config.max_browses,
        browse_seconds=config.browse_seconds,
        slow_mo_ms=config.slow_mo_ms,
        exit_when_fail=config.exit_when_fail,
    )
    ensure_parent_dir(setup_config.session_path)

    async with browser_page(setup_config, use_session=False) as (context, page):
        await page.goto(setup_config.login_url, wait_until="domcontentloaded")
        if wait_for_enter:
            await asyncio.to_thread(input, "登录完成后请回到此窗口按 Enter 保存会话...")
        await context.storage_state(path=str(setup_config.session_path))

    LOGGER.info("会话已保存到：%s", setup_config.session_path)
    return EXIT_OK


async def run_tasks(config: AppConfig, *, dry_run: bool = False, pause_on_finish: bool = False) -> int:
    config.ensure_session_exists()
    async with browser_page(config, use_session=True) as (_context, page):
        runner = BlablaTaskRunner(page, config, dry_run=dry_run)
        summary = await runner.run_all()

        for line in summary.format_lines():
            LOGGER.info(line)

        if pause_on_finish:
            await asyncio.to_thread(input, "任务执行结束，浏览器将保持打开。检查完成后按 Enter 关闭浏览器...")

    if summary.ok:
        return EXIT_OK
    return 1 if config.exit_when_fail else EXIT_OK


async def diagnose(config: AppConfig) -> int:
    config.ensure_session_exists()
    async with browser_page(config, use_session=True) as (_context, page):
        runner = BlablaTaskRunner(page, config, dry_run=True)
        report = await runner.diagnose()

    for line in report.format_lines():
        LOGGER.info(line)
    return EXIT_OK if report.login_ok else 3


def clear_session(config: AppConfig, *, yes: bool) -> int:
    if not yes:
        raise ConfigError("删除会话需要显式确认：请使用 `blablalink-tasker clear-session --yes`")

    if config.session_path.exists():
        config.session_path.unlink()
        LOGGER.info("已删除会话文件：%s", config.session_path)
    else:
        LOGGER.info("会话文件不存在，无需删除：%s", config.session_path)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
