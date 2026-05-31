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
    set "RUN_EXIT_CODE=%ERRORLEVEL%"
    if not "%RUN_EXIT_CODE%"=="0" (
        echo.
        echo BlablalinkTasker 日常任务失败，退出码：%RUN_EXIT_CODE%
        echo 将继续尝试奖励兑换。
        echo.
    )

    blablalink-tasker redeem
    set "REDEEM_EXIT_CODE=%ERRORLEVEL%"
    if not "%REDEEM_EXIT_CODE%"=="0" (
        set "EXIT_CODE=%REDEEM_EXIT_CODE%"
    ) else (
        set "EXIT_CODE=%RUN_EXIT_CODE%"
    )
) else (
    blablalink-tasker %*
    set "EXIT_CODE=%ERRORLEVEL%"
)

if not "%EXIT_CODE%"=="0" (
    echo.
    echo BlablalinkTasker 运行失败，退出码：%EXIT_CODE%
)

exit /b %EXIT_CODE%
