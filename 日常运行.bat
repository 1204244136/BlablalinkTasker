@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if "%~1"=="" (
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
