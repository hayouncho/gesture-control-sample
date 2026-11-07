@echo off
setlocal
rem Gesture Control - desktop app launcher. Double-click this file to run.
rem Uses the folder of this .bat file as the project folder.
rem Keep this file ASCII-only with CRLF line endings: the project path may contain Korean and spaces.

set "APP_DIR=%~dp0"
set "PYW=%APP_DIR%.venv\Scripts\pythonw.exe"

if not exist "%PYW%" goto :no_venv
if not exist "%APP_DIR%models\hand_landmarker.task" goto :no_model
if not exist "%APP_DIR%app_gui.py" goto :no_app

cd /d "%APP_DIR%"
start "" "%PYW%" "%APP_DIR%app_gui.py"
exit /b 0

:no_venv
echo [ERROR] Virtual environment not found:
echo   "%PYW%"
echo Follow section 3 "Install" in README.md first.
pause
exit /b 1

:no_model
echo [ERROR] Hand model file not found:
echo   "%APP_DIR%models\hand_landmarker.task"
echo Run this in the project folder: .venv\Scripts\python.exe download_model.py
pause
exit /b 1

:no_app
echo [ERROR] app_gui.py not found in "%APP_DIR%"
pause
exit /b 1
