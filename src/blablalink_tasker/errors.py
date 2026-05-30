"""Application-specific exceptions and exit codes."""

from __future__ import annotations


EXIT_OK = 0
EXIT_TASK_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_LOGIN_REQUIRED = 3
EXIT_SELECTOR_CHANGED = 4


class BlablaTaskerError(Exception):
    """Base class for expected application errors."""


class ConfigError(BlablaTaskerError):
    """Configuration or local session state is invalid."""


class LoginRequiredError(BlablaTaskerError):
    """The saved session is missing, expired, or not authenticated."""


class SelectorChangedError(BlablaTaskerError):
    """The website layout no longer matches the known selectors."""


class TaskRunError(BlablaTaskerError):
    """A task failed while running."""


def exit_code_for_error(error: BaseException) -> int:
    """Map expected exceptions to process exit codes."""

    if isinstance(error, ConfigError):
        return EXIT_CONFIG_ERROR
    if isinstance(error, LoginRequiredError):
        return EXIT_LOGIN_REQUIRED
    if isinstance(error, SelectorChangedError):
        return EXIT_SELECTOR_CHANGED
    return EXIT_TASK_ERROR
