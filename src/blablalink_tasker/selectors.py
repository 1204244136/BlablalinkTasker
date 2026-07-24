"""Centralized BlablaLink page selectors.

The selectors come from the reference Automa workflow and are intentionally
kept in one file because the website may change its DOM structure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelectorSet:
    cookie_close_button: str = "#onetrust-close-btn-container button"
    check_in_button: str = 'aside[data-cname="pc-tools"] button:has-text("Sign In")'
    check_in_done: str = 'aside[data-cname="pc-tools"] button:has-text("Done")'
    check_in_success_message: str = 'text="Sign In Success"'
    authenticated_points_balance: str = 'aside[data-cname="pc-tools"] p.tabular-nums'
    logged_out_marker: str = 'aside[data-cname="pc-tools"] p:text-is("Daily Check-in")'
    like_target: str = (
        ".recommend .card-item "
        ".inline-flex.items-center.justify-center.cursor-pointer.flex-row "
        'svg[viewBox="0 0 48 48"]'
    )
    browse_target: str = ".recommend .card-item > .font-bold.line-clamp-2"
    home_event_dialog: str = '[role="dialog"]:has(h2)'
    points_expand_button: str = ".btn-mask.cursor-pointer"
    points_browse_task_row: str = (
        'xpath=//*[normalize-space(text())="Browse 5 posts"]'
        '/ancestor::*[@data-cname="index"][1]'
    )
    points_like_task_row: str = (
        'xpath=//*[normalize-space(text())="Like 5 posts"]'
        '/ancestor::*[@data-cname="index"][1]'
    )
    session_expired_message: str = 'text="Your session has expired, please log in again."'
    game_binding_link: str = 'button:has-text("Link")'
    reward_card: str = ".masonry-item"
    reward_title: str = (
        r".text-\[length\:11px\]"
        r".line-clamp-2"
        r".mb-\[10px\]"
        r".font-bold"
        r".text-\[color\:var\(--other-6\)\]"
        r".leading-\[14px\]"
    )
    reward_redeem_button: str = 'text="Redeem"'
    reward_modal_title: str = 'text="Redeem Detail"'
    reward_loading_text: str = 'text="Loading"'
    reward_confirm_button: str = 'text="Confirm"'
    reward_token_amount: str = (
        r".flex.items-center.w-full.justify-between.mt-\[8px\].px-\[12px\] "
        r".font-\[DINNextLTProBold\]"
        r".text-\[color\:var\(--other-6\)\]"
        r".text-\[length\:20px\]"
    )

    login_links: tuple[str, ...] = (
        "text=Log in",
        "text=Login",
        "text=登录",
        "a[href*='login']",
        "button:has-text('登录')",
        "button:has-text('Login')",
    )


DEFAULT_SELECTORS = SelectorSet()
