@echo off
setlocal
set "YASB_CONFIG_HOME=%~dp0config"
if not exist "%~dp0yasb\yasb.exe" (
    echo Run install.cmd first, then use Start Caelestia YASB from the Start menu.
    pause
    exit /b 1
)
start "" "%~dp0yasb\yasb.exe"
