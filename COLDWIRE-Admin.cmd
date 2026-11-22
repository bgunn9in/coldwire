@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" if "%~1"=="" pause
exit /b %exit_code%
