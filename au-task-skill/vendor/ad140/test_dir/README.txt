Place the resource packing files here:

packres.exe
new_packres.bat

new_packres.bat must not contain pause. Recommended content:

@echo off
cd /d "%~dp0"
packres.exe -n test_dir -list OUTPUT.LST -o dir_music -normal
exit /b %errorlevel%

The workflow will also place converted files, OUTPUT.LST, and dir_music here.
