@echo off
setlocal
cd /d "%~dp0"
call "%~dp0play.bat" --wait True %*
exit /b %ERRORLEVEL%
