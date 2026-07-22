@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 audio_processor.py %*
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo 未找到 Python 3。
        echo 请从 https://www.python.org/downloads/windows/ 安装，并勾选 Add Python to PATH。
        pause
        exit /b 1
    )
    python audio_processor.py %*
)

set "EXIT_CODE=%errorlevel%"
echo.
if "%EXIT_CODE%"=="0" (
    echo 操作已完成。
) else (
    echo 操作结束，但存在错误。退出代码：%EXIT_CODE%
)
pause
exit /b %EXIT_CODE%
