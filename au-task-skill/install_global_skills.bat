@echo off
setlocal
cd /d "%~dp0"

py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 goto create_with_py

python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 goto create_with_python

echo Python 3.10 or newer was not found.
goto failed

:create_with_py
py -3 -m venv ".venv"
if errorlevel 1 goto failed
goto install_dependencies

:create_with_python
python -m venv ".venv"
if errorlevel 1 goto failed

:install_dependencies
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" "install_cursor.py" install
if errorlevel 1 goto failed

echo.
echo AU Task standalone MCP and Skills were installed.
echo Reload the Cursor window before use.
pause
exit /b 0

:failed
echo Failed to install AU Task skills.
pause
exit /b 1
