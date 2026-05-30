@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if "%~1"=="" (
    blablalink-tasker renew-session --verbose
    set "RENEW_EXIT_CODE=%ERRORLEVEL%"
    if not "%RENEW_EXIT_CODE%"=="0" (
        echo.
        echo BlablalinkTasker 会话续期失败，退出码：%RENEW_EXIT_CODE%
        echo 将继续执行日常任务；如果任务失败，请重新运行 blablalink-tasker setup。
        echo.
    )

    blablalink-tasker run
) else (
    blablalink-tasker %*
)
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo BlablalinkTasker 运行失败，退出码：%EXIT_CODE%
)

exit /b %EXIT_CODE%
