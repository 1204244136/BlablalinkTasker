"""Centralized BlablaLink page selectors.

The selectors come from the reference Automa workflow and are intentionally
kept in one file because the website may change its DOM structure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelectorSet:
    # CSS class names containing Tailwind square brackets/colon need escaping.
    check_in_button: str = r"div.w-\[85\%\]"
    check_in_close: str = "i.absolute-center"
    like_target: str = r".recommend > .relative:nth-child(7) > div .flex-row > .text-\[length\:12px\]"
    browse_target: str = r".recommend > .relative:nth-child(7) > div .inline-flex:nth-child(2) > .text-\[length\:12px\]"
    post_close: str = ".fill-current path:nth-child(1)"
    points_expand_button: str = (
        r".flex.items-center.justify-center.h-\[16px\].w-\[43px\].bg-black.btn-mask.cursor-pointer"
    )
    points_progress_text: str = (
        r".font-\[Inter\]"
        r".text-\[length\:13px\]"
        r".text-\[color\:var\(--color-white\)\]"
        r".leading-\[16px\]"
        r".font-medium"
        r".\!text-\[color\:var\(--text-3\)\]"
        r".opacity-60"
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
