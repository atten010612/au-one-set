@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto run_with_py

python -c "import sys; assert sys.version_info.major == 3" >nul 2>nul
if not errorlevel 1 goto run_with_python

echo 未找到 Python 3。
echo 请从 https://www.python.org/downloads/windows/ 安装，并勾选 Add Python to PATH。
set "EXIT_CODE=1"
goto finish

:run_with_py
py -3 "%~dp0audio_processor.py" %*
set "EXIT_CODE=%errorlevel%"
goto finish

:run_with_python
python "%~dp0audio_processor.py" %*
set "EXIT_CODE=%errorlevel%"

:finish
echo.
if "%EXIT_CODE%"=="0" goto success
echo 操作结束，但存在错误。退出代码：%EXIT_CODE%
goto pause_and_exit

:success
echo 操作已完成。

:pause_and_exit
pause
exit /b %EXIT_CODE%
