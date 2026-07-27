@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto uninstall_with_venv
py -3 "install_cursor.py" uninstall
goto done

:uninstall_with_venv
".venv\Scripts\python.exe" "install_cursor.py" uninstall

:done
echo Reload the Cursor window to refresh MCP and Skills.
pause
