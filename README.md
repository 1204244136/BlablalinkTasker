# BlablalinkTasker

Blablalink 社区任务命令行自动化工具。

本项目用于在命令行中完成 Blablalink / NIKKE 社区每日任务。当前版本基于 Python + Playwright，通过浏览器自动化执行网页上的签到、点赞 / 重新点赞、浏览等任务。

> 本工具不会收集或保存账号密码，不会绕过 CAPTCHA、人机验证或网站风控。如果登录状态失效，请重新运行 `setup` 手动登录。

## 功能

- 保存 Blablalink 登录会话
- 命令行执行社区每日任务
- 支持无头运行，适合本地定时任务
- 支持可视化调试模式
- 支持 dry-run 检查任务入口
- 支持执行完成后暂停浏览器，方便确认结果

## 运行环境

- Windows 10 / Windows 11
- Python 3.10 或更高版本
- Git，用于克隆仓库
- Chromium 浏览器由 Playwright 自动安装

如果本机还没有基础环境，请先参考官方文档安装：

- [Python 官方下载页面](https://www.python.org/downloads/)
- [Git 官方下载页面](https://git-scm.com/downloads)

安装 Python 时建议勾选 “Add python.exe to PATH”。

## 快速导航

- [方法 1：在自己电脑上运行](#方法-1在自己电脑上运行)
- [首次登录配置](#首次登录配置)
- [日常运行](#日常运行)
- [会话续期](#会话续期)
- [MXU 自定义程序联动 MDA](#mxu-自定义程序联动-mda)
- [调试命令](#调试命令)
- [Windows 任务计划程序定时运行](#windows-任务计划程序定时运行)
- [常见问题](#常见问题)
- [安全说明](#安全说明)

## 方法 1：在自己电脑上运行

当前推荐本地运行。原因是本项目依赖浏览器登录会话，放在本地电脑上最简单，也更安全。

### 1. 克隆仓库

```powershell
git clone https://github.com/1204244136/BlablalinkTasker.git
cd BlablalinkTasker
```

如果你是直接下载源码压缩包，解压后进入项目目录即可。

### 2. 安装 Python 依赖

```powershell
python -m pip install -e .
```

如果你还需要运行测试：

```powershell
python -m pip install -e ".[dev]"
```

### 3. 安装 Playwright 浏览器

```powershell
python -m playwright install chromium
```

该命令会下载 Playwright 使用的 Chromium。第一次安装需要等待一段时间。

## 首次登录配置

第一次使用，或者登录状态过期后，需要运行：

```powershell
blablalink-tasker setup
```

执行后会打开浏览器：

1. 在浏览器中手动登录 Blablalink。
2. 确认已经进入正常登录后的页面。
3. 回到 PowerShell / 终端窗口。
4. 按 Enter 保存会话。

会话会保存到：

```text
.blablalink/storage_state.json
```

该文件可能包含 cookie / token，已经在 `.gitignore` 中忽略。请不要提交或分享该文件。

## 日常运行

登录配置完成后，每天直接运行：

```powershell
blablalink-tasker run
```

默认会无窗口执行任务。正常情况下，执行结束后终端会输出每日任务摘要。

如果你使用的启动器不方便直接填写命令行程序和参数，可以使用仓库内置的批处理文件：

```text
日常运行.bat
```

该文件会自动切换到项目目录并执行：

```powershell
blablalink-tasker run
```

## 会话续期

Blablalink 登录状态通常有有效期。已有会话仍可用时，可以运行：

```powershell
blablalink-tasker renew-session --verbose
```

该命令会使用当前保存的 `game_*` Cookie 请求 Blablalink 登录接口刷新会话，并把新的 Cookie 写回 `.blablalink/storage_state.json`。

注意：该功能是实验性的。如果 Blablalink 服务端存在 30 天硬过期限制，仅刷新 Cookie 可能仍然无法避免最终过期。续期失败或会话已经失效时，仍然需要重新运行：

```powershell
blablalink-tasker setup
```

如果使用仓库内置的 `日常运行.bat`，脚本会先执行：

```powershell
blablalink-tasker renew-session --verbose
```

然后再执行：

```powershell
blablalink-tasker run
```

续期失败不会阻止日常任务继续执行；如果日常任务也失败，再重新运行 `blablalink-tasker setup`。

## MXU 自定义程序联动 MDA

MDA 是一个 NIKKE 自动化脚本项目，MXU 是 MDA 使用的 UI 框架。MXU 提供“自定义程序”功能，可以在启动 MDA 时顺带运行本工具。

如果需要在 MXU 中配置 BlablalinkTasker，可以直接指定仓库中的批处理文件。

### 添加位置

在 MDA 主界面中，点击底部的“添加任务”，进入“特殊任务”分类，选择“自定义程序”。添加后即可填写程序路径和参数。

### 推荐配置

- 程序路径：选择本仓库下的 `日常运行.bat`
- 附加参数：留空
- 等待退出：建议开启
- 已运行时跳过：建议开启
- 通过 cmd 启动：一般可以关闭；如果启动异常，再尝试开启

`日常运行.bat` 会先切换到脚本所在目录，再执行日常任务。这样即使 MXU 从其他工作目录启动，也能正确找到 `.blablalink/storage_state.json`。

### 首次使用注意

MXU 的自定义程序适合在日常启动 MDA 项目时顺带启动本工具，不适合首次登录配置。首次登录仍然需要先在 PowerShell 中手动运行：

```powershell
blablalink-tasker setup
```

确认 `setup` 成功后，再在 MXU 的自定义程序中调用 `日常运行.bat`。

## 调试命令

日常用户一般只需要 `blablalink-tasker run` 或 `日常运行.bat`。如果需要排查登录、页面选择器或浏览器点击行为，再参考本节。

### 查看浏览器执行过程

```powershell
blablalink-tasker run --headful --verbose
```

### 执行完成后不立刻关闭浏览器

```powershell
blablalink-tasker run --headful --verbose --pause-on-finish
```

任务执行结束后，浏览器会保持打开。确认页面状态后，回到终端按 Enter 关闭浏览器。

### 慢动作执行

```powershell
blablalink-tasker run --headful --verbose --slow-mo-ms 1000 --pause-on-finish
```

`--slow-mo-ms 1000` 表示每个 Playwright 操作额外放慢 1000 毫秒。

### 只测试选择器，不实际点击

```powershell
blablalink-tasker run --headful --verbose --dry-run
```

该命令只检查任务入口是否能找到，不会点击签到、点赞或浏览按钮。

### 限制测试次数

调试时建议先少量执行：

```powershell
blablalink-tasker run --headful --verbose --slow-mo-ms 1000 --max-likes 2 --max-browses 2 --pause-on-finish
```

确认没有问题后，再运行完整任务：

```powershell
blablalink-tasker run --headful --verbose --slow-mo-ms 1000 --pause-on-finish
```

### 诊断登录和选择器状态

```powershell
blablalink-tasker diagnose --headful --verbose
```

该命令会检查：

- 当前会话是否可能已登录
- 页面标题和 URL
- 签到、点赞、浏览等关键选择器是否可见

诊断命令不会点击任务按钮。

## Windows 任务计划程序定时运行

确认手动运行稳定后，可以使用 Windows 任务计划程序每天自动执行。

### 1. 找到命令路径

在 PowerShell 中运行：

```powershell
where.exe blablalink-tasker
```

记下输出路径，例如：

```text
C:\Users\你的用户名\AppData\Local\Programs\Python\Python312\Scripts\blablalink-tasker.exe
```

### 2. 创建任务计划

1. 打开“任务计划程序”。
1. 点击“创建基本任务”。
1. 设置名称，例如 `BlablalinkTasker`。
1. 触发器选择“每天”。
1. 时间建议选择你通常不会使用电脑的时间。
1. 操作选择“启动程序”。
1. 程序或脚本填写 `where.exe blablalink-tasker` 查到的完整路径。
1. 参数填写：

```text
run
```

1. 起始于填写项目目录，例如：

```text
C:\Users\12042\Documents\GitHub\BlablalinkTasker
```

### 3. 手动测试计划任务

创建后，右键任务，选择“运行”。

如果任务失败，建议先回到项目目录手动执行：

```powershell
blablalink-tasker run --headful --verbose --pause-on-finish
```

确认登录状态和页面流程是否正常。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--headful` | 显示浏览器窗口 |
| `--headless` | 强制无头运行 |
| `--verbose` | 输出详细日志 |
| `--dry-run` | 只检查任务入口，不点击 |
| `--pause-on-finish` | 执行完成后等待 Enter 再关闭浏览器 |
| `--slow-mo-ms 1000` | 每个 Playwright 操作放慢 1000 毫秒 |
| `--max-likes 2` | 限制点赞 / 重新点赞次数 |
| `--max-browses 2` | 限制浏览次数 |
| `--points-repair-rounds 3` | 奖励中心复核补做最大轮数 |
| `--timeout-ms 30000` | 增加页面操作超时时间 |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BLABLA_BASE_URL` | `https://www.blablalink.com/` | Blablalink 首页 |
| `BLABLA_SESSION_PATH` | `.blablalink/storage_state.json` | Playwright 会话文件 |
| `BLABLA_HEADLESS` | `true` | 默认是否无头运行 |
| `BLABLA_TIMEOUT_MS` | `15000` | 页面操作超时时间 |
| `BLABLA_MAX_LIKES` | `5` | 点赞 / 重新点赞最大次数 |
| `BLABLA_MAX_BROWSES` | `5` | 浏览最大次数 |
| `BLABLA_BROWSE_SECONDS` | `1.0` | 每次浏览停留秒数 |
| `BLABLA_POINTS_REPAIR_ROUNDS` | `3` | 奖励中心复核补做最大轮数 |
| `BLABLA_SLOW_MO_MS` | `0` | Playwright slow motion 调试延迟 |
| `BLABLA_EXIT_WHEN_FAIL` | `true` | 失败时返回非零退出码 |

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 完成，或当天任务已经完成 |
| `1` | 未知运行时错误 / 任务执行错误 |
| `2` | 配置错误或会话文件缺失 |
| `3` | 需要重新登录 / 会话过期 |
| `4` | 页面结构变化 / 选择器失效 |

## 常见问题

### 1. 提示找不到会话文件

请先运行：

```powershell
blablalink-tasker setup
```

### 2. 诊断显示可能未登录

说明保存的登录状态可能已经失效。重新运行：

```powershell
blablalink-tasker setup
```

### 3. 浏览器一闪而过，无法确认是否执行成功

使用：

```powershell
blablalink-tasker run --headful --verbose --pause-on-finish
```

### 4. 页面动作太快，看不清

使用：

```powershell
blablalink-tasker run --headful --verbose --slow-mo-ms 1000 --pause-on-finish
```

### 5. 页面改版导致任务失败

先运行：

```powershell
blablalink-tasker diagnose --headful --verbose
```

如果关键选择器不可见，可能需要更新代码中的选择器。

## 开发测试

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

## 安全说明

- 请不要分享 `.blablalink/storage_state.json`。
- 请不要把 `.blablalink/` 目录提交到仓库。
- 如果怀疑会话泄露，请在 Blablalink 中退出登录或清理登录状态，然后重新运行 `setup`。
- 本工具仅用于个人账号的日常网页任务自动化。
