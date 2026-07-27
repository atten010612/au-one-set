@echo off
setlocal
cd /d "%~dp0"

set "TARGET=%USERPROFILE%\.cursor\skills"
if not exist "%TARGET%" mkdir "%TARGET%"

xcopy ".cursor\skills\au-task0" "%TARGET%\au-task0" /E /I /Y >nul
if errorlevel 1 goto failed
xcopy ".cursor\skills\au-task1" "%TARGET%\au-task1" /E /I /Y >nul
if errorlevel 1 goto failed
xcopy ".cursor\skills\au-task2" "%TARGET%\au-task2" /E /I /Y >nul
if errorlevel 1 goto failed

echo AU Task skills were installed globally:
echo   /au-task0  convert and package
echo   /au-task1  convert only
echo   /au-task2  package only
echo Reload the Cursor window before use.
pause
exit /b 0

:failed
echo Failed to install AU Task skills.
pause
exit /b 1
