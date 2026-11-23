@echo off
setlocal
pushd "%~dp0" || exit /b 1
where py.exe >nul 2>&1
if not errorlevel 1 (
    py -3 update_lists.py %*
    goto finished
)
where python.exe >nul 2>&1
if not errorlevel 1 (
    python update_lists.py %*
    goto finished
)
echo Install Python 3.10 or newer from python.org and run this file again.
set "code=1"
goto close
:finished
set "code=%ERRORLEVEL%"
:close
popd
if "%~1"=="" if not defined COLDWIRE_LISTS_NO_PAUSE pause
exit /b %code%
