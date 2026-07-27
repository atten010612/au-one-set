@echo off
setlocal

set "TARGET=%USERPROFILE%\.cursor\skills"
if exist "%TARGET%\au-task0" rmdir /S /Q "%TARGET%\au-task0"
if exist "%TARGET%\au-task1" rmdir /S /Q "%TARGET%\au-task1"
if exist "%TARGET%\au-task2" rmdir /S /Q "%TARGET%\au-task2"
reg delete "HKCU\Environment" /V AU_TASK_SKILL_HOME /F >nul 2>nul

echo AU Task skills were removed.
echo Reload the Cursor window to refresh the command list.
pause
