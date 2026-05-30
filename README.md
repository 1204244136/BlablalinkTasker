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
- Chromium 浏览器由 Playwright 自动安装

## 快速导航

- [方法 1：在自己电脑上运行](#方法-1在自己电脑上运行)
- [首次登录配置](#首次登录配置)
- [日常运行](#日常运行)
- [调试命令](#调试命令)
- [Windows 任务计划程序定时运行](#windows-任务计划程序定时运行)
- [常见问题](#常见问题)
- [发布与工作流评估](#发布与工作流评估)

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

## 调试命令

### 查看浏览器执行过程

如果你想看到浏览器实际点击过程：

```powershell
blablalink-tasker run --headful --verbose
```

### 执行完成后不立刻关闭浏览器

推荐调试时使用：

```powershell
blablalink-tasker run --headful --verbose --pause-on-finish
```

任务执行结束后，浏览器会保持打开。确认页面状态后，回到终端按 Enter 关闭浏览器。

### 慢动作执行

如果动作太快看不清：

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
| `--timeout-ms 30000` | 增加页面操作超时时间 |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BLABLA_BASE_URL` | `https://www.blablalink.com/` | Blablalink 首页 |
| `BLABLA_SESSION_PATH` | `.blablalink/storage_state.json` | Playwright 会话文件 |
| `BLABLA_HEADLESS` | `true` | 默认是否无头运行 |
| `BLABLA_TIMEOUT_MS` | `15000` | 页面操作超时时间 |
| `BLABLA_MAX_LIKES` | `5` | 点赞 / 重新点赞最大次数 |
| `BLABLA_MAX_BROWSES` | `6` | 浏览最大次数 |
| `BLABLA_BROWSE_SECONDS` | `1.0` | 每次浏览停留秒数 |
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

## 发布与工作流评估

### 当前是否建议构建 GitHub Actions 自动运行？

暂不建议。

原因：

1. 本项目依赖 Playwright 的浏览器登录会话文件 `.blablalink/storage_state.json`。
2. 该文件包含敏感 cookie / token，不适合提交到公开仓库。
3. GitHub Actions 的运行环境是临时环境，每次运行都需要恢复会话文件。
4. 如果把会话文件放进 Actions Secrets，需要额外处理 base64 编码、文件恢复、过期更新等问题，使用门槛较高。
5. Blablalink 页面自动化依赖浏览器环境，云端无头浏览器更容易遇到登录失效、验证码或风控问题。

因此，当前阶段推荐先发布源码，并引导用户在本地运行。

### 当前是否建议发布 Release？

暂不建议打包 exe 作为正式 Release 产物。

原因：

1. Playwright 依赖浏览器二进制，打包成 exe 后仍然需要处理 Chromium 安装或随包分发。
2. 如果把浏览器也打包进去，Release 体积会明显变大。
3. 当前项目还处于页面选择器验证阶段，网站改版时可能需要频繁更新。
4. 直接源码安装更透明，也更方便用户自行调试。

### 当前推荐发布方式

推荐先发布源码仓库，并在 README 中说明：

```powershell
python -m pip install -e .
python -m playwright install chromium
blablalink-tasker setup
blablalink-tasker run
```

等后续版本稳定后，再考虑：

- 增加 GitHub Actions 仅用于运行测试；
- 增加 PyInstaller 打包脚本；
- 发布 Windows exe；
- 增加 Release 自动构建工作流。

## 安全说明

- 请不要分享 `.blablalink/storage_state.json`。
- 请不要把 `.blablalink/` 目录提交到仓库。
- 如果怀疑会话泄露，请在 Blablalink 中退出登录或清理登录状态，然后重新运行 `setup`。
- 本工具仅用于个人账号的日常网页任务自动化。
