@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\play.ps1" %*
set "CRAFTER_EXIT=%ERRORLEVEL%"
if not "%CRAFTER_EXIT%"=="0" (
  echo.
  echo Crafter could not start. See the error above and README.md.
  pause
)
exit /b %CRAFTER_EXIT%
