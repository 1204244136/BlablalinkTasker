"""Result models used by the task runner and CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    """Normalized task status values."""

    COMPLETED = "completed"
    ALREADY_DONE = "already_done"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True)
class TaskResult:
    """Outcome for one task group."""

    name: str
    status: TaskStatus
    message: str = ""
    attempted: int = 0
    completed: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {
            TaskStatus.COMPLETED,
            TaskStatus.ALREADY_DONE,
            TaskStatus.SKIPPED,
        }


@dataclass(slots=True)
class TaskSummary:
    """Summary for a complete run."""

    login_ok: bool
    results: list[TaskResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.login_ok and all(result.ok for result in self.results)

    def format_lines(self) -> list[str]:
        lines = ["BlablaLink 任务摘要", f"- 登录状态: {'正常' if self.login_ok else '需要重新登录'}"]
        for result in self.results:
            suffix = ""
            if result.attempted or result.completed:
                suffix = f"（尝试 {result.attempted}，完成 {result.completed}）"
            message = f" - {result.message}" if result.message else ""
            lines.append(f"- {result.name}: {result.status.value}{suffix}{message}")
        return lines
