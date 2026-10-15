@echo off
REM One command to answer "did I break anything?" - run before committing.
REM
REM   scripts\verify.bat
REM
REM Runs, in order: ruff lint, the Apps Script node test suite, the python test
REM suite. Exits non-zero if any step fails.
setlocal

cd /d "%~dp0\.."

set "PYTHON=%PYTHON%"
if "%PYTHON%"=="" set "PYTHON=venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo error: '%PYTHON%' not found. Set up the environment first:
    echo   python -m venv venv ^&^& venv\Scripts\pip install -r requirements-dev.txt
    exit /b 1
)

set FAILURES=0

echo.
echo == ruff check ==
"%PYTHON%" -m ruff check .
if errorlevel 1 set /a FAILURES+=1

echo.
echo == apps script tests (node) ==
where node >nul 2>nul
if errorlevel 1 (
    echo SKIPPED: node is not installed ^(needed for the Apps Script tests^)
) else (
    node --test "apps_script/tests/**/*.test.js"
    if errorlevel 1 set /a FAILURES+=1
)

echo.
echo == python tests ^(pytest^) ==
"%PYTHON%" -m pytest tests/ -q
if errorlevel 1 set /a FAILURES+=1

echo.
if "%FAILURES%"=="0" (
    echo All checks passed.
    exit /b 0
)
echo %FAILURES% check^(s^) failed.
exit /b %FAILURES%
