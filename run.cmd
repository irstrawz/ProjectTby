@echo off
rem Launches the game or any project script with the project's virtualenv.
rem
rem   run.cmd                     play
rem   run.cmd --smoke 600         pass main.py arguments straight through
rem   run.cmd selftest.py         or run a different script in the same env
rem   run.cmd tools\build_exe.py  build the distributable
rem
rem This exists alongside run.ps1 because PowerShell refuses to run .ps1 files
rem at all under the default execution policy, and the fix for that is a
rem machine security setting. A .cmd file is not subject to that policy, so
rem this works on a fresh Windows install with nothing configured.
rem
rem Works from any directory: it changes to the project folder first, because
rem the tools read and write paths relative to it.
setlocal

set "ROOT=%~dp0"

rem Prefer a virtualenv beside the project, then one inside it.
set "PY=%ROOT%..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" goto :novenv

pushd "%ROOT%"

rem A first argument ending in .py is the script to run; anything else is
rem arguments for main.py. An empty %1 leaves FIRST empty, which is not ".py",
rem so a bare "run.cmd" starts the game.
set "FIRST=%~1"
if /i "%FIRST:~-3%"==".py" (
    "%PY%" %*
) else (
    "%PY%" main.py %*
)
set "CODE=%ERRORLEVEL%"

popd
exit /b %CODE%

:novenv
echo No virtualenv found. Looked for:
echo   %ROOT%..\.venv\Scripts\python.exe
echo   %ROOT%.venv\Scripts\python.exe
echo.
echo Create one and install the dependencies with:
echo   py -m venv "%ROOT%..\.venv"
echo   "%ROOT%..\.venv\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt"
exit /b 1
