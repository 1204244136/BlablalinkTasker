@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"
set "EXIT_CODE=0"

if not "%~1"=="" goto run_args

blablalink-tasker run
set "RUN_EXIT_CODE=%ERRORLEVEL%"
if not "%RUN_EXIT_CODE%"=="0" call :run_failed

blablalink-tasker redeem
set "REDEEM_EXIT_CODE=%ERRORLEVEL%"
set "EXIT_CODE=%RUN_EXIT_CODE%"
if not "%REDEEM_EXIT_CODE%"=="0" set "EXIT_CODE=%REDEEM_EXIT_CODE%"
goto finish

:run_args
blablalink-tasker %*
set "EXIT_CODE=%ERRORLEVEL%"
goto finish

:run_failed
echo.
echo BlablalinkTasker 日常任务失败，退出码：%RUN_EXIT_CODE%
echo 将继续尝试奖励兑换。
echo.
exit /b 0

:finish
if not "%EXIT_CODE%"=="0" call :final_failed
exit /b %EXIT_CODE%

:final_failed
echo.
echo BlablalinkTasker 运行失败，退出码：%EXIT_CODE%
exit /b 0
