@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 goto create_environment

python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 goto create_environment_with_python

echo 未找到 Python 3.10 或更高版本。
echo 请从 https://www.python.org/downloads/windows/ 安装 Python。
goto failed

:create_environment
py -3 -m venv ".venv"
if errorlevel 1 goto failed
goto install_dependencies

:create_environment_with_python
python -m venv ".venv"
if errorlevel 1 goto failed

:install_dependencies
echo 正在安装 MCP 和 Windows 自动化依赖……
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r "requirements-mcp.txt"
if errorlevel 1 goto failed

echo.
echo 正在检查便携软件目录……
if not exist "tools\ffmpeg.exe" echo [缺少] tools\ffmpeg.exe
if not exist "tools\ffprobe.exe" echo [缺少] tools\ffprobe.exe
if not exist "vendor\converter\音频文件转换工具_1.2.2.exe" echo [缺少] vendor\converter\音频文件转换工具_1.2.2.exe
if not exist "vendor\ad140\packres\pRFiles.exe" echo [缺少] vendor\ad140\packres\pRFiles.exe
if not exist "vendor\ad140\test_dir\packres.exe" echo [缺少] vendor\ad140\test_dir\packres.exe
if not exist "vendor\ad140\test_dir\new_packres.bat" echo [缺少] vendor\ad140\test_dir\new_packres.bat

echo.
echo MCP Python 环境安装完成。
echo 请在 Cursor 中重新加载窗口，然后检查 audio-workflow MCP。
pause
exit /b 0

:failed
echo.
echo MCP 安装失败，请查看上方错误。
pause
exit /b 1
