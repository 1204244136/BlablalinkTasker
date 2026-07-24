# BlablalinkTasker 开发指南

## 项目概览

本项目是 Python 3.10+ 命令行工具，使用 Playwright 自动化 Blablalink 的网页签到、帖子点赞、帖子浏览和奖励兑换流程。

- `src/blablalink_tasker/cli.py`：命令行参数、子命令分发和退出码处理。
- `src/blablalink_tasker/tasks.py`：每日任务、进度复核和补做流程。
- `src/blablalink_tasker/rewards.py`：奖励卡片解析、兑换规划和结果确认。
- `src/blablalink_tasker/selectors.py`：集中维护页面选择器。
- `tests/`：以 mocked Playwright 页面为主的单元测试。

## 修改约定

- 页面结构变化时，优先在 `selectors.py` 更新选择器，不要把页面选择器散落到业务代码中。
- 浏览器操作必须等待可观察的页面状态变化；不要仅用固定延迟判定成功。
- 点赞、浏览和兑换需要限制动作次数，并在重试或补做流程中共享累计预算。
- 浏览帖子应按详情页 URL 去重，避免页面重排后重复访问同一帖子。
- 奖励兑换只有在余额或卡片库存发生变化后，才能写入本地兑换记录。
- 不绕过 CAPTCHA、人机验证或网站风控。登录失效时应提示用户重新执行 `setup`。
- 不提交 `.blablalink/`、`.claude/`、`.env`、日志或其他本地会话与工具配置。

## 在线调试

- 先使用 `diagnose` 或 `--dry-run` 检查登录状态和选择器，再执行会改变账号状态的操作。
- 调试每日任务时，使用 `--max-likes 1 --max-browses 1` 控制影响范围。
- 未经用户明确授权，不执行真实奖励兑换；需要核对兑换规划时使用 `redeem --dry-run`。
- 复用用户已登录的浏览器会话时，不读取、输出或提交 Cookie、Token 等凭据。

## 测试与检查

安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

修改业务逻辑后运行完整测试：

```powershell
python -m pytest -q -p no:cacheprovider
git diff --check
```

修改单一模块时可以先运行对应测试文件，但提交前仍需运行完整测试套件。新增或修复浏览器流程时，应覆盖成功、入口缺失、状态未变化、重试耗尽和累计预算等边界情况。

## 提交约定

提交信息使用 Conventional Commits 格式，说明部分使用中文：

```text
<type>(<scope>): <中文说明>
```

常用类型：

- `feat`：新增功能。
- `fix`：修复缺陷或适配外部页面变化。
- `docs`：仅修改文档。
- `test`：仅修改测试。
- `refactor`：不改变外部行为的重构。
- `chore`：构建、依赖或仓库维护。

代码和对应测试应放在同一提交中。仅当各提交都具备清晰边界且不会留下不可运行的中间状态时才拆分；文档可按需独立提交。
