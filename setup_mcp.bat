@echo off
setlocal
cd /d "%~dp0"

py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 goto create_environment

python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 goto create_environment_with_python

echo Python 3.10 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/
goto failed

:create_environment
py -3 -m venv ".venv"
if errorlevel 1 goto failed
goto install_dependencies

:create_environment_with_python
python -m venv ".venv"
if errorlevel 1 goto failed

:install_dependencies
echo Installing MCP and Windows automation dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r "requirements-mcp.txt"
if errorlevel 1 goto failed

echo.
echo Checking local tools and system PATH...
".venv\Scripts\python.exe" "mcp_server.py" --check

echo.
echo MCP Python environment setup is complete.
echo Reload the Cursor window, then call check_audio_environment.
pause
exit /b 0

:failed
echo.
echo MCP setup failed. Review the error above.
pause
exit /b 1
